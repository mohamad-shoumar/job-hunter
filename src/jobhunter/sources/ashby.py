"""Ashby job boards. Public API, no key: developers.ashbyhq.com/docs/public-job-posting-api"""

from __future__ import annotations

from ..extract import normalize_workplace, remote_status_from_location
from ..models import REMOTE, UNKNOWN, Job
from ..text import html_to_text, parse_datetime
from .base import Source, SourceResult, describe_error, enabled_entries

API = "https://api.ashbyhq.com/posting-api/job-board/{token}"


class AshbySource(Source):
    name = "ashby"

    def __init__(self, boards: list[dict]):
        self.boards = boards

    def fetch(self, http) -> SourceResult:
        result = SourceResult(self.name)
        for board in self.boards:
            try:
                data = http.get_json(API.format(token=board["board_token"]), params={"includeCompensation": "true"})
            except Exception as exc:
                result.errors.append(f"{board['company']} ({board['board_token']}): {describe_error(exc)}")
                continue
            jobs = [j for j in data.get("jobs") or [] if j.get("isListed", True)]
            if not jobs:
                result.notes.append(f"{board['company']}: board has no open jobs")
            result.jobs.extend(parse_job(raw, board) for raw in jobs)
        return result


def _period(interval: str | None) -> str | None:
    v = (interval or "").lower()
    for period in ("year", "month", "hour"):
        if period in v:
            return period
    return None


def parse_job(raw: dict, board: dict) -> Job:
    locations = [raw.get("location")] + [s.get("location") for s in raw.get("secondaryLocations") or []]
    locations = [loc.strip() for loc in locations if loc and loc.strip()]
    title = (raw.get("title") or "").strip()
    remote_status = normalize_workplace(raw.get("workplaceType"))
    if remote_status == UNKNOWN:
        remote_status = REMOTE if raw.get("isRemote") else remote_status_from_location(", ".join(locations), title)
    compensation = raw.get("compensation") or {}
    salary = next(
        (c for c in compensation.get("summaryComponents") or [] if (c.get("compensationType") or "").lower() == "salary"),
        {},
    )
    return Job(
        source="ashby",
        source_job_id=raw["id"],
        source_url=raw.get("jobUrl") or "",
        company=board["company"],
        title=title,
        description=raw.get("descriptionPlain") or html_to_text(raw.get("descriptionHtml")),
        application_url=raw.get("jobUrl") or raw.get("applyUrl"),
        company_location=board.get("company_location"),
        location_raw=" / ".join(locations) or None,
        allowed_locations=locations,
        remote_status=remote_status,
        employment_type=raw.get("employmentType"),
        salary_min=salary.get("minValue"),
        salary_max=salary.get("maxValue"),
        salary_currency=salary.get("currencyCode"),
        salary_period=_period(salary.get("interval")),
        salary_raw=compensation.get("scrapeableCompensationSalarySummary") or compensation.get("compensationTierSummary"),
        posted_at=parse_datetime(raw.get("publishedAt")),
    )


def from_config(section) -> AshbySource | None:
    boards = enabled_entries(section)
    return AshbySource(boards) if boards else None
