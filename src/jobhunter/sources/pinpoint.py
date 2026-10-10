"""Pinpoint careers sites: <slug>.pinpointhq.com/postings.json, public, no key.

One request gives every job with its full description. It states no posting
date, so these jobs go to needs_review ("age unknown") rather than the
shortlist. Tabby hires through it.
"""

from __future__ import annotations

from ..extract import normalize_workplace
from ..models import Job
from ..text import html_to_text
from .base import Source, SourceResult, describe_error, enabled_entries

API = "https://{token}.pinpointhq.com/postings.json"
_SECTIONS = ("description", "key_responsibilities", "skills_knowledge_expertise", "benefits")


class PinpointSource(Source):
    name = "pinpoint"

    def __init__(self, boards: list[dict]):
        self.boards = boards

    def fetch(self, http) -> SourceResult:
        result = SourceResult(self.name)
        for board in self.boards:
            try:
                postings = http.get_json(API.format(token=board["board_token"])).get("data") or []
            except Exception as exc:
                result.errors.append(f"{board['company']} ({board['board_token']}): {describe_error(exc)}")
                continue
            if not postings:
                result.notes.append(f"{board['company']}: board has no open jobs")
            result.jobs.extend(parse_job(raw, board) for raw in postings)
        return result


def _money(value) -> float | None:
    try:
        return float(value) if value not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None


def parse_job(raw: dict, board: dict) -> Job:
    location = raw.get("location") or {}
    # Pinpoint's "name" is the country ("UAE", "Egypt") or the word "Remote", which is not a place.
    parts = (location.get("city"), location.get("name"))
    place = ", ".join(v.strip() for v in parts if v and v.strip() and v.strip().lower() != "remote")
    visible = str(raw.get("compensation_visible")).lower() == "true"
    low, high = (_money(raw.get("compensation_minimum")), _money(raw.get("compensation_maximum"))) if visible else (None, None)
    frequency = (raw.get("compensation_frequency") or "").lower()
    return Job(
        source="pinpoint",
        source_job_id=str(raw["id"]),
        source_url=raw.get("url") or "",
        company=board["company"],
        title=(raw.get("title") or "").strip(),
        description="\n\n".join(html_to_text(raw.get(k)) for k in _SECTIONS if raw.get(k)),
        application_url=raw.get("url"),
        company_location=board.get("company_location"),
        location_raw=place or None,
        allowed_locations=[place] if place else [],
        remote_status=normalize_workplace(raw.get("workplace_type")),
        employment_type=raw.get("employment_type"),
        salary_min=low,
        salary_max=high,
        salary_currency=raw.get("compensation_currency") if low or high else None,
        salary_period=next((p for p in ("year", "month", "hour") if p in frequency), None) if low or high else None,
    )


def from_config(section) -> PinpointSource | None:
    boards = enabled_entries(section)
    return PinpointSource(boards) if boards else None
