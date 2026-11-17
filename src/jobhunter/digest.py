"""The daily digest (package 1.2a): the day's top 3-5 jobs and one small project idea for each.

`jobhunter digest`, and the evening run with `--digest` (scripts/local.jobhunter.evening.plist).

Which jobs is code alone: filed under the day's report (`report_date`), shortlisted or on the
visa list, still New, one per company, by the fit score (fitgrade.py), and only scores of
`min_score` or more (60 by default: on the stored jobs of 2026-11-11 to 11-17 that kept 3-5 a day,
where 65 left 1-2 on some days and 55 let in half-fits). At most 5. A job with no score is never
picked; the file says how many there were.

The idea is one model call per job (`claude-code` by default, through `llm.json_model`). The model
gets the posting and only the profile's Skills section, never the experience, so it cannot borrow
a claim from it. Code then checks what it can, and drops the idea (the job stays listed) when:
  - its quote (the team's likely problem, in the posting's words) is not in the posting (`find_quote`);
  - it claims experience ("years of", "experienced in", "I built", "your experience with" ...);
  - it is not buildable in a day (hours outside 1-10), or no stack item is left.
A stack item named neither in the posting nor in your Skills section is removed (many postings name
no tools at all: Augustus's on 2026-11-17 named none, so the stack then comes from your skills); one
that is not in your Skills section is marked new to you.

Each kept idea is a `projects` row, status `suggested` (store/projects.py), with the digest's day
and rank in its idea_json. A job that already has a project row, in any status, is never asked
again, so re-running a day adds nothing. Nothing is built from here: building waits for your go.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path

from .fitgrade import grade_of
from .llm import JsonModel, Usage, error_line, find_quote, json_model
from .profile import sections, strip_notes
from .report import one_per_company
from .store import JobStore
from .store.lists import digest_candidates
from .store.projects import insert_suggested, projects_for_jobs

log = logging.getLogger(__name__)

MAX_TOP = 5
SKILLS_SECTION = "Skills (confirmed)"
POSTING = "posting"
MAX_HOURS = 10

SYSTEM = """You suggest one small project a job seeker could build in one day to show one employer they \
can do the job. You get the job posting and the seeker's confirmed skills, nothing else about them.

- problem: the problem this team most likely has that the role is hired to solve, in one sentence.
- quote: the words in the posting that show that problem, copied exactly, word for word (at least 5 words).
- title: a short project title.
- does: exactly 3 short lines saying what the project does.
- stack: the languages, frameworks and tools to build it with, small enough to build in one day: the \
ones the posting names (with its own spelling), preferring those also in their skills. When the posting \
names none, pick from their skills.
- shows: one sentence on what the finished project would show this employer.
- hours: how many hours it takes, 1 to 10.
- limits: one sentence on what it leaves out (no real company data, no logins, a small sample).

Never claim the seeker has experience, years or past work with anything: you do not know their history. \
Say what the project does and shows, not what they have done. No company data, logos or brand."""

SCHEMA = {
    "type": "object",
    "properties": {
        "problem": {"type": "string"},
        "quote": {"type": "string"},
        "title": {"type": "string"},
        "does": {"type": "array", "items": {"type": "string"}},
        "stack": {"type": "array", "items": {"type": "string"}},
        "shows": {"type": "string"},
        "hours": {"type": "number"},
        "limits": {"type": "string"},
    },
    "required": ["problem", "quote", "title", "does", "stack", "shows", "hours", "limits"],
    "additionalProperties": False,
}
EXAMPLE = json.dumps({
    "problem": "Their payment events arrive out of order and reports disagree.",
    "quote": "reconcile payment events from several providers",
    "title": "Payment event reconciler",
    "does": ["Reads sample payment events from two made-up providers.",
             "Matches them by id and amount and flags the ones that disagree.",
             "Serves the result as a small JSON API with tests."],
    "stack": ["Python", "FastAPI", "PostgreSQL"],
    "shows": "That you can turn messy event data into a tested service in their stack.",
    "hours": 6,
    "limits": "Made-up sample data only; no real provider APIs.",
})

# Words that claim experience. The idea is about a project to build, never about the seeker's past. Narrow on
# purpose: "user experience in checkout" or "domain expertise" describe the team, not a claim.
_CLAIM = re.compile(
    r"\b(?:years?|yrs) of (?:experience|work|professional)\b|\bexperienced (?:in|with)\b"
    r"|\b(?:your|hands-on|prior|previous|proven|professional) experience\b|\btrack record\b|\bseasoned\b"
    r"|\byour (?:background|past work|career)\b|\bmy\b"
    r"|\byou(?:'ve| have)(?: already)? (?:built|worked|used|led|shipped|run|managed|designed|experience)\b"
    r"|\balready (?:know|built|used)\b", re.I)
# "I", "I've", "I have" (case matters: "i" is rarely a word, and "I/O" is not a person).
_FIRST_PERSON = re.compile(r"\bI(?:'ve|'m| have| am)?\b(?!/)")


@dataclass
class DigestConfig:
    """config/digest.json."""

    model: str = "claude-code"
    top: int = MAX_TOP
    min_score: int = 60
    description_chars: int = 6000
    workers: int = 3

    @classmethod
    def load(cls, path: Path) -> DigestConfig:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Pick:
    row: sqlite3.Row
    score: int
    others: int = 0  # the company's other open jobs that day
    idea: dict | None = None
    project_id: int | None = None
    note: str = ""


@dataclass
class DigestRun:
    day: str
    picks: list[Pick] = field(default_factory=list)
    candidates: int = 0
    unscored: int = 0
    asked: int = 0
    added: int = 0
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    path: Path | None = None


def pick_jobs(rows: list[sqlite3.Row], top: int, min_score: int) -> list[Pick]:
    """The best job of each company with a score of `min_score` or more, best first, at most `top` (and 5)."""
    scored = [row for row in rows if grade_of(row)]
    scored.sort(key=lambda row: (grade_of(row)["score"], row["fit_score"], row["id"]), reverse=True)
    picks = []
    for best, others in one_per_company(scored):
        score = grade_of(best)["score"]
        if score >= min_score:
            picks.append(Pick(best, score, len(others)))
    return picks[: max(1, min(top, MAX_TOP))]


def skills_text(profile_path: Path) -> str:
    """The profile's Skills section as its bullet lines, without your notes or TODOs. Nothing else of the profile."""
    if not profile_path.exists():
        return ""
    body = sections(profile_path.read_text()).get(SKILLS_SECTION, "")
    lines = [strip_notes(line.strip()) for line in body.splitlines() if line.strip().startswith("- ")]
    return "\n".join(line for line in lines if line and "TODO" not in line)


def _words(text: str) -> str:
    return " " + " ".join(re.findall(r"[a-z0-9+#]+", text.lower())) + " "


def _has(text: str, name: str) -> bool:
    """`name` word for word in `text` (case and punctuation ignored): "Node.js" in "we use Node.js"."""
    wanted = _words(name).strip()
    return bool(wanted) and f" {wanted} " in _words(text)


def posting_text(row: sqlite3.Row) -> str:
    return f"{row['title']}\n{row['description'] or ''}"


def _posting_message(row: sqlite3.Row, skills: str, chars: int) -> str:
    description = " ".join((row["description"] or "").split())
    cut = description[:chars] + (" …" if len(description) > chars else "")
    return "\n".join([
        "## Their skills (confirmed)", skills or "(none listed)", "",
        "## The posting", f"Title: {row['title']}", f"Company: {row['company']}",
        f"Location: {row['location_raw'] or 'not given'}", f"Posting: {cut or '(no text)'}",
    ])


def check_idea(answer: dict, row: sqlite3.Row, skills: str) -> tuple[dict | None, str]:
    """(the idea code could check, "") or (None, why it was dropped)."""
    if not isinstance(answer, dict):
        return None, "the model gave no answer"
    text = posting_text(row)
    clean = {k: " ".join(str(answer.get(k) or "").split()) for k in ("problem", "quote", "title", "shows", "limits")}
    does = [" ".join(str(line).split()) for line in answer.get("does") or [] if str(line).strip()][:3]
    if not all(clean[k] for k in ("problem", "quote", "title", "shows")) or not does:
        return None, "the model left out part of the idea"
    if not find_quote(clean["quote"], [(POSTING, text)]):
        return None, f"its quote is not in the posting: \"{clean['quote'][:120]}\""
    for part in (clean["problem"], clean["title"], clean["shows"], clean["limits"], *does):
        claim = _CLAIM.search(part) or _FIRST_PERSON.search(part)
        if claim:
            return None, f"it claims experience (\"{claim.group(0)}\" in \"{part[:120]}\")"
    try:
        hours = float(answer.get("hours"))
    except (TypeError, ValueError):
        return None, "no hours given"
    if not 1 <= hours <= MAX_HOURS:
        return None, f"not buildable in a day ({hours:g} hours)"
    stack, left_out = [], []
    for item in answer.get("stack") or []:
        name = " ".join(str(item).split())
        if not name or any(s["name"].lower() == name.lower() for s in stack):
            continue
        in_posting, yours = _has(text, name), _has(skills, name)
        if in_posting or yours:
            stack.append({"name": name, "yours": yours, "in_posting": in_posting})
        else:
            left_out.append(name)
    if not stack:
        return None, "none of its stack is named in the posting or your skills"
    idea = {**clean, "does": does, "stack": stack, "hours": round(hours, 1)}
    if left_out:
        idea["left_out"] = left_out  # stack items named neither in the posting nor in your skills
    return idea, ""


class IdeaWriter:
    def __init__(self, config: DigestConfig, model: JsonModel):
        self.config = config
        self.model = model

    @property
    def label(self) -> str:
        return self.config.model

    def ask(self, row: sqlite3.Row, skills: str) -> tuple[dict, Usage]:
        usage = Usage()
        message = _posting_message(row, skills, self.config.description_chars)
        answer = self.model.ask(SYSTEM, [{"role": "user", "content": message}], SCHEMA, usage, EXAMPLE,
                                max_tokens=1200)
        return answer, usage


def build_writer(config: DigestConfig) -> tuple[IdeaWriter | None, str | None]:
    """(the writer, None), or (None, why the ideas are off)."""
    model, note = json_model(config.model, "Digest ideas")
    return (IdeaWriter(config, model), None) if model else (None, note)


def run_digest(store: JobStore, writer: IdeaWriter | None, config: DigestConfig, profile_path: Path,
               reports_dir: Path, day: str, now: datetime, top: int | None = None) -> DigestRun:
    """Pick the day's jobs, get an idea for each that has no project yet, save the kept ones, write the file."""
    run = DigestRun(day)
    rows = digest_candidates(store, day)
    run.candidates = len(rows)
    run.unscored = sum(1 for row in rows if not grade_of(row))
    run.picks = pick_jobs(rows, top or config.top, config.min_score)
    existing = projects_for_jobs(store, [p.row["id"] for p in run.picks])
    to_ask = []
    for rank, pick in enumerate(run.picks, 1):
        project = existing.get(pick.row["id"])
        if project:
            pick.project_id = project["id"]
            pick.idea = json.loads(project["idea_json"]) if project["idea_json"] else None
            pick.note = f"project #{project['id']} ({project['status']}) from an earlier run"
        else:
            to_ask.append((rank, pick))
    skills = skills_text(profile_path)
    if to_ask and writer is None:
        run.notes.append("ideas are off: no model")
    elif to_ask and not skills:
        run.notes.append(f"no Skills section in {profile_path}: no ideas")
    elif to_ask:
        store.commit()  # nothing is held open while the model thinks
        with ThreadPoolExecutor(max_workers=max(1, writer.config.workers)) as pool:
            futures = [(rank, pick, pool.submit(writer.ask, pick.row, skills)) for rank, pick in to_ask]
            for rank, pick, future in futures:
                run.asked += 1
                try:
                    answer, usage = future.result()
                except Exception as exc:  # one failed idea must not stop the rest
                    log.warning("digest idea #%s failed: %s", pick.row["id"], error_line(exc))
                    run.errors.append(f"#{pick.row['id']} {pick.row['company']}: {error_line(exc)}")
                    pick.note = "no idea: the model call failed"
                    continue
                run.cost_usd += usage.cost(writer.label) or 0
                idea, why = check_idea(answer, pick.row, skills)
                if idea is None:
                    pick.note = f"idea dropped: {why}"
                    continue
                idea.update(digest_date=day, rank=rank, score=pick.score, model=writer.label)
                stack = ", ".join(s["name"] for s in idea["stack"])
                pick.project_id = insert_suggested(store, pick.row["id"], idea["title"], idea, stack, now)
                store.commit()
                pick.idea = idea
                run.added += 1
    run.path = write_digest(reports_dir, run, config.min_score)
    return run


def _stack_line(stack: list[dict]) -> str:
    return ", ".join(s["name"] + ("" if s.get("yours") else " (new to you)") for s in stack)


def render(run: DigestRun, min_score: int) -> str:
    out = [f"# Daily digest, {run.day}", ""]
    out.append(f"Top {len(run.picks)} of the day's {run.candidates} open jobs (shortlisted or visa list, still "
               f"New), one per company, fit score {min_score} or more.")
    if run.unscored:
        out.append(f"{run.unscored} of them have no fit score yet, so they could not be picked (`jobhunter grade`).")
    out += ["Nothing is built until you say go.", ""]
    if not run.picks:
        out += ["_No job scored well enough today._", ""]
    for n, pick in enumerate(run.picks, 1):
        row = pick.row
        out.append(f"## {n}. {row['title']} at {row['company']} ({pick.score}/100, job #{row['id']})")
        out.append("")
        place = row["location_raw"] or "location not given"
        link = row["application_url"] or row["source_url"] or ""
        status = "visa list" if row["status"] == "visa_list" else "shortlisted"
        out.append(f"{place} · {status}" + (f" · [posting]({link})" if link else "")
                   + (f" · {pick.others} more open at {row['company']}" if pick.others else ""))
        out.append("")
        idea = pick.idea
        if not idea:
            out += [f"_{pick.note or 'No idea.'}_", ""]
            continue
        out += [f"**Their likely problem:** {idea['problem']}", "", f"> \"{idea['quote']}\"", "",
                f"**Project: {idea['title']}**", ""]
        out += [f"- {line}" for line in idea["does"]]
        out += ["", f"**Stack:** {_stack_line(idea['stack'])}", "",
                f"**What it shows them:** {idea['shows']}", "",
                f"**Hours:** {idea['hours']:g} · **Limits:** {idea['limits'] or 'none given'}", ""]
        out += [f"_Project #{pick.project_id}, suggested" + (f"; {pick.note}" if pick.note else "") + "._", ""]
    return "\n".join(out)


def write_digest(reports_dir: Path, run: DigestRun, min_score: int) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"digest_{run.day}.md"
    path.write_text(render(run, min_score))
    return path
