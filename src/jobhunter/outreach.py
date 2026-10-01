"""The daily run's outreach step, after the jobs are stored and classified.

  1. contacts for this run's new shortlisted jobs, best fit first, within the
     day's share of Hunter credits (never in a date-range run);
  2. an email draft for each of them that has a contact;
  3. a tailored CV for each of them, best fit first (cv.py), which becomes the
     email attachment and what you upload when applying through the posting;
  4. the inbox check (replies, bounces) and ghosting.

Nothing is ever sent here. Each part catches its own errors, so a missing
network at wake-up or a bad key becomes a line in the log and the reports are
still written.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .config import OutreachConfig, Paths
from .contacts import build_finder, find_contacts, run_budget
from .cv import build_cv_writer, tailor_for_job, tailored_of
from .llm import error_line
from .mailer import check_inbox, mail_account
from .models import SHORTLISTED
from .pitch import build_writer, draft_for_job, load_profile
from .store import JobStore
from . import tracking

log = logging.getLogger(__name__)

MAX_DRAFTS_PER_RUN = 15


def run_outreach(store: JobStore, paths: Paths, new_ids: list[int], now: datetime, ai: bool = True,
                 lookups: bool = True) -> dict:
    config = OutreachConfig.load(paths.outreach_file)
    summary: dict = {"contacts": None, "drafts": [], "cvs": [], "inbox": None, "notes": [], "errors": []}
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

    # Date-range runs skip this too: they can hold a month of jobs.
    if lookups and ai and config.auto_tailor and new_shortlisted:
        try:
            writer, note = build_cv_writer(config)
            if note:
                summary["notes"].append(note)
            best_first = sorted(new_shortlisted, key=lambda row: -(row["fit_score"] or 0))
            for row in best_first[:config.max_cvs_per_run] if writer else []:
                if tailored_of(tracking.get_application(store, row["id"])):
                    continue  # the button tailors it again
                try:
                    meta = tailor_for_job(store, row["id"], writer, paths.profile_file, config, now, pick=False)
                    summary["cvs"].append(f"#{row['id']}: {meta['file']}")
                except Exception as exc:  # noqa: BLE001
                    summary["errors"].append(f"cv #{row['id']}: {error_line(exc)}")
        except Exception as exc:  # noqa: BLE001
            log.exception("tailoring failed")
            summary["errors"].append(f"cvs: {error_line(exc)}")

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
