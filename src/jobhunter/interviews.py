"""What a company's interviews are like, for the fit score's 20 interview points (rubric.py).

Asked only for a company whose posting does not say. One lookup per company, kept in the
`interview_styles` table and asked again after `interview_recheck_days`. First the public
"hiring-without-whiteboards" list (MIT, one line per company with a note on its process; read
by code, its note judged with the same phrases as a posting), then the model (Claude Code with
web search), which names a page and quotes it; code fetches that page itself and the answer
counts only when the quote is found there (find_quote), like the posting dates (posted_date.py).
A quote only the model saw is stored as "not found", never used. Glassdoor, Reddit, Blind,
levels.fyi and Kununu block or forbid scripts (docs/research/2026-11-15-hiring-track-record-and-
interview-style.md): never fetched, and their quotes are not used.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .ai_check import fetch_page, for_quotes
from .config import Filters
from .fitgrade import FitGradeConfig, grade_of, rescore, to_grade
from .identity import company_key
from .llm import JsonModel, Usage, error_line, find_quote, json_model
from .store import JobStore
from .store.companies import interview_styles, save_interview_style
from .text import parse_datetime

log = logging.getLogger(__name__)

HWW_URL = "https://raw.githubusercontent.com/poteto/hiring-without-whiteboards/main/README.md"
HWW = "hiring-without-whiteboards"
# Sites that block scripts or forbid them in their terms: never fetched, so never a source.
NO_FETCH = ("glassdoor.", "reddit.com", "teamblind.com", "levels.fyi", "kununu.com")
_HWW_LINE = re.compile(r"^- \[(?P<name>[^\]]+)\]\([^)]*\)\s*\|[^|\n]*\|\s*(?P<note>.+)$", re.M)
_LIVE = re.compile(r"\b(?:live[- ]coding|pair[- ]programming|pair[- ]coding|whiteboard\w*|hackerrank|leetcode|"
                   r"codility|coderpad|codesignal)\b", re.I)
_NEGATED = re.compile(r"\b(?:no|not|never|without|instead of)\b[^.;,]{0,20}$", re.I)
_PROCESS = re.compile(r"\b(?:take[- ]home|assignment|project|exercise|interview|call|discussion|conversation|stage|step)s?\b",
                      re.I)
_NUMBERS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
_ROUNDS = re.compile(r"\b(\d|two|three|four|five|six|seven)[- ](?:stages?|steps?|rounds?|interviews?)\b", re.I)


def read_note(note: str) -> dict | None:
    """A process note or quote judged by code: live coding named (and not negated) is "yes"; live coding
    negated ("no whiteboard"), or a process described without it, is "no"; anything else None."""
    found = list(_LIVE.finditer(note))
    live = next((m for m in found if not _NEGATED.search(note[:m.start()])), None)
    if not live and not found and not _PROCESS.search(note):  # "We never do live coding" says no by itself
        return None
    m = _ROUNDS.search(note)
    rounds = (int(m.group(1)) if m.group(1).isdigit() else _NUMBERS[m.group(1).lower()]) if m else None
    return {"live_coding": "yes" if live else "no", "rounds": rounds, "quote": " ".join(note.split())[:300]}


def parse_hww(text: str) -> dict[str, str]:
    """{company key: its process note} from the list's README."""
    return {company_key(m.group("name")): m.group("note").strip() for m in _HWW_LINE.finditer(text or "")}


SYSTEM = """You find out how one company interviews software engineers, from pages on the web: \
the company's own careers or "how we hire" page, its engineering blog, or a public GitHub repository \
about its hiring. Do not use Glassdoor, Reddit, Blind, levels.fyi or Kununu: their pages cannot be checked.

Answer:
- live_coding: "yes" when the process has live coding, pair programming, a whiteboard, or a coding \
test such as HackerRank, Codility or LeetCode; "no" when a source describes the process and it has none \
of those (a take-home assignment or a system design talk is "no"); "unknown" when you found nothing clear.
- rounds: the number of interview stages, or null.
- quote: the exact words from source_url that say so, copied word for word (code checks them on that page). \
The quote itself must name the step ("a 60-minute pair programming session", "a take-home task, then a \
call"): code reads the quote, not the page title.
- source_url: the page the quote is on.
- reason: one short sentence on what you found.

Only answer "yes" or "no" with a quote from a page you opened. Use at most 3 searches and 3 page fetches."""

SCHEMA = {
    "type": "object",
    "properties": {
        "live_coding": {"type": "string", "enum": ["yes", "no", "unknown"]},
        "rounds": {"type": ["integer", "null"]},
        "quote": {"type": "string"},
        "source_url": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["live_coding", "rounds", "quote", "source_url", "reason"],
    "additionalProperties": False,
}
EXAMPLE = json.dumps({"live_coding": "no", "rounds": 3, "quote": "We don't do live coding interviews.",
                      "source_url": "https://example.com/careers/how-we-hire", "reason": "Their hiring page says so."})


@dataclass
class Lookup:
    answer: dict | None  # {"live_coding", "rounds", "quote", "source"} when the quote was found
    found_by: str
    source_url: str
    reason: str


@dataclass
class InterviewFinder:
    model: JsonModel | None
    http: object
    label: str = ""
    _hww: dict[str, str] | None = None

    def listed(self, company: str) -> Lookup | None:
        """The company's line on hiring-without-whiteboards, read by code, or None (read once per run)."""
        if self._hww is None:
            try:
                self._hww = parse_hww(self.http.get_text(HWW_URL))
            except Exception as exc:
                log.info("interviews: could not read %s: %s", HWW, error_line(exc))
                self._hww = {}
        note = self._hww.get(company_key(company))
        found = read_note(note) if note else None
        if found is None:
            return None
        return Lookup({**found, "source": HWW}, HWW, HWW_URL, f"On {HWW}: {found['quote'][:120]}")

    def find(self, company: str, hint: str = "") -> Lookup:
        """One company. Raises on a model error, so it is tried again next run."""
        listed = self.listed(company)
        if listed or self.model is None:
            return listed or Lookup(None, HWW, "", f"Not on {HWW}")
        prompt = f"Company: {company}\n{hint}".strip()
        answer = self.model.ask(SYSTEM, [{"role": "user", "content": prompt}], SCHEMA, Usage(), EXAMPLE)
        live = answer.get("live_coding") if answer.get("live_coding") in ("yes", "no") else "unknown"
        quote = " ".join(str(answer.get("quote") or "").split())
        url = str(answer.get("source_url") or "").strip()
        reason = " ".join(str(answer.get("reason") or "").split())[:300]
        if live == "unknown" or not quote or not url.startswith("http"):
            return Lookup(None, self.label, url, reason or "nothing clear found")
        if any(host in url.lower() for host in NO_FETCH):
            return Lookup(None, self.label, url, f"Not used: that site blocks scripts, so its quote cannot be checked. {reason}")
        page = fetch_page(url, self.http)
        found_at = find_quote(quote, for_quotes(url, page)) if page else None
        if found_at is None:
            why = "the page could not be read" if page is None else "its quote was not found on the page"
            return Lookup(None, self.label, url, f"Not used: {why}. {reason}")
        read = read_note(quote)
        if read is None or read["live_coding"] != live:
            return Lookup(None, self.label, found_at, f"Not used: its quote does not say so by itself. {reason}")
        rounds = answer.get("rounds")
        return Lookup({"live_coding": live, "rounds": rounds if isinstance(rounds, int) and rounds > 0 else None,
                       "quote": quote, "source": found_at}, self.label, found_at, reason)


def build_finder(config: FitGradeConfig) -> tuple[InterviewFinder | None, str | None]:
    """The finder: the list always, the web step when `interview_model` can run (else a note why not)."""
    if config.max_interview_lookups_per_run <= 0:
        return None, None
    from .http import Http

    model, note = json_model(config.interview_model, "interview lookup web step") if config.interview_model else (None, None)
    if model is not None:
        model.tools = "WebSearch,WebFetch"
    return InterviewFinder(model, Http(timeout=20, retries=1), config.interview_model if model else HWW), note


@dataclass
class InterviewRun:
    looked_up: int = 0
    found: int = 0
    errors: list[str] = field(default_factory=list)
    changed_days: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {"looked_up": self.looked_up, "found": self.found, "errors": self.errors}


def said_in_posting(grade: dict) -> bool:
    """Whether the posting itself said how they interview (then no lookup is needed)."""
    interview = grade.get("answer", {}).get("interview") or {}
    return "(posting)" in str((grade.get("parts", {}).get("interview") or [0, ""])[1]) and bool(interview)


def companies_to_look_up(store: JobStore, config: FitGradeConfig, now: datetime) -> dict[str, list]:
    """{company key: its open scored rows} for companies whose postings do not say how they interview and
    that were not looked up in the last interview_recheck_days. Best score first."""
    rows = [r for r in to_grade(store, now, config.lookback_days, regrade=True) if grade_of(r)]
    waiting: dict[str, list] = {}
    for row in sorted(rows, key=lambda r: -grade_of(r)["score"]):
        if said_in_posting(grade_of(row)):
            continue
        waiting.setdefault(company_key(row["company"]), []).append(row)
    done = interview_styles(store, list(waiting))
    fresh_after = now - timedelta(days=config.interview_recheck_days)
    return {k: v for k, v in waiting.items()
            if k and not (k in done and (parse_datetime(done[k]["checked_at"]) or now) >= fresh_after)}


def look_up_interviews(store: JobStore, finder: InterviewFinder, config: FitGradeConfig, profile_path: Path,
                       now: datetime, filters: Filters | None = None) -> InterviewRun:
    """Look up the best-scored companies (up to the per-run cap), save each, and rescore their jobs."""
    run = InterviewRun()
    for key, rows in list(companies_to_look_up(store, config, now).items())[: config.max_interview_lookups_per_run]:
        company = rows[0]["company"]
        try:
            found = finder.find(company, f"Job they are hiring for: {rows[0]['title']}")
        except Exception as exc:  # one company must not stop the rest
            log.warning("interview lookup %s failed: %s", company, error_line(exc))
            run.errors.append(f"{company}: {error_line(exc)}")
            continue
        save_interview_style(store, key, company, found.answer, found.found_by, found.source_url, found.reason, now)
        run.looked_up += 1
        run.found += bool(found.answer)
        if found.answer:
            run.changed_days |= rescore(store, [store.get(r["id"]) for r in rows], profile_path, filters)
        store.commit()
    return run
