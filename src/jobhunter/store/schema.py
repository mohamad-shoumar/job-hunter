"""The database schema, and the numbered changes that bring an older database up to it.

SCHEMA is the whole database as it is now: a new database is created from it,
complete. Its CREATE ... IF NOT EXISTS also adds a table an older database is
missing, so a new table needs no migration. A new column does: CREATE TABLE
leaves an existing table as it is, so the column is added by a migration
(which skips it when it is there already), and an index on that column is
created there too, after the column exists.

`PRAGMA user_version` records the last migration a database has run. A
database from before the migrations is version 0.
"""

from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    stats_json TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    ats_key TEXT,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    source_url TEXT,
    application_url TEXT,
    company_location TEXT,
    location_raw TEXT,
    allowed_locations_json TEXT NOT NULL DEFAULT '[]',
    allowed_utc_offsets_json TEXT NOT NULL DEFAULT '[]',
    remote_status TEXT NOT NULL,
    employment_type TEXT,
    contract_info_json TEXT NOT NULL DEFAULT '[]',
    salary_min REAL,
    salary_max REAL,
    salary_currency TEXT,
    salary_period TEXT,
    salary_raw TEXT,
    required_yoe INTEGER,
    skills_json TEXT NOT NULL DEFAULT '[]',
    posted_at TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    first_seen_run_id INTEGER REFERENCES runs(id),
    status TEXT NOT NULL,
    eligibility TEXT NOT NULL,
    eligibility_reasons_json TEXT NOT NULL DEFAULT '[]',
    relevance TEXT NOT NULL,
    relevance_reasons_json TEXT NOT NULL DEFAULT '[]',
    fit_score INTEGER NOT NULL DEFAULT 0,
    reject_reason TEXT,
    reject_code TEXT,
    reported_at TEXT,
    report_date TEXT,
    ai_check_json TEXT,
    fit_grade_json TEXT,
    date_check_json TEXT
);
CREATE INDEX IF NOT EXISTS jobs_fingerprint ON jobs (fingerprint);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_ats_key ON jobs (ats_key) WHERE ats_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS jobs_unreported ON jobs (status) WHERE reported_at IS NULL;
-- jobs_report_date is created by migration 1 (report_date came later).

CREATE TABLE IF NOT EXISTS sightings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    source TEXT NOT NULL,
    source_job_id TEXT NOT NULL,
    source_url TEXT,
    location_raw TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE (source, source_job_id)
);
CREATE INDEX IF NOT EXISTS sightings_job ON sightings (job_id);

-- Outreach and tracking (contacts.py, pitch.py, mailer.py, tracking.py).
-- Separate from `jobs`, so `reclassify` never touches them.

CREATE TABLE IF NOT EXISTS companies (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    domain TEXT,
    domain_source TEXT,
    size_range TEXT,
    size_count INTEGER,
    is_job_board INTEGER NOT NULL DEFAULT 0,
    email_pattern TEXT,
    accept_all INTEGER,
    lookup_state TEXT,
    lookup_started_at TEXT,
    looked_up_at TEXT,
    note TEXT,
    credits REAL NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_key TEXT NOT NULL REFERENCES companies(key),
    full_name TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    position TEXT,
    role TEXT NOT NULL,
    email TEXT,
    email_status TEXT,
    confidence INTEGER,
    linkedin_url TEXT,
    source TEXT NOT NULL,
    evidence_url TEXT,
    evidence_quote TEXT,
    verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS contacts_company ON contacts (company_key);

CREATE TABLE IF NOT EXISTS applications (
    job_id INTEGER PRIMARY KEY REFERENCES jobs(id),
    stage TEXT NOT NULL,
    closed_reason TEXT,
    contact_id INTEGER REFERENCES contacts(id),
    subject TEXT,
    hook TEXT,
    pitch TEXT,
    body TEXT,
    draft_version INTEGER NOT NULL DEFAULT 0,
    draft_edited INTEGER NOT NULL DEFAULT 0,
    draft_blocked INTEGER NOT NULL DEFAULT 0,
    draft_warnings_json TEXT NOT NULL DEFAULT '[]',
    draft_meta_json TEXT,
    applied_at TEXT,
    emailed_at TEXT,
    follow_ups INTEGER NOT NULL DEFAULT 0,
    next_follow_up_at TEXT,
    replied_at TEXT,
    reply_from TEXT,
    reply_snippet TEXT,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    cv_file TEXT,
    cv_tailored_json TEXT,
    cover_letter_json TEXT,
    skip_reason TEXT,
    skip_note TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    ref TEXT
);
CREATE INDEX IF NOT EXISTS events_job ON events (job_id);
CREATE UNIQUE INDEX IF NOT EXISTS events_ref ON events (kind, ref) WHERE ref IS NOT NULL;

-- Every email sent. seq 0 is the first email, 1 and 2 the follow-ups. The
-- unique index is the check-and-set that stops a double send: a second
-- 'sending' row for the same step cannot be inserted.
CREATE TABLE IF NOT EXISTS sent_mail (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES jobs(id),
    contact_id INTEGER REFERENCES contacts(id),
    kind TEXT NOT NULL,
    seq INTEGER NOT NULL DEFAULT 0,
    message_id TEXT NOT NULL UNIQUE,
    in_reply_to TEXT,
    to_addr TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    guessed INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL,
    error TEXT,
    thread_id TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS sent_mail_once ON sent_mail (job_id, seq)
    WHERE kind != 'test' AND state != 'failed';

-- Inbox messages already handled, so two scans never count one twice.
CREATE TABLE IF NOT EXISTS mail_seen (
    message_key TEXT PRIMARY KEY,
    job_id INTEGER,
    kind TEXT NOT NULL,
    seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Watched boards (boards.py): the public board of each company with a shortlisted job.
CREATE TABLE IF NOT EXISTS watched_boards (
    kind TEXT NOT NULL,
    slug TEXT NOT NULL,
    company TEXT NOT NULL,
    company_key TEXT NOT NULL,
    from_job_id INTEGER,
    reason TEXT NOT NULL,
    added_at TEXT NOT NULL,
    removed_at TEXT,
    PRIMARY KEY (kind, slug)
);
CREATE INDEX IF NOT EXISTS watched_boards_company ON watched_boards (company_key);

-- Companies whose board was guessed and not found, so they are not tried every day.
CREATE TABLE IF NOT EXISTS board_probes (
    company_key TEXT PRIMARY KEY,
    probed_at TEXT NOT NULL,
    note TEXT
);
"""


def _add_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    """Add the columns `table` does not have yet."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for column, kind in columns.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")


def _v1_added_columns(conn: sqlite3.Connection) -> None:
    """The columns added before migrations had numbers. A version-0 database has some, all or none of them."""
    _add_columns(conn, "jobs", {"report_date": "TEXT", "ai_check_json": "TEXT", "fit_grade_json": "TEXT",
                                "date_check_json": "TEXT"})
    _add_columns(conn, "applications", {"cv_file": "TEXT", "cv_tailored_json": "TEXT", "cover_letter_json": "TEXT",
                                        "skip_reason": "TEXT", "skip_note": "TEXT"})
    conn.execute("CREATE INDEX IF NOT EXISTS jobs_report_date ON jobs (report_date)")


# Migration n is MIGRATIONS[n - 1]. Only ever add to the end; each one must be safe to run on a database
# that SCHEMA has just created, since a new database runs them all too.
MIGRATIONS = [_v1_added_columns]
LATEST_VERSION = len(MIGRATIONS)


def user_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> None:
    """Create what is missing, then run the migrations this database has not run yet."""
    conn.executescript(SCHEMA)
    for number in range(user_version(conn) + 1, LATEST_VERSION + 1):
        MIGRATIONS[number - 1](conn)
        conn.execute(f"PRAGMA user_version = {number}")
    conn.commit()
