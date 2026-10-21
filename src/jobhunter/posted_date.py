"""When was an undated job posted? For jobs in needs_review that no source gave a date.

A job with no date is never shortlisted (classify: an unknown age is not a fresh
one), and Google Jobs through SerpApi often gives none. Two steps, like the AI check:

1. Code fetches the job's own links (ai_check.job_links) and reads the schema.org
   JobPosting `datePosted` the page gives search engines: where Google gets its date.
2. Only when no page has one: `web_model` (the Claude Code CLI with WebSearch and
   WebFetch) looks for the date and quotes the words that state it. Code fetches
   that page, finds the quote word for word (find_quote) and reads the date out of
   the quote itself ("Posted 5 days ago", "October 2, 2026"): the model's own idea
   of the date is never used.

A found date goes into jobs.posted_at and the evidence into jobs.date_check_json,
and the usual age rule judges the job: a fresh one is shortlisted, an old one is
rejected as too_old. Settings live in config/ai_check.json (`find_dates`,
`max_dates_per_run`).
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .ai_check import JOB_DESCRIPTION, AiCheckConfig, _for_quotes, fetch_page, job_links
from .classify import classify, recheck_age
from .config import Filters
from .llm import CLAUDE_CODE, JsonModel, Usage, error_line, find_quote, json_model
from .models import Classification, DateCheck, Job
from .store import JobStore, row_to_job
from .text import iso, parse_datetime, parse_relative_age

log = logging.getLogger(__name__)

FOUND_ON_PAGE = "page"

# The JSON-LD a job page gives search engines, or the same as microdata.
_DATE_POSTED = re.compile(
    r""""datePosted"\s*:\s*"(?P<date>[^"]{8,40})"|itemprop=["']datePosted["'][^>]*?content=["'](?P<meta>[^"']{8,40})""",
    re.I,
)
_ISO_DATE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
_MONTH = r"(?P<month>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_MONTH_FIRST = re.compile(_MONTH + r"\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<year>20\d\d)\b", re.I)
_DAY_FIRST = re.compile(r"\b(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+" + _MONTH + r",?\s+(?P<year>20\d\d)\b", re.I)
_TODAY = re.compile(r"\b(?:just\s+posted|posted\s+today|today)\b", re.I)
_YESTERDAY = re.compile(r"\byesterday\b", re.I)

SYSTEM = """\
You find the date a job posting was first published.

Search the web for this exact role at this company: the company's careers page \
or its Greenhouse, Lever, Ashby or Workable board, LinkedIn, or a job board that \
shows when it was posted ("Posted 5 days ago", "Date posted: October 2, 2026"). \
Make sure it is the same role: same company and same title. When pages disagree, \
use the earliest date.

Open the page with WebFetch. Code fetches that URL again and looks for your \
quote there, then reads the date from the quote, so:
- quote: copied character for character from the page: the words that state \
the date, with the date in them ("Posted 5 days ago", "Posted on October 2, \
2026", "\\"datePosted\\": \\"2026-10-02\\""). Do not paraphrase or add words.
- source_url: the page the quote comes from.
- found: false when no page says when it was posted; quote and source_url may \
then be empty.
- reason: one plain sentence, e.g. "The company's Lever posting shows Posted \
on October 2, 2026."

Answer with the JSON only.
"""

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "reason": {"type": "string", "description": "One plain sentence."},
        "quote": {"type": "string", "description": "Exact words from the page that state the date."},
        "source_url": {"type": "string", "description": "The page the quote is from."},
    },
    "required": ["found", "reason", "quote", "source_url"],
    "additionalProperties": False,
}
ANSWER_EXAMPLE = ('{"found": true, "reason": "The Lever posting shows Posted on October 2, 2026.", '
                  '"quote": "Posted on October 2, 2026", "source_url": "https://jobs.lever.co/acme/1234"}')


def date_in(quote: str, now: datetime) -> datetime | None:
    """The date a quote states, read by code: a date, or an age counted back from now. None for a future date."""
    found = None
    if m := _ISO_DATE.search(quote):
        found = _day(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    elif m := (_MONTH_FIRST.search(quote) or _DAY_FIRST.search(quote)):
        found = _day(int(m.group("year")), _MONTHS[m.group("month").lower()[:3]], int(m.group("day")))
    elif aged := parse_relative_age(quote, now):
        found = aged
    elif _YESTERDAY.search(quote):
        found = now - timedelta(days=1)
    elif _TODAY.search(quote):
        found = now
    if found is None or found > now + timedelta(days=1):
        return None
    return found.replace(microsecond=0)


def _day(year: int, month: int, day: int) -> datetime | None:
    try:  # noon UTC, so the date stays the same in Beirut
        return datetime(year, month, day, 12, tzinfo=timezone.utc)
    except ValueError:
        return None


def date_on_page(raw: str) -> tuple[str, str] | None:
    """(the datePosted text as written, its value) from a page's schema.org data, or None."""
    for m in _DATE_POSTED.finditer(raw):
        value = m.group("date") or m.group("meta")
        if parse_datetime(value) or _ISO_DATE.search(value):
            return " ".join(m.group(0).split()), value
    return None


def _from_value(value: str) -> datetime | None:
    parsed = parse_datetime(value)
    if parsed:
        return parsed.astimezone(timezone.utc).replace(microsecond=0)
    m = _ISO_DATE.search(value)
    return _day(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


@dataclass
class DateFinder:
    """Code reads the job's pages; `model` (Claude Code with web search) only when none has a date."""

    config: AiCheckConfig
    http: object
    model: JsonModel | None = None
    label: str = FOUND_ON_PAGE

    def find(self, job: Job, now: datetime) -> DateCheck:
        """One job. Raises on a model error, so it is tried again next run."""
        for url in job_links(job, self.config.max_fetches_per_job):
            page = fetch_page(url, self.http)
            found = date_on_page(page[1]) if page else None
            posted = _from_value(found[1]) if found else None
            if posted and posted <= now + timedelta(days=1):
                return DateCheck(iso(posted), found[0], url, FOUND_ON_PAGE,
                                 "The page's schema.org data gives the date it was posted.", iso(now))
        if self.model is None:
            return DateCheck(None, found_by=FOUND_ON_PAGE, reason="No page of the job gives a date.",
                             checked_at=iso(now))
        return self._search(job, now)

    def _search(self, job: Job, now: datetime) -> DateCheck:
        links = dict.fromkeys(u for u in (job.application_url, job.source_url) if u)
        prompt = "\n".join([
            f"Company: {job.company}",
            f"Job title: {job.title}",
            f"Location as posted: {job.location_raw or 'none'}",
            f"Links: {', '.join(links) or 'none'}",
            f"First seen by us: {(job.first_seen or now).date().isoformat()}",
            "",
            f"Use at most {self.config.max_searches_per_job} searches and {self.config.max_fetches_per_job} page fetches.",
        ])
        answer = self.model.ask(SYSTEM, [{"role": "user", "content": prompt}], ANSWER_SCHEMA, Usage(), ANSWER_EXAMPLE)
        quote = " ".join(str(answer.get("quote") or "").split())
        stated_url = str(answer.get("source_url") or "").strip()
        reason = " ".join(str(answer.get("reason") or "").split())
        base = DateCheck(None, quote, stated_url, self.label, reason, iso(now))
        if not answer.get("found") or not quote:
            return base
        pages = [(JOB_DESCRIPTION, job.description or "")]
        if stated_url.startswith("http") and (page := fetch_page(stated_url, self.http)):
            pages += _for_quotes(stated_url, page)
        found_at = find_quote(quote, pages, stated_url)
        posted = date_in(quote, now) if found_at else None
        if found_at is None:
            return replace(base, reason=f"Its quote was not found on the page, so it is not used. {reason}")
        if posted is None:
            return replace(base, source_url=found_at, reason=f"Its quote states no date code can read. {reason}")
        return replace(base, posted_at=iso(posted), source_url=found_at)


def build_finder(config_file: Path, require_enabled: bool = True) -> tuple[DateFinder | None, str | None]:
    """The finder, or None and (when it matters) a note saying why it is off. The web step uses
    `web_model` from config/ai_check.json, or `model` when that is Claude Code; without one, pages only."""
    config = AiCheckConfig.load(config_file)
    if require_enabled and not (config.enabled and config.find_dates):
        return None, None
    from .http import Http

    finder = DateFinder(config, Http(timeout=20, retries=1))
    web = config.web_model or (config.model if config.model.startswith(CLAUDE_CODE) else "")
    if not web:
        return finder, None
    model, note = json_model(web, "posting dates web step")
    if model is None:
        return finder, f"posting dates: no web step ({note}); job pages only"
    model.tools, model.timeout = "WebSearch,WebFetch", config.web_timeout
    finder.model, finder.label = model, web
    return finder, None


# --- running over stored jobs ---------------------------------------------


@dataclass
class DateRun:
    checked: int = 0
    found: Counter = field(default_factory=Counter)
    status_changes: Counter = field(default_factory=Counter)
    changed_days: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    model: str = ""

    def to_dict(self) -> dict:
        return {
            "checked": self.checked,
            "found": dict(self.found),
            "status_changes": dict(self.status_changes),
            "errors": self.errors,
            "notes": self.notes,
            "model": self.model,
        }


def find_dates(store: JobStore, finder: DateFinder, rows, filters: Filters, now: datetime,
               on_result=None) -> DateRun:
    """Look up `rows`, save each result as it arrives and re-classify that job.

    on_result(row, check, classification) is called for each finished job.
    """
    run = DateRun(model=finder.label)
    rows = list(rows)
    if not rows:
        return run
    with ThreadPoolExecutor(max_workers=max(1, finder.config.workers)) as pool:
        futures = {pool.submit(finder.find, row_to_job(row), now): row for row in rows}
        for future in as_completed(futures):
            row = futures[future]
            try:
                check = future.result()
            except Exception as exc:
                run.errors.append(f"#{row['id']} {row['company']}: {error_line(exc)}")
                continue
            store.save_date_check(row["id"], check)
            stored = store.get(row["id"])
            cls: Classification = classify(row_to_job(stored), filters, now, check_age=recheck_age(stored))
            store.update_classification(row["id"], cls)
            store.commit()
            run.checked += 1
            run.found[f"found by {check.found_by}" if check.posted_at else "not found"] += 1
            if cls.status != row["status"]:
                run.status_changes[f"{row['status']} -> {cls.status}"] += 1
                if row["report_date"]:
                    run.changed_days.add(row["report_date"])
            if on_result:
                on_result(row, check, cls)
    return run
