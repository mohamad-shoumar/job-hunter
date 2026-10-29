"""Jobs read together with their application: the app's job list, Today's new jobs, the jobs the
daily run grades and prepares, and the examples the fit grade learns from."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from ..models import (
    CLOSED, NEW, REACHED_OUT, REJECTED, SAVED, SHORTLISTED, STAGE_LABELS, VISA_LIST,
)
from ..text import iso
from .jobs import JobStore

# Columns for a SELECT over `jobs j LEFT JOIN applications a`: when the job last moved to
# Reached out (set_stage writes "Saved → Reached out"). See tracking.reached_out_at.
OUTREACH_COLUMNS = f"""
    (SELECT MAX(e.at) FROM events e WHERE e.job_id = j.id AND e.kind = 'stage'
     AND e.detail LIKE '%→ {STAGE_LABELS[REACHED_OUT]}%') AS moved_to_reached_out_at,
    a.updated_at AS application_updated_at
"""

# The job list's views and years filters: only these keys pick SQL text; every value goes in as a parameter.
_OPEN = "COALESCE(a.stage, :new) != :closed"
JOB_VIEWS = {
    "active": f"j.status = :shortlisted AND {_OPEN}",
    "shortlisted": f"j.status = :shortlisted AND {_OPEN}",
    "visa_list": f"j.status = :visa_list AND {_OPEN}",
    "tracked": "a.stage IS NOT NULL AND a.stage NOT IN (:new, :closed)",
    "closed": "a.stage = :closed",
    "rejected": "j.status = :rejected AND j.report_date IS NOT NULL",
}
# Years asked, in brackets that don't overlap: a job that doesn't say is only in "none".
YEARS = {"lt3": "j.required_yoe < 3", "3-4": "j.required_yoe >= 3 AND j.required_yoe < 4",
         "4-5": "j.required_yoe >= 4 AND j.required_yoe < 5", "5+": "j.required_yoe >= 5",
         "none": "j.required_yoe IS NULL"}
_NAMES = {"new": NEW, "closed": CLOSED, "shortlisted": SHORTLISTED, "visa_list": VISA_LIST, "rejected": REJECTED}


def job_list(store: JobStore, view: str, q: str = "", yoe: str = "",
             posted_since: datetime | None = None) -> list[sqlite3.Row]:
    """The app's job list (GET /api/jobs), with OUTREACH_COLUMNS: `view` a JOB_VIEWS key, `q` words in the title
    or company, `yoe` a YEARS key (or empty), `posted_since` the date the row shows (posted, else found)."""
    where = JOB_VIEWS[view]
    params: dict = dict(_NAMES)
    if q.strip():
        where += " AND (j.title LIKE :q OR j.company LIKE :q)"
        params["q"] = f"%{q.strip()}%"
    if yoe:
        where += f" AND {YEARS[yoe]}"
    if posted_since:
        where += " AND COALESCE(j.posted_at, j.first_seen) >= :since"
        params["since"] = iso(posted_since)
    return store.conn.execute(
        f"""
        SELECT j.*, a.stage, a.closed_reason, a.skip_reason, a.body IS NOT NULL AS has_draft, a.draft_blocked,
               a.next_follow_up_at, a.emailed_at, a.applied_at, a.replied_at,
               a.cv_tailored_json IS NOT NULL AS has_cv, a.cover_letter_json IS NOT NULL AS has_cover,
               {OUTREACH_COLUMNS}
        FROM jobs j LEFT JOIN applications a ON a.job_id = j.id
        WHERE {where}
        ORDER BY COALESCE(j.report_date, substr(j.first_seen, 1, 10)) DESC,
                 CASE j.status WHEN :shortlisted THEN 0 ELSE 1 END,
                 COALESCE(json_extract(j.fit_grade_json, '$.grade'), 3) DESC, j.fit_score DESC, j.id DESC
        LIMIT 500
        """,
        params,
    ).fetchall()


def new_jobs(store: JobStore, status: str, since: datetime) -> list[sqlite3.Row]:
    """Jobs with `status` first seen since `since` that you have not acted on (Today), best grade first."""
    return store.conn.execute(
        """
        SELECT j.id, j.title, j.company, j.status, j.fit_score, j.report_date,
               json_extract(j.fit_grade_json, '$.grade') AS fit_grade FROM jobs j
        LEFT JOIN applications a ON a.job_id = j.id
        WHERE (a.job_id IS NULL OR a.stage = ?) AND j.status = ? AND j.first_seen >= ?
        ORDER BY COALESCE(json_extract(j.fit_grade_json, '$.grade'), 3) DESC, j.fit_score DESC, j.id DESC
        """,
        (NEW, status, iso(since)),
    ).fetchall()


def jobs_to_grade(store: JobStore, statuses, since_day: str, regrade: bool = False) -> list[sqlite3.Row]:
    """Jobs with one of `statuses` from report days since `since_day` (YYYY-MM-DD) that are still New or Saved,
    newest first. Without `regrade`, only the ones with no fit grade yet."""
    statuses = tuple(statuses)
    ungraded = "" if regrade else " AND j.fit_grade_json IS NULL"
    marks = ", ".join("?" for _ in statuses)
    return store.conn.execute(
        f"SELECT j.* FROM jobs j LEFT JOIN applications a ON a.job_id = j.id "
        f"WHERE j.status IN ({marks}) AND j.report_date >= ? AND COALESCE(a.stage, ?) IN (?, ?)"
        f"{ungraded} ORDER BY j.report_date DESC, j.id DESC",
        (*statuses, since_day, NEW, NEW, SAVED),
    ).fetchall()


def shortlisted_new_or_saved(store: JobStore, since_day: str) -> list[sqlite3.Row]:
    """Shortlisted jobs from report days since `since_day` (YYYY-MM-DD) that are still New or Saved."""
    return store.conn.execute(
        "SELECT jobs.* FROM jobs LEFT JOIN applications ON applications.job_id = jobs.id "
        "WHERE jobs.status = ? AND jobs.report_date >= ? AND COALESCE(applications.stage, ?) IN (?, ?)",
        (SHORTLISTED, since_day, NEW, NEW, SAVED),
    ).fetchall()


def applied_jobs(store: JobStore, limit: int) -> list[sqlite3.Row]:
    """Jobs you applied to (and did not skip later), latest application first."""
    return store.conn.execute(
        "SELECT j.* FROM applications a JOIN jobs j ON j.id = a.job_id "
        "WHERE a.applied_at IS NOT NULL AND NOT (a.stage = ? AND a.closed_reason = 'skipped') "
        "ORDER BY a.applied_at DESC LIMIT ?", (CLOSED, limit),
    ).fetchall()


def skipped_jobs(store: JobStore, limit: int) -> list[sqlite3.Row]:
    """Jobs you skipped, with your reason and note: ones with a reason first, then the latest."""
    return store.conn.execute(
        "SELECT j.*, a.skip_reason, a.skip_note FROM applications a JOIN jobs j ON j.id = a.job_id "
        "WHERE a.stage = ? AND a.closed_reason = 'skipped' "
        "ORDER BY (a.skip_reason IS NOT NULL OR a.skip_note IS NOT NULL) DESC, a.updated_at DESC LIMIT ?",
        (CLOSED, limit),
    ).fetchall()
