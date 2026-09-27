"""Command line: `jobhunter run | check | report | reclassify | show | stats | sources`."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from . import pipeline
from .ai_check import build_checker, check_jobs
from .classify import classify
from .config import Filters, Paths, load_dotenv, load_json, resolve_root
from .extract import enrich
from .report import write_report
from .sources import build_sources
from .models import NEEDS_REVIEW
from .store import JobStore, row_to_job
from .text import utcnow


def _load(args) -> tuple[Paths, dict, Filters]:
    paths = Paths(resolve_root(args.home))
    if not paths.sources_file.exists():
        raise SystemExit(f"no config at {paths.sources_file} (run from the project folder or pass --home)")
    load_dotenv(paths.env_file)
    return paths, load_json(paths.sources_file), Filters.load(paths.filters_file)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date, expected YYYY-MM-DD: {value}") from None


def _date_range(args) -> tuple[date, date] | None:
    today = pipeline.local_day(utcnow())
    if args.days:
        if args.from_date or args.to_date:
            raise SystemExit("use --days or --from/--to, not both")
        return today - timedelta(days=args.days - 1), today
    if args.to_date and not args.from_date:
        raise SystemExit("--to needs --from")
    if not args.from_date:
        return None
    end = min(args.to_date or today, today)  # nothing is posted in the future
    if end < args.from_date:
        raise SystemExit("--to is before --from")
    return args.from_date, end


def _print_report_counts(store: JobStore, report_paths: list[Path]) -> None:
    for path in report_paths:
        c = Counter(row["status"] for row in store.jobs_for_report(path.stem))
        print(f"{path}   {c['shortlisted']} shortlisted, {c['needs_review']} need review, {c['rejected']} rejected")


def cmd_run(args) -> int:
    paths, sources_config, filters = _load(args)
    only = {s.strip() for s in args.sources.split(",")} if args.sources else None
    date_range = _date_range(args)
    summary, report_paths = pipeline.run(
        paths, sources_config, filters, only=only, report=not args.no_report, date_range=date_range, ai=not args.no_ai
    )
    for name, stats in sorted(summary.sources.items()):
        flag = f"  ({len(stats.errors)} errors)" if stats.errors else ""
        print(f"{name:16} {stats.fetched:5} listings  {stats.new:4} new{flag}")
    breakdown = ", ".join(f"{v} {k}" for k, v in summary.new_by_status.most_common())
    print(f"\n{summary.new} new jobs" + (f": {breakdown}" if breakdown else "") + "\n")
    if summary.ai_check:
        ai = summary.ai_check
        verdicts = ", ".join(f"{n} {v}" for v, n in ai["verdicts"].items()) or "none"
        print(f"AI check: {ai['checked']} jobs ({verdicts}), about ${ai['cost_usd']:.2f}")
        for line in ai["notes"] + ai["errors"]:
            print(f"  {line}")
        print()
    store = JobStore(paths.db_file)
    try:
        _print_report_counts(store, report_paths)
    finally:
        store.close()
    return 0


def cmd_report(args) -> int:
    """Rebuild one day's file, or (no --date) put never-reported relevant jobs into today's."""
    paths, _, filters = _load(args)
    now = utcnow()
    store = JobStore(paths.db_file)
    try:
        if args.date:
            day = args.date.isoformat()
        else:
            day = pipeline.local_day(now).isoformat()
            store.set_report_date([row["id"] for row in store.unreported()], day)
            store.commit()
        path = write_report(store, paths.reports_dir, day, store.last_run_stats(), now, filters.max_posting_age_days)
        _print_report_counts(store, [path])
    finally:
        store.close()
    return 0


def cmd_check(args) -> int:
    """AI web check for needs_review jobs: given ids, or the unchecked ones newest first."""
    paths, _, filters = _load(args)
    checker, note = build_checker(paths.ai_check_file, require_enabled=False)
    if checker is None:
        raise SystemExit(note)
    now = utcnow()
    store = JobStore(paths.db_file)
    try:
        if args.job_ids:
            rows = []
            for job_id in args.job_ids:
                row = store.get(job_id)
                if row is None:
                    print(f"#{job_id}: no such job")
                elif row["status"] != NEEDS_REVIEW and not row["ai_check_json"]:  # AI-decided jobs may be re-checked
                    print(f"#{job_id}: skipped, status is {row['status']} (only needs_review jobs are AI-checked)")
                else:
                    rows.append(row)
            waiting = len(rows)
        else:
            rows = store.needs_ai_check(recheck=args.recheck)
            waiting = len(rows)
            rows = rows[: args.limit or checker.config.max_jobs_per_run]
        if not rows:
            print("nothing to check")
            return 0
        print(f"checking {len(rows)} of {waiting} jobs with {checker.config.model}\n")

        def show(row, check, cls):
            found = "" if check.verified or check.verdict == "unknown" else " (quote not found, not used)"
            print(f"#{row['id']:<5} {row['company']} — {row['title']}")
            print(f"       {check.verdict}{found} -> {cls.status}: {check.reason}")
            if check.quote:
                print(f'       "{check.quote}" ({check.source_url})')

        result = check_jobs(store, checker, rows, filters, now, on_result=show)
        rebuilt = [write_report(store, paths.reports_dir, day, store.last_run_stats(), now, filters.max_posting_age_days)
                   for day in sorted(result.changed_days)]
    finally:
        store.close()
    print(f"\n{result.checked} checked, about ${result.cost_usd:.2f}")
    for change, count in result.status_changes.most_common():
        print(f"{count:5}  {change}")
    for line in result.notes + result.errors:
        print(f"  {line}")
    if waiting > len(rows):
        print(f"{waiting - len(rows)} more waiting: run it again, or pass --limit")
    for path in rebuilt:
        print(f"rebuilt {path}")
    return 1 if result.errors and not result.checked else 0


def cmd_reclassify(args) -> int:
    paths, _, filters = _load(args)
    store = JobStore(paths.db_file)
    changes: Counter = Counter()
    changed_days: set[str] = set()
    now = utcnow()
    try:
        for row in store.all_jobs():
            job = enrich(row_to_job(row))  # re-extract too, so extraction changes apply
            store.update_skills(row["id"], job.skills)
            # Age only decides whether a job is taken at all. Once it sits in a
            # report (fresh when found, or asked for by a date range) it is not
            # re-judged on age - unless age is what rejected it.
            check_age = not row["report_date"] or row["reject_code"] == "too_old"
            cls = classify(job, filters, now, check_age=check_age)
            if cls.status != row["status"] or cls.eligibility.verdict != row["eligibility"]:
                changes[f"{row['status']} -> {cls.status}"] += 1
                if row["report_date"]:
                    changed_days.add(row["report_date"])
            store.update_classification(row["id"], cls)
        store.commit()
        summary = store.last_run_stats()
        rebuilt = [write_report(store, paths.reports_dir, day, summary, now, filters.max_posting_age_days)
                   for day in sorted(changed_days)]
    finally:
        store.close()
    if not changes:
        print("no changes")
    for change, count in changes.most_common():
        print(f"{count:5}  {change}")
    for path in rebuilt:
        print(f"rebuilt {path}")
    print("jobs that became shortlisted/needs_review and were never reported go into the next daily report")
    return 0


def cmd_show(args) -> int:
    paths, _, _ = _load(args)
    store = JobStore(paths.db_file)
    try:
        row = store.get(args.job_id)
        if not row:
            print(f"no job #{args.job_id}", file=sys.stderr)
            return 1
        sightings = store.sightings_for([row["id"]])[row["id"]]
    finally:
        store.close()
    print(f"#{row['id']}  {row['title']} — {row['company']}")
    print(f"status: {row['status']}" + (f"  ({row['reject_reason']})" if row["reject_reason"] else ""))
    print(f"eligibility: {row['eligibility']}")
    for reason in json.loads(row["eligibility_reasons_json"]):
        print(f"  - {reason}")
    if row["ai_check_json"]:
        ai = json.loads(row["ai_check_json"])
        cost = f", about ${ai['cost_usd']:.2f}" if ai.get("cost_usd") is not None else ""
        print(f"ai check: {ai['verdict']}" + ("" if ai["verified"] else " (quote not verified)")
              + f"  [{ai['model']}, {ai['checked_at'][:10]}, {ai['searches']} searches{cost}]")
        print(f"  - {ai['reason']}")
        if ai["quote"]:
            print(f'  - "{ai["quote"]}" ({ai["source_url"]})')
    print(f"relevance: {row['relevance']}  fit {row['fit_score']}")
    for reason in json.loads(row["relevance_reasons_json"]):
        print(f"  - {reason}")
    print(f"remote: {row['remote_status']}   location: {row['location_raw']}")
    print(f"allowed locations: {', '.join(json.loads(row['allowed_locations_json'])) or '-'}")
    print(f"employment: {row['employment_type']}   yoe: {row['required_yoe']}   salary: {row['salary_raw'] or row['salary_min']}")
    print(f"skills: {', '.join(json.loads(row['skills_json']))}")
    print(f"posted: {row['posted_at']}   first seen: {row['first_seen']}   last seen: {row['last_seen']}")
    print(f"apply: {row['application_url']}")
    for s in sightings:
        print(f"seen on {s['source']}: {s['source_url']}")
    if args.description:
        print("\n" + row["description"])
    return 0


def cmd_stats(args) -> int:
    paths, _, _ = _load(args)
    store = JobStore(paths.db_file)
    try:
        print(json.dumps(store.counts(), indent=2))
    finally:
        store.close()
    return 0


def cmd_sources(args) -> int:
    _, sources_config, _ = _load(args)
    sources, notes = build_sources(sources_config)
    for source in sources:
        print(f"enabled   {source.name}")
    for note in notes:
        print(f"skipped   {note}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobhunter", description=__doc__)
    parser.add_argument("--home", help="project folder (default: $JOBHUNTER_HOME, else the folder holding config/)")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "run",
        help="fetch every source, store, classify new jobs, write reports/<date>.md",
        description="Without dates: new jobs go into today's report. With --from/--to or --days: "
        "the sources are fetched once and every job posted in the range goes into the report "
        "for the day it was posted (one file per day).",
    )
    p.add_argument("--sources", help="comma-separated source names, e.g. himalayas,lever")
    p.add_argument("--from", dest="from_date", type=_date, metavar="YYYY-MM-DD", help="first day of a date range")
    p.add_argument("--to", dest="to_date", type=_date, metavar="YYYY-MM-DD", help="last day of the range (default: today)")
    p.add_argument("--days", type=int, metavar="N", help="the last N days, today included (--days 7 = this week)")
    p.add_argument("--no-report", action="store_true", help="store and classify only")
    p.add_argument("--no-ai", action="store_true", help="skip the AI web check even if config/ai_check.json enables it")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser(
        "check",
        help="AI web check: can the company hire from Lebanon? (needs_review jobs, needs ANTHROPIC_API_KEY)",
        description="Claude searches the web for each job and returns a verdict with a quote. The quote must be "
        "found word for word on the page before it changes a job's status. Without ids: the unchecked "
        "needs_review jobs, newest first, up to max_jobs_per_run from config/ai_check.json.",
    )
    p.add_argument("job_ids", type=int, nargs="*", help="check these jobs (again, if already checked)")
    p.add_argument("--limit", type=int, metavar="N", help="check at most N jobs (default: max_jobs_per_run)")
    p.add_argument("--recheck", action="store_true", help="include jobs already checked (unknown or unverified)")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("report", help="rebuild reports/<date>.md from the database")
    p.add_argument("--date", type=_date, metavar="YYYY-MM-DD",
                   help="the day to rebuild (default: today, adding relevant jobs never reported)")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("reclassify", help="re-apply the filters to every stored job (after editing them)")
    p.set_defaults(func=cmd_reclassify)

    p = sub.add_parser("show", help="everything stored about one job, and why it got its status")
    p.add_argument("job_id", type=int)
    p.add_argument("-d", "--description", action="store_true", help="print the full description too")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("stats", help="counts by status and source")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("sources", help="which sources are enabled")
    p.set_defaults(func=cmd_sources)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs full request URLs at INFO, which would put the SerpApi key in logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return args.func(args)
