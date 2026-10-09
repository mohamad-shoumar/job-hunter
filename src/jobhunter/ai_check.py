"""AI web check for jobs the rules leave unclear (status needs_review).

The rules decide everything they can quote. When they cannot tell whether a
company hires from Lebanon ("Remote", no country list), Claude searches the
web - the company's own posting of the role, its careers page - and records a
verdict with a short quote and the page it came from.

Two ways to run it (config/ai_check.json):
- `model` "claude-*": the Anthropic API with its own web search and fetch.
- `model` "deepseek-*" (no web search): code fetches the job's own links and,
  for a Greenhouse/Lever/Ashby posting, its public API; DeepSeek reads them and
  the description. Jobs it cannot settle go to `web_model` "claude-code": the
  Claude Code CLI with WebSearch/WebFetch, on your Claude login, no API bill.
  Code then fetches the page it names itself, because what Claude Code read
  never reaches us.

The quote is then checked in code: it must appear word for word in the job
description or in text the API returned from a page Claude opened (or, for
DeepSeek and Claude Code, a page code fetched). Only a
verified quote changes a job's status (see classify.apply_ai_check):
`cannot_hire` rejects it, `can_hire` shortlists it as `likely`. Anything else
leaves it in needs_review with the finding attached.

Results are stored in jobs.ai_check_json, so `reclassify` keeps them, and a
job is checked once unless asked again (`jobhunter check --recheck`).
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, fields, replace
from datetime import datetime
from pathlib import Path

from .classify import classify
from .config import Filters
from .eligibility import assess_eligibility
from .llm import CLAUDE_CODE, JsonModel, Usage, error_line, find_quote, forced_tool_choice, json_model, pages_read, plain
from .models import CAN_HIRE, CANNOT_HIRE, UNKNOWN_HIRE, AiCheck, Classification, Job
from .store import JobStore, row_to_job
from .text import html_to_text, iso

log = logging.getLogger(__name__)

JOB_DESCRIPTION = "job description"
MAX_REQUESTS = 6  # per job: pause_turn continuations, plus one nudge to record the verdict
DESCRIPTION_CHARS = 8000


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
    # With a deepseek-* model: the second step for jobs it could not settle ("claude-code", "claude-code:sonnet";
    # empty: none).
    web_model: str = ""
    web_timeout: int = 420
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
        self.label = config.model

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
        usage = Usage()
        tool_choice = {"type": "auto"}
        answer = None
        for _ in range(MAX_REQUESTS):
            response = self.client.messages.create(
                model=self.config.model, max_tokens=4096, system=SYSTEM, tools=self._tools(),
                tool_choice=tool_choice, messages=messages,
            )
            usage.add(response.usage)
            blocks = [plain(b) for b in response.content]
            pages += list(pages_read(blocks))
            answer = next((b.get("input") for b in blocks
                           if b.get("type") == "tool_use" and b.get("name") == "record_verdict"), None)
            if answer is not None:
                break
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason != "pause_turn":  # pause_turn: send it back as-is and the search goes on
                messages.append({"role": "user", "content": "Call record_verdict now with what you found."})
                tool_choice = forced_tool_choice(self.config.model, "record_verdict")
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


# --- DeepSeek over pages code fetched, then Claude Code with web search ------------------

ANSWER_SCHEMA = {k: v for k, v in RECORD_VERDICT["input_schema"].items()}
ANSWER_EXAMPLE = ('{"verdict": "cannot_hire", "reason": "The Greenhouse posting lists Remote - United States only.", '
                  '"quote": "Location: Remote - United States", "source_url": "https://boards.greenhouse.io/acme/jobs/42"}')
PAGE_CHARS = 12000
# Job boards that block scripts (Himalayas answers 403) or need a login: no point fetching them.
_NO_FETCH_HOSTS = ("himalayas.app", "linkedin.com", "indeed.com", "glassdoor.", "news.ycombinator.com")
_URL_RE = re.compile(r"""https?://[^\s"'<>)\]]+""")
_GREENHOUSE = re.compile(r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)", re.I)
_LEVER = re.compile(r"jobs\.(eu\.)?lever\.co/([^/?#]+)/([0-9a-f]{8}-[0-9a-f-]{27})", re.I)
_ASHBY = re.compile(r"jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f]{8}-[0-9a-f-]{27})", re.I)

PAGES_SYSTEM = SYSTEM.split("Research the web")[0] + """\
You cannot browse. Below are the job description and the pages code fetched \
for this job (its own links and, when there is one, the company's posting on \
its job board). Decide from them only.

Verdicts:""" + SYSTEM.split("Verdicts:")[1].split("Evidence:")[0] + """\
Evidence:
- quote: copied character for character from one page below or the job \
description. A short phrase or one sentence, under 300 characters. Do not \
paraphrase, shorten with "...", or join separate parts.
- source_url: the page's URL as given below, or "job description".
- For unknown, quote and source_url may be empty.
- reason: one plain sentence.
"""

WEB_SYSTEM = SYSTEM.replace("Research the web, then call record_verdict once.",
                            "Research the web with WebSearch and WebFetch, then answer with the JSON verdict.") \
    .replace("open it with web_fetch, so the quote can be checked against the page text.",
             "open it with WebFetch. Code fetches that URL again and looks for the quote there, so quote the page's "
             "own words, never a summary of it.")


def _host(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url).split("/")[0].lower()


def posting_api_text(url: str, http) -> str | None:
    """A Greenhouse, Lever or Ashby posting read through the board's public API: title, location and text.

    Their pages are often built by JavaScript, so a plain fetch of the page has no location line."""
    if m := _GREENHOUSE.search(url):
        raw = http.get_json(f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}")
        location = (raw.get("location") or {}).get("name") or ""
        return f"{raw.get('title') or ''}\nLocation: {location}\n\n{html_to_text(html.unescape(raw.get('content') or ''))}"
    if m := _LEVER.search(url):
        api = "api.eu.lever.co" if m.group(1) else "api.lever.co"
        raw = http.get_json(f"https://{api}/v0/postings/{m.group(2)}/{m.group(3)}")
        cats = raw.get("categories") or {}
        places = ", ".join(cats.get("allLocations") or [cats.get("location") or ""])
        return (f"{raw.get('text') or ''}\nLocation: {places}\nWorkplace: {raw.get('workplaceType') or ''}\n\n"
                f"{raw.get('descriptionPlain') or ''}\n{raw.get('additionalPlain') or ''}")
    if m := _ASHBY.search(url):
        board = http.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{m.group(1)}")
        raw = next((j for j in board.get("jobs") or [] if str(j.get("id", "")).lower() == m.group(2).lower()), None)
        if raw is None:
            return None
        places = [raw.get("location") or ""] + [s.get("location") or "" for s in raw.get("secondaryLocations") or []]
        return (f"{raw.get('title') or ''}\nLocation: {', '.join(p for p in places if p)}\n"
                f"Workplace: {raw.get('workplaceType') or ''}\n\n{raw.get('descriptionPlain') or ''}")
    return None


def fetch_page(url: str, http) -> tuple[str, str] | None:
    """(readable text, everything the page returned) as code sees it, or None when it cannot be read.

    An ATS posting is read through its board's API. The second part is only for finding a quote: a page
    often keeps text in embedded data (Recruitee's application questions) that the readable text leaves out."""
    try:
        text = posting_api_text(url, http)
        raw = text
        if text is None:
            raw = http.get_text(url)
            text = html_to_text(raw)
    except Exception as exc:
        log.info("ai_check: could not read %s: %s", url, error_line(exc))
        return None
    if not text.strip():
        return None
    return text.strip(), html.unescape(raw)


def _for_quotes(url: str, page: tuple[str, str]) -> list[tuple[str, str]]:
    text, raw = page
    return [(url, text)] + ([(url, raw)] if raw != text else [])


def job_links(job: Job, limit: int) -> list[str]:
    """The job's own links, then links in its description: a posting first, job boards that block scripts never."""
    found = [job.application_url, job.source_url,
             *(u.rstrip(".,;") for u in _URL_RE.findall(job.description or ""))]
    links = [u for u in dict.fromkeys(u for u in found if u) if not any(h in _host(u) for h in _NO_FETCH_HOSTS)]
    links.sort(key=lambda u: not (_GREENHOUSE.search(u) or _LEVER.search(u) or _ASHBY.search(u)))
    return links[:limit]


def _pages_message(job: Job, rule_reason: str, pages: list[tuple[str, str]]) -> str:
    parts = [_job_message(job, rule_reason)]
    for url, text in pages:
        parts += ["", f"--- Page: {url} ---", text[:PAGE_CHARS]]
    return "\n".join(parts)


def _result(answer: dict, pages: list[tuple[str, str]], model: str, now: datetime, usage: Usage,
            searches: int = 0) -> AiCheck:
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
        model=model,
        checked_at=iso(now),
        searches=searches,
        cost_usd=usage.cost(model),
    )


class PagesChecker:
    """DeepSeek (or any JSON model) reading the description and the pages code fetched for the job."""

    def __init__(self, config: AiCheckConfig, model: JsonModel, http):
        self.config = config
        self.model = model
        self.http = http
        self.label = config.model

    def check(self, job: Job, now: datetime) -> AiCheck:
        rule_reason = (assess_eligibility(job).reasons or [""])[0]
        fetched = {url: page for url in job_links(job, self.config.max_fetches_per_job)
                   if (page := fetch_page(url, self.http))}
        usage = Usage()
        message = _pages_message(job, rule_reason, [(url, text) for url, (text, _) in fetched.items()])
        answer = self.model.ask(PAGES_SYSTEM, [{"role": "user", "content": message}], ANSWER_SCHEMA, usage,
                                ANSWER_EXAMPLE, max_tokens=1024)
        pages = [(JOB_DESCRIPTION, job.description or "")]
        for url, page in fetched.items():
            pages += _for_quotes(url, page)
        return _result(answer, pages, self.config.model, now, usage)


class WebChecker:
    """The Claude Code CLI with WebSearch and WebFetch. What it read never reaches us, so code fetches the page it
    names and looks for the quote there (or in the description)."""

    def __init__(self, config: AiCheckConfig, model: JsonModel, http):
        self.config = config
        self.model = model
        self.http = http
        self.label = config.web_model

    def check(self, job: Job, now: datetime) -> AiCheck:
        rule_reason = (assess_eligibility(job).reasons or [""])[0]
        usage = Usage()
        prompt = (_job_message(job, rule_reason) + f"\n\nUse at most {self.config.max_searches_per_job} searches "
                  f"and {self.config.max_fetches_per_job} page fetches.")
        answer = self.model.ask(WEB_SYSTEM, [{"role": "user", "content": prompt}], ANSWER_SCHEMA, usage, ANSWER_EXAMPLE)
        if not answer.get("verdict"):
            raise RuntimeError("Claude Code gave no verdict")
        stated_url = str(answer.get("source_url") or "").strip()
        pages = [(JOB_DESCRIPTION, job.description or "")]
        if stated_url.startswith("http") and (page := fetch_page(stated_url, self.http)):
            pages += _for_quotes(stated_url, page)
        return _result(answer, pages, self.config.web_model, now, usage)


class TwoStepChecker:
    """The cheap check first; the web check only for a job it could not settle with a quote found on a page."""

    def __init__(self, first: PagesChecker, second: WebChecker):
        self.first = first
        self.second = second
        self.config = first.config
        self.label = f"{first.label}, then {second.label}"

    def check(self, job: Job, now: datetime) -> AiCheck:
        first = self.first.check(job, now)
        if first.verified:
            return first
        return self.second.check(job, now)  # verified or not, it looked further


def build_checker(config_file: Path, require_enabled: bool = True):
    """The checker, or None and (when it matters) a note saying why it is off."""
    config = AiCheckConfig.load(config_file)
    if require_enabled and not config.enabled:
        return None, None
    if config.model.startswith(("deepseek", CLAUDE_CODE)):
        from .http import Http

        http = Http(timeout=20, retries=1)
        first, note = json_model(config.model, "ai_check")
        if first is None:
            return None, f"ai_check skipped: {note}"
        if config.model.startswith(CLAUDE_CODE):  # Claude Code alone: the web step for every job
            first.tools, first.timeout = "WebSearch,WebFetch", config.web_timeout
            return WebChecker(replace(config, web_model=config.model), first, http), None
        checker = PagesChecker(config, first, http)
        if not config.web_model:
            return checker, None
        web, note = json_model(config.web_model, "ai_check web step")
        if web is None:
            return checker, f"ai_check: no web step ({note}); DeepSeek only"
        web.tools, web.timeout = "WebSearch,WebFetch", config.web_timeout
        return TwoStepChecker(checker, WebChecker(config, web, http)), None
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


def _fatal(exc: Exception) -> bool:
    """Errors every other job would hit too: bad key, no credit, unknown model or tool."""
    return getattr(exc, "status_code", None) in (400, 401, 403, 404)


def check_jobs(store: JobStore, checker: AiChecker, rows, filters: Filters, now: datetime,
               on_result=None) -> CheckRun:
    """Check `rows`, save each result as it arrives and re-classify that job.

    on_result(row, check, classification) is called for each finished job.
    """
    run = CheckRun(model=checker.label)
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
                run.errors.append(f"#{row['id']} {row['company']}: {error_line(exc)}")
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
