"""Command line: `jobhunter run | serve | contacts | inbox | check | report | reclassify | show | stats | boards |
sources | sponsors`."""

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
from .posted_date import build_finder, find_dates
from .classify import classify, recheck_age
from .config import Filters, Paths, load_dotenv, load_json, resolve_root
from .extract import enrich
from .fitgrade import build_grader, grade_jobs, to_grade
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
    filters = Filters.load(paths.filters_file)
    if filters.visa:
        from .sponsors import Registers

        filters.visa.registers = Registers.load(paths.sponsors_dir)
    return paths, load_json(paths.sources_file), filters


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
        print(f"{path}   {c['shortlisted']} shortlisted, {c['needs_review']} need review, "
              f"{c['visa_list']} on the visa list, {c['rejected']} rejected")


def cmd_run(args) -> int:
    paths, sources_config, filters = _load(args)
    only = {s.strip() for s in args.sources.split(",")} if args.sources else None
    skip = {s.strip() for s in args.skip.split(",")} if args.skip else None
    date_range = _date_range(args)
    options = pipeline.RunOptions(only=only, skip=skip, report=not args.no_report, date_range=date_range,
                                  ai=not args.no_ai, outreach=not args.no_outreach)
    summary, report_paths = pipeline.run(paths, sources_config, filters, options)
    for name, stats in sorted(summary.sources.items()):
        flag = f"  ({len(stats.errors)} errors)" if stats.errors else ""
        print(f"{name:16} {stats.fetched:5} listings  {stats.new:4} new{flag}")
    breakdown = ", ".join(f"{v} {k}" for k, v in summary.new_by_status.most_common())
    print(f"\n{summary.new} new jobs" + (f": {breakdown}" if breakdown else "") + "\n")
    if summary.date_check:
        dc = summary.date_check
        found = ", ".join(f"{n} {v}" for v, n in dc.found.items()) or "none"
        print(f"Posting dates: {dc.checked} undated jobs looked up ({found})")
        for line in dc.notes + dc.errors:
            print(f"  {line}")
        print()
    if summary.ai_check:
        ai = summary.ai_check
        verdicts = ", ".join(f"{n} {v}" for v, n in ai.verdicts.items()) or "none"
        print(f"AI check: {ai.checked} jobs ({verdicts}), about ${ai.cost_usd:.2f}")
        for line in ai.notes + ai.errors:
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
    if summary.boards and (summary.boards.added or summary.boards.errors):
        print(f"Boards now watched: {len(summary.boards.added)}")
        for added in summary.boards.added:
            print(f"  {added['board']} ({added['company']}): {added['reason']}")
        for line in summary.boards.errors:
            print(f"  {line}")
        print()
    store = JobStore(paths.db_file)
    try:
        _print_report_counts(store, report_paths)
    finally:
        store.close()
    return 0


def cmd_boards(args) -> int:
    """The company boards watched because a job there was shortlisted (boards.py)."""
    from . import boards
    from .store.watched import watched_boards

    paths, _, _ = _load(args)
    store = JobStore(paths.db_file)
    try:
        if args.remove:
            if not boards.remove(store, args.remove, utcnow()):
                raise SystemExit(f"not watched: {args.remove} (write it as kind:slug, e.g. ashby:dualentry)")
            print(f"stopped watching {args.remove}; it will not be added again")
            return 0
        rows = watched_boards(store, include_removed=args.all)
    finally:
        store.close()
    if not rows:
        print("no watched boards yet: one is added when a job at a company with a public board is shortlisted")
    for row in rows:
        removed = f"  (removed {row['removed_at'][:10]})" if row["removed_at"] else ""
        print(f"{row['kind'] + ':' + row['slug']:32} {row['company']}  added {row['added_at'][:10]}{removed}")
        print(f"{'':32} {row['reason']}")
    return 0


def cmd_sponsors(args) -> int:
    """The government lists of visa sponsors the visa list checks companies against (sponsors.py)."""
    from . import sponsors
    from .http import Http

    paths, _, filters = _load(args)
    if args.update:
        with Http(timeout=120) as http:
            done, errors = sponsors.update(http, paths.sponsors_dir, utcnow())
        for line in done + errors:
            print(line)
        print("run `jobhunter reclassify` to re-check stored jobs against them")
        return 1 if errors and not done else 0
    registers = filters.visa.registers if filters.visa else None
    if args.company:
        if not registers or not registers.index:
            raise SystemExit("no lists downloaded yet: run `jobhunter sponsors --update`")
        for country, name in sponsors.LISTS.items():
            row = registers.find(country, args.company, [args.place or ""])
            print(f"{country}: {row.quote() if row else 'not found'}  ({name})")
        return 0
    for country, name in sponsors.LISTS.items():
        meta = registers.meta.get(country) if registers else None
        if meta:
            print(f"{country}: {meta['rows']:,} employers, {name}; updated {meta.get('updated') or '?'}, "
                  f"fetched {(meta.get('fetched_at') or '?')[:10]}")
        else:
            print(f"{country}: not downloaded ({name}); run `jobhunter sponsors --update`")
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


def cmd_grade(args) -> int:
    """AI fit grade for shown jobs: given ids, or the open (New or Saved) ungraded ones from the last days."""
    paths, _, filters = _load(args)
    grader, note = build_grader(paths.fit_grade_file, require_enabled=False)
    if grader is None:
        raise SystemExit(note or "fit grades are off")
    now = utcnow()
    store = JobStore(paths.db_file)
    try:
        if args.job_ids:
            rows = [row for row in (store.get(i) for i in args.job_ids) if row]
        else:
            rows = to_grade(store, now, args.days or grader.config.lookback_days, regrade=args.regrade)
        waiting = len(rows)
        rows = rows[: args.limit or None] if not args.job_ids else rows
        if not rows:
            print("nothing to grade")
            return 0
        print(f"grading {len(rows)} of {waiting} jobs with {grader.label}\n")

        def show(row, grade):
            print(f"#{row['id']:<5} {grade['grade']}/5  {row['company']} — {row['title']}")
            print(f"       {grade['reason']}")

        result = grade_jobs(store, grader, rows, paths.profile_file, now, on_result=show)
        rebuilt = [write_report(store, paths.reports_dir, day, store.last_run_stats(), now, filters.max_posting_age_days)
                   for day in sorted(result.changed_days)]
    finally:
        store.close()
    print(f"\n{result.graded} graded (learning from {result.examples or 'no examples'}), about ${result.cost_usd:.3f}")
    for line in result.notes + result.errors:
        print(f"  {line}")
    for path in rebuilt:
        print(f"rebuilt {path}")
    return 1 if result.errors and not result.graded else 0


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


def cmd_dates(args) -> int:
    """Posting dates for undated needs_review jobs: given ids, or the ones not looked up yet, newest first."""
    paths, _, filters = _load(args)
    finder, note = build_finder(paths.ai_check_file, require_enabled=False)
    if note:
        print(note)
    now = utcnow()
    store = JobStore(paths.db_file)
    try:
        if args.job_ids:
            rows = []
            for job_id in args.job_ids:
                row = store.get(job_id)
                if row is None:
                    print(f"#{job_id}: no such job")
                elif row["posted_at"] and not row["date_check_json"]:
                    print(f"#{job_id}: skipped, its source gave a date ({row['posted_at'][:10]})")
                else:
                    rows.append(row)
            waiting = len(rows)
        else:
            rows = store.needs_date_check(recheck=args.recheck)
            waiting = len(rows)
            rows = rows[: args.limit or finder.config.max_dates_per_run]
        if not rows:
            print("nothing to look up")
            return 0
        how = "job pages" + ("" if finder.model is None else f", then {finder.label}")
        print(f"looking up {len(rows)} of {waiting} undated jobs ({how})\n")

        def show(row, check, cls):
            print(f"#{row['id']:<5} {row['company']} — {row['title']}")
            print(f"       {check.posted_at[:10] if check.posted_at else 'no date'} -> {cls.status}: {check.reason}")
            if check.quote:
                print(f'       "{check.quote}" ({check.source_url})')

        result = find_dates(store, finder, rows, filters, now, on_result=show)
        rebuilt = [write_report(store, paths.reports_dir, day, store.last_run_stats(), now, filters.max_posting_age_days)
                   for day in sorted(result.changed_days)]
    finally:
        store.close()
    print(f"\n{result.checked} looked up")
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
    pending: list = []

    def save() -> None:
        # A run takes minutes: the jobs are judged with no write lock held and
        # saved 100 at a time, so the web app's saves never wait long.
        for job_id, job, cls in pending:
            store.update_extracted(job_id, job)
            store.update_classification(job_id, cls)
        store.commit()
        pending.clear()

    try:
        for row in store.all_jobs():
            job = row_to_job(row)
            job.required_yoe = None  # no source sets it: it is always read from the text
            job = enrich(job)  # re-extract too, so extraction changes apply
            cls = classify(job, filters, now, check_age=recheck_age(row))
            if cls.status != row["status"] or cls.eligibility.verdict != row["eligibility"]:
                changes[f"{row['status']} -> {cls.status}"] += 1
                if row["report_date"]:
                    changed_days.add(row["report_date"])
            pending.append((row["id"], job, cls))
            if len(pending) == 100:
                save()
        save()
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
    print("jobs that became shortlisted/needs_review/visa_list and were never reported go into the next daily report")
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
    if row["date_check_json"]:
        dc = json.loads(row["date_check_json"])
        print(f"posting date: {dc['posted_at'][:10] if dc['posted_at'] else 'not found'}"
              f"  [{dc['found_by']}, {dc['checked_at'][:10]}]")
        print(f"  - {dc['reason']}")
        if dc["quote"]:
            print(f'  - "{dc["quote"]}" ({dc["source_url"]})')
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
    """A cover letter for each job: <cv_dir>/<Name>_CoverLetter_<Company>_<MonYYYY>.md (why this company, then yours)."""
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
            print(f"  read: {', '.join(meta['pages']) or 'the posting only'}")
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
            rows = store.reported_shortlisted()
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
    p.add_argument("--skip", help="comma-separated source names to leave out, e.g. serpapi")
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
        help="write a two-paragraph cover letter for jobs, next to the tailored CVs",
        description="Paragraph 1 is why you want to join the company: the model writes it from the posting and "
        "pages code fetches from the company's site, and code checks every name and number against them and "
        "your profile. Paragraph 2 is cover_paragraph (config/outreach.json), word for word. Writes "
        "<Name>_CoverLetter_<Company>_<MonYYYY>.md in cv_dir.",
    )
    p.add_argument("job_ids", type=int, nargs="+")
    p.set_defaults(func=cmd_cover)

    p = sub.add_parser("inbox", help="check Gmail for replies and bounces (also runs in the daily run)")
    p.set_defaults(func=cmd_inbox)

    p = sub.add_parser(
        "check",
        help="AI web check: can the company hire from Lebanon? (needs_review jobs; models in config/ai_check.json)",
        description="The model in config/ai_check.json reads the job's pages (DeepSeek), then searches the web for "
        "the ones it could not settle (web_model, e.g. Claude Code), and returns a verdict with a quote. The quote must be "
        "found word for word on the page before it changes a job's status. Without ids: the unchecked "
        "needs_review jobs, newest first, up to max_jobs_per_run from config/ai_check.json.",
    )
    p.add_argument("job_ids", type=int, nargs="*", help="check these jobs (again, if already checked)")
    p.add_argument("--limit", type=int, metavar="N", help="check at most N jobs (default: max_jobs_per_run)")
    p.add_argument("--recheck", action="store_true", help="include jobs already checked (unknown or unverified)")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser(
        "dates",
        help="find when undated needs_review jobs were posted (job pages, then web search; config/ai_check.json)",
        description="Code reads the schema.org datePosted on the job's own pages; when none has one, web_model "
        "(Claude Code) searches the web and quotes the words that state the date. Code finds the quote on the page "
        "and reads the date from it, then the age rule judges the job. Without ids: the undated needs_review jobs "
        "not looked up yet, newest first, up to max_dates_per_run.",
    )
    p.add_argument("job_ids", type=int, nargs="*", help="look up these jobs (again, if already looked up)")
    p.add_argument("--limit", type=int, metavar="N", help="look up at most N jobs (default: max_dates_per_run)")
    p.add_argument("--recheck", action="store_true", help="include jobs looked up before without finding a date")
    p.set_defaults(func=cmd_dates)

    p = sub.add_parser(
        "grade",
        help="AI fit grade 1-5 for shown jobs, learned from your Applied and skipped jobs (sorting only)",
        description="Each grade is one model call that reads your profile's facts, `preferences` in "
        "config/fit_grade.json, and your latest Applied and skipped jobs (with your skip reasons). It only "
        "sorts: it never changes a job's status. Without ids: the open (New or Saved) shortlisted, needs-review "
        "and visa-list jobs from the last lookback_days that have no grade yet.",
    )
    p.add_argument("job_ids", type=int, nargs="*", help="grade these jobs (again, if already graded)")
    p.add_argument("--regrade", action="store_true", help="grade open jobs again with today's examples")
    p.add_argument("--days", type=int, metavar="N", help="look back N report days (default: lookback_days)")
    p.add_argument("--limit", type=int, metavar="N", help="grade at most N jobs")
    p.set_defaults(func=cmd_grade)

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

    p = sub.add_parser("boards", help="company job boards watched because a job there was shortlisted")
    p.add_argument("--remove", metavar="KIND:SLUG", help="stop watching one, e.g. ashby:dualentry (never re-added)")
    p.add_argument("--all", action="store_true", help="include removed boards")
    p.set_defaults(func=cmd_boards)

    p = sub.add_parser("sources", help="which sources are enabled")
    p.set_defaults(func=cmd_sources)

    p = sub.add_parser("sponsors", help="government lists of visa sponsors (UK, NL, IE) for the visa list",
                       description="Without options: what is downloaded. The daily run refreshes them every "
                                   "refresh_days (visa_list in config/filters.json).")
    p.add_argument("--update", action="store_true", help="download the lists now")
    p.add_argument("--company", help="look a company up in each list")
    p.add_argument("--place", help="with --company: the job's town, for one-word names (e.g. London)")
    p.set_defaults(func=cmd_sponsors)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs full request URLs at INFO, which would put the SerpApi key in logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return args.func(args)
