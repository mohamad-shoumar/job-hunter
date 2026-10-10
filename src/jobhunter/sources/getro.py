"""Investor (VC) job boards on Getro: the open jobs at the companies a fund invested in.

No agencies by design, and each job links to the company's own careers page,
so a shortlisted one lets boards.py start watching that company's board.

The search API is public and needs `Accept: application/json` (406 without
it). It returns no description; the job pages that have one answer 403. So a
Getro job carries its title, locations, work mode and skills only, and the
rules and the AI check work from those and the company's own posting.

Each board has its own filters: remote for the big funds, the countries you
would move to for the Gulf ones (Hub71, MEVP, BECO). Find a board's
collection id in its page source: "network":{"id":...}.
"""

from __future__ import annotations

from ..models import HYBRID, ONSITE, REMOTE, UNKNOWN, Job
from ..text import parse_datetime
from .base import Source, SourceResult, describe_error, enabled_entries

API = "https://api.getro.com/api/v2/collections/{id}/search/jobs"
HEADERS = {"Accept": "application/json"}
PAGE_SIZE = 100
_WORK_MODE = {"remote": REMOTE, "hybrid": HYBRID, "on_site": ONSITE}
_PERIOD = {"year": "year", "month": "month", "hour": "hour"}


class GetroSource(Source):
    name = "getro"

    def __init__(self, boards: list[dict], queries: list[str], max_pages: int = 2):
        self.boards = boards
        self.queries = queries
        self.max_pages = max_pages

    def fetch(self, http) -> SourceResult:
        result = SourceResult(self.name)
        for board in self.boards:
            seen: set[str] = set()
            for query in board.get("queries") or self.queries:
                try:
                    for page in range(self.max_pages):
                        body = {"hits_per_page": PAGE_SIZE, "page": page, "query": query,
                                "filters": board.get("filters") or {}}
                        data = http.post_json(API.format(id=board["collection_id"]), body, HEADERS)
                        jobs = (data.get("results") or {}).get("jobs") or []
                        for raw in jobs:
                            if str(raw.get("id")) not in seen:
                                seen.add(str(raw.get("id")))
                                result.jobs.append(parse_job(raw))
                        if len(jobs) < PAGE_SIZE:
                            break
                except Exception as exc:
                    result.errors.append(f"{board['name']} ({board['collection_id']}) {query!r}: {describe_error(exc)}")
            if not seen:
                result.notes.append(f"{board['name']}: no jobs matched")
        return result


def _money(cents) -> float | None:
    return cents / 100 if isinstance(cents, (int, float)) and cents > 0 else None


def parse_job(raw: dict) -> Job:
    org = raw.get("organization") or {}
    locations = [loc.strip() for loc in raw.get("locations") or [] if loc and loc.strip()]
    # "Remote" next to countries is the work mode, not a place anyone may live.
    places = [loc for loc in locations if loc.lower() != "remote"]
    low, high = _money(raw.get("compensation_amount_min_cents")), _money(raw.get("compensation_amount_max_cents"))
    url = raw.get("url") or ""
    return Job(
        source="getro",
        source_job_id=str(raw["id"]),
        source_url=url,
        company=(org.get("name") or "").strip(),
        title=(raw.get("title") or "").strip(),
        application_url=url or None,
        location_raw=" / ".join(locations) or None,
        allowed_locations=places,
        remote_status=_WORK_MODE.get(raw.get("work_mode") or "", UNKNOWN),
        salary_min=low,
        salary_max=high,
        salary_currency=raw.get("compensation_currency") if low or high else None,
        salary_period=_PERIOD.get(raw.get("compensation_period") or "") if low or high else None,
        tags=list(raw.get("skills") or []),
        posted_at=parse_datetime(raw.get("created_at")),
    )


def from_config(section) -> GetroSource | None:
    if not isinstance(section, dict) or not section.get("enabled", True):
        return None
    boards = enabled_entries(section.get("boards"))
    if not boards:
        return None
    return GetroSource(boards, section.get("queries") or ["python"], int(section.get("max_pages", 2)))
