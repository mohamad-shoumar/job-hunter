"""What every source adapter looks like.

An adapter turns one job site into Job objects. It fills only what the site
states; extract.enrich() and the classifiers do the rest. One broken board or
query must not stop the others: adapters record the error and move on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import httpx

from ..models import Job


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

    def fetch(self, http) -> SourceResult:  # pragma: no cover - interface
        raise NotImplementedError


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
