"""The fit score: 0-100 by the user's rubric (rubric.py), with each part's points and why.

Sorting only. The rules (eligibility.py, relevance.py) decide a job's status, each with a
quotable reason; the score never changes a status, never hides a job and never rejects one.
It orders the report, the To apply column and which jobs get a CV first.

How a job is scored (the user's call 2026-11-15, decision 26, replacing the 1-5 grade that
learned from Applied and skipped jobs):
  - the model (Claude Code by default) reads the posting and the profile's facts and answers
    only what needs reading: the seniority level, the required skills, the domain, benefits,
    equity and what the posting says about its interviews, each with a quote;
  - code checks each quote against the posting (find_quote), scores every part from
    rubric.py and adds them up. Years, visa and location, and salary are code alone.
  - when the posting says nothing about its interviews, interviews.py looks the company up
    once (cached per company) and `rescore` updates its jobs.
A job keeps its score; `jobhunter grade --regrade` scores the open ones again.
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

from . import rubric
from .config import Filters
from .extract import find_required_yoe
from .identity import company_key
from .llm import JsonModel, Usage, error_line, find_quote, json_model
from .models import SHORTLISTED, VISA_LIST
from .profile import load_profile, sections
from .rubric import Interview
from .store import JobStore
from .store.companies import interview_styles
from .store.lists import company_postings, jobs_to_grade
from .text import iso
from .visa import read_posting

log = logging.getLogger(__name__)

SHOWN = (SHORTLISTED, VISA_LIST)
POSTING = "posting"

SYSTEM = """You read one job posting for one job seeker and answer a few questions about it, each \
from the posting's own words. Code turns your answers into points; you do not score anything.

- seniority: the level the role is pitched at. "junior", "mid", "senior", "staff_or_above" (staff, \
principal, lead, head, manager of engineers), or "not_stated". Read the title first, then the text.
- required_skills: the technical skills the posting REQUIRES (must have), as short names ("Python", \
"PostgreSQL", "Kubernetes"). Leave out nice-to-haves, soft skills and spoken languages. At most 15. For \
each, profile_words: the words in their profile that show they have it, copied exactly from the profile \
("API design" for "REST APIs", "Git" for "Version control"), or "" when the profile does not show it. \
Do not stretch: a different language or tool is not the same skill.
- domain: how the seeker's past work (their profile below) relates to what this company does. \
"direct" (they worked in this domain), "transferable" (a close or overlapping domain), "unrelated".
- benefits_quote: words from the posting naming meaningful benefits (health insurance, pension, \
learning budget, paid leave beyond the legal minimum), copied exactly; "" when there are none.
- equity_quote: words from the posting offering equity, stock options or RSUs, copied exactly; "" when none.
- interview: what the posting says about its hiring process. live_coding "yes" when it names live \
coding, pair programming, a whiteboard, or a coding test such as HackerRank, Codility or LeetCode as an \
interview step (pair programming as part of the daily work is not an interview); "no" when it describes the process and none of those are in it, or says there is none; "unknown" when it does not \
say. rounds: the number of interview stages it describes, or null. quote: the words it rests on, copied exactly.
- reason: one short sentence in plain words naming what matters most about this job for this person.

Copy every quote word for word from the posting: a quote code cannot find there scores nothing."""

SCHEMA = {
    "type": "object",
    "properties": {
        "seniority": {"type": "string", "enum": list(rubric.SENIORITY)},
        "required_skills": {"type": "array", "items": {
            "type": "object",
            "properties": {"skill": {"type": "string"}, "profile_words": {"type": "string"}},
            "required": ["skill", "profile_words"],
            "additionalProperties": False,
        }},
        "domain": {"type": "string", "enum": list(rubric.DOMAIN)},
        "domain_why": {"type": "string"},
        "benefits_quote": {"type": "string"},
        "equity_quote": {"type": "string"},
        "interview": {
            "type": "object",
            "properties": {"live_coding": {"type": "string", "enum": ["yes", "no", "unknown"]},
                           "rounds": {"type": ["integer", "null"]}, "quote": {"type": "string"}},
            "required": ["live_coding", "rounds", "quote"],
            "additionalProperties": False,
        },
        "reason": {"type": "string"},
    },
    "required": ["seniority", "required_skills", "domain", "domain_why", "benefits_quote", "equity_quote",
                 "interview", "reason"],
    "additionalProperties": False,
}
EXAMPLE = json.dumps({
    "seniority": "mid", "required_skills": [{"skill": "Python", "profile_words": "Python"},
                                            {"skill": "REST APIs", "profile_words": "API design"},
                                            {"skill": "Rust", "profile_words": ""}],
    "domain": "transferable",
    "domain_why": "Payments, close to the logistics billing work in the profile.",
    "benefits_quote": "private health insurance and a learning budget", "equity_quote": "",
    "interview": {"live_coding": "unknown", "rounds": None, "quote": ""},
    "reason": "A mid-level Python backend role asking 3+ years.",
})


@dataclass
class FitGradeConfig:
    """config/fit_grade.json. `enabled` controls the daily run; `jobhunter grade` runs either way."""

    enabled: bool = False
    model: str = "claude-code:opus"
    max_jobs_per_run: int = 60
    # Jobs filed under the last this-many report days are scored, if still open (New or Saved).
    lookback_days: int = 7
    description_chars: int = 6000
    workers: int = 4
    # The company interview lookup (interviews.py): its model, and how many companies a run.
    interview_model: str = "claude-code:sonnet"
    max_interview_lookups_per_run: int = 10
    interview_recheck_days: int = 90

    @classmethod
    def load(cls, path: Path) -> FitGradeConfig:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def profile_summary(profile_path: Path) -> str:
    """The profile's facts and target roles. load_profile leaves out the Basics (contact details)."""
    profile = load_profile(profile_path)
    targets = " ".join(sections(profile_path.read_text()).get("Target roles", "").split())
    lines = [f"Target roles: {targets}"] if targets and "TODO" not in targets else []
    return "\n".join(lines + [f"- {fact}" for fact in profile.facts])


def _posting(row: sqlite3.Row, chars: int) -> str:
    description = " ".join((row["description"] or "").split())
    cut = description[:chars] + (" …" if len(description) > chars else "")
    return "\n".join([f"Title: {row['title']}", f"Company: {row['company']}",
                      f"Location: {row['location_raw'] or 'not given'}", f"Posting: {cut or '(no text)'}"])


@dataclass
class Context:
    """What every job's score shares: the profile, the country rules and the salary floors."""

    profile: str
    skills: set[str]
    years: float | None
    filters: Filters | None = None
    floors: rubric.SalaryFloors = field(default_factory=rubric.SalaryFloors.from_env)

    @classmethod
    def load(cls, profile_path: Path, filters: Filters | None) -> Context:
        profile = load_profile(profile_path)
        return cls(profile_summary(profile_path), profile.skills, profile.years, filters)


def _quoted(quote: str, text: str) -> str:
    """The quote when code finds it in `text`, else ""."""
    quote = " ".join(str(quote or "").split())
    return quote if quote and find_quote(quote, [(POSTING, text)]) else ""


def other_offer(store: JobStore, row: sqlite3.Row) -> str | None:
    """A track record of hiring from abroad: the company's other postings offered a visa in two or more
    different months (one month only says they do now; docs/research/2026-11-15-hiring-track-record-...).
    The newest such sentence, with the months, or None."""
    months: dict[str, str] = {}
    for other in company_postings(store, row["company"], row["id"]):
        offers = read_posting(other["description"] or "").offers
        if offers:
            months.setdefault((other["first_seen"] or "")[:7], offers[0])
    if len(months) < 2:
        return None
    newest = max(months)
    return f"{months[newest]} ({len(months)} months: {', '.join(sorted(months))})"


def score(row: sqlite3.Row, answer: dict, context: Context, company_interview: Interview | None = None,
          offer_elsewhere: str | None = None) -> dict:
    """The rubric's parts for one job: {name: [points, why]}, the total, and the interview star.

    Pure: the model's `answer` was given already, so `rescore` can run it again with no model."""
    text = f"{row['title']}\n{row['description'] or ''}"
    filters = context.filters
    visa_rules = filters.visa if filters else None
    relocation = filters.relocation if filters else None
    level = answer.get("seniority") if answer.get("seniority") in rubric.SENIORITY else "not_stated"
    domain = answer.get("domain") if answer.get("domain") in rubric.DOMAIN else "unrelated"
    found = find_required_yoe(row["description"]) if row["required_yoe"] else None
    years, years_why = rubric.years_points(row["required_yoe"], context.years)
    if found and found[0] == row["required_yoe"]:
        years_why += f' ("{rubric._short(found[1], 100)}")'
    skills = rubric.skills_points(list(answer.get("required_skills") or []), context.skills, context.profile)
    benefits = _quoted(answer.get("benefits_quote"), text)
    equity = _quoted(answer.get("equity_quote"), text)

    said = Interview.from_dict(answer.get("interview"))
    said.quote = _quoted(said.quote, text)
    if said.live_coding != "unknown" and said.quote:
        said.source = POSTING
        interview = said
    else:
        interview = company_interview or Interview()
    interview_pts, star, interview_why = rubric.interview_points(interview)

    parts = {
        "seniority": [rubric.SENIORITY[level], level.replace("_", " ")],
        "skills": list(skills),
        "years": [years, years_why],
        "domain": [rubric.DOMAIN[domain], f"{domain}: {' '.join(str(answer.get('domain_why') or '').split())[:160]}"],
        "visa": list(rubric.visa_points(row, relocation, offer_elsewhere)),
        "salary": list(rubric.salary_points(row, visa_rules, relocation, context.floors)),
        "benefits": [rubric.BENEFITS_MAX if benefits else 0, f'"{rubric._short(benefits, 120)}"' if benefits else "none named"],
        "equity": [rubric.EQUITY_MAX if equity else 0, f'"{rubric._short(equity, 120)}"' if equity else "none named"],
        "interview": [interview_pts, interview_why],
    }
    return {"score": rubric.total(parts), "parts": parts, "star": star, "rubric": rubric.RUBRIC_VERSION}


class FitGrader:
    def __init__(self, config: FitGradeConfig, model: JsonModel):
        self.config = config
        self.model = model

    @property
    def label(self) -> str:
        return self.config.model

    def ask(self, row: sqlite3.Row, context: Context) -> tuple[dict, Usage]:
        usage = Usage()
        message = (f"## Their profile (facts)\n{context.profile}\n\n"
                   f"## The posting\n{_posting(row, self.config.description_chars)}")
        answer = self.model.ask(SYSTEM, [{"role": "user", "content": message}], SCHEMA, usage, EXAMPLE, max_tokens=1200)
        if not isinstance(answer, dict) or answer.get("seniority") not in rubric.SENIORITY \
                or answer.get("domain") not in rubric.DOMAIN or not str(answer.get("reason") or "").strip():
            raise ValueError(f"the model gave no usable answer: {json.dumps(answer)[:200]}")
        return answer, usage

    def grade(self, store_reads: tuple[Interview | None, str | None], row: sqlite3.Row, context: Context,
              now: datetime) -> dict:
        answer, usage = self.ask(row, context)
        company_interview, offer_elsewhere = store_reads
        result = score(row, answer, context, company_interview, offer_elsewhere)
        return {**result, "reason": " ".join(str(answer["reason"]).split())[:300], "answer": answer,
                "model": self.config.model, "at": iso(now), "cost_usd": usage.cost(self.config.model)}


def build_grader(config_file: Path, require_enabled: bool = True) -> tuple[FitGrader | None, str | None]:
    """(the grader, None), or (None, why it is off). Off and silent when the config says so."""
    config = FitGradeConfig.load(config_file)
    if require_enabled and not config.enabled:
        return None, None
    model, note = json_model(config.model, "Fit scores")
    return (FitGrader(config, model), None) if model else (None, note)


@dataclass
class GradeRun:
    graded: int = 0
    grades: Counter = field(default_factory=Counter)  # by tens: {70: 3} is three jobs scored 70-79
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    model: str = ""
    interviews: dict = field(default_factory=dict)
    changed_days: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {"graded": self.graded, "grades": {str(k): v for k, v in sorted(self.grades.items())},
                "errors": self.errors, "notes": self.notes, "cost_usd": round(self.cost_usd, 3),
                "model": self.model, "interviews": self.interviews}


def to_grade(store: JobStore, now: datetime, days: int, regrade: bool = False) -> list[sqlite3.Row]:
    """Shown jobs from the last `days` report days that you have not acted on (New or Saved), newest first."""
    since = (now.astimezone().date() - timedelta(days=max(1, days) - 1)).isoformat()
    return jobs_to_grade(store, SHOWN, since, regrade)


def store_reads(store: JobStore, row: sqlite3.Row) -> tuple[Interview | None, str | None]:
    """What a score reads from the store besides the job: the company's interview lookup, another posting's offer."""
    found = interview_styles(store, [company_key(row["company"])]).get(company_key(row["company"]))
    return (Interview.from_dict(json.loads(found["answer_json"])) if found and found["answer_json"] else None,
            other_offer(store, row))


def grade_jobs(store: JobStore, grader: FitGrader, rows, profile_path: Path, now: datetime,
               filters: Filters | None = None, on_result=None) -> GradeRun:
    """Score `rows` and save each score as it arrives. on_result(row, grade) is called for each one."""
    run = GradeRun(model=grader.label)
    rows = list(rows)
    if not rows:
        return run
    if not profile_path.exists():
        run.notes.append(f"no profile at {profile_path}: nothing scored")
        return run
    context = Context.load(profile_path, filters)
    reads = {row["id"]: store_reads(store, row) for row in rows}  # the store is read here, not in the threads
    with ThreadPoolExecutor(max_workers=max(1, grader.config.workers)) as pool:
        futures = {pool.submit(grader.grade, reads[row["id"]], row, context, now): row for row in rows}
        for future in as_completed(futures):
            row = futures[future]
            try:
                grade = future.result()
            except Exception as exc:  # one bad answer must not stop the rest
                log.warning("fit score #%s failed: %s", row["id"], error_line(exc))
                run.errors.append(f"#{row['id']} {row['company']}: {error_line(exc)}")
                continue
            store.save_fit_grade(row["id"], grade)
            store.commit()
            run.graded += 1
            run.grades[grade["score"] // 10 * 10] += 1
            run.cost_usd += grade["cost_usd"] or 0
            if row["report_date"]:
                run.changed_days.add(row["report_date"])
            if on_result:
                on_result(row, grade)
    return run


def rescore(store: JobStore, rows, profile_path: Path, filters: Filters | None = None) -> set[str]:
    """Score `rows` again from their stored answers, with no model (after a company lookup). The days changed."""
    context = Context.load(profile_path, filters) if profile_path.exists() else None
    changed = set()
    for row in rows:
        grade = grade_of(row)
        if not context or not grade or "answer" not in grade:
            continue
        new = {**grade, **score(row, grade["answer"], context, *store_reads(store, row))}
        if new != grade:
            store.save_fit_grade(row["id"], new)
            if row["report_date"]:
                changed.add(row["report_date"])
    return changed


def grade_of(row) -> dict | None:
    """The stored fit score of a jobs row (the 0-100 rubric), or None. An old 1-5 grade reads as None."""
    try:
        value = row["fit_grade_json"]
    except (IndexError, KeyError):
        return None
    grade = json.loads(value) if value else None
    return grade if grade and "score" in grade else None


# A job with no score yet (over the cap, or an error) sorts in the middle, not below every low one.
UNGRADED = 50


def sort_grade(row) -> int:
    """For sorting best first: the score, or UNGRADED when there is none."""
    grade = grade_of(row)
    return grade["score"] if grade else UNGRADED
