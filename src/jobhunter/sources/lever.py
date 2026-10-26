"""Lever job boards. Public API, no key: github.com/lever/postings-api"""

from __future__ import annotations

from ..extract import normalize_workplace, remote_status_from_location
from ..models import UNKNOWN, Job
from ..text import clean_text, html_to_text, parse_datetime
from .base import BoardError, BoardSource, enabled_entries, pay_period

API = "https://api.lever.co/v0/postings/{token}"


class LeverSource(BoardSource):
    name = "lever"

    def postings(self, http, board: dict) -> list[dict]:
        data = http.get_json(API.format(token=board["board_token"]), params={"mode": "json"})
        if not isinstance(data, list):  # {"ok": false, "error": "Document not found"}
            raise BoardError(data.get("error", "unexpected response"))
        return data

    def parse(self, raw: dict, board: dict) -> Job:
        return parse_job(raw, board)


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
        salary_period=pay_period(salary.get("interval")),
        posted_at=parse_datetime(raw.get("createdAt")),
    )


def from_config(section) -> LeverSource | None:
    boards = enabled_entries(section)
    return LeverSource(boards) if boards else None
