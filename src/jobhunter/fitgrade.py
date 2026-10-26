"""AI fit grade: how much you would want a job, learned from the jobs you applied to and skipped.

Sorting only. The rules (eligibility.py, relevance.py) decide a job's status, each with a
quotable reason; the grade never changes a status, never hides a job and never rejects one.
It orders the report, the To apply column and which jobs get a CV first, and shows one
sentence saying why.

How it learns: there are no hand-written preference rules. Each grade is one model call
that reads
  - the profile's facts (experience, skills, target roles; no contact details),
  - what you said you want (`preferences` in config/fit_grade.json, in your words),
  - your latest choices as examples: jobs you marked Applied, and jobs you skipped with
    the skip reason and note you gave,
and grades the job 1-5 the way those choices point. Each Applied or Skip changes the
examples, so the next grades follow. Stages you set by hand (Reached out, Interviewing)
are not used. A job keeps its grade; `jobhunter grade --regrade` grades the open ones
again with today's examples.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta
from pathlib import Path

from .extract import find_required_yoe
from .llm import JsonModel, Usage, error_line, json_model
from .profile import load_profile, sections
from .store import JobStore
from .text import iso
from .tracking import SKIP_REASONS

log = logging.getLogger(__name__)

SHOWN = ("shortlisted", "needs_review", "visa_list")

SYSTEM = """You help one job seeker sort the job postings they will read today. Grade how much this \
person would want to apply to the job below, from 1 (they would skip it) to 5 (exactly what they look for).

Judge it the way their own choices point. The jobs they applied to and the jobs they skipped, with \
their reasons, are the best evidence of what they want; what they told you comes next; their profile \
says what they can do.

Do not judge whether the company can hire someone from their country, or visas: other code decides \
that. Do not reward a posting for listing many skills: look at what the role mostly is, the seniority \
and years it asks for, and the stack it is built on.

The reason is one short sentence in plain words naming what in the posting decided the grade, e.g. \
"Asks for 7+ years and is mostly Kubernetes work, like the roles you skipped as too senior." Be exact \
about them: cite a skip reason only where they gave one ("skipped (no reason given)" says only that they \
skipped it), and name only skills and work their profile lists.
"""
SCHEMA = {
    "type": "object",
    "properties": {"grade": {"type": "integer", "minimum": 1, "maximum": 5}, "reason": {"type": "string"}},
    "required": ["grade", "reason"],
    "additionalProperties": False,
}
EXAMPLE = '{"grade": 4, "reason": "A Python backend role asking 3+ years, like the ones you applied to."}'


@dataclass
class FitGradeConfig:
    """config/fit_grade.json. `enabled` controls the daily run; `jobhunter grade` runs either way."""

    enabled: bool = False
    model: str = "deepseek-v4-flash"
    max_jobs_per_run: int = 60
    # Jobs filed under the last this-many report days are graded, if still open (New or Saved).
    lookback_days: int = 7
    max_liked_examples: int = 20
    max_skipped_examples: int = 30
    description_chars: int = 3500
    preferences: str = ""
    workers: int = 4

    @classmethod
    def load(cls, path: Path) -> FitGradeConfig:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Examples:
    liked: list[str]
    skipped: list[str]

    @property
    def counts(self) -> str:
        return f"{len(self.liked)} applied, {len(self.skipped)} skipped"


def _where(row: sqlite3.Row) -> str:
    place = row["location_raw"] or "no location given"
    abroad = "; on-site abroad, would need a visa" if row["status"] == "visa_list" else ""
    return f"{row['remote_status']}, {place}{abroad}"


def _job_line(row: sqlite3.Row) -> str:
    skills = json.loads(row["skills_json"] or "[]")
    years = f"asks {row['required_yoe']}+ yrs" if row["required_yoe"] else "years not stated"
    return f'"{row["title"]}" at {row["company"]} | {_where(row)} | {years} | {", ".join(skills[:8]) or "no skills found"}'


def load_examples(store: JobStore, config: FitGradeConfig) -> Examples:
    """Your Applied jobs (liked) and skipped jobs (with your reason), newest first.

    Skips you gave a reason for come first: they say the most.
    """
    liked = store.conn.execute(
        "SELECT j.* FROM applications a JOIN jobs j ON j.id = a.job_id "
        "WHERE a.applied_at IS NOT NULL AND NOT (a.stage = 'closed' AND a.closed_reason = 'skipped') "
        "ORDER BY a.applied_at DESC LIMIT ?", (config.max_liked_examples,),
    ).fetchall()
    skipped = store.conn.execute(
        "SELECT j.*, a.skip_reason, a.skip_note FROM applications a JOIN jobs j ON j.id = a.job_id "
        "WHERE a.stage = 'closed' AND a.closed_reason = 'skipped' "
        "ORDER BY (a.skip_reason IS NOT NULL OR a.skip_note IS NOT NULL) DESC, a.updated_at DESC LIMIT ?",
        (config.max_skipped_examples,),
    ).fetchall()

    def why(row) -> str:
        said = "; ".join(x for x in (SKIP_REASONS.get(row["skip_reason"] or ""), row["skip_note"]) if x)
        return f" | skipped: {said}" if said else " | skipped (no reason given)"

    return Examples([f"- {_job_line(r)}" for r in liked], [f"- {_job_line(r)}{why(r)}" for r in skipped])


def profile_summary(profile_path: Path) -> str:
    """The profile's facts and target roles. load_profile leaves out the Basics (contact details)."""
    profile = load_profile(profile_path)
    targets = " ".join(sections(profile_path.read_text()).get("Target roles", "").split())
    lines = [f"Target roles: {targets}"] if targets and "TODO" not in targets else []
    return "\n".join(lines + [f"- {fact}" for fact in profile.facts])


def _posting(row: sqlite3.Row, chars: int) -> str:
    found = find_required_yoe(row["description"]) if row["required_yoe"] else None
    years = f'{row["required_yoe"]}+ ("{found[1]}")' if found else "not stated"
    salary = row["salary_raw"] or ""
    description = " ".join((row["description"] or "").split())
    cut = description[:chars] + (" …" if len(description) > chars else "")
    return "\n".join([
        f"Title: {row['title']}", f"Company: {row['company']}", f"Where: {_where(row)}", f"Years asked: {years}",
        *([f"Pay: {salary}"] if salary else []),
        f"Skills found: {', '.join(json.loads(row['skills_json'] or '[]')) or 'none'}",
        f"Posting: {cut or '(no text)'}",
    ])


class FitGrader:
    def __init__(self, config: FitGradeConfig, model: JsonModel):
        self.config = config
        self.model = model

    @property
    def label(self) -> str:
        return self.config.model

    def context(self, profile: str, examples: Examples) -> str:
        """The part every job's message shares: who you are and what your choices say."""
        none = "- (none yet)"
        return "\n\n".join([
            "## Their profile (facts)\n" + profile,
            "## What they told you\n" + (self.config.preferences.strip() or "(nothing)"),
            "## Jobs they applied to\n" + ("\n".join(examples.liked) or none),
            "## Jobs they skipped, with their reason\n" + ("\n".join(examples.skipped) or none),
        ])

    def grade(self, row: sqlite3.Row, context: str, now: datetime) -> dict:
        usage = Usage()
        message = f"{context}\n\n## The job to grade\n{_posting(row, self.config.description_chars)}"
        answer = self.model.ask(SYSTEM, [{"role": "user", "content": message}], SCHEMA, usage, EXAMPLE, max_tokens=300)
        grade, reason = answer.get("grade"), " ".join(str(answer.get("reason") or "").split())
        if isinstance(grade, str) and grade.strip().isdigit():
            grade = int(grade)
        if not isinstance(grade, int) or isinstance(grade, bool) or not 1 <= grade <= 5 or not reason:
            raise ValueError(f"the model gave no usable grade: {json.dumps(answer)[:200]}")
        return {"grade": grade, "reason": reason[:300], "model": self.config.model, "at": iso(now),
                "cost_usd": usage.cost(self.config.model)}


def build_grader(config_file: Path, require_enabled: bool = True) -> tuple[FitGrader | None, str | None]:
    """(the grader, None), or (None, why it is off). Off and silent when the config says so."""
    config = FitGradeConfig.load(config_file)
    if require_enabled and not config.enabled:
        return None, None
    model, note = json_model(config.model, "Fit grades")
    return (FitGrader(config, model), None) if model else (None, note)


@dataclass
class GradeRun:
    graded: int = 0
    grades: Counter = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    model: str = ""
    examples: str = ""
    changed_days: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {"graded": self.graded, "grades": {str(k): v for k, v in sorted(self.grades.items())},
                "errors": self.errors, "notes": self.notes, "cost_usd": round(self.cost_usd, 3),
                "model": self.model, "examples": self.examples}


def to_grade(store: JobStore, now: datetime, days: int, regrade: bool = False) -> list[sqlite3.Row]:
    """Shown jobs from the last `days` report days that you have not acted on (New or Saved), newest first."""
    since = (now.astimezone().date() - timedelta(days=max(1, days) - 1)).isoformat()
    ungraded = "" if regrade else " AND j.fit_grade_json IS NULL"
    marks = ", ".join("?" for _ in SHOWN)
    return store.conn.execute(
        f"SELECT j.* FROM jobs j LEFT JOIN applications a ON a.job_id = j.id "
        f"WHERE j.status IN ({marks}) AND j.report_date >= ? AND COALESCE(a.stage, 'new') IN ('new', 'saved')"
        f"{ungraded} ORDER BY j.report_date DESC, j.id DESC",
        (*SHOWN, since),
    ).fetchall()


def grade_jobs(store: JobStore, grader: FitGrader, rows, profile_path: Path, now: datetime,
               on_result=None) -> GradeRun:
    """Grade `rows` and save each grade as it arrives. on_result(row, grade) is called for each one."""
    run = GradeRun(model=grader.label)
    rows = list(rows)
    if not rows:
        return run
    if not profile_path.exists():
        run.notes.append(f"no profile at {profile_path}: nothing graded")
        return run
    examples = load_examples(store, grader.config)
    run.examples = examples.counts
    context = grader.context(profile_summary(profile_path), examples)
    with ThreadPoolExecutor(max_workers=max(1, grader.config.workers)) as pool:
        futures = {pool.submit(grader.grade, row, context, now): row for row in rows}
        for future in as_completed(futures):
            row = futures[future]
            try:
                grade = future.result()
            except Exception as exc:  # one bad answer must not stop the rest
                log.warning("fit grade #%s failed: %s", row["id"], error_line(exc))
                run.errors.append(f"#{row['id']} {row['company']}: {error_line(exc)}")
                continue
            store.save_fit_grade(row["id"], grade)
            store.commit()
            run.graded += 1
            run.grades[grade["grade"]] += 1
            run.cost_usd += grade["cost_usd"] or 0
            if row["report_date"]:
                run.changed_days.add(row["report_date"])
            if on_result:
                on_result(row, grade)
    return run


def grade_of(row) -> dict | None:
    """The stored grade of a jobs row, or None."""
    try:
        value = row["fit_grade_json"]
    except (IndexError, KeyError):
        return None
    return json.loads(value) if value else None


# A job with no grade yet (over the cap, or an error) sorts in the middle, not below every 1/5 job.
UNGRADED = 3


def sort_grade(row) -> int:
    """For sorting best first: the grade, or UNGRADED when there is none."""
    grade = grade_of(row)
    return grade["grade"] if grade else UNGRADED
