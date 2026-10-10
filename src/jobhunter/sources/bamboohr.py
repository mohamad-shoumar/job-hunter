"""BambooHR careers pages: <slug>.bamboohr.com/careers/list, public JSON, no key.

The list has titles and places only; each job's own page
(/careers/<id>/detail) adds the description and the posting date, so one
request per job. Toters (Lebanon) hires through it.
"""

from __future__ import annotations

from ..models import HYBRID, ONSITE, REMOTE, UNKNOWN, Job
from ..text import html_to_text, parse_datetime
from .base import Source, SourceResult, describe_error, enabled_entries

LIST = "https://{token}.bamboohr.com/careers/list"
DETAIL = "https://{token}.bamboohr.com/careers/{id}/detail"
# BambooHR's locationType, read from its careers page, not documented: 0 in an office, 1 remote, 2 hybrid.
# Toters' are 0 and 2; Lebanon listed decides those either way.
_LOCATION_TYPE = {"0": ONSITE, "1": REMOTE, "2": HYBRID}


class BambooHRSource(Source):
    name = "bamboohr"

    def __init__(self, boards: list[dict]):
        self.boards = boards

    def fetch(self, http) -> SourceResult:
        result = SourceResult(self.name)
        for board in self.boards:
            token = board["board_token"]
            try:
                listed = http.get_json(LIST.format(token=token)).get("result") or []
            except Exception as exc:
                result.errors.append(f"{board['company']} ({token}): {describe_error(exc)}")
                continue
            if not listed:
                result.notes.append(f"{board['company']}: board has no open jobs")
            for row in listed:
                try:
                    detail = http.get_json(DETAIL.format(token=token, id=row["id"])).get("result") or {}
                except Exception as exc:
                    result.errors.append(f"{board['company']} job {row['id']}: {describe_error(exc)}")
                    detail = {}
                result.jobs.append(parse_job(row, (detail.get("jobOpening") or {}), board))
        return result


def _place(location: dict | None) -> str:
    location = location or {}
    parts = [location.get("city"), location.get("addressCountry") or location.get("country")]
    if not parts[1] and location.get("state") != location.get("city"):
        parts.insert(1, location.get("state"))
    return ", ".join(p.strip() for p in parts if p and p.strip())


def parse_job(row: dict, detail: dict, board: dict) -> Job:
    token = board["board_token"]
    place = _place(detail.get("location") or row.get("location"))
    url = detail.get("jobOpeningShareUrl") or f"https://{token}.bamboohr.com/careers/{row['id']}"
    status = REMOTE if row.get("isRemote") else _LOCATION_TYPE.get(str(row.get("locationType")), UNKNOWN)
    return Job(
        source="bamboohr",
        source_job_id=f"{token}:{row['id']}",
        source_url=url,
        company=board["company"],
        title=(row.get("jobOpeningName") or "").strip(),
        description=html_to_text(detail.get("description")),
        application_url=url,
        company_location=board.get("company_location"),
        location_raw=place or None,
        allowed_locations=[place] if place else [],
        remote_status=status,
        employment_type=row.get("employmentStatusLabel"),
        posted_at=parse_datetime(detail.get("datePosted")),
    )


def from_config(section) -> BambooHRSource | None:
    boards = enabled_entries(section)
    return BambooHRSource(boards) if boards else None
