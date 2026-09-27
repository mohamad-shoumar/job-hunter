"""Lever job boards. Public API, no key: github.com/lever/postings-api"""

from __future__ import annotations

from ..extract import normalize_workplace, remote_status_from_location
from ..models import UNKNOWN, Job
from ..text import clean_text, html_to_text, parse_datetime
from .base import Source, SourceResult, describe_error, enabled_entries

API = "https://api.lever.co/v0/postings/{token}"


class LeverSource(Source):
    name = "lever"

    def __init__(self, boards: list[dict]):
        self.boards = boards

    def fetch(self, http) -> SourceResult:
        result = SourceResult(self.name)
        for board in self.boards:
            try:
                data = http.get_json(API.format(token=board["board_token"]), params={"mode": "json"})
            except Exception as exc:
                result.errors.append(f"{board['company']} ({board['board_token']}): {describe_error(exc)}")
                continue
            if not isinstance(data, list):  # {"ok": false, "error": "Document not found"}
                result.errors.append(f"{board['company']} ({board['board_token']}): {data.get('error', 'unexpected response')}")
                continue
            if not data:
                result.notes.append(f"{board['company']}: board has no open jobs")
            result.jobs.extend(parse_job(raw, board) for raw in data)
        return result


def _period(interval: str | None) -> str | None:
    v = (interval or "").lower()
    for period in ("year", "month", "hour"):
        if period in v:
            return period
    return None


def parse_job(raw: dict, board: dict) -> Job:
    categories = raw.get("categories") or {}
    locations = [loc for loc in (categories.get("allLocations") or [categories.get("location")]) if loc]
    title = (raw.get("text") or "").strip()
    remote_status = normalize_workplace(raw.get("workplaceType"))
    if remote_status == UNKNOWN:
        remote_status = remote_status_from_location(", ".join(locations), title)
    parts = [raw.get("descriptionPlain") or html_to_text(raw.get("description"))]
    for block in raw.get("lists") or []:  # requirements / responsibilities sections
        parts += [block.get("text") or "", html_to_text(block.get("content"))]
    parts.append(raw.get("additionalPlain") or html_to_text(raw.get("additional")))
    salary = raw.get("salaryRange") or {}
    return Job(
        source="lever",
        source_job_id=raw["id"],
        source_url=raw.get("hostedUrl") or "",
        company=board["company"],
        title=title,
        description=clean_text("\n\n".join(p for p in parts if p)),
        application_url=raw.get("hostedUrl") or raw.get("applyUrl"),
        company_location=board.get("company_location"),
        location_raw=" / ".join(locations) or None,
        allowed_locations=locations,
        remote_status=remote_status,
        employment_type=categories.get("commitment"),
        salary_min=salary.get("min"),
        salary_max=salary.get("max"),
        salary_currency=salary.get("currency"),
        salary_period=_period(salary.get("interval")),
        posted_at=parse_datetime(raw.get("createdAt")),
    )


def from_config(section) -> LeverSource | None:
    boards = enabled_entries(section)
    return LeverSource(boards) if boards else None
