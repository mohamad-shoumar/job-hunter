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
import time as clock
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from functools import partial
from pathlib import Path

from . import boards, sponsors
from .ai_check import AiChecker, CheckRun, build_checker, check_jobs
from .boards import WatchRun
from .classify import classify
from .config import Filters, OutreachConfig
from .extract import enrich
from .fitgrade import FitGrader, GradeRun, build_grader, grade_jobs, to_grade
from .http import Http, wait_for_network
from .models import NEEDS_REVIEW, UNCLEAR, Job
from .posted_date import DateFinder, DateRun, build_finder, find_dates
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
class RunOptions:
    """What one run does. ai=False skips every model call; ai_checker, date_finder and fit_grader override the ones
    built from config/ai_check.json and config/fit_grade.json.

    outreach=False skips contacts, drafts and the inbox check (outreach.py). `only` fetches just those sources;
    `skip` leaves those out (the morning run skips serpapi, whose credits last only for one run a day). A run given
    no `http` makes its own and waits for the network first; `now` is for tests.
    """

    only: set[str] | None = None
    skip: set[str] | None = None
    report: bool = True
    date_range: tuple[date, date] | None = None
    ai: bool = True
    outreach: bool = True
    ai_checker: AiChecker | None = None
    date_finder: DateFinder | None = None
    fit_grader: FitGrader | None = None
    http: Http | None = None
    now: datetime | None = None


@dataclass
class RunSummary:
    run_id: int
    started_at: str
    sources: dict[str, SourceStats] = field(default_factory=dict)
    new_by_status: Counter = field(default_factory=Counter)
    reject_codes: Counter = field(default_factory=Counter)
    config_notes: list[str] = field(default_factory=list)
    # The optional steps' results, None when a step did not run. run_outreach returns a plain dict.
    ai_check: CheckRun | None = None
    date_check: DateRun | None = None
    fit_grade: GradeRun | None = None
    outreach: dict | None = None
    boards: WatchRun | None = None
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
            "ai_check": _as_dict(self.ai_check),
            "date_check": _as_dict(self.date_check),
            "fit_grade": _as_dict(self.fit_grade),
            "outreach": self.outreach,
            "boards": _as_dict(self.boards),
        }


def _as_dict(result) -> dict | None:
    return None if result is None else result.to_dict()


# Error lines that mean the request never reached the site (describe_error names the httpx class).
_CONNECTION_ERRORS = ("ConnectError", "ConnectTimeout")


def _lost_connection(result: SourceResult) -> bool:
    return any(kind in error for error in result.errors for kind in _CONNECTION_ERRORS)


def fetch_all(sources: list[Source], http: Http, workers: int = 6, retry_after: float = 60.0) -> list[SourceResult]:
    """Fetch sources in parallel. A crashing adapter becomes an error line, not a failed run.

    A source with a connection error is fetched once more after `retry_after` seconds (unless it
    pays per request, `refetch=False`); its jobs from both tries are kept, its errors from the second.
    """

    def safe_fetch(source: Source) -> SourceResult:
        try:
            return source.fetch(http)
        except Exception as exc:  # an adapter bug must not stop the other sources
            log.exception("source %s crashed", source.name)
            return SourceResult(source.name, errors=[f"adapter crashed: {describe_error(exc)}"])

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(safe_fetch, sources))
        again = [i for i, (source, result) in enumerate(zip(sources, results))
                 if source.refetch and _lost_connection(result)]
        if not again:
            return results
        log.info("connection errors in %s: trying again in %.0fs",
                 ", ".join(sources[i].name for i in again), retry_after)
        clock.sleep(retry_after)
        for i, second in zip(again, pool.map(safe_fetch, [sources[i] for i in again])):
            first = results[i]
            note = f"fetched again after {len(first.errors)} error(s) the first time"
            results[i] = SourceResult(first.source, first.jobs + second.jobs, second.errors, second.notes + [note])
    return results


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


def date_check_days(store: JobStore, finder: DateFinder, days: list[str], filters: Filters,
                    now: datetime) -> DateRun:
    """Look up when the undated needs_review jobs filed under `days` were posted, newest first, up to the cap.

    Before the AI check, so one that turns out too old is rejected without it. Its changed_days are the report days
    whose jobs changed status."""
    waiting = [row for day in days for row in store.jobs_for_report(day)
               if row["status"] == NEEDS_REVIEW and not row["posted_at"] and not row["date_check_json"]]
    waiting.sort(key=lambda r: (r["first_seen"], r["id"]), reverse=True)
    limit = finder.config.max_dates_per_run
    result = find_dates(store, finder, waiting[:limit], filters, now)
    if len(waiting) > limit:
        result.notes.append(f"{len(waiting) - limit} more left for the next run or `jobhunter dates`")
    return result


def ai_check_days(store: JobStore, checker: AiChecker, days: list[str], filters: Filters,
                  now: datetime) -> CheckRun:
    """AI-check the unchecked needs_review jobs filed under `days`, newest first, up to the per-run cap.

    Its changed_days are the report days whose jobs changed status, so their files are written again."""
    waiting = [row for day in days for row in store.jobs_for_report(day)
               if row["status"] == NEEDS_REVIEW and row["eligibility"] == UNCLEAR and not row["ai_check_json"]]
    waiting.sort(key=lambda r: (r["posted_at"] or r["first_seen"], r["id"]), reverse=True)
    limit = checker.config.max_jobs_per_run
    result = check_jobs(store, checker, waiting[:limit], filters, now)
    if len(waiting) > limit:
        result.notes.append(f"{len(waiting) - limit} more left for the next run or `jobhunter check`")
    return result


def grade_recent(store: JobStore, grader: FitGrader, profile_file: Path, now: datetime) -> GradeRun:
    """Fit-grade the ungraded shown jobs of the last lookback_days, newest first, up to the per-run cap."""
    rows = to_grade(store, now, grader.config.lookback_days)
    limit = grader.config.max_jobs_per_run
    result = grade_jobs(store, grader, rows[:limit], profile_file, now)
    if len(rows) > limit:
        result.notes.append(f"{len(rows) - limit} more left for the next run or `jobhunter grade`")
    return result


def refresh_sponsors(root_paths, filters: Filters, http: Http, now: datetime, summary: RunSummary) -> None:
    """Download the government sponsor lists older than refresh_days (sponsors.py), before jobs are classified."""
    folder = root_paths.sponsors_dir
    due = sponsors.stale(folder, filters.visa.refresh_days, now)
    if due:
        done, errors = sponsors.update(http, folder, now, due)
        summary.config_notes += [f"sponsor lists: {line}" for line in done + errors]
    if due or filters.visa.registers is None:
        filters.visa.registers = sponsors.Registers.load(folder)


def _model(given, build, config_file: Path, notes: list[str]):
    """`given` (a test's fake), else the one built from `config_file`; a note says why it is off."""
    if given is not None:
        return given
    built, note = build(config_file)
    if note:
        notes.append(note)
    return built


def _chosen(sources: list[Source], only: set[str] | None, skip: set[str] | None, notes: list[str]) -> list[Source]:
    """The sources `only` names (an unknown name stops the run), minus the ones `skip` names."""
    if only:
        unknown = only - {s.name for s in sources}
        if unknown:
            raise SystemExit(f"unknown or disabled source(s): {', '.join(sorted(unknown))}")
        sources = [s for s in sources if s.name in only]
    if skip:
        # A note, not an error: the scheduled morning run must not fail when serpapi is turned off.
        unknown = skip - {s.name for s in sources}
        if unknown:
            notes.append(f"--skip: no enabled source named {', '.join(sorted(unknown))}")
        sources = [s for s in sources if s.name not in skip]
    return sources


def _wait_for_network(notes: list[str]) -> None:
    """The scheduled runs start as the Mac wakes: wait for the network, with a note when that took a while."""
    waited = wait_for_network()
    if waited is None:
        notes.append("no network after 5 minutes of waiting; fetching anyway")
    elif waited >= 1:
        notes.append(f"waited {waited:.0f}s for the network before fetching")


def _outreach_failed(errors: list[str]) -> dict:
    """What a crashed outreach step records: run_outreach returns a plain dict, not a result type."""
    return {"contacts": None, "drafts": [], "inbox": None, "notes": [], "errors": errors}


def _step(label: str, work: Callable, failed: Callable):
    """Run one optional step, work(). A crash is logged and becomes failed(errors=[line]): the step's own result
    type with one error line, so stats_json keeps the step's keys and the run goes on to write the reports."""
    try:
        return work()
    except Exception as exc:  # e.g. a broken config/outreach.json: the reports still get written
        log.exception("%s step failed", label)
        return failed(errors=[f"{label}: {describe_error(exc)}"])


def run(root_paths, sources_config: dict, filters: Filters,
        options: RunOptions | None = None) -> tuple[RunSummary, list[Path]]:
    """Fetch every source, store and classify, run the optional steps, then write the reports. See RunOptions."""
    opts = options or RunOptions()
    now = opts.now or utcnow()
    sources, config_notes = build_sources(sources_config)
    ai_checker = date_finder = fit_grader = None
    if opts.ai:
        ai_checker = _model(opts.ai_checker, build_checker, root_paths.ai_check_file, config_notes)
        date_finder = _model(opts.date_finder, build_finder, root_paths.ai_check_file, config_notes)
        fit_grader = _model(opts.fit_grader, build_grader, root_paths.fit_grade_file, config_notes)
    watch = boards.WatchConfig.from_sources(sources_config)

    store = JobStore(root_paths.db_file)
    own_http = opts.http is None
    http = opts.http or Http()
    try:
        if watch.enabled:
            boards.add_watched_sources(sources, store, sources_config)
        sources = _chosen(sources, opts.only, opts.skip, config_notes)
        if opts.date_range:
            since = datetime.combine(opts.date_range[0], time.min).astimezone()  # local midnight
            for source in sources:
                source.since = since
        run_id = store.start_run(now)
        summary = RunSummary(run_id=run_id, started_at=iso(now), config_notes=config_notes)
        if own_http:
            _wait_for_network(config_notes)
        if filters.visa and opts.only is None:
            refresh_sponsors(root_paths, filters, http, now, summary)
        log.info("fetching %d sources: %s", len(sources), ", ".join(s.name for s in sources))
        results = fetch_all(sources, http)
        ingest(store, results, filters, run_id, now, summary)
        if opts.date_range:
            days = assign_range(store, summary, filters, now, *opts.date_range)
        else:
            days = assign_daily(store, summary, now)
        # Earlier days whose jobs the look-backs below changed: their files are written again too.
        touched: set[str] = set()
        if date_finder:
            date_days = days if opts.date_range else recent_days(now, date_finder.config.lookback_days)
            summary.date_check = _step("posting dates",
                                       lambda: date_check_days(store, date_finder, date_days, filters, now),
                                       partial(DateRun, model=date_finder.label))
            touched |= summary.date_check.changed_days
        if ai_checker:
            # A daily run also looks back, so jobs over one day's cap are checked on the next days.
            check_days = days if opts.date_range else recent_days(now, ai_checker.config.lookback_days)
            summary.ai_check = _step("AI check", lambda: ai_check_days(store, ai_checker, check_days, filters, now),
                                     partial(CheckRun, model=ai_checker.label))
            touched |= summary.ai_check.changed_days
        if fit_grader and not opts.date_range:
            # After the AI check (it can move a job to the shortlist), before the CVs (made best grade first).
            summary.fit_grade = _step("fit grade",
                                      lambda: grade_recent(store, fit_grader, root_paths.profile_file, now),
                                      partial(GradeRun, model=fit_grader.label))
            touched |= summary.fit_grade.changed_days
        if watch.enabled:
            # After the AI check, so a job it shortlisted counts too. New boards are fetched from the next run.
            summary.boards = _step("boards", lambda: boards.watch_shortlisted(
                store, http, sources_config, filters, OutreachConfig.load(root_paths.outreach_file), now, watch,
            ), WatchRun)
        if opts.outreach:
            # Date-range runs never spend lookup credits: they would use up the month.
            summary.outreach = _step("outreach", lambda: run_outreach(
                store, root_paths, summary.new_ids, now, ai=opts.ai, lookups=opts.date_range is None,
            ), _outreach_failed)
        store.finish_run(run_id, summary.to_dict(), utcnow())
        paths = [
            write_report(store, root_paths.reports_dir, day, summary.to_dict(), now, filters.max_posting_age_days)
            for day in sorted(set(days) | touched)
        ] if opts.report else []
        return summary, paths
    finally:
        store.close()
        if own_http:
            http.close()
