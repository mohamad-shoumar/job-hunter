"""One run: fetch every source, store and dedupe, classify new jobs, write reports.

Two ways to run:

  daily       jobs found for the first time go into today's report
              (reports/<today>.md). Running twice in a day adds to the same file.
  date range  (--from/--to) the sources are fetched ONCE and every listing
              posted inside the range goes into the report for its posting day,
              one file per day. Fetching once per day would return exactly the
              same listings each time - the sites only show what is open now -
              and would spend 7x the SerpApi credits.
"""

from __future__ import annotations

import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

from . import boards, sponsors
from .ai_check import AiChecker, build_checker, check_jobs
from .classify import classify
from .config import Filters, OutreachConfig
from .extract import enrich
from .fitgrade import FitGrader, build_grader, grade_jobs, to_grade
from .http import Http
from .models import NEEDS_REVIEW, UNCLEAR, Job
from .outreach import run_outreach
from .report import write_report
from .sources import Source, SourceResult, build_sources
from .sources.base import describe_error
from .store import JobStore, row_to_job
from .text import iso, parse_datetime, utcnow

log = logging.getLogger(__name__)


@dataclass
class SourceStats:
    fetched: int = 0
    new: int = 0
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class RunSummary:
    run_id: int
    started_at: str
    sources: dict[str, SourceStats] = field(default_factory=dict)
    new_by_status: Counter = field(default_factory=Counter)
    reject_codes: Counter = field(default_factory=Counter)
    config_notes: list[str] = field(default_factory=list)
    ai_check: dict | None = None
    fit_grade: dict | None = None
    outreach: dict | None = None
    boards: dict | None = None
    # Job ids this run touched (new or seen again), and the new ones. Not saved.
    seen_ids: set[int] = field(default_factory=set)
    new_ids: list[int] = field(default_factory=list)

    @property
    def fetched(self) -> int:
        return sum(s.fetched for s in self.sources.values())

    @property
    def new(self) -> int:
        return sum(s.new for s in self.sources.values())

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "sources": {name: asdict(stats) for name, stats in self.sources.items()},
            "new_by_status": dict(self.new_by_status),
            "reject_codes": dict(self.reject_codes),
            "config_notes": self.config_notes,
            "ai_check": self.ai_check,
            "fit_grade": self.fit_grade,
            "outreach": self.outreach,
            "boards": self.boards,
        }


def fetch_all(sources: list[Source], http: Http, workers: int = 6) -> list[SourceResult]:
    """Fetch sources in parallel. A crashing adapter becomes an error line, not a failed run."""

    def safe_fetch(source: Source) -> SourceResult:
        try:
            return source.fetch(http)
        except Exception as exc:  # an adapter bug must not stop the other sources
            log.exception("source %s crashed", source.name)
            return SourceResult(source.name, errors=[f"adapter crashed: {describe_error(exc)}"])

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(safe_fetch, sources))


def _unique(jobs: list[Job]) -> list[Job]:
    """One entry per source_job_id (search queries overlap)."""
    return list({job.source_job_id: job for job in jobs if job.source_job_id}.values())


def ingest(store: JobStore, results: list[SourceResult], filters: Filters, run_id: int, now: datetime,
           summary: RunSummary) -> None:
    for result in results:
        stats = summary.sources.setdefault(result.source, SourceStats())
        stats.errors += result.errors
        stats.notes += result.notes
        jobs = _unique(result.jobs)
        stats.fetched += len(jobs)
        for job in jobs:
            try:
                enrich(job)
                existing = store.find_match(job, now, filters.dedupe_window_days)
                if existing is not None:
                    store.touch(existing, job, now)
                    summary.seen_ids.add(existing)
                    continue
                job.first_seen = now
                cls = classify(job, filters, now)
                job_id = store.insert(job, cls, run_id, now)
            except Exception as exc:  # one malformed listing must not drop the rest
                log.exception("failed to store %s %s", job.source, job.source_job_id)
                stats.errors.append(f"{job.source_job_id}: {describe_error(exc)}")
                continue
            summary.seen_ids.add(job_id)
            summary.new_ids.append(job_id)
            stats.new += 1
            summary.new_by_status[cls.status] += 1
            if cls.reject_code:
                summary.reject_codes[cls.reject_code] += 1
        store.commit()


def local_day(dt: datetime) -> date:
    """The calendar day in this machine's time zone (Lebanon, for the daily schedule)."""
    return dt.astimezone().date()


def days_between(start: date, end: date) -> list[str]:
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def recent_days(now: datetime, count: int) -> list[str]:
    """Today and the `count - 1` days before it (at least today)."""
    today = local_day(now)
    return days_between(today - timedelta(days=max(1, count) - 1), today)


def assign_daily(store: JobStore, summary: RunSummary, now: datetime) -> list[str]:
    """New jobs, plus relevant jobs never shown before (e.g. after reclassify), go to today."""
    today = local_day(now).isoformat()
    store.set_report_date(summary.new_ids + [row["id"] for row in store.unreported()], today)
    store.commit()
    return [today]


def assign_range(store: JobStore, summary: RunSummary, filters: Filters, now: datetime,
                 start: date, end: date) -> list[str]:
    """Every listing this run saw that was posted in [start, end] goes to its posting day.

    Only jobs seen in this run count, so closed postings and removed sources
    stay out. A new job with no posting date goes to the last day.
    """
    new = set(summary.new_ids)
    # Days that lose a job to its posting day must be re-rendered too.
    touched_days: set[str] = set()
    for row in store.jobs_by_ids(summary.seen_ids):
        posted = parse_datetime(row["posted_at"])
        if posted:
            day = local_day(posted)
            if not start <= day <= end:
                continue
        elif row["id"] in new:
            day = end
        else:
            continue
        if row["reject_code"] == "too_old":  # the range asked for these, however old
            store.update_classification(row["id"], classify(row_to_job(row), filters, now, check_age=False))
        if row["report_date"] and row["report_date"] != day.isoformat():
            touched_days.add(row["report_date"])
        store.set_report_date([row["id"]], day.isoformat())
    store.commit()
    return sorted(set(days_between(start, end)) | touched_days)


def ai_check_days(store: JobStore, checker: AiChecker, days: list[str], filters: Filters,
                  now: datetime, summary: RunSummary) -> None:
    """AI-check the unchecked needs_review jobs filed under `days`, newest first, up to the per-run cap."""
    waiting = [row for day in days for row in store.jobs_for_report(day)
               if row["status"] == NEEDS_REVIEW and row["eligibility"] == UNCLEAR and not row["ai_check_json"]]
    waiting.sort(key=lambda r: (r["posted_at"] or r["first_seen"], r["id"]), reverse=True)
    limit = checker.config.max_jobs_per_run
    result = check_jobs(store, checker, waiting[:limit], filters, now)
    if len(waiting) > limit:
        result.notes.append(f"{len(waiting) - limit} more left for the next run or `jobhunter check`")
    summary.ai_check = result.to_dict()


def refresh_sponsors(root_paths, filters: Filters, http: Http, now: datetime, summary: RunSummary) -> None:
    """Download the government sponsor lists older than refresh_days (sponsors.py), before jobs are classified."""
    folder = root_paths.sponsors_dir
    due = sponsors.stale(folder, filters.visa.refresh_days, now)
    if due:
        done, errors = sponsors.update(http, folder, now, due)
        summary.config_notes += [f"sponsor lists: {line}" for line in done + errors]
    if due or filters.visa.registers is None:
        filters.visa.registers = sponsors.Registers.load(folder)


def run(root_paths, sources_config: dict, filters: Filters, only: set[str] | None = None,
        skip: set[str] | None = None, report: bool = True, http: Http | None = None, now: datetime | None = None,
        date_range: tuple[date, date] | None = None, ai: bool = True,
        ai_checker: AiChecker | None = None, outreach: bool = True,
        fit_grader: FitGrader | None = None) -> tuple[RunSummary, list[Path]]:
    """ai=False skips every model call. ai_checker and fit_grader override the ones built from
    config/ai_check.json and config/fit_grade.json.

    outreach=False skips contacts, drafts and the inbox check (outreach.py). `skip` leaves those sources out
    (the morning run skips serpapi, whose credits last only for one run a day).
    """
    now = now or utcnow()
    sources, config_notes = build_sources(sources_config)
    if ai and ai_checker is None:
        ai_checker, note = build_checker(root_paths.ai_check_file)
        if note:
            config_notes.append(note)
    if ai and fit_grader is None:
        fit_grader, note = build_grader(root_paths.fit_grade_file)
        if note:
            config_notes.append(note)
    watch = boards.WatchConfig.from_sources(sources_config)

    store = JobStore(root_paths.db_file)
    own_http = http is None
    http = http or Http()
    try:
        if watch.enabled:
            boards.add_watched_sources(sources, store, sources_config)
        if only:
            unknown = only - {s.name for s in sources}
            if unknown:
                raise SystemExit(f"unknown or disabled source(s): {', '.join(sorted(unknown))}")
            sources = [s for s in sources if s.name in only]
        if skip:
            # A note, not an error: the scheduled morning run must not fail when serpapi is turned off.
            unknown = skip - {s.name for s in sources}
            if unknown:
                config_notes.append(f"--skip: no enabled source named {', '.join(sorted(unknown))}")
            sources = [s for s in sources if s.name not in skip]
        if date_range:
            since = datetime.combine(date_range[0], time.min).astimezone()  # local midnight
            for source in sources:
                source.since = since
        run_id = store.start_run(now)
        summary = RunSummary(run_id=run_id, started_at=iso(now), config_notes=config_notes)
        if filters.visa and only is None:
            refresh_sponsors(root_paths, filters, http, now, summary)
        log.info("fetching %d sources: %s", len(sources), ", ".join(s.name for s in sources))
        results = fetch_all(sources, http)
        ingest(store, results, filters, run_id, now, summary)
        if date_range:
            days = assign_range(store, summary, filters, now, *date_range)
        else:
            days = assign_daily(store, summary, now)
        if ai and ai_checker:
            # A daily run also looks back, so jobs over one day's cap are checked on the next days.
            check_days = days if date_range else recent_days(now, ai_checker.config.lookback_days)
            ai_check_days(store, ai_checker, check_days, filters, now, summary)
        if ai and fit_grader and not date_range:
            # After the AI check (it can move a job to the shortlist), before the CVs (made best grade first).
            try:
                rows = to_grade(store, now, fit_grader.config.lookback_days)
                result = grade_jobs(store, fit_grader, rows[:fit_grader.config.max_jobs_per_run],
                                    root_paths.profile_file, now)
                if len(rows) > fit_grader.config.max_jobs_per_run:
                    result.notes.append(f"{len(rows) - fit_grader.config.max_jobs_per_run} more left for the next "
                                        "run or `jobhunter grade`")
                summary.fit_grade = result.to_dict()
            except Exception as exc:  # grades only sort: the run goes on without them
                log.exception("fit grade step failed")
                summary.fit_grade = {"graded": 0, "grades": {}, "errors": [f"fit grade: {describe_error(exc)}"],
                                     "notes": [], "cost_usd": 0, "model": fit_grader.label, "examples": ""}
        if watch.enabled:
            # After the AI check, so a job it shortlisted counts too. New boards are fetched from the next run.
            try:
                summary.boards = boards.watch_shortlisted(
                    store, http, sources_config, filters, OutreachConfig.load(root_paths.outreach_file), now, watch,
                ).to_dict()
            except Exception as exc:
                log.exception("watch boards step failed")
                summary.boards = {"added": [], "probed": 0, "notes": [], "errors": [f"boards: {describe_error(exc)}"]}
        if outreach:
            # Date-range runs never spend lookup credits: they would use up the month.
            try:
                summary.outreach = run_outreach(store, root_paths, summary.new_ids, now, ai=ai,
                                                lookups=date_range is None)
            except Exception as exc:  # e.g. a broken config/outreach.json: the reports still get written
                log.exception("outreach step failed")
                summary.outreach = {"contacts": None, "drafts": [], "inbox": None, "notes": [],
                                    "errors": [f"outreach: {describe_error(exc)}"]}
        store.finish_run(run_id, summary.to_dict(), utcnow())
        paths = [
            write_report(store, root_paths.reports_dir, day, summary.to_dict(), now, filters.max_posting_age_days)
            for day in days
        ] if report else []
        return summary, paths
    finally:
        store.close()
        if own_http:
            http.close()
