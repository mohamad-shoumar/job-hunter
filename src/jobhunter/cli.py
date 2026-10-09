"""Command line: `jobhunter run | serve | contacts | inbox | check | report | reclassify | show | stats | sources`."""

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
    if not paths.profile_file.exists():
        # Your profile is not in git: a fresh copy of the project starts from the example.
        print(f"No {paths.profile_file.relative_to(paths.root)} yet, so no CVs, cover letters or emails: copy "
              "profile/master_profile.example.md there and fill it in.", file=sys.stderr)
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
        paths, sources_config, filters, only=only, report=not args.no_report, date_range=date_range, ai=not args.no_ai,
        outreach=not args.no_outreach,
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
    if summary.outreach:
        o = summary.outreach
        if o["contacts"]:
            c = o["contacts"]
            print(f"Contacts: {c['found']} found for {c['looked_up']} companies, {c['credits']:g} Hunter credits, "
                  f"about ${c['cost_usd']:.2f}")
        if o["drafts"]:
            print(f"Drafts: {len(o['drafts'])}")
        if o.get("cvs"):
            print(f"CVs tailored: {', '.join(o['cvs'])}")
        if o.get("covers"):
            print(f"Cover letters: {', '.join(o['covers'])}")
        if o["inbox"]:
            i = o["inbox"]
            print(f"Inbox: {i['replies']} replies, {i['probable']} probable, {i['bounces']} bounces")
        for line in o["notes"] + o["errors"]:
            print(f"  {line}")
        print("Open `jobhunter serve` to see contacts and send emails.\n")
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
        print(f"checking {len(rows)} of {waiting} jobs with {checker.label}\n")

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
            job = row_to_job(row)
            job.required_yoe = None  # no source sets it: it is always read from the text
            job = enrich(job)  # re-extract too, so extraction changes apply
            store.update_extracted(row["id"], job)
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


def cmd_serve(args) -> int:
    """The local web app: jobs, contacts, email drafts, sending, tracking."""
    import secrets
    import threading
    import webbrowser

    paths, _, _ = _load(args)
    try:
        import uvicorn

        from .web.app import create_app
    except ImportError:
        raise SystemExit("the web app needs FastAPI: .venv/bin/pip install -e '.[web]'") from None
    port = args.port
    token = secrets.token_urlsafe(24)
    app = create_app(paths, token, allowed_hosts=[f"127.0.0.1:{port}", f"localhost:{port}"])
    url = f"http://127.0.0.1:{port}/"
    print(f"jobhunter on {url}  (Ctrl+C to stop)")
    if not args.no_open:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


def cmd_tailor(args) -> int:
    """A CV tailored to each job: versions/<name>.md and its PDF in the resume folder, attached to the job."""
    from .config import OutreachConfig
    from .cv import build_cv_writer, tailor_for_job

    paths, _, _ = _load(args)
    config = OutreachConfig.load(paths.outreach_file)
    writer, note = build_cv_writer(config)
    if writer is None:
        raise SystemExit(note)
    store = JobStore(paths.db_file)
    try:
        for job_id in args.job_ids:
            meta = tailor_for_job(store, job_id, writer, paths.profile_file, config, utcnow(),
                                  replace_edits=args.replace_edits)
            print(f"#{job_id}: {Path(config.cv_dir).expanduser() / meta['file']} ({meta['pages']} page"
                  f"{'s' if meta['pages'] != 1 else ''}, {meta['model']}, about ${meta['cost_usd']:.3f})")
            print(f"  headline: {meta['headline']}")
            for line in meta["changes"]:
                print(f"  - {line}")
            for line in meta["notes"]:
                print(f"  ! {line}")
            if meta["gaps"]:
                print(f"  the posting asks for, not in your profile: {', '.join(meta['gaps'])}")
    finally:
        store.close()
    return 0


def cmd_cover(args) -> int:
    """A cover letter for each job: <cv_dir>/<Name>_CoverLetter_<Company>_<MonYYYY>.md, checked against the profile."""
    from .config import OutreachConfig
    from .cover import build_cover_writer, cover_for_job

    paths, _, _ = _load(args)
    config = OutreachConfig.load(paths.outreach_file)
    writer, note = build_cover_writer(config)
    if writer is None:
        raise SystemExit(note)
    store = JobStore(paths.db_file)
    try:
        for job_id in args.job_ids:
            meta = cover_for_job(store, job_id, writer, paths.profile_file, config, utcnow())
            print(f"#{job_id}: {meta['path']} ({meta['words']} words, {meta['model']}, about ${meta['cost_usd']:.3f})")
            for line in meta["notes"]:
                print(f"  - {line}")
            for line in meta["removed"]:
                print(f"  ! removed by the checks: {line}")
            for line in meta["warnings"]:
                print(f"  ? {line}")
            if meta["gaps_named"]:
                print(f"  says you have not worked with: {', '.join(meta['gaps_named'])}")
    finally:
        store.close()
    return 0


def cmd_rebuild_cv(args) -> int:
    """After you edit a job's CV text by hand: rebuild its PDF (no model) and list lines to look at."""
    from .config import OutreachConfig
    from .cv import TailorError, save_version

    paths, _, _ = _load(args)
    config = OutreachConfig.load(paths.outreach_file)
    store = JobStore(paths.db_file)
    try:
        for job_id in args.job_ids:
            try:
                result = save_version(store, job_id, config, paths.profile_file, utcnow())
            except TailorError as exc:
                print(f"#{job_id}: {exc}")
                continue
            folder = Path(config.resume_dir).expanduser()
            print(f"#{job_id}: {folder / result['source']} -> {Path(config.cv_dir).expanduser() / result['file']} "
                  f"({result['pages']} page{'s' if result['pages'] != 1 else ''})")
            for line in result["notes"]:
                print(f"  ! {line}")
            if result["checks"]:
                print("  These lines say more than your profile; look at them:")
            for line in result["checks"]:
                print(f"  - {line}")
    finally:
        store.close()
    return 0


def cmd_contacts(args) -> int:
    """Find who to email for given jobs, or for shortlisted jobs that have no contact yet (best fit first)."""
    from .config import OutreachConfig
    from .contacts import build_finder, find_contacts

    paths, _, _ = _load(args)
    config = OutreachConfig.load(paths.outreach_file)
    finder, note = build_finder(config)
    if finder is None:
        raise SystemExit(note)
    if note:
        print(note)
    now = utcnow()
    store = JobStore(paths.db_file)
    try:
        if args.job_ids:
            rows = [r for r in (store.get(i) for i in args.job_ids) if r]
        else:
            rows = store.conn.execute(
                "SELECT * FROM jobs WHERE status = 'shortlisted' AND report_date IS NOT NULL ORDER BY id DESC"
            ).fetchall()
        account = finder.account()
        if account and account.remaining is not None:
            print(f"Hunter: {account.remaining:g} credits left, reset {account.reset_date}")

        def show(job, lookup):
            from .contacts import chosen_contact

            contact = chosen_contact(store, job, config)
            who = (f"{contact['full_name']} ({contact['position'] or contact['role']}) "
                   f"<{contact['email'] or '?'}> [{contact['email_status'] or 'no email'}]") if contact else "-"
            print(f"#{job['id']:<5} {lookup.company[:28]:28} {lookup.status:9} {who}")
            if lookup.note:
                print(f"       {lookup.note}")

        run = find_contacts(store, finder, rows, now, args.limit, use_claude=not args.no_claude, on_result=show)
    finally:
        store.close()
    print(f"\n{run.looked_up} looked up, {run.found} found, {run.skipped} job boards, "
          f"{run.credits:g} credits, about ${run.cost_usd:.2f}")
    for line in run.notes + run.errors:
        print(f"  {line}")
    return 0


def cmd_inbox(args) -> int:
    """Check Gmail for replies and bounces to the emails sent from the app."""
    from .config import OutreachConfig
    from .mailer import check_inbox, mail_account

    paths, _, _ = _load(args)
    account = mail_account()
    if account is None:
        raise SystemExit("set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env")
    store = JobStore(paths.db_file)
    try:
        result = check_inbox(store, account, OutreachConfig.load(paths.outreach_file), utcnow())
    finally:
        store.close()
    print(f"{result.scanned} new messages: {result.replies} replies, {result.probable} probable, "
          f"{result.auto_replies} auto-replies, {result.bounces} bounces")
    for line in result.resolved + result.notes:
        print(f"  {line}")
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
    p.add_argument("--no-ai", action="store_true", help="no Claude calls: skip the AI web check and email drafts")
    p.add_argument("--no-outreach", action="store_true", help="skip contact lookups, drafts and the inbox check")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("serve", help="the local web app: jobs, who to contact, email drafts, sending, tracking")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-open", action="store_true", help="do not open the browser")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser(
        "contacts",
        help="find who to email (Hunter, then Claude) for jobs, or for shortlisted jobs without a contact",
        description="Per company, once. Without ids: shortlisted jobs that are in a report, best fit first.",
    )
    p.add_argument("job_ids", type=int, nargs="*")
    p.add_argument("--limit", type=int, metavar="N", help="look up at most N new companies")
    p.add_argument("--no-claude", action="store_true", help="Hunter only, no Claude web search")
    p.set_defaults(func=cmd_contacts)

    p = sub.add_parser(
        "tailor",
        help="tailor your CV to jobs (resume.md layout, profile facts) and attach it to them",
        description="The model picks, orders and rewords your profile's bullets and skills for the posting; code "
        "checks every line against profile/master_profile.md. Writes versions/<name>.md and its PDF in "
        "resume_dir (config/outreach.json), and makes the PDF the job's email attachment.",
    )
    p.add_argument("job_ids", type=int, nargs="+")
    p.add_argument("--replace-edits", action="store_true", help="tailor again even if you edited the CV by hand")
    p.set_defaults(func=cmd_tailor)

    p = sub.add_parser(
        "rebuild-cv",
        help="rebuild a job's CV PDF after you edited its text, and list lines that say more than your profile",
        description="Edit resume/versions/<name>.md in any editor (delete a line, or put // in front of it), then "
        "run this: build.py rebuilds the PDF with no model, so what you wrote is what prints. Works for tailored "
        "CVs and ones you made by hand. The Edit CV text button in `jobhunter serve` does the same.",
    )
    p.add_argument("job_ids", type=int, nargs="+")
    p.set_defaults(func=cmd_rebuild_cv)

    p = sub.add_parser(
        "cover",
        help="write a cover letter for jobs from your profile facts, next to the tailored CVs",
        description="The model writes the opening, one or two paragraphs citing your profile facts, and the "
        "closing; code checks every sentence against profile/master_profile.md and leaves out one that "
        "adds anything. Writes <Name>_CoverLetter_<Company>_<MonYYYY>.md in cv_dir (config/outreach.json).",
    )
    p.add_argument("job_ids", type=int, nargs="+")
    p.set_defaults(func=cmd_cover)

    p = sub.add_parser("inbox", help="check Gmail for replies and bounces (also runs in the daily run)")
    p.set_defaults(func=cmd_inbox)

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
