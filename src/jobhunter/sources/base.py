"""What every source adapter looks like.

An adapter turns one job site into Job objects. It fills only what the site
states; extract.enrich() and the classifiers do the rest. One broken board,
query or posting must not stop the others: adapters record the error and move on
(parse_each for postings, BoardSource for one board per company).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from ..models import Job

log = logging.getLogger(__name__)


@dataclass
class SourceResult:
    source: str
    jobs: list[Job] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class Source:
    name: str = ""
    # Set by a date-range run to the start of the range. Sources that page
    # newest-first (Himalayas) or split by month (HN) use it to reach back far
    # enough; the rest return everything they have anyway.
    since: datetime | None = None
    # Fetched again after a connection error (pipeline.fetch_all). False for a source that pays
    # per request, where a second try would spend its credits again.
    refetch: bool = True

    def fetch(self, http) -> SourceResult:  # pragma: no cover - interface
        raise NotImplementedError


class BoardError(Exception):
    """The board answered with an error of its own ({"ok": false, "error": "Document not found"}), shown as is."""


class BoardSource(Source):
    """One careers board per company (Greenhouse, Lever, ...). Each board is fetched alone and each of its
    postings parsed alone, so a broken board or posting costs only itself."""

    def __init__(self, boards: list[dict]):
        self.boards = boards

    def fetch(self, http) -> SourceResult:
        result = SourceResult(self.name)
        for board in self.boards:
            label = self.label(board)
            try:
                postings = self.postings(http, board)
            except BoardError as exc:
                result.errors.append(f"{label}: {exc}")
                continue
            except Exception as exc:
                result.errors.append(f"{label}: {describe_error(exc)}")
                continue
            if not postings:
                result.notes.append(f"{board['company']}: board has no open jobs")
            result.jobs += parse_each(postings, lambda raw, board=board: self.parse(raw, board), result.errors, label)
        return result

    def label(self, board: dict) -> str:
        """How an error line names the board: "Acme (acme)"."""
        return f"{board['company']} ({board['board_token']})"

    def postings(self, http, board: dict) -> list[dict]:  # pragma: no cover - interface
        """The board's raw postings. An error here is one line for the whole board."""
        raise NotImplementedError

    def parse(self, raw: dict, board: dict) -> Job:  # pragma: no cover - interface
        """One posting as a Job. An error here is one line for this posting only."""
        raise NotImplementedError


def parse_each(items, parse, errors: list[str], where: str = "", key: str = "id") -> list:
    """`parse` on each item alone, in order: a bad item becomes one error line ("Acme (acme) job 42: KeyError:
    'title'", by its `key`, else "item 3" by its place) and the rest are kept."""
    parsed = []
    for number, item in enumerate(items, 1):
        try:
            parsed.append(parse(item))
        except Exception as exc:  # one malformed posting must not cost the others
            ident = item.get(key) if isinstance(item, dict) else None
            name = f"{where} job {ident}" if ident else f"{where} item {number}"
            log.exception("%s could not be read", name.strip())
            errors.append(f"{name.strip()}: {describe_error(exc)}")
    return parsed


def pay_period(interval: str | None) -> str | None:
    """A pay interval ("per-year-salary", "1 MONTH") as "year", "month" or "hour"; None when it names none."""
    v = (interval or "").lower()
    for period in ("year", "month", "hour"):
        if period in v:
            return period
    return None


def describe_error(exc: Exception) -> str:
    """A short error line with no query string, so API keys never reach logs or reports."""
    if isinstance(exc, httpx.HTTPStatusError):
        url = exc.request.url.copy_with(query=None)
        return f"HTTP {exc.response.status_code} from {url}"
    if isinstance(exc, httpx.RequestError):
        url = exc.request.url.copy_with(query=None) if exc.request else ""
        return f"{type(exc).__name__} for {url}"
    return f"{type(exc).__name__}: {exc}"


def enabled_entries(entries) -> list[dict]:
    return [e for e in entries or [] if isinstance(e, dict) and e.get("enabled", True)]


def section_enabled(section) -> bool:
    return isinstance(section, dict) and bool(section.get("enabled", True))
