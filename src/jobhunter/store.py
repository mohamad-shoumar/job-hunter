"""SQLite persistence. The database is the system's memory; reports are output.

Tables:
  jobs       one row per real-world job (after cross-source dedup), including
             rejected ones, so a rejected job never comes back as "new"
  sightings  every (source, source_job_id) that pointed at a job
  runs       one row per pipeline run, with per-source stats

A job is classified once, when it is first seen. Later sightings only update
last_seen and fill in fields that were empty. `jobhunter reclassify` re-runs
the rules on every stored job after the rules change.

jobs.report_date (YYYY-MM-DD, local time) is the daily report a job belongs
to: the day a daily run first found it, or its posting day in a date-range
run. Every reports/<date>.md is rendered from the rows with that date, so a
report can always be rebuilt and two runs on one day share one file.

jobs.ai_check_json is the AI web check's finding (ai_check.py). It is kept
apart from the rule verdict so `reclassify` can combine the two again.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from .identity import ats_key_from_url, fingerprint
from .models import AiCheck, Classification, Job
from .text import iso, parse_datetime

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
    ai_check_json TEXT
);
CREATE INDEX IF NOT EXISTS jobs_fingerprint ON jobs (fingerprint);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_ats_key ON jobs (ats_key) WHERE ats_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS jobs_unreported ON jobs (status) WHERE reported_at IS NULL;

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
""" + """
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
    cv_tailored_json TEXT
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
"""

# Columns added after the first release, for databases created before them.
_ADDED_COLUMNS = {"report_date": "TEXT", "ai_check_json": "TEXT"}

# Filled from a later sighting only when the stored value is empty.
_FILL_IF_EMPTY = (
    "description", "company_location", "employment_type", "salary_min", "salary_max",
    "salary_currency", "salary_period", "salary_raw", "required_yoe", "posted_at",
)


def job_ats_key(job: Job) -> str | None:
    return ats_key_from_url(job.application_url) or ats_key_from_url(job.source_url)


def _job_values(job: Job) -> dict:
    return {
        "company": job.company,
        "title": job.title,
        "description": job.description or "",
        "application_url": job.application_url,
        "company_location": job.company_location,
        "location_raw": job.location_raw,
        "allowed_locations_json": json.dumps(job.allowed_locations),
        "allowed_utc_offsets_json": json.dumps(job.allowed_utc_offsets),
        "remote_status": job.remote_status,
        "employment_type": job.employment_type,
        "contract_info_json": json.dumps(job.contract_info),
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
        "salary_period": job.salary_period,
        "salary_raw": job.salary_raw,
        "required_yoe": job.required_yoe,
        "skills_json": json.dumps(job.skills),
        "posted_at": iso(job.posted_at),
    }


def _classification_values(cls: Classification) -> dict:
    return {
        "status": cls.status,
        "eligibility": cls.eligibility.verdict,
        "eligibility_reasons_json": json.dumps(cls.eligibility.reasons),
        "relevance": cls.relevance.verdict,
        "relevance_reasons_json": json.dumps(cls.relevance.reasons),
        "fit_score": cls.fit_score,
        "reject_reason": cls.reject_reason,
        "reject_code": cls.reject_code,
    }


def row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        source=row["source"],
        source_job_id=str(row["id"]),
        source_url=row["source_url"] or "",
        company=row["company"],
        title=row["title"],
        description=row["description"],
        application_url=row["application_url"],
        company_location=row["company_location"],
        location_raw=row["location_raw"],
        allowed_locations=json.loads(row["allowed_locations_json"]),
        allowed_utc_offsets=json.loads(row["allowed_utc_offsets_json"]),
        remote_status=row["remote_status"],
        employment_type=row["employment_type"],
        contract_info=json.loads(row["contract_info_json"]),
        salary_min=row["salary_min"],
        salary_max=row["salary_max"],
        salary_currency=row["salary_currency"],
        salary_period=row["salary_period"],
        salary_raw=row["salary_raw"],
        required_yoe=row["required_yoe"],
        skills=json.loads(row["skills_json"]),
        posted_at=parse_datetime(row["posted_at"]),
        first_seen=parse_datetime(row["first_seen"]),
        last_seen=parse_datetime(row["last_seen"]),
        ai_check=AiCheck(**json.loads(row["ai_check_json"])) if row["ai_check_json"] else None,
    )


class JobStore:
    """migrate=False skips the schema work (the web app migrates once at start).

    check_same_thread=False lets one request's connection be used from the
    different threads FastAPI runs a request's parts on; a connection is still
    only ever used by one request.
    """

    def __init__(self, path: Path | str, migrate: bool = True, check_same_thread: bool = True):
        on_disk = str(path) != ":memory:"
        if on_disk:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), timeout=15, check_same_thread=check_same_thread)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        # The daily run and the web app can write at the same time: WAL lets
        # readers go on during a write, and the timeout waits out short locks.
        self.conn.execute("PRAGMA busy_timeout = 15000")
        if not migrate:
            return
        if on_disk:
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        existing = {row["name"] for row in self.conn.execute("PRAGMA table_info(jobs)")}
        for column, kind in _ADDED_COLUMNS.items():
            if column not in existing:
                self.conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {kind}")
        app_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(applications)")}
        for column in ("cv_file", "cv_tailored_json"):
            if column not in app_columns:
                self.conn.execute(f"ALTER TABLE applications ADD COLUMN {column} TEXT")
        self.conn.execute("CREATE INDEX IF NOT EXISTS jobs_report_date ON jobs (report_date)")
        self.conn.commit()

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    # --- runs ---------------------------------------------------------------

    def start_run(self, now: datetime) -> int:
        cur = self.conn.execute("INSERT INTO runs (started_at) VALUES (?)", (iso(now),))
        self.conn.commit()
        return cur.lastrowid

    def last_run_stats(self) -> dict | None:
        row = self.conn.execute(
            "SELECT stats_json FROM runs WHERE stats_json IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return json.loads(row["stats_json"]) if row else None

    def finish_run(self, run_id: int, stats: dict, now: datetime) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, stats_json = ? WHERE id = ?", (iso(now), json.dumps(stats), run_id)
        )
        self.conn.commit()

    # --- matching and writing ----------------------------------------------

    def find_match(self, job: Job, now: datetime, window_days: int) -> int | None:
        """The stored job this listing is a sighting of, or None if it is new. See identity.py."""
        row = self.conn.execute(
            "SELECT job_id FROM sightings WHERE source = ? AND source_job_id = ?", (job.source, job.source_job_id)
        ).fetchone()
        if row:
            return row["job_id"]
        ats = job_ats_key(job)
        if ats:
            row = self.conn.execute("SELECT id FROM jobs WHERE ats_key = ?", (ats,)).fetchone()
            if row:
                return row["id"]
        cutoff = iso(now - timedelta(days=window_days))
        rows = self.conn.execute(
            "SELECT id, ats_key FROM jobs WHERE fingerprint = ? AND last_seen >= ? ORDER BY last_seen DESC",
            (fingerprint(job.company, job.title), cutoff),
        ).fetchall()
        for candidate in rows:
            if ats and candidate["ats_key"] and candidate["ats_key"] != ats:
                continue  # same title, different ATS posting: a separate job
            return candidate["id"]
        return None

    def insert(self, job: Job, cls: Classification, run_id: int | None, now: datetime) -> int:
        values = {
            **_job_values(job),
            **_classification_values(cls),
            "fingerprint": fingerprint(job.company, job.title),
            "ats_key": job_ats_key(job),
            "source": job.source,
            "source_url": job.source_url,
            "first_seen": iso(now),
            "last_seen": iso(now),
            "first_seen_run_id": run_id,
        }
        columns = ", ".join(values)
        placeholders = ", ".join(f":{k}" for k in values)
        cur = self.conn.execute(f"INSERT INTO jobs ({columns}) VALUES ({placeholders})", values)
        self._add_sighting(cur.lastrowid, job, now)
        return cur.lastrowid

    def touch(self, job_id: int, job: Job, now: datetime) -> None:
        """Record another sighting of a stored job and fill fields it was missing."""
        existing = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        new = _job_values(job)
        updates = {"last_seen": iso(now)}
        for column in _FILL_IF_EMPTY:
            if existing[column] in (None, "") and new[column] not in (None, ""):
                updates[column] = new[column]
        ats = job_ats_key(job)
        if ats and not existing["ats_key"]:
            if not self.conn.execute("SELECT 1 FROM jobs WHERE ats_key = ?", (ats,)).fetchone():
                updates["ats_key"] = ats
        # Prefer a direct ATS link over an aggregator page.
        if job.application_url and (
            not existing["application_url"]
            or (ats_key_from_url(job.application_url) and not ats_key_from_url(existing["application_url"]))
        ):
            updates["application_url"] = job.application_url
        assignments = ", ".join(f"{k} = :{k}" for k in updates)
        self.conn.execute(f"UPDATE jobs SET {assignments} WHERE id = :id", {**updates, "id": job_id})
        self._add_sighting(job_id, job, now)

    def _add_sighting(self, job_id: int, job: Job, now: datetime) -> None:
        self.conn.execute(
            """
            INSERT INTO sightings (job_id, source, source_job_id, source_url, location_raw, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (source, source_job_id) DO UPDATE
                SET last_seen = excluded.last_seen, source_url = excluded.source_url
            """,
            (job_id, job.source, job.source_job_id, job.source_url, job.location_raw, iso(now), iso(now)),
        )

    def update_extracted(self, job_id: int, job: Job) -> None:
        """Save what `enrich` reads from the text, after the extraction rules change."""
        self.conn.execute("UPDATE jobs SET skills_json = ?, required_yoe = ? WHERE id = ?",
                          (json.dumps(job.skills), job.required_yoe, job_id))

    def save_ai_check(self, job_id: int, check: AiCheck) -> None:
        self.conn.execute("UPDATE jobs SET ai_check_json = ? WHERE id = ?", (json.dumps(asdict(check)), job_id))

    def update_classification(self, job_id: int, cls: Classification) -> None:
        values = _classification_values(cls)
        assignments = ", ".join(f"{k} = :{k}" for k in values)
        self.conn.execute(f"UPDATE jobs SET {assignments} WHERE id = :id", {**values, "id": job_id})

    # --- reading ------------------------------------------------------------

    def get(self, job_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

    def all_jobs(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()

    def needs_ai_check(self, recheck: bool = False) -> list[sqlite3.Row]:
        """Jobs waiting for review because the rules could not tell about Lebanon, newest
        first. `recheck` includes ones already checked."""
        unchecked = "" if recheck else " AND ai_check_json IS NULL"
        return self.conn.execute(
            f"SELECT * FROM jobs WHERE status = 'needs_review' AND eligibility = 'unclear'{unchecked} "
            "ORDER BY COALESCE(posted_at, first_seen) DESC, id DESC"
        ).fetchall()

    def unreported(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM jobs WHERE reported_at IS NULL AND status IN ('shortlisted', 'needs_review') ORDER BY id"
        ).fetchall()

    def mark_reported(self, job_ids: list[int], now: datetime) -> None:
        self.conn.executemany("UPDATE jobs SET reported_at = ? WHERE id = ?", [(iso(now), i) for i in job_ids])
        self.conn.commit()

    def set_report_date(self, job_ids, day: str) -> None:
        self.conn.executemany("UPDATE jobs SET report_date = ? WHERE id = ?", [(day, i) for i in job_ids])

    def jobs_for_report(self, day: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM jobs WHERE report_date = ? ORDER BY id", (day,)).fetchall()

    def jobs_by_ids(self, job_ids) -> list[sqlite3.Row]:
        ids = list(job_ids)
        rows: list[sqlite3.Row] = []
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            marks = ", ".join("?" * len(chunk))
            rows += self.conn.execute(f"SELECT * FROM jobs WHERE id IN ({marks})", chunk).fetchall()
        return rows

    def sightings_for(self, job_ids: list[int]) -> dict[int, list[sqlite3.Row]]:
        found: dict[int, list[sqlite3.Row]] = {i: [] for i in job_ids}
        for chunk_start in range(0, len(job_ids), 500):
            chunk = job_ids[chunk_start:chunk_start + 500]
            marks = ", ".join("?" * len(chunk))
            for row in self.conn.execute(
                f"SELECT * FROM sightings WHERE job_id IN ({marks}) ORDER BY first_seen, id", chunk
            ):
                found[row["job_id"]].append(row)
        return found

    def get_kv(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_kv(self, key: str, value: str | None) -> None:
        self.conn.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def counts(self) -> dict:
        by_status = dict(self.conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall())
        by_source = dict(self.conn.execute("SELECT source, COUNT(*) FROM sightings GROUP BY source").fetchall())
        runs = self.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        return {"jobs_by_status": by_status, "sightings_by_source": by_source, "runs": runs}
