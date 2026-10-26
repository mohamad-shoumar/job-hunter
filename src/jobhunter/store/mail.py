"""The sent_mail and mail_seen tables: every email sent, and the inbox messages already handled (mailer.py).

A sent_mail row's state is 'sending' (saved before the SMTP call), 'sent' or
'failed'; kind is 'first', 'follow_up' or 'test' (a test to yourself, which
counts toward nothing).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from ..text import iso
from .jobs import JobStore

# --- one email --------------------------------------------------------------------


def start_send(store: JobStore, job_id: int, contact_id: int | None, kind: str, seq: int, message_id: str,
               in_reply_to: str | None, to_addr: str, subject: str, body: str, guessed: bool, now: datetime) -> int:
    """Save an email as 'sending', before the SMTP call. Returns the row id. Raises sqlite3.IntegrityError when
    this step of this job was sent, or is being sent, already (the unique index sent_mail_once)."""
    cur = store.conn.execute(
        """
        INSERT INTO sent_mail (job_id, contact_id, kind, seq, message_id, in_reply_to, to_addr, subject, body,
                               guessed, state, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'sending', ?)
        """,
        (job_id, contact_id, kind, seq, message_id, in_reply_to, to_addr, subject, body, 1 if guessed else 0,
         iso(now)),
    )
    return cur.lastrowid


def get_mail(store: JobStore, row_id: int) -> sqlite3.Row | None:
    return store.conn.execute("SELECT * FROM sent_mail WHERE id = ?", (row_id,)).fetchone()


def set_sent(store: JobStore, row_id: int, when: datetime) -> None:
    store.conn.execute("UPDATE sent_mail SET state = 'sent', sent_at = ?, error = NULL WHERE id = ?",
                       (iso(when), row_id))


def set_failed(store: JobStore, row_id: int, error: str) -> None:
    store.conn.execute("UPDATE sent_mail SET state = 'failed', error = ? WHERE id = ?", (error, row_id))


def set_error(store: JobStore, row_id: int, error: str) -> None:
    """A note on a send whose outcome is not known yet; the state stays 'sending'."""
    store.conn.execute("UPDATE sent_mail SET error = ? WHERE id = ?", (error, row_id))


def set_thread(store: JobStore, row_id: int, thread_id: str | None) -> None:
    store.conn.execute("UPDATE sent_mail SET thread_id = ? WHERE id = ?", (thread_id, row_id))


# --- lists ------------------------------------------------------------------------


def sent_for_job(store: JobStore, job_id: int) -> list[sqlite3.Row]:
    """The real emails that went out about this job, first email first."""
    return store.conn.execute(
        "SELECT * FROM sent_mail WHERE job_id = ? AND kind != 'test' AND state = 'sent' ORDER BY seq", (job_id,)
    ).fetchall()


def mail_for_job(store: JobStore, job_id: int) -> list[sqlite3.Row]:
    """Every email about this job, tests and failures too, oldest first."""
    return store.conn.execute("SELECT * FROM sent_mail WHERE job_id = ? ORDER BY id", (job_id,)).fetchall()


def our_mail(store: JobStore, include_sending: bool = False) -> list[sqlite3.Row]:
    """Every email that went out; with `include_sending`, also the ones whose send is not confirmed yet."""
    if include_sending:
        return store.conn.execute("SELECT * FROM sent_mail WHERE state != 'failed'").fetchall()
    return store.conn.execute("SELECT * FROM sent_mail WHERE state = 'sent'").fetchall()


def has_mail(store: JobStore) -> bool:
    """Whether anything was sent, or is being sent."""
    return store.conn.execute("SELECT 1 FROM sent_mail WHERE state != 'failed' LIMIT 1").fetchone() is not None


def sends_since(store: JobStore, since: datetime) -> list[sqlite3.Row]:
    """(created_at, guessed) of the real emails sent, or being sent, since `since`."""
    return store.conn.execute(
        "SELECT created_at, guessed FROM sent_mail WHERE kind != 'test' AND state != 'failed' AND created_at >= ?",
        (iso(since),),
    ).fetchall()


def sent_count_since(store: JobStore, since: datetime) -> int:
    return store.conn.execute(
        "SELECT COUNT(*) FROM sent_mail WHERE kind != 'test' AND state = 'sent' AND sent_at >= ?", (iso(since),)
    ).fetchone()[0]


def unsure_sends(store: JobStore, started_before: datetime) -> list[sqlite3.Row]:
    """Sends still 'sending' that started before `started_before`, with the job's title and company."""
    return store.conn.execute(
        "SELECT sm.*, j.title, j.company FROM sent_mail sm JOIN jobs j ON j.id = sm.job_id "
        "WHERE sm.state = 'sending' AND sm.created_at <= ?", (iso(started_before),),
    ).fetchall()


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


# --- the inbox --------------------------------------------------------------------


def is_seen(store: JobStore, message_key: str) -> bool:
    return store.conn.execute("SELECT 1 FROM mail_seen WHERE message_key = ?", (message_key,)).fetchone() is not None


def mark_seen(store: JobStore, message_key: str, job_id: int | None, kind: str, now: datetime) -> None:
    store.conn.execute("INSERT OR IGNORE INTO mail_seen (message_key, job_id, kind, seen_at) VALUES (?, ?, ?, ?)",
                       (message_key, job_id, kind, iso(now)))
