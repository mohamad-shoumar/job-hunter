"""Application tracking: stages, the timeline, follow-up dates, ghosting, stats.

A job you act on gets one `applications` row. Its history is in `events`, and
every email sent is in `sent_mail` (see mailer.py). None of these tables are
touched by `reclassify`.

Stages, in order: new -> saved -> reached_out -> replied -> interviewing ->
offer, plus closed (with a reason: rejected, ghosted, skipped). "New" is a job
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
from .store import JobStore
from .text import iso, parse_datetime

NEW = "new"
SAVED = "saved"
REACHED_OUT = "reached_out"
REPLIED = "replied"
INTERVIEWING = "interviewing"
OFFER = "offer"
CLOSED = "closed"
STAGES = [NEW, SAVED, REACHED_OUT, REPLIED, INTERVIEWING, OFFER, CLOSED]
STAGE_LABELS = {
    NEW: "New", SAVED: "Saved", REACHED_OUT: "Reached out", REPLIED: "Replied",
    INTERVIEWING: "Interviewing", OFFER: "Offer", CLOSED: "Closed",
}
CLOSED_REASONS = ("rejected", "ghosted", "skipped")

# Stages a reply can move a job out of. Interviewing/offer are ahead of a reply already.
_BEFORE_REPLY = {NEW, SAVED, REACHED_OUT, CLOSED}


class TrackingError(ValueError):
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


def get_application(store: JobStore, job_id: int) -> sqlite3.Row | None:
    return store.conn.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()


def add_event(store: JobStore, job_id: int, kind: str, detail: str, now: datetime, ref: str | None = None) -> bool:
    """False when an event with the same (kind, ref) exists, so repeated inbox scans add nothing."""
    try:
        store.conn.execute(
            "INSERT INTO events (job_id, at, kind, detail, ref) VALUES (?, ?, ?, ?, ?)",
            (job_id, iso(now), kind, detail, ref),
        )
    except sqlite3.IntegrityError:
        return False
    return True


def events_for(store: JobStore, job_id: int) -> list[sqlite3.Row]:
    return store.conn.execute("SELECT * FROM events WHERE job_id = ? ORDER BY at, id", (job_id,)).fetchall()


def ensure_application(store: JobStore, job_id: int, now: datetime) -> sqlite3.Row:
    row = get_application(store, job_id)
    if row:
        return row
    if not store.get(job_id):
        raise TrackingError(f"no job #{job_id}")
    store.conn.execute(
        "INSERT INTO applications (job_id, stage, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (job_id, NEW, iso(now), iso(now)),
    )
    return get_application(store, job_id)


def _update(store: JobStore, job_id: int, values: dict, now: datetime) -> None:
    values = {**values, "updated_at": iso(now)}
    assignments = ", ".join(f"{k} = :{k}" for k in values)
    store.conn.execute(f"UPDATE applications SET {assignments} WHERE job_id = :job_id", {**values, "job_id": job_id})


def _stage_label(stage: str, reason: str | None) -> str:
    return STAGE_LABELS[stage] + (f" ({reason})" if stage == CLOSED and reason else "")


def set_stage(store: JobStore, job_id: int, stage: str, now: datetime, reason: str | None = None,
              detail: str = "") -> sqlite3.Row:
    if stage not in STAGES:
        raise TrackingError(f"unknown stage {stage!r}")
    if stage == CLOSED and reason not in CLOSED_REASONS:
        raise TrackingError(f"closing needs a reason: {', '.join(CLOSED_REASONS)}")
    row = ensure_application(store, job_id, now)
    reason = reason if stage == CLOSED else None
    if row["stage"] == stage and row["closed_reason"] == reason:
        return row
    # next_follow_up_at is kept: follow-ups are only shown for jobs in "reached
    # out", so moving a job away and back restores its schedule.
    _update(store, job_id, {"stage": stage, "closed_reason": reason}, now)
    text = f"{_stage_label(row['stage'], row['closed_reason'])} → {_stage_label(stage, reason)}"
    add_event(store, job_id, "stage", text + (f": {detail}" if detail else ""), now)
    return get_application(store, job_id)


def update_notes(store: JobStore, job_id: int, notes: str, now: datetime) -> None:
    ensure_application(store, job_id, now)
    _update(store, job_id, {"notes": notes}, now)


def mark_applied(store: JobStore, job_id: int, when: datetime | None, now: datetime) -> sqlite3.Row:
    """Applied through the posting. `when=None` clears it."""
    row = ensure_application(store, job_id, now)
    _update(store, job_id, {"applied_at": iso(when) if when else None}, now)
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
    _update(store, job_id, values, now)
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
    _update(store, job_id, {
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
    store.conn.execute(
        "UPDATE contacts SET email_status = 'bounced' WHERE lower(email) = lower(?)", (address,)
    )
    if get_application(store, job_id):
        _update(store, job_id, {"next_follow_up_at": None}, now)
    return True


def apply_ghosting(store: JobStore, now: datetime, config: OutreachConfig) -> list[int]:
    """Close as ghosted the jobs emailed long enough ago with no reply. Returns their ids."""
    ghosted = []
    # A job you moved back after it was ghosted once is left alone.
    rows = store.conn.execute(
        """
        SELECT * FROM applications a WHERE stage = ? AND emailed_at IS NOT NULL AND replied_at IS NULL
        AND NOT EXISTS (SELECT 1 FROM events e WHERE e.job_id = a.job_id AND e.kind = 'ghosted')
        """,
        (REACHED_OUT,),
    ).fetchall()
    for row in rows:
        if now >= ghost_date(parse_datetime(row["emailed_at"]), config):
            set_stage(store, row["job_id"], CLOSED, now, reason="ghosted",
                      detail="no reply after the first email and the follow-up schedule")
            add_event(store, row["job_id"], "ghosted", "No reply: closed as ghosted", now)
            ghosted.append(row["job_id"])
    return ghosted


# --- sending limits -----------------------------------------------------------


def sends_today(store: JobStore, now: datetime) -> dict:
    """Real emails sent (or being sent) on today's local date. Test sends to yourself do not count."""
    today = local_day(now)
    total = guessed = 0
    for row in store.conn.execute(
        "SELECT created_at, guessed FROM sent_mail WHERE kind != 'test' AND state != 'failed' AND created_at >= ?",
        (iso(now - timedelta(days=2)),),
    ):
        if local_day(parse_datetime(row["created_at"])) == today:
            total += 1
            guessed += row["guessed"]
    return {"total": total, "guessed": guessed}


def company_contacted(store: JobStore, company_key: str, job_id: int) -> list[sqlite3.Row]:
    """Emails already sent to anyone at this company for another job."""
    return store.conn.execute(
        """
        SELECT sm.*, j.title FROM sent_mail sm
        JOIN jobs j ON j.id = sm.job_id
        JOIN contacts c ON c.id = sm.contact_id
        WHERE c.company_key = ? AND sm.job_id != ? AND sm.kind != 'test' AND sm.state = 'sent'
        ORDER BY sm.created_at
        """,
        (company_key, job_id),
    ).fetchall()


# --- views --------------------------------------------------------------------


def today(store: JobStore, now: datetime, config: OutreachConfig) -> dict:
    replies = store.conn.execute(
        "SELECT a.*, j.title, j.company FROM applications a JOIN jobs j ON j.id = a.job_id "
        "WHERE a.stage = ? ORDER BY a.replied_at DESC", (REPLIED,),
    ).fetchall()
    due = store.conn.execute(
        """
        SELECT a.*, j.title, j.company, c.full_name, c.email, c.email_status FROM applications a
        JOIN jobs j ON j.id = a.job_id LEFT JOIN contacts c ON c.id = a.contact_id
        WHERE a.stage = ? AND a.replied_at IS NULL AND a.next_follow_up_at IS NOT NULL
        AND a.next_follow_up_at <= ? AND COALESCE(c.email_status, '') != 'bounced'
        ORDER BY a.next_follow_up_at
        """,
        (REACHED_OUT, iso(now)),
    ).fetchall()
    week_ago = iso(now - timedelta(days=7))
    new_jobs = store.conn.execute(
        """
        SELECT j.id, j.title, j.company, j.status, j.fit_score, j.report_date FROM jobs j
        LEFT JOIN applications a ON a.job_id = j.id
        WHERE (a.job_id IS NULL OR a.stage = 'new') AND j.status = 'shortlisted' AND j.first_seen >= ?
        ORDER BY j.fit_score DESC, j.id DESC
        """,
        (week_ago,),
    ).fetchall()
    ghosted = store.conn.execute(
        "SELECT e.job_id, e.at, j.title, j.company FROM events e JOIN jobs j ON j.id = e.job_id "
        "WHERE e.kind = 'ghosted' AND e.at >= ? ORDER BY e.at DESC", (week_ago,),
    ).fetchall()
    unsure = store.conn.execute(
        "SELECT sm.*, j.title, j.company FROM sent_mail sm JOIN jobs j ON j.id = sm.job_id "
        "WHERE sm.state = 'sending' AND sm.created_at <= ?", (iso(now - timedelta(minutes=2)),),
    ).fetchall()
    return {
        "replies": [dict(r) for r in replies],
        "follow_ups_due": [dict(r) for r in due],
        "new_jobs": [dict(r) for r in new_jobs],
        "ghosted": [dict(r) for r in ghosted],
        "unsure_sends": [dict(r) for r in unsure],
        "sends_today": sends_today(store, now),
        "caps": {"total": config.daily_send_cap, "guessed": config.daily_guessed_cap},
    }


def _size_bucket(size_range: str | None, config: OutreachConfig) -> str:
    from .contacts import size_upper_bound  # contacts imports tracking; import here to avoid a cycle

    upper = size_upper_bound(size_range)
    if upper is None:
        return "unknown"
    return f"≤{config.small_company_max_employees}" if upper <= config.small_company_max_employees \
        else f">{config.small_company_max_employees}"


def stats(store: JobStore, now: datetime, config: OutreachConfig) -> dict:
    stages = {s: 0 for s in STAGES}
    closed: dict[str, int] = {}
    for row in store.conn.execute("SELECT stage, closed_reason, COUNT(*) AS n FROM applications GROUP BY 1, 2"):
        stages[row["stage"]] += row["n"]
        if row["stage"] == CLOSED:
            closed[row["closed_reason"] or "?"] = row["n"]
    # Reply rate per contact role and company size, over jobs that got a real email.
    by_role: dict[str, dict] = {}
    by_size: dict[str, dict] = {}
    rows = store.conn.execute(
        """
        SELECT a.job_id, a.replied_at, c.role, co.size_range FROM applications a
        JOIN sent_mail sm ON sm.job_id = a.job_id AND sm.seq = 0 AND sm.kind = 'first' AND sm.state = 'sent'
        LEFT JOIN contacts c ON c.id = sm.contact_id
        LEFT JOIN companies co ON co.key = c.company_key
        """
    ).fetchall()
    for row in rows:
        for table, key in ((by_role, row["role"] or "unknown"), (by_size, _size_bucket(row["size_range"], config))):
            entry = table.setdefault(key, {"emailed": 0, "replied": 0})
            entry["emailed"] += 1
            entry["replied"] += 1 if row["replied_at"] else 0
    week_ago = iso(now - timedelta(days=7))
    sent_week = store.conn.execute(
        "SELECT COUNT(*) FROM sent_mail WHERE kind != 'test' AND state = 'sent' AND sent_at >= ?", (week_ago,)
    ).fetchone()[0]
    bounced = store.conn.execute("SELECT COUNT(*) FROM events WHERE kind = 'bounced'").fetchone()[0]
    return {
        "stages": stages,
        "closed": closed,
        "emailed": len(rows),
        "replied": sum(1 for r in rows if r["replied_at"]),
        "bounced": bounced,
        "applied": store.conn.execute("SELECT COUNT(*) FROM applications WHERE applied_at IS NOT NULL").fetchone()[0],
        "by_role": by_role,
        "by_size": by_size,
        "sent_this_week": sent_week,
        "sends_today": sends_today(store, now),
    }


def warnings_of(row: sqlite3.Row | None) -> list[str]:
    return json.loads(row["draft_warnings_json"]) if row and row["draft_warnings_json"] else []
