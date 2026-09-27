"""AI web check for jobs the rules leave unclear (status needs_review).

The rules decide everything they can quote. When they cannot tell whether a
company hires from Lebanon ("Remote", no country list), Claude searches the
web - the company's own posting of the role, its careers page - and records a
verdict with a short quote and the page it came from.

The quote is then checked in code: it must appear word for word in the job
description or in text the API returned from a page Claude opened. Only a
verified quote changes a job's status (see classify.apply_ai_check):
`cannot_hire` rejects it, `can_hire` shortlists it as `likely`. Anything else
leaves it in needs_review with the finding attached.

Results are stored in jobs.ai_check_json, so `reclassify` keeps them, and a
job is checked once unless asked again (`jobhunter check --recheck`).
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path

from .classify import classify
from .config import Filters
from .eligibility import assess_eligibility
from .models import CAN_HIRE, CANNOT_HIRE, UNKNOWN_HIRE, AiCheck, Classification, Job
from .store import JobStore, row_to_job
from .text import iso

log = logging.getLogger(__name__)

JOB_DESCRIPTION = "job description"
MAX_REQUESTS = 6  # per job: pause_turn continuations, plus one nudge to record the verdict
DESCRIPTION_CHARS = 8000

# USD per million tokens (input, output), platform.claude.com/docs/en/models/overview,
# checked 2026-09-27. Only used for the cost estimate that runs print.
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5": (2.0, 10.0), "claude-haiku-4-5": (1.0, 5.0)}
SEARCH_PRICE = 10.0 / 1000

SYSTEM = """\
You check whether a company can hire a software engineer who lives in Lebanon \
(Beirut; UTC+2 in winter, UTC+3 in summer; Middle East; part of EMEA) to work \
remotely from Lebanon, as an employee or a contractor.

Research the web, then call record_verdict once.

Where to look, in order:
1. The company's own posting of this exact role: its careers page, or its \
Greenhouse, Lever, Ashby, Workable or similar board. Its location line often \
says what the job board did not, e.g. "Remote - US". Make sure it is the same \
role: a company may post one title for the US and another for EMEA.
2. The company's general policy: a careers page, handbook or FAQ that says \
where it hires.

Verdicts:
- cannot_hire: the evidence limits this role, or all of the company's hiring, \
to places that do not include Lebanon: a country list, "US only", "must be \
based in the EU", required time zones that exclude UTC+2/UTC+3, a list of \
employer-of-record countries without Lebanon.
- can_hire: the evidence explicitly allows Lebanon, anywhere/worldwide, or a \
region that includes Lebanon (EMEA, Middle East, "UTC+2 to UTC+4"), and \
nothing narrower applies to this role.
- unknown: anything else. A salary in USD, a US headquarters, US benefits or \
"US preferred" are not evidence. Neither is a job board's own "Worldwide" or \
"Anywhere" label. Say unknown rather than guess.

Evidence:
- When you find the page that answers the question, open it with web_fetch, \
so the quote can be checked against the page text.
- quote: copied character for character from that page, or from the job \
description below. A short phrase or one sentence, under 300 characters. Do \
not paraphrase, shorten with "...", or join separate parts.
- source_url: the page the quote comes from, or "job description".
- For unknown, quote and source_url may be empty.
- reason: one plain sentence, e.g. "The company's Greenhouse posting for this \
role lists Remote - United States only."
"""

RECORD_VERDICT = {
    "name": "record_verdict",
    "description": "Record the answer, once, after the research.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": [CAN_HIRE, CANNOT_HIRE, UNKNOWN_HIRE]},
            "reason": {"type": "string", "description": "One plain sentence."},
            "quote": {"type": "string", "description": "Exact text from the page or the job description."},
            "source_url": {"type": "string", "description": "The page the quote is from, or 'job description'."},
        },
        "required": ["verdict", "reason", "quote", "source_url"],
        "additionalProperties": False,
    },
}


@dataclass
class AiCheckConfig:
    """config/ai_check.json. `enabled` controls the daily run; `jobhunter check` runs either way."""

    enabled: bool = False
    model: str = "claude-opus-5-5"
    max_jobs_per_run: int = 25
    max_searches_per_job: int = 4
    max_fetches_per_job: int = 3
    max_page_tokens: int = 12000
    workers: int = 4

    @classmethod
    def load(cls, path: Path) -> AiCheckConfig:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def _plain(obj) -> dict:
    """SDK objects and test dicts alike, so new block types never break parsing."""
    if obj is None:
        return {}
    return obj if isinstance(obj, dict) else obj.model_dump()


def _words(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.lower()))


def find_quote(quote: str, pages: list[tuple[str, str]], stated_url: str = "") -> str | None:
    """Where the quote appears word for word (case and punctuation ignored), or None.

    Fewer than three words proves nothing ("Remote" is on every page).
    """
    wanted = _words(quote)
    if wanted.count(" ") < 2:
        return None
    for url, text in sorted(pages, key=lambda page: page[0] != stated_url):
        if f" {wanted} " in f" {_words(text)} ":
            return url
    return None


def _pages_read(blocks: list[dict]):
    """(url, text) for everything the API itself returned from the web."""
    for block in blocks:
        if block.get("type") == "web_fetch_tool_result":
            result = block.get("content") or {}
            source = (result.get("content") or {}).get("source") or {}
            if result.get("type") == "web_fetch_result" and source.get("type") == "text" and source.get("data"):
                yield result.get("url") or "", source["data"]
        elif block.get("type") == "text":
            # cited_text is extracted by the API from the page, not written by the model.
            for citation in block.get("citations") or []:
                if citation.get("cited_text") and citation.get("url"):
                    yield citation["url"], citation["cited_text"]


@dataclass
class _Usage:
    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0
    searches: int = 0

    def add(self, usage) -> None:
        u = _plain(usage)
        self.input += u.get("input_tokens") or 0
        self.output += u.get("output_tokens") or 0
        self.cache_write += u.get("cache_creation_input_tokens") or 0
        self.cache_read += u.get("cache_read_input_tokens") or 0
        self.searches += (u.get("server_tool_use") or {}).get("web_search_requests") or 0

    def cost(self, model: str) -> float | None:
        price = next((p for name, p in PRICES.items() if model.startswith(name)), None)
        if price is None:
            return None
        per_in, per_out = price
        tokens = self.input * per_in + self.cache_write * per_in * 1.25 + self.cache_read * per_in * 0.1
        return round((tokens + self.output * per_out) / 1e6 + self.searches * SEARCH_PRICE, 4)


def _job_message(job: Job, rule_reason: str) -> str:
    links = dict.fromkeys(u for u in (job.application_url, job.source_url) if u)
    return "\n".join([
        f"Company: {job.company}",
        f"Job title: {job.title}",
        f"Links: {', '.join(links) or 'none'}",
        f"Location as posted: {job.location_raw or 'none'}",
        f"What the rules found: {rule_reason}",
        "",
        "Job description:",
        (job.description or "(empty)")[:DESCRIPTION_CHARS],
    ])


class AiChecker:
    def __init__(self, config: AiCheckConfig, client):
        self.config = config
        self.client = client

    def _tools(self) -> list[dict]:
        return [
            {"type": "web_search_20260318", "name": "web_search", "max_uses": self.config.max_searches_per_job},
            {"type": "web_fetch_20260318", "name": "web_fetch", "max_uses": self.config.max_fetches_per_job,
             "max_content_tokens": self.config.max_page_tokens},
            RECORD_VERDICT,
        ]

    def check(self, job: Job, now: datetime) -> AiCheck:
        """One job. Raises on API errors, so a failed check is retried next run."""
        rule_reason = (assess_eligibility(job).reasons or [""])[0]
        messages: list[dict] = [{"role": "user", "content": _job_message(job, rule_reason)}]
        pages = [(JOB_DESCRIPTION, job.description or "")]
        usage = _Usage()
        tool_choice = {"type": "auto"}
        answer = None
        for _ in range(MAX_REQUESTS):
            response = self.client.messages.create(
                model=self.config.model, max_tokens=4096, system=SYSTEM, tools=self._tools(),
                tool_choice=tool_choice, messages=messages,
            )
            usage.add(response.usage)
            blocks = [_plain(b) for b in response.content]
            pages += list(_pages_read(blocks))
            answer = next((b.get("input") for b in blocks
                           if b.get("type") == "tool_use" and b.get("name") == "record_verdict"), None)
            if answer is not None:
                break
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason != "pause_turn":  # pause_turn: send it back as-is and the search goes on
                messages.append({"role": "user", "content": "Call record_verdict now with what you found."})
                tool_choice = {"type": "tool", "name": "record_verdict"}
        if answer is None:
            raise RuntimeError(f"no verdict after {MAX_REQUESTS} requests")

        verdict = answer.get("verdict") if answer.get("verdict") in (CAN_HIRE, CANNOT_HIRE) else UNKNOWN_HIRE
        quote = " ".join(str(answer.get("quote") or "").split())
        stated_url = str(answer.get("source_url") or "").strip()
        found_at = find_quote(quote, pages, stated_url) if verdict != UNKNOWN_HIRE else None
        return AiCheck(
            verdict=verdict,
            reason=" ".join(str(answer.get("reason") or "").split()),
            quote=quote,
            source_url=found_at or stated_url,
            verified=found_at is not None,
            model=self.config.model,
            checked_at=iso(now),
            searches=usage.searches,
            cost_usd=usage.cost(self.config.model),
        )


def build_checker(config_file: Path, require_enabled: bool = True) -> tuple[AiChecker | None, str | None]:
    """The checker, or None and (when it matters) a note saying why it is off."""
    config = AiCheckConfig.load(config_file)
    if require_enabled and not config.enabled:
        return None, None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None, "ai_check skipped: set ANTHROPIC_API_KEY in .env to turn it on"
    import anthropic  # only needed when the check runs

    return AiChecker(config, anthropic.Anthropic(max_retries=4, timeout=300)), None


# --- running over stored jobs ---------------------------------------------


@dataclass
class CheckRun:
    checked: int = 0
    verdicts: Counter = field(default_factory=Counter)
    status_changes: Counter = field(default_factory=Counter)
    changed_days: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    model: str = ""

    def to_dict(self) -> dict:
        return {
            "checked": self.checked,
            "verdicts": dict(self.verdicts),
            "status_changes": dict(self.status_changes),
            "errors": self.errors,
            "notes": self.notes,
            "cost_usd": round(self.cost_usd, 2),
            "model": self.model,
        }


def _error_line(exc: Exception) -> str:
    # The key travels in a header, so it is never part of these messages.
    return " ".join(f"{type(exc).__name__}: {exc}".split())[:300]


def _fatal(exc: Exception) -> bool:
    """Errors every other job would hit too: bad key, no credit, unknown model or tool."""
    return getattr(exc, "status_code", None) in (400, 401, 403, 404)


def check_jobs(store: JobStore, checker: AiChecker, rows, filters: Filters, now: datetime,
               on_result=None) -> CheckRun:
    """Check `rows`, save each result as it arrives and re-classify that job.

    on_result(row, check, classification) is called for each finished job.
    """
    run = CheckRun(model=checker.config.model)
    rows = list(rows)
    if not rows:
        return run
    stopped = False
    with ThreadPoolExecutor(max_workers=max(1, checker.config.workers)) as pool:
        futures = {pool.submit(checker.check, row_to_job(row), now): row for row in rows}
        for future in as_completed(futures):
            if future.cancelled():
                continue
            row = futures[future]
            try:
                check = future.result()
            except Exception as exc:
                run.errors.append(f"#{row['id']} {row['company']}: {_error_line(exc)}")
                if _fatal(exc) and not stopped:
                    stopped = True
                    run.notes.append("stopped early: the same error would hit every job")
                    for other in futures:
                        other.cancel()
                continue
            store.save_ai_check(row["id"], check)
            # Same rule as `reclassify`: age is not re-judged once a job sits in a report.
            check_age = not row["report_date"] or row["reject_code"] == "too_old"
            cls: Classification = classify(row_to_job(store.get(row["id"])), filters, now, check_age=check_age)
            store.update_classification(row["id"], cls)
            store.commit()
            run.checked += 1
            run.verdicts[check.verdict if check.verified or check.verdict == UNKNOWN_HIRE
                         else f"{check.verdict} (quote not found)"] += 1
            run.cost_usd += check.cost_usd or 0
            if cls.status != row["status"]:
                run.status_changes[f"{row['status']} -> {cls.status}"] += 1
                if row["report_date"]:
                    run.changed_days.add(row["report_date"])
            if on_result:
                on_result(row, check, cls)
    return run
