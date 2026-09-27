"""Remotive public API: github.com/remotive-com/remote-jobs-api

Terms: link back to the Remotive URL and name Remotive as the source (the
report does both). The API ignores search parameters and returns its latest
jobs, so there is nothing to query - the local filters decide.
"""

from __future__ import annotations

from ..identity import find_ats_url
from ..models import REMOTE, Job
from ..text import html_to_text, parse_datetime
from .base import Source, SourceResult, describe_error, section_enabled

API = "https://remotive.com/api/remote-jobs"


class RemotiveSource(Source):
    name = "remotive"

    def __init__(self, limit: int = 100, category: str | None = None):
        self.limit = limit
        self.category = category

    def fetch(self, http) -> SourceResult:
        result = SourceResult(self.name)
        params = {"limit": self.limit}
        if self.category:
            params["category"] = self.category
        try:
            data = http.get_json(API, params=params)
        except Exception as exc:
            result.errors.append(describe_error(exc))
            return result
        result.jobs.extend(parse_job(raw) for raw in (data.get("jobs") or [])[: self.limit])
        return result


def parse_job(raw: dict) -> Job:
    location = (raw.get("candidate_required_location") or "").strip()
    return Job(
        source="remotive",
        source_job_id=str(raw["id"]),
        source_url=raw.get("url") or "",
        company=raw.get("company_name") or "",
        title=raw.get("title") or "",
        description=html_to_text(raw.get("description")),
        application_url=find_ats_url(raw.get("description")) or raw.get("url"),
        location_raw=location or None,
        allowed_locations=[part.strip() for part in location.split(",") if part.strip()],
        remote_status=REMOTE,
        employment_type=raw.get("job_type"),
        salary_raw=raw.get("salary") or None,
        tags=[str(t) for t in raw.get("tags") or []] + [raw.get("category") or ""],
        posted_at=parse_datetime(raw.get("publication_date")),
    )


def from_config(section) -> RemotiveSource | None:
    if not section_enabled(section) or section.get("provider", "remotive") != "remotive":
        return None
    return RemotiveSource(int(section.get("limit", 100)), section.get("category"))
