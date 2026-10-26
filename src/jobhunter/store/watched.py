"""The watched_boards and board_probes tables: company boards fetched since a job there was shortlisted (boards.py)."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from ..text import iso
from .jobs import JobStore


def watched_boards(store: JobStore, include_removed: bool = False) -> list[sqlite3.Row]:
    where = "" if include_removed else " WHERE removed_at IS NULL"
    return store.conn.execute(f"SELECT * FROM watched_boards{where} ORDER BY added_at, kind, slug").fetchall()


def add_watched_board(store: JobStore, kind: str, slug: str, company: str, company_key: str, from_job_id: int | None,
                      reason: str, now: datetime) -> None:
    store.conn.execute(
        "INSERT INTO watched_boards (kind, slug, company, company_key, from_job_id, reason, added_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (kind, slug, company, company_key, from_job_id, reason, iso(now)))


def remove_watched_board(store: JobStore, kind: str, slug: str, now: datetime) -> bool:
    """Mark the board removed (the slug in any case). False when it is not watched."""
    cur = store.conn.execute(
        "UPDATE watched_boards SET removed_at = ? WHERE kind = ? AND lower(slug) = lower(?) AND removed_at IS NULL",
        (iso(now), kind, slug))
    return cur.rowcount > 0


def board_probes(store: JobStore) -> list[sqlite3.Row]:
    """Companies whose board was looked for and not found, and when."""
    return store.conn.execute("SELECT * FROM board_probes").fetchall()


def record_probe(store: JobStore, company_key: str, now: datetime, note: str) -> None:
    store.conn.execute(
        "INSERT INTO board_probes (company_key, probed_at, note) VALUES (?, ?, ?) "
        "ON CONFLICT (company_key) DO UPDATE SET probed_at = excluded.probed_at, note = excluded.note",
        (company_key, iso(now), note))
