"""The companies and contacts tables: each company looked up once, and the people found there (contacts.py)."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from ..text import iso
from .jobs import JobStore, rows_in

# --- companies --------------------------------------------------------------------


def get_company(store: JobStore, key: str) -> sqlite3.Row | None:
    return store.conn.execute("SELECT * FROM companies WHERE key = ?", (key,)).fetchone()


def companies_by_key(store: JobStore, keys) -> dict[str, sqlite3.Row]:
    """{key: its companies row}, for the keys that have one."""
    return {r["key"]: r for r in rows_in(store, "SELECT * FROM companies WHERE key IN ({marks})", keys)}


def add_company(store: JobStore, key: str, name: str) -> None:
    store.conn.execute("INSERT INTO companies (key, name) VALUES (?, ?)", (key, name))


def new_company(key: str, name: str) -> dict:
    """The row add_company would write (the schema's defaults), for reads that must not write one."""
    return {"key": key, "name": name, "domain": None, "domain_source": None, "size_range": None, "size_count": None,
            "is_job_board": 0, "email_pattern": None, "accept_all": None, "lookup_state": None,
            "lookup_started_at": None, "looked_up_at": None, "note": None, "credits": 0.0, "cost_usd": 0.0}


def update_company(store: JobStore, key: str, **values) -> None:
    """Set `values` (columns named by code)."""
    assignments = ", ".join(f"{k} = :{k}" for k in values)
    store.conn.execute(f"UPDATE companies SET {assignments} WHERE key = :key", {**values, "key": key})


def claim_lookup(store: JobStore, key: str, now: datetime, stale_before: datetime) -> bool:
    """Mark the company's lookup as running. False when another lookup has run since `stale_before`."""
    return store.conn.execute(
        "UPDATE companies SET lookup_state = 'running', lookup_started_at = ? WHERE key = ? "
        "AND (lookup_state IS NULL OR lookup_state != 'running' OR lookup_started_at < ?)",
        (iso(now), key, iso(stale_before)),
    ).rowcount > 0


def forget_lookup(store: JobStore, key: str) -> None:
    """So the next Find contact looks the company up again."""
    store.conn.execute("UPDATE companies SET lookup_state = NULL WHERE key = ?", (key,))


def job_board_keys(store: JobStore) -> set[str]:
    """Companies marked as a job board or agency."""
    return {r["key"] for r in store.conn.execute("SELECT key FROM companies WHERE is_job_board = 1")}


def company_domains(store: JobStore) -> dict[str, str | None]:
    return {r["key"]: r["domain"] for r in store.conn.execute("SELECT key, domain FROM companies")}


# --- contacts ---------------------------------------------------------------------


def company_contacts(store: JobStore, key: str) -> list[sqlite3.Row]:
    return store.conn.execute("SELECT * FROM contacts WHERE company_key = ? ORDER BY id", (key,)).fetchall()


def contacts_by_company(store: JobStore, keys) -> dict[str, list[sqlite3.Row]]:
    """{key: company_contacts(key)} for many companies, in the same order (by id)."""
    found: dict[str, list[sqlite3.Row]] = {}
    for row in rows_in(store, "SELECT * FROM contacts WHERE company_key IN ({marks}) ORDER BY id", keys):
        found.setdefault(row["company_key"], []).append(row)
    return found


def get_contact(store: JobStore, contact_id: int) -> sqlite3.Row | None:
    return store.conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()


def contacts_by_id(store: JobStore, contact_ids) -> dict[int, sqlite3.Row]:
    return {r["id"]: r for r in rows_in(store, "SELECT * FROM contacts WHERE id IN ({marks})", contact_ids)}


def contact_at(store: JobStore, contact_id: int, key: str) -> bool:
    """Whether the contact works at this company."""
    return store.conn.execute("SELECT 1 FROM contacts WHERE id = ? AND company_key = ?",
                              (contact_id, key)).fetchone() is not None


def contact_id_by_email(store: JobStore, key: str, email: str) -> int | None:
    """`email` in lowercase."""
    row = store.conn.execute("SELECT id FROM contacts WHERE company_key = ? AND lower(email) = ?",
                             (key, email)).fetchone()
    return row["id"] if row else None


def contact_id_by_name(store: JobStore, key: str, full_name: str) -> int | None:
    row = store.conn.execute("SELECT id FROM contacts WHERE company_key = ? AND lower(full_name) = lower(?)",
                             (key, full_name)).fetchone()
    return row["id"] if row else None


def insert_contact(store: JobStore, key: str, values: dict) -> int:
    """A new contact at company `key` ({column: value}, columns named by code). Returns its id."""
    columns = ", ".join(["company_key", *values])
    marks = ", ".join(["?"] * (len(values) + 1))
    cur = store.conn.execute(f"INSERT INTO contacts ({columns}) VALUES ({marks})", [key, *values.values()])
    return cur.lastrowid


def update_contact(store: JobStore, contact_id: int, values: dict) -> None:
    """Set `values` ({column: value}, columns named by code)."""
    assignments = ", ".join(f"{k} = :{k}" for k in values)
    store.conn.execute(f"UPDATE contacts SET {assignments} WHERE id = :id", {**values, "id": contact_id})


def set_email_status(store: JobStore, contact_id: int, status: str) -> None:
    store.conn.execute("UPDATE contacts SET email_status = ? WHERE id = ?", (status, contact_id))


def mark_bounced(store: JobStore, address: str) -> None:
    """Every contact with this email address (any case)."""
    store.conn.execute("UPDATE contacts SET email_status = 'bounced' WHERE lower(email) = lower(?)", (address,))
