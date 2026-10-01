"""The daily run's outreach step, after the jobs are stored and classified.

  1. contacts for this run's new shortlisted jobs, best fit first, within the
     day's share of Hunter credits (never in a date-range run);
  2. an email draft for each of them that has a contact;
  3. a tailored CV for each of them, best fit first (cv.py), which becomes the
     email attachment and what you upload when applying through the posting;
  4. a cover letter for each of them (cover.py), next to the CV;
  5. the inbox check (replies, bounces) and ghosting.

Steps 3 and 4 also catch up on shortlisted jobs from the last catch_up_days
that still have no CV or letter (one that failed on a network error at
wake-up is tried again the next day), within the same per-run caps. Only
jobs still at New or Saved, and not one that already has a CV you made for
that company (the PDF the email would attach).

Nothing is ever sent here. Each part catches its own errors, so a missing
network at wake-up or a bad key becomes a line in the log and the reports are
still written.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .config import OutreachConfig, Paths
from .contacts import build_finder, clean_company_name, find_contacts, run_budget
from .cover import build_cover_writer, cover_for_job, cover_of
from .cv import build_cv_writer, tailor_for_job, tailored_of
from .llm import error_line
from .mailer import check_inbox, mail_account
from .models import SHORTLISTED
from .pitch import build_writer, cv_for, draft_for_job, load_profile
from .store import JobStore
from . import tracking

log = logging.getLogger(__name__)

MAX_DRAFTS_PER_RUN = 15


def run_outreach(store: JobStore, paths: Paths, new_ids: list[int], now: datetime, ai: bool = True,
                 lookups: bool = True) -> dict:
    config = OutreachConfig.load(paths.outreach_file)
    summary: dict = {"contacts": None, "drafts": [], "cvs": [], "covers": [], "inbox": None, "notes": [], "errors": []}
    new_shortlisted = [row for row in (store.get(i) for i in new_ids) if row and row["status"] == SHORTLISTED]
    ready: list[int] = []

    if lookups and config.auto_lookup and new_shortlisted:
        try:
            finder, note = build_finder(config)
            if note:
                summary["notes"].append(note)
            use_claude = ai and config.claude_fallback_in_daily_run
            if finder and (finder.hunter or use_claude):
                limit = run_budget(finder.account(), now, config) if finder.hunter else config.max_companies_per_run
                run = find_contacts(store, finder, new_shortlisted, now, limit, use_claude=use_claude)
                summary["contacts"] = run.to_dict()
                ready = run.found_job_ids
        except Exception as exc:  # noqa: BLE001
            log.exception("contact lookup failed")
            summary["errors"].append(f"contacts: {error_line(exc)}")

    fixed = config.pitch_mode != "ai"
    if config.auto_draft and ready and (fixed or ai):
        try:
            writer, note = (None, None) if fixed else build_writer(config)
            if note:
                summary["notes"].append(note)
            if fixed or writer:
                profile = load_profile(paths.profile_file)
                for job_id in ready[:MAX_DRAFTS_PER_RUN]:
                    app = tracking.get_application(store, job_id)
                    if app and app["body"]:
                        continue  # a draft exists; the button rewrites it
                    try:
                        status = draft_for_job(store, job_id, writer, profile, config, now)
                        summary["drafts"].append(f"#{job_id}: {status}")
                    except Exception as exc:  # noqa: BLE001
                        summary["errors"].append(f"draft #{job_id}: {error_line(exc)}")
        except Exception as exc:  # noqa: BLE001
            log.exception("drafting failed")
            summary["errors"].append(f"drafts: {error_line(exc)}")

    # Date-range runs skip these too: they can hold a month of jobs.
    if lookups and ai:
        waiting = to_prepare(store, new_shortlisted, config, now)
        new_ids_set = {row["id"] for row in new_shortlisted}

        def has_cv(row, app) -> bool:
            if tailored_of(app):
                return True
            # An older job may already have a CV you made for the company: the one the email attaches.
            chosen = cv_for(config, clean_company_name(row["company"])[0], app["cv_file"] if app else None)
            return row["id"] not in new_ids_set and chosen is not None and chosen.name != config.default_cv

        if config.auto_tailor:
            prepare(summary, "cvs", "cv", waiting, has_cv, config.max_cvs_per_run, lambda: build_cv_writer(config),
                    lambda writer, job_id: tailor_for_job(store, job_id, writer, paths.profile_file, config, now,
                                                          pick=False)["file"], store)
        if config.auto_cover:
            prepare(summary, "covers", "cover", waiting, lambda row, app: bool(cover_of(app)), config.max_covers_per_run,
                    lambda: build_cover_writer(config),
                    lambda writer, job_id: cover_for_job(store, job_id, writer, paths.profile_file, config, now)["file"],
                    store)

    try:
        account = mail_account()
        if account:
            summary["inbox"] = check_inbox(store, account, config, now).to_dict()
        else:
            ghosted = tracking.apply_ghosting(store, now, config)
            store.commit()
            if ghosted:
                summary["notes"].append(f"{len(ghosted)} closed as ghosted")
    except Exception as exc:  # noqa: BLE001
        log.exception("inbox check failed")
        summary["errors"].append(f"inbox: {error_line(exc)}")
    return summary


def to_prepare(store: JobStore, new_shortlisted: list, config: OutreachConfig, now: datetime) -> list:
    """This run's new shortlisted jobs, best fit first, then older ones from the last catch_up_days.

    Older jobs only while they are New or Saved: one you reached out about, or closed, is left alone.
    """
    def best_first(rows):
        return sorted(rows, key=lambda row: -(row["fit_score"] or 0))

    rows = best_first(new_shortlisted)
    if config.catch_up_days > 0:
        since = (now.astimezone().date() - timedelta(days=config.catch_up_days)).isoformat()
        seen = {row["id"] for row in rows}
        older = store.conn.execute(
            "SELECT jobs.* FROM jobs LEFT JOIN applications ON applications.job_id = jobs.id "
            "WHERE jobs.status = ? AND jobs.report_date >= ? AND COALESCE(applications.stage, ?) IN (?, ?)",
            (SHORTLISTED, since, tracking.NEW, tracking.NEW, tracking.SAVED),
        ).fetchall()
        rows += best_first(row for row in older if row["id"] not in seen)
    return rows


def prepare(summary: dict, key: str, label: str, rows: list, done, limit: int, build, make, store: JobStore) -> None:
    """Make one thing (a CV, a cover letter) for each job in `rows` that has none yet, up to `limit`."""
    try:
        todo = [row for row in rows if not done(row, tracking.get_application(store, row["id"]))]  # the button redoes one
        if not todo:
            return
        writer, note = build()
        if note:
            summary["notes"].append(note)
        if writer is None:
            return
        for row in todo[:limit]:
            try:
                summary[key].append(f"#{row['id']}: {make(writer, row['id'])}")
            except Exception as exc:  # noqa: BLE001
                summary["errors"].append(f"{label} #{row['id']}: {error_line(exc)}")
    except Exception as exc:  # noqa: BLE001
        log.exception("%s step failed", label)
        summary["errors"].append(f"{key}: {error_line(exc)}")
