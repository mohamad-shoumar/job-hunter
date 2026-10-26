"""The applications and events tables: where you are with each job you act on, and its timeline.

tracking.py decides the stages and the follow-up dates; pitch.py, cv.py and
cover.py keep the draft, the tailored CV and the cover letter here.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from ..models import REACHED_OUT, REPLIED
from ..text import iso
from .jobs import JobStore, rows_in

# --- one job's row ------------------------------------------------------------


def get_application(store: JobStore, job_id: int) -> sqlite3.Row | None:
    return store.conn.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()


def picked_contacts(store: JobStore, job_ids) -> dict[int, int]:
    """{job id: the contact picked for it}, for the jobs that have one."""
    sql = "SELECT job_id, contact_id FROM applications WHERE contact_id IS NOT NULL AND job_id IN ({marks})"
    return {r["job_id"]: r["contact_id"] for r in rows_in(store, sql, job_ids)}


def insert_application(store: JobStore, job_id: int, stage: str, now: datetime) -> None:
    store.conn.execute(
        "INSERT INTO applications (job_id, stage, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (job_id, stage, iso(now), iso(now)),
    )


def update_application(store: JobStore, job_id: int, values: dict, now: datetime) -> None:
    """Set `values` ({column: value}, columns named by code) and updated_at."""
    values = {**values, "updated_at": iso(now)}
    assignments = ", ".join(f"{k} = :{k}" for k in values)
    store.conn.execute(f"UPDATE applications SET {assignments} WHERE job_id = :job_id", {**values, "job_id": job_id})


def set_application_contact(store: JobStore, job_id: int, contact_id: int) -> None:
    """The contact picked in the app. updated_at is left as it is."""
    store.conn.execute("UPDATE applications SET contact_id = ? WHERE job_id = ?", (contact_id, job_id))


def set_cv_file(store: JobStore, job_id: int, cv_file: str | None) -> None:
    """The CV the email attaches, picked in the app ("none": no CV). updated_at is left as it is."""
    store.conn.execute("UPDATE applications SET cv_file = ? WHERE job_id = ?", (cv_file, job_id))


# --- what is made for a job: the draft, the CV, the cover letter ----------------


def write_draft(store: JobStore, job_id: int, subject: str, hook: str, pitch: str, body: str, blocked: bool,
                warnings: list[str], meta: dict, contact_id: int | None, now: datetime) -> None:
    """A newly written draft: a new version, not edited by you. A None contact keeps the one picked before."""
    store.conn.execute(
        """
        UPDATE applications SET subject = ?, hook = ?, pitch = ?, body = ?, draft_version = draft_version + 1,
            draft_edited = 0, draft_blocked = ?, draft_warnings_json = ?, draft_meta_json = ?,
            contact_id = COALESCE(?, contact_id), updated_at = ?
        WHERE job_id = ?
        """,
        (subject, hook, pitch, body, 1 if blocked else 0, json.dumps(warnings), json.dumps(meta), contact_id,
         iso(now), job_id),
    )


def set_draft_body(store: JobStore, job_id: int, body: str, now: datetime) -> None:
    """A rebuilt body (the contact or the CV changed): a new draft version."""
    store.conn.execute("UPDATE applications SET body = ?, draft_version = draft_version + 1, updated_at = ? "
                       "WHERE job_id = ?", (body, iso(now), job_id))


def write_edited_draft(store: JobStore, job_id: int, subject: str, body: str, warnings: list[str],
                       now: datetime) -> None:
    """Your own edit: a new version, marked edited and no longer blocked."""
    store.conn.execute(
        "UPDATE applications SET subject = ?, body = ?, draft_version = draft_version + 1, draft_edited = 1, "
        "draft_blocked = 0, draft_warnings_json = ?, updated_at = ? WHERE job_id = ?",
        (subject, body, json.dumps(warnings), iso(now), job_id),
    )


def save_tailored_cv(store: JobStore, job_id: int, meta: dict, now: datetime, attach: str | None = None) -> None:
    """The tailored CV's details. `attach` names a PDF the email attaches from now on; None leaves cv_file."""
    store.conn.execute(
        "UPDATE applications SET cv_tailored_json = ?, cv_file = COALESCE(?, cv_file), updated_at = ? WHERE job_id = ?",
        (json.dumps(meta), attach or None, iso(now), job_id),
    )


def save_cover_letter(store: JobStore, job_id: int, meta: dict, now: datetime) -> None:
    store.conn.execute("UPDATE applications SET cover_letter_json = ?, updated_at = ? WHERE job_id = ?",
                       (json.dumps(meta), iso(now), job_id))


# --- events ---------------------------------------------------------------------


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


# --- across jobs ------------------------------------------------------------------


def ghost_candidates(store: JobStore) -> list[sqlite3.Row]:
    """Reached out by email with no reply. A job closed as ghosted once and moved back is left out."""
    return store.conn.execute(
        """
        SELECT * FROM applications a WHERE stage = ? AND emailed_at IS NOT NULL AND replied_at IS NULL
        AND NOT EXISTS (SELECT 1 FROM events e WHERE e.job_id = a.job_id AND e.kind = 'ghosted')
        """,
        (REACHED_OUT,),
    ).fetchall()


def replied(store: JobStore) -> list[sqlite3.Row]:
    """Jobs in Replied, with their title and company, latest reply first."""
    return store.conn.execute(
        "SELECT a.*, j.title, j.company FROM applications a JOIN jobs j ON j.id = a.job_id "
        "WHERE a.stage = ? ORDER BY a.replied_at DESC", (REPLIED,),
    ).fetchall()


def follow_ups_due(store: JobStore, now: datetime) -> list[sqlite3.Row]:
    """Follow-ups due by `now` for jobs still waiting for a reply, unless the contact's email bounced."""
    return store.conn.execute(
        """
        SELECT a.*, j.title, j.company, c.full_name, c.email, c.email_status FROM applications a
        JOIN jobs j ON j.id = a.job_id LEFT JOIN contacts c ON c.id = a.contact_id
        WHERE a.stage = ? AND a.replied_at IS NULL AND a.next_follow_up_at IS NOT NULL
        AND a.next_follow_up_at <= ? AND COALESCE(c.email_status, '') != 'bounced'
        ORDER BY a.next_follow_up_at
        """,
        (REACHED_OUT, iso(now)),
    ).fetchall()


def ghosted_since(store: JobStore, since: datetime) -> list[sqlite3.Row]:
    return store.conn.execute(
        "SELECT e.job_id, e.at, j.title, j.company FROM events e JOIN jobs j ON j.id = e.job_id "
        "WHERE e.kind = 'ghosted' AND e.at >= ? ORDER BY e.at DESC", (iso(since),),
    ).fetchall()


def stage_counts(store: JobStore) -> list[sqlite3.Row]:
    """(stage, closed_reason, n) rows."""
    return store.conn.execute("SELECT stage, closed_reason, COUNT(*) AS n FROM applications GROUP BY 1, 2").fetchall()


def first_emails(store: JobStore) -> list[sqlite3.Row]:
    """Each job whose first email went out: when it got a reply, the contact's role and the company's size."""
    return store.conn.execute(
        """
        SELECT a.job_id, a.replied_at, c.role, co.size_range FROM applications a
        JOIN sent_mail sm ON sm.job_id = a.job_id AND sm.seq = 0 AND sm.kind = 'first' AND sm.state = 'sent'
        LEFT JOIN contacts c ON c.id = sm.contact_id
        LEFT JOIN companies co ON co.key = c.company_key
        """
    ).fetchall()


def bounce_count(store: JobStore) -> int:
    return store.conn.execute("SELECT COUNT(*) FROM events WHERE kind = 'bounced'").fetchone()[0]


def applied_count(store: JobStore) -> int:
    return store.conn.execute("SELECT COUNT(*) FROM applications WHERE applied_at IS NOT NULL").fetchone()[0]
