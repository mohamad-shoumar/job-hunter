"""Greenhouse job boards. Public API, no key: developers.greenhouse.io/job-board.html"""

from __future__ import annotations

import html

from ..extract import remote_status_from_location
from ..models import Job
from ..text import html_to_text, parse_datetime
from .base import Source, SourceResult, describe_error, enabled_entries

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


class GreenhouseSource(Source):
    name = "greenhouse"

    def __init__(self, boards: list[dict]):
        self.boards = boards

    def fetch(self, http) -> SourceResult:
        result = SourceResult(self.name)
        for board in self.boards:
            try:
                data = http.get_json(API.format(token=board["board_token"]), params={"content": "true"})
            except Exception as exc:
                result.errors.append(f"{board['company']} ({board['board_token']}): {describe_error(exc)}")
                continue
            jobs = data.get("jobs") or []
            if not jobs:
                result.notes.append(f"{board['company']}: board has no open jobs")
            result.jobs.extend(parse_job(raw, board) for raw in jobs)
        return result


def parse_job(raw: dict, board: dict) -> Job:
    location = ((raw.get("location") or {}).get("name") or "").strip()
    title = (raw.get("title") or "").strip()
    url = raw.get("absolute_url") or ""
    # Greenhouse returns the description HTML entity-escaped.
    content = html.unescape(raw.get("content") or "")
    return Job(
        source="greenhouse",
        source_job_id=str(raw["id"]),
        source_url=url,
        company=board.get("company") or raw.get("company_name") or board["board_token"],
        title=title,
        description=html_to_text(content),
        application_url=url,
        company_location=board.get("company_location"),
        location_raw=location or None,
        allowed_locations=[location] if location else [],
        remote_status=remote_status_from_location(location, title),
        posted_at=parse_datetime(raw.get("first_published") or raw.get("updated_at")),
    )


def from_config(section) -> GreenhouseSource | None:
    boards = enabled_entries(section)
    return GreenhouseSource(boards) if boards else None
