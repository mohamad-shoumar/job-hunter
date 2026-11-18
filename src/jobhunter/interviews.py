"""A company's AI engineering culture, for the fit score's 20 culture points (rubric.py).

Asked only for a company whose posting does not show it. One lookup per company, kept in the
`interview_styles` table and asked again after `interview_recheck_days`. The model (Claude Code
with web search) reads the company's engineering blog, careers and "how we hire" pages and what
it says about AI tools, and tags it AI-native, traditional or unknown, naming a page and quoting
it; code fetches that page itself and the tag counts only when the quote is found there
(find_quote), like the posting dates (posted_date.py). A quote only the model saw is stored as
"not found", never used. Glassdoor, Reddit, Blind, levels.fyi and Kununu block or forbid scripts
(docs/research/2026-11-15-hiring-track-record-and-interview-style.md): never fetched, and their
quotes are not used. Until 2026-11-18 this looked up live coding only; a row checked before
CULTURE_FROM is looked up again.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .ai_check import fetch_page, for_quotes
from .config import Filters
from .fitgrade import POSTING, FitGradeConfig, grade_of, rescore, to_grade
from .identity import company_key
from .llm import JsonModel, Usage, error_line, find_quote, json_model
from .rubric import AI_NATIVE, CULTURE_TAGS, UNKNOWN
from .store import JobStore
from .store.companies import interview_styles, save_interview_style
from .text import parse_datetime

log = logging.getLogger(__name__)

# Sites that block scripts or forbid them in their terms: never fetched, so never a source.
NO_FETCH = ("glassdoor.", "reddit.com", "teamblind.com", "levels.fyi", "kununu.com")
# Lookups before this asked about live coding only: they are done again.
CULTURE_FROM = datetime(2026, 11, 18, tzinfo=UTC)

SYSTEM = """You find out one company's AI engineering culture, from pages on the web: the company's \
engineering blog, its careers or "how we hire" page, its job postings, or a public GitHub repository \
about how it works. Do not use Glassdoor, Reddit, Blind, levels.fyi or Kununu: their pages cannot be checked.

Look at its engineering culture, how much it uses AI tools, and its interview process, and answer:
- tag: "ai_native" when engineers there use AI-assisted coding (Cursor, Copilot, Claude Code and the like), \
own the product and ship fast; "traditional" when it stresses deep language expertise, coding without AI \
help, or algorithm-heavy interviews (live coding, LeetCode, HackerRank, a whiteboard); "unknown" when you \
found too little to say.
- why: one sentence saying why.
- quote: the exact words from source_url that show it, copied word for word (code checks them on that page).
- source_url: the page the quote is on.

Only answer "ai_native" or "traditional" with a quote from a page you opened. Use at most 3 searches and \
3 page fetches."""

SCHEMA = {
    "type": "object",
    "properties": {
        "tag": {"type": "string", "enum": list(CULTURE_TAGS)},
        "why": {"type": "string"},
        "quote": {"type": "string"},
        "source_url": {"type": "string"},
    },
    "required": ["tag", "why", "quote", "source_url"],
    "additionalProperties": False,
}
EXAMPLE = json.dumps({"tag": AI_NATIVE, "why": "Their engineering blog says every engineer codes with AI agents.",
                      "quote": "Every engineer here works with Claude Code and Cursor every day.",
                      "source_url": "https://example.com/blog/how-we-build"})


@dataclass
class Lookup:
    answer: dict | None  # {"tag", "why", "quote", "source"} when the quote was found
    found_by: str
    source_url: str
    reason: str


@dataclass
class InterviewFinder:
    model: JsonModel | None
    http: object
    label: str = ""

    def find(self, company: str, hint: str = "") -> Lookup:
        """One company. Raises on a model error, so it is tried again next run."""
        if self.model is None:
            return Lookup(None, self.label, "", "no model to look it up")
        prompt = f"Company: {company}\n{hint}".strip()
        answer = self.model.ask(SYSTEM, [{"role": "user", "content": prompt}], SCHEMA, Usage(), EXAMPLE)
        tag = answer.get("tag") if answer.get("tag") in CULTURE_TAGS else UNKNOWN
        quote = " ".join(str(answer.get("quote") or "").split())
        url = str(answer.get("source_url") or "").strip()
        why = " ".join(str(answer.get("why") or "").split())[:300]
        if tag == UNKNOWN or not quote or not url.startswith("http"):
            return Lookup(None, self.label, url, why or "nothing clear found")
        if any(host in url.lower() for host in NO_FETCH):
            return Lookup(None, self.label, url, f"Not used: that site blocks scripts, so its quote cannot be checked. {why}")
        page = fetch_page(url, self.http)
        found_at = find_quote(quote, for_quotes(url, page)) if page else None
        if found_at is None:
            reason = "the page could not be read" if page is None else "its quote was not found on the page"
            return Lookup(None, self.label, url, f"Not used: {reason}. {why}")
        return Lookup({"tag": tag, "why": why, "quote": quote, "source": found_at}, self.label, found_at, why)


def build_finder(config: FitGradeConfig) -> tuple[InterviewFinder | None, str | None]:
    """The finder, when `interview_model` can run (else None and a note why not)."""
    if config.max_interview_lookups_per_run <= 0 or not config.interview_model:
        return None, None
    from .http import Http

    model, note = json_model(config.interview_model, "AI culture lookup")
    if model is None:
        return None, note
    model.tools = "WebSearch,WebFetch"
    return InterviewFinder(model, Http(timeout=20, retries=1), config.interview_model), None


@dataclass
class InterviewRun:
    looked_up: int = 0
    found: int = 0
    errors: list[str] = field(default_factory=list)
    changed_days: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {"looked_up": self.looked_up, "found": self.found, "errors": self.errors}


def said_in_posting(grade: dict) -> bool:
    """Whether the posting itself showed the culture, with a quote code found (then no lookup is needed)."""
    return f"({POSTING})" in str((grade.get("parts", {}).get("culture") or [0, ""])[1])


def companies_to_look_up(store: JobStore, config: FitGradeConfig, now: datetime) -> dict[str, list]:
    """{company key: its open scored rows} for companies whose postings do not show their AI culture and
    that were not looked up in the last interview_recheck_days (nor before CULTURE_FROM). Best score first."""
    rows = [r for r in to_grade(store, now, config.lookback_days, regrade=True) if grade_of(r)]
    waiting: dict[str, list] = {}
    for row in sorted(rows, key=lambda r: -grade_of(r)["score"]):
        if said_in_posting(grade_of(row)):
            continue
        waiting.setdefault(company_key(row["company"]), []).append(row)
    done = interview_styles(store, list(waiting))
    # min(): a clock before the change (the tests' made-up dates) has no live-coding-only rows to redo.
    fresh_after = max(now - timedelta(days=config.interview_recheck_days), min(CULTURE_FROM, now))
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
            log.warning("AI culture lookup %s failed: %s", company, error_line(exc))
            run.errors.append(f"{company}: {error_line(exc)}")
            continue
        save_interview_style(store, key, company, found.answer, found.found_by, found.source_url, found.reason, now)
        run.looked_up += 1
        run.found += bool(found.answer)
        if found.answer:
            run.changed_days |= rescore(store, [store.get(r["id"]) for r in rows], profile_path, filters)
        store.commit()
    return run
