"""Application tracking: stages, the timeline, follow-up dates, ghosting, stats.

A job you act on gets one `applications` row. Its history is in `events`, and
every email sent is in `sent_mail` (see mailer.py). None of these tables are
touched by `reclassify`. Their queries are in store/applications.py and store/mail.py.

Stages, in order (models.STAGES): new -> saved -> reached_out -> replied ->
interviewing -> offer, plus closed (with a reason: rejected, ghosted, skipped). "New" is a job
you have not acted on yet: no row, or a row that only holds a draft or a
contact the daily run found. "Reached out" covers both applying through the posting and emailing a
person; `applied_at` and `emailed_at` say which.

Follow-ups come due on business days (Mon-Fri): 4 days after the first email,
then 7 more (config/outreach.json). They are never sent automatically. A job
that gets no reply is closed as ghosted once the whole schedule plus
`ghost_after_business_days` has passed, whether or not the follow-ups were
sent. A reply that arrives later moves it back to replied.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from .config import OutreachConfig
from .errors import BadRequest
from .hunter import size_upper_bound
from .models import CLOSED, NEW, REACHED_OUT, REPLIED, SAVED, SHORTLISTED, STAGE_LABELS, STAGES, VISA_LIST
from .store import JobStore
from .store.applications import (
    add_event, applied_count, bounce_count, first_emails, follow_ups_due, get_application, ghost_candidates,
    ghosted_since, insert_application, replied, stage_counts, update_application,
)
from .store.companies import mark_bounced
from .store.lists import new_jobs
from .store.mail import sends_since, sent_count_since, unsure_sends
from .text import iso, parse_datetime

CLOSED_REASONS = ("rejected", "ghosted", "skipped")
# Why you skipped a job: one tap, plus an optional note in your own words. The fit grade
# (fitgrade.py) shows these to the model with the job, so later grades follow them.
SKIP_REASONS = {
    "too_senior": "Too senior",
    "wrong_stack": "Wrong stack",
    "not_open": "Not open to me",
    "junk": "Agency, repost or gig",
    "not_my_role": "Not my kind of role",
    "low_pay": "Pay too low",
    "other": "Other",
}

# Stages a reply can move a job out of. Interviewing/offer are ahead of a reply already.
_BEFORE_REPLY = {NEW, SAVED, REACHED_OUT, CLOSED}


class TrackingError(BadRequest):
    """A request that makes no sense for the job's current state. The message is shown to you."""


def add_business_days(start: datetime, days: int) -> datetime:
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def ghost_date(emailed_at: datetime, config: OutreachConfig) -> datetime:
    total = sum(config.follow_up_business_days) + config.ghost_after_business_days
    return add_business_days(emailed_at, total)


def local_day(dt: datetime) -> str:
    return dt.astimezone().date().isoformat()


# --- rows -------------------------------------------------------------------


def ensure_application(store: JobStore, job_id: int, now: datetime) -> sqlite3.Row:
    row = get_application(store, job_id)
    if row:
        return row
    if not store.get(job_id):
        raise TrackingError(f"no job #{job_id}")
    insert_application(store, job_id, NEW, now)
    return get_application(store, job_id)


def _stage_label(stage: str, reason: str | None) -> str:
    return STAGE_LABELS[stage] + (f" ({reason})" if stage == CLOSED and reason else "")


def set_stage(store: JobStore, job_id: int, stage: str, now: datetime, reason: str | None = None,
              detail: str = "", skip_reason: str | None = None, skip_note: str = "") -> sqlite3.Row:
    """`skip_reason` (a SKIP_REASONS key) and `skip_note` only when closing as skipped; both optional."""
    if stage not in STAGES:
        raise TrackingError(f"unknown stage {stage!r}")
    if stage == CLOSED and reason not in CLOSED_REASONS:
        raise TrackingError(f"closing needs a reason: {', '.join(CLOSED_REASONS)}")
    if skip_reason and skip_reason not in SKIP_REASONS:
        raise TrackingError(f"unknown skip reason {skip_reason!r}: {', '.join(SKIP_REASONS)}")
    row = ensure_application(store, job_id, now)
    reason = reason if stage == CLOSED else None
    skipped = reason == "skipped"
    why = (skip_reason or None) if skipped else None
    note = " ".join((skip_note or "").split())[:300] if skipped else ""
    if row["stage"] == stage and row["closed_reason"] == reason and (
            not skipped or (row["skip_reason"], row["skip_note"] or "") == (why, note)):
        return row
    # next_follow_up_at is kept: follow-ups are only shown for jobs in "reached
    # out", so moving a job away and back restores its schedule.
    update_application(store, job_id, {"stage": stage, "closed_reason": reason, "skip_reason": why,
                                       "skip_note": note or None}, now)
    text = f"{_stage_label(row['stage'], row['closed_reason'])} → {_stage_label(stage, reason)}"
    said = ", ".join(x for x in (SKIP_REASONS.get(why or ""), note) if x)
    add_event(store, job_id, "stage", text + (f": {said}" if said else "") + (f": {detail}" if detail else ""), now)
    return get_application(store, job_id)


def update_notes(store: JobStore, job_id: int, notes: str, now: datetime) -> None:
    ensure_application(store, job_id, now)
    update_application(store, job_id, {"notes": notes}, now)


def mark_applied(store: JobStore, job_id: int, when: datetime | None, now: datetime) -> sqlite3.Row:
    """Applied through the posting. `when=None` clears it."""
    row = ensure_application(store, job_id, now)
    update_application(store, job_id, {"applied_at": iso(when) if when else None}, now)
    if when:
        add_event(store, job_id, "applied", f"Applied through the posting ({local_day(when)})", now)
        if row["stage"] in (NEW, SAVED):
            set_stage(store, job_id, REACHED_OUT, now)
    else:
        add_event(store, job_id, "applied", "Applied date cleared", now)
    return get_application(store, job_id)


# --- email lifecycle (called by mailer.py) -----------------------------------


def record_sent(store: JobStore, job_id: int, seq: int, to_addr: str, now: datetime,
                config: OutreachConfig) -> None:
    row = ensure_application(store, job_id, now)
    schedule = config.follow_up_business_days
    next_due = add_business_days(now, schedule[seq]) if seq < len(schedule) else None
    values: dict = {"follow_ups": seq, "next_follow_up_at": iso(next_due) if not row["replied_at"] else None}
    if seq == 0:
        values["emailed_at"] = iso(now)
    update_application(store, job_id, values, now)
    what = "Emailed" if seq == 0 else f"Follow-up {seq} sent"
    add_event(store, job_id, "emailed" if seq == 0 else "follow_up", f"{what} to {to_addr}", now)
    if row["stage"] in (NEW, SAVED, CLOSED):
        set_stage(store, job_id, REACHED_OUT, now)


def record_reply(store: JobStore, job_id: int, when: datetime, sender: str, snippet: str, now: datetime,
                 ref: str, probable: bool = False) -> bool:
    row = ensure_application(store, job_id, now)
    what = "Probable reply" if probable else "Reply"
    if not add_event(store, job_id, "replied", f"{what} from {sender}: {snippet[:200]}", now, ref=ref):
        return False
    update_application(store, job_id, {
        "replied_at": row["replied_at"] or iso(when), "reply_from": sender, "reply_snippet": snippet[:500],
        "next_follow_up_at": None,
    }, now)
    if row["stage"] in _BEFORE_REPLY:
        set_stage(store, job_id, REPLIED, now, detail=f"{what.lower()} from {sender}")
    return True


def record_auto_reply(store: JobStore, job_id: int, sender: str, subject: str, now: datetime, ref: str) -> bool:
    return add_event(store, job_id, "auto_reply", f"Auto-reply from {sender}: {subject[:150]}", now, ref=ref)


def record_bounce(store: JobStore, job_id: int, address: str, detail: str, now: datetime, ref: str) -> bool:
    if not add_event(store, job_id, "bounced", f"Bounced: {address} ({detail[:150]})", now, ref=ref):
        return False
    mark_bounced(store, address)
    if get_application(store, job_id):
        update_application(store, job_id, {"next_follow_up_at": None}, now)
    return True


def apply_ghosting(store: JobStore, now: datetime, config: OutreachConfig) -> list[int]:
    """Close as ghosted the jobs emailed long enough ago with no reply. Returns their ids."""
    ghosted = []
    for row in ghost_candidates(store):
        if now >= ghost_date(parse_datetime(row["emailed_at"]), config):
            set_stage(store, row["job_id"], CLOSED, now, reason="ghosted",
                      detail="no reply after the first email and the follow-up schedule")
            add_event(store, row["job_id"], "ghosted", "No reply: closed as ghosted", now)
            ghosted.append(row["job_id"])
    return ghosted


# --- applied, no email yet ---------------------------------------------------------


def reached_out_at(row) -> str | None:
    """When you reached out: the later of applying and emailing. A job you moved to Reached out
    by hand has neither, so it is when you moved it. `row` has store.lists.OUTREACH_COLUMNS."""
    dates = [d for d in (row["applied_at"], row["emailed_at"]) if d]
    if dates:
        return max(dates, key=parse_datetime)
    return row["moved_to_reached_out_at"] or row["application_updated_at"]


# --- sending limits -----------------------------------------------------------


def sends_today(store: JobStore, now: datetime) -> dict:
    """Real emails sent (or being sent) on today's local date. Test sends to yourself do not count."""
    today = local_day(now)
    total = guessed = 0
    for row in sends_since(store, now - timedelta(days=2)):
        if local_day(parse_datetime(row["created_at"])) == today:
            total += 1
            guessed += row["guessed"]
    return {"total": total, "guessed": guessed}


# --- views --------------------------------------------------------------------


def today(store: JobStore, now: datetime, config: OutreachConfig) -> dict:
    replies = replied(store)
    due = follow_ups_due(store, now)
    week_ago = now - timedelta(days=7)
    new_shortlisted = new_jobs(store, SHORTLISTED, week_ago)
    new_visa = new_jobs(store, VISA_LIST, week_ago)
    ghosted = ghosted_since(store, week_ago)
    unsure = unsure_sends(store, now - timedelta(minutes=2))
    return {
        "replies": [dict(r) for r in replies],
        "follow_ups_due": [dict(r) for r in due],
        "new_jobs": [dict(r) for r in new_shortlisted],
        "new_visa_jobs": [dict(r) for r in new_visa],
        "ghosted": [dict(r) for r in ghosted],
        "unsure_sends": [dict(r) for r in unsure],
        "sends_today": sends_today(store, now),
        "caps": {"total": config.daily_send_cap, "guessed": config.daily_guessed_cap},
    }


def _size_bucket(size_range: str | None, config: OutreachConfig) -> str:
    upper = size_upper_bound(size_range)
    if upper is None:
        return "unknown"
    return f"≤{config.small_company_max_employees}" if upper <= config.small_company_max_employees \
        else f">{config.small_company_max_employees}"


def stats(store: JobStore, now: datetime, config: OutreachConfig) -> dict:
    stages = {s: 0 for s in STAGES}
    closed: dict[str, int] = {}
    for row in stage_counts(store):
        stages[row["stage"]] += row["n"]
        if row["stage"] == CLOSED:
            closed[row["closed_reason"] or "?"] = row["n"]
    # Reply rate per contact role and company size, over jobs that got a real email.
    by_role: dict[str, dict] = {}
    by_size: dict[str, dict] = {}
    rows = first_emails(store)
    for row in rows:
        for table, key in ((by_role, row["role"] or "unknown"), (by_size, _size_bucket(row["size_range"], config))):
            entry = table.setdefault(key, {"emailed": 0, "replied": 0})
            entry["emailed"] += 1
            entry["replied"] += 1 if row["replied_at"] else 0
    sent_week = sent_count_since(store, now - timedelta(days=7))
    bounced = bounce_count(store)
    return {
        "stages": stages,
        "closed": closed,
        "emailed": len(rows),
        "replied": sum(1 for r in rows if r["replied_at"]),
        "bounced": bounced,
        "applied": applied_count(store),
        "by_role": by_role,
        "by_size": by_size,
        "sent_this_week": sent_week,
        "sends_today": sends_today(store, now),
    }


def warnings_of(row: sqlite3.Row | None) -> list[str]:
    return json.loads(row["draft_warnings_json"]) if row and row["draft_warnings_json"] else []
