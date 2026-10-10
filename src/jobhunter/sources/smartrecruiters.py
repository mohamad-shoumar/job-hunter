"""SmartRecruiters company boards: public Posting API, no key.

api.smartrecruiters.com/v1/companies/<id>/postings lists jobs with a date and
a place; each posting's own URL adds the description (one request per job,
skipped for postings already too old to keep). `country` limits a big
company to one country: Delivery Hero with "ae" is talabat and InstaShop in
the UAE. Company ids are case-sensitive.
"""

from __future__ import annotations

from datetime import timedelta

from ..models import HYBRID, ONSITE, REMOTE, Job
from ..text import html_to_text, parse_datetime, utcnow
from .base import Source, SourceResult, describe_error, enabled_entries

API = "https://api.smartrecruiters.com/v1/companies/{id}/postings"
PAGE = 100
# Older postings are rejected as too old anyway, so their descriptions are not fetched.
DETAIL_MAX_AGE_DAYS = 45


class SmartRecruitersSource(Source):
    name = "smartrecruiters"

    def __init__(self, boards: list[dict]):
        self.boards = boards

    def fetch(self, http) -> SourceResult:
        result = SourceResult(self.name)
        cutoff = utcnow() - timedelta(days=DETAIL_MAX_AGE_DAYS)
        for board in self.boards:
            company_id = board["board_token"]
            countries = board.get("countries") or [None]
            for country in countries:
                label = f"{board['company']} ({company_id}{', ' + country if country else ''})"
                try:
                    postings = self._list(http, company_id, country)
                except Exception as exc:
                    result.errors.append(f"{label}: {describe_error(exc)}")
                    continue
                if not postings:
                    result.notes.append(f"{label}: board has no open jobs")
                for raw in postings:
                    detail = {}
                    posted = parse_datetime(raw.get("releasedDate"))
                    if not posted or posted >= cutoff:
                        try:
                            detail = http.get_json(f"{API.format(id=company_id)}/{raw['id']}")
                        except Exception as exc:
                            result.errors.append(f"{label} job {raw['id']}: {describe_error(exc)}")
                    result.jobs.append(parse_job(raw, detail, board))
        return result

    def _list(self, http, company_id: str, country: str | None) -> list[dict]:
        postings: list[dict] = []
        while True:
            params = {"limit": PAGE, "offset": len(postings), **({"country": country} if country else {})}
            data = http.get_json(API.format(id=company_id), params=params)
            page = data.get("content") or []
            postings.extend(page)
            if len(page) < PAGE or len(postings) >= (data.get("totalFound") or 0):
                return postings


def parse_job(raw: dict, detail: dict, board: dict) -> Job:
    location = raw.get("location") or {}
    place = location.get("fullLocation") or ", ".join(
        v for v in (location.get("city"), location.get("country")) if v)
    status = REMOTE if location.get("remote") else HYBRID if location.get("hybrid") else ONSITE
    sections = (detail.get("jobAd") or {}).get("sections") or {}
    description = "\n\n".join(
        html_to_text(s.get("text")) for s in sections.values() if isinstance(s, dict) and s.get("text"))
    url = detail.get("postingUrl") or (
        f"https://jobs.smartrecruiters.com/{(raw.get('company') or {}).get('identifier') or board['board_token']}/{raw['id']}")
    return Job(
        source="smartrecruiters",
        source_job_id=str(raw["id"]),
        source_url=url,
        company=board.get("company") or (raw.get("company") or {}).get("name") or "",
        title=(raw.get("name") or "").strip(),
        description=description,
        application_url=url,
        company_location=board.get("company_location"),
        location_raw=place or None,
        allowed_locations=[place] if place else [],
        remote_status=status,
        employment_type=((raw.get("typeOfEmployment") or {}).get("label")),
        posted_at=parse_datetime(raw.get("releasedDate")),
    )


def from_config(section) -> SmartRecruitersSource | None:
    boards = enabled_entries(section)
    return SmartRecruitersSource(boards) if boards else None
