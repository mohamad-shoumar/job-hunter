"""Remote OK public API: remoteok.com/api

Terms: link back to the Remote OK URL and name Remote OK as the source. The
API returns its latest ~100 jobs and ignores search parameters, so `queries`
here is a LOCAL pre-filter on each job's title and tags.
"""

from __future__ import annotations

from ..identity import find_ats_url
from ..models import REMOTE, Job
from ..text import fix_mojibake, has_phrase, html_to_text, normalize_words, parse_datetime
from .base import Source, SourceResult, describe_error, section_enabled

API = "https://remoteok.com/api"


class RemoteOkSource(Source):
    name = "remoteok"

    def __init__(self, limit: int = 250, queries: list[str] | None = None):
        self.limit = limit
        self.queries = [normalize_words(q) for q in queries or [] if normalize_words(q)]

    def fetch(self, http) -> SourceResult:
        result = SourceResult(self.name)
        try:
            data = http.get_json(API)
        except Exception as exc:
            result.errors.append(describe_error(exc))
            return result
        listings = [x for x in data if isinstance(x, dict) and x.get("id")]  # item 0 is the legal notice
        if self.queries:
            listings = [x for x in listings if self._wanted(x)]
        result.jobs.extend(parse_job(raw) for raw in listings[: self.limit])
        return result

    def _wanted(self, raw: dict) -> bool:
        haystack = normalize_words(" ".join([raw.get("position") or "", " ".join(raw.get("tags") or [])]))
        return any(has_phrase(haystack, q) for q in self.queries)


def _positive(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def parse_job(raw: dict) -> Job:
    # Remote OK serves some text double-encoded; fix it before anything reads it.
    location = fix_mojibake(raw.get("location")).strip()
    low, high = _positive(raw.get("salary_min")), _positive(raw.get("salary_max"))
    return Job(
        source="remoteok",
        source_job_id=str(raw["id"]),
        source_url=raw.get("url") or "",
        company=fix_mojibake(raw.get("company")),
        title=fix_mojibake(raw.get("position")),
        description=html_to_text(fix_mojibake(raw.get("description"))),
        application_url=find_ats_url(raw.get("description")) or raw.get("apply_url") or raw.get("url"),
        location_raw=location or None,
        allowed_locations=[location] if location else [],
        remote_status=REMOTE,
        salary_min=low,
        salary_max=high,
        salary_currency="USD" if low or high else None,
        salary_period="year" if low or high else None,
        tags=[str(t) for t in raw.get("tags") or []],
        posted_at=parse_datetime(raw.get("date") or raw.get("epoch")),
    )


def from_config(section) -> RemoteOkSource | None:
    if not section_enabled(section):
        return None
    return RemoteOkSource(int(section.get("limit", 250)), section.get("queries"))
