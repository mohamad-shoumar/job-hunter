"""JobStore: the connection, and the jobs, sightings, runs and kv tables.

Tables:
  jobs       one row per real-world job (after cross-source dedup), including
             rejected ones, so a rejected job never comes back as "new"
  sightings  every (source, source_job_id) that pointed at a job
  runs       one row per pipeline run, with per-source stats
  kv         small values a step keeps between runs (the inbox scan's last message)

A job is classified once, when it is first seen. Later sightings only update
last_seen and fill in fields that were empty. `jobhunter reclassify` re-runs
the rules on every stored job after the rules change.

jobs.report_date (YYYY-MM-DD, local time) is the daily report a job belongs
to: the day a daily run first found it, or its posting day in a date-range
run. Every reports/<date>.md is rendered from the rows with that date, so a
report can always be rebuilt and two runs on one day share one file.

jobs.ai_check_json is the AI web check's finding (ai_check.py). It is kept
apart from the rule verdict so `reclassify` can combine the two again.
jobs.fit_grade_json is the AI fit grade (fitgrade.py): only for sorting, never
part of the status, so `reclassify` leaves it alone.
jobs.date_check_json is where an undated job's posting date was found (posted_date.py); the date itself
goes into posted_at, which a later sighting only fills when empty.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from ..identity import ats_key_from_url, fingerprint
from ..models import SHORTLISTED, UNCLEAR, VISA_LIST, AiCheck, Classification, DateCheck, Job
from ..text import iso, parse_datetime
from .schema import migrate as migrate_schema

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
        date_check=DateCheck(**json.loads(row["date_check_json"])) if row["date_check_json"] else None,
    )


def rows_in(store: JobStore, sql: str, values) -> list[sqlite3.Row]:
    """The rows of `sql`, whose `IN ({marks})` takes `values` 500 at a time (SQLite caps one statement's
    parameters), so a list of any length costs one query per 500."""
    values = list(values)
    rows: list[sqlite3.Row] = []
    for start in range(0, len(values), 500):
        chunk = values[start:start + 500]
        rows += store.conn.execute(sql.format(marks=", ".join("?" * len(chunk))), chunk).fetchall()
    return rows


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
        migrate_schema(self.conn)

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

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

    def save_date_check(self, job_id: int, check: DateCheck) -> None:
        """The evidence, and the date it found when the job still has none."""
        self.conn.execute("UPDATE jobs SET date_check_json = ?, posted_at = COALESCE(posted_at, ?) WHERE id = ?",
                          (json.dumps(asdict(check)), check.posted_at, job_id))

    def save_fit_grade(self, job_id: int, grade: dict) -> None:
        self.conn.execute("UPDATE jobs SET fit_grade_json = ? WHERE id = ?", (json.dumps(grade), job_id))

    def update_classification(self, job_id: int, cls: Classification) -> None:
        values = _classification_values(cls)
        assignments = ", ".join(f"{k} = :{k}" for k in values)
        self.conn.execute(f"UPDATE jobs SET {assignments} WHERE id = :id", {**values, "id": job_id})

    # --- reading ------------------------------------------------------------

    def get(self, job_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

    def all_jobs(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()

    def needs_date_check(self, recheck: bool = False) -> list[sqlite3.Row]:
        """Undated shortlisted jobs, newest first. `recheck` includes ones searched before without luck."""
        unchecked = "" if recheck else " AND date_check_json IS NULL"
        return self.conn.execute(
            f"SELECT * FROM jobs WHERE status = ? AND posted_at IS NULL{unchecked} "
            "ORDER BY first_seen DESC, id DESC", (SHORTLISTED,)
        ).fetchall()

    def needs_ai_check(self, recheck: bool = False) -> list[sqlite3.Row]:
        """Shortlisted jobs whose rules could not tell about Lebanon, newest first. `recheck`
        includes ones already checked."""
        unchecked = "" if recheck else " AND ai_check_json IS NULL"
        return self.conn.execute(
            f"SELECT * FROM jobs WHERE status = ? AND eligibility = ?{unchecked} "
            "ORDER BY COALESCE(posted_at, first_seen) DESC, id DESC", (SHORTLISTED, UNCLEAR)
        ).fetchall()

    def unreported(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM jobs WHERE reported_at IS NULL AND status IN (?, ?) ORDER BY id",
            (SHORTLISTED, VISA_LIST),
        ).fetchall()

    def mark_reported(self, job_ids: list[int], now: datetime) -> None:
        self.conn.executemany("UPDATE jobs SET reported_at = ? WHERE id = ?", [(iso(now), i) for i in job_ids])
        self.conn.commit()

    def set_report_date(self, job_ids, day: str) -> None:
        self.conn.executemany("UPDATE jobs SET report_date = ? WHERE id = ?", [(day, i) for i in job_ids])

    def jobs_for_report(self, day: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM jobs WHERE report_date = ? ORDER BY id", (day,)).fetchall()

    def with_status(self, *statuses: str) -> list[sqlite3.Row]:
        """Every job with one of these statuses, newest first."""
        marks = ", ".join("?" * len(statuses))
        return self.conn.execute(f"SELECT * FROM jobs WHERE status IN ({marks}) ORDER BY id DESC", statuses).fetchall()

    def reported_shortlisted(self) -> list[sqlite3.Row]:
        """Shortlisted jobs that are in a daily report, newest first."""
        return self.conn.execute(
            "SELECT * FROM jobs WHERE status = ? AND report_date IS NOT NULL ORDER BY id DESC", (SHORTLISTED,)
        ).fetchall()

    def applications_for(self, job_ids) -> dict[int, sqlite3.Row]:
        """{job id: its applications row}, for the jobs that have one."""
        ids = list(job_ids)
        found: dict[int, sqlite3.Row] = {}
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            marks = ", ".join("?" * len(chunk))
            for row in self.conn.execute(f"SELECT * FROM applications WHERE job_id IN ({marks})", chunk):
                found[row["job_id"]] = row
        return found

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
