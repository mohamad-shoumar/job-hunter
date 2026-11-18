"""projects (spec 6.1): proof-of-work project ideas and builds, one row per project.

The daily digest (digest.py) writes the `suggested` rows, one per job, with the digest's day in
idea_json. Status names come from models.py and go in as parameters. Nothing here commits.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from ..models import PROJECT_SUGGESTED
from ..text import iso
from .jobs import JobStore


def projects_for_jobs(store: JobStore, job_ids) -> dict[int, sqlite3.Row]:
    """{job id: its latest project row} for the jobs that have one, whatever its status."""
    ids = list(job_ids)
    if not ids:
        return {}
    marks = ", ".join("?" for _ in ids)
    rows = store.conn.execute(f"SELECT * FROM projects WHERE job_id IN ({marks}) ORDER BY id", ids).fetchall()
    return {row["job_id"]: row for row in rows}


def insert_suggested(store: JobStore, job_id: int, title: str, idea: dict, stack: str, now: datetime) -> int:
    """A `suggested` project for the job, from a digest idea. Returns its id."""
    cursor = store.conn.execute(
        "INSERT INTO projects (job_id, title, idea_json, stack, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (job_id, title, json.dumps(idea), stack, PROJECT_SUGGESTED, iso(now), iso(now)),
    )
    return cursor.lastrowid


def digest_days(store: JobStore, limit: int = 1) -> list[str]:
    """The latest days (YYYY-MM-DD) a digest suggested projects on, newest first."""
    rows = store.conn.execute(
        "SELECT DISTINCT json_extract(idea_json, '$.digest_date') AS day FROM projects "
        "WHERE json_extract(idea_json, '$.digest_date') IS NOT NULL ORDER BY day DESC LIMIT ?", (limit,),
    ).fetchall()
    return [row["day"] for row in rows]


def digest_projects(store: JobStore, day: str, limit: int = 5) -> list[sqlite3.Row]:
    """The projects a digest suggested on `day`, with their job and where you are with it, best score first.
    At most `limit`: a second digest the same day (by hand, then the evening run) may add ideas for jobs scored
    in between."""
    return store.conn.execute(
        """
        SELECT p.id AS project_id, p.title AS project_title, p.idea_json, p.stack, p.status AS project_status,
               j.id AS job_id, j.title, j.company, j.status, j.location_raw,
               json_extract(j.fit_grade_json, '$.score') AS fit_grade,
               json_extract(j.fit_grade_json, '$.culture.tag') AS fit_culture,
               json_extract(j.fit_grade_json, '$.culture.why') AS fit_culture_why, a.stage
        FROM projects p JOIN jobs j ON j.id = p.job_id LEFT JOIN applications a ON a.job_id = j.id
        WHERE json_extract(p.idea_json, '$.digest_date') = ?
        ORDER BY json_extract(p.idea_json, '$.score') DESC, p.id
        LIMIT ?
        """,
        (day, limit),
    ).fetchall()
