"""Himalayas search API. Public, no key: himalayas.app/api

The search endpoint takes `country=LB` and then only returns jobs whose
location restrictions include Lebanon or are empty. Empty often just means
Himalayas does not know, so those jobs carry no location and the local rules
decide from the description.
"""

from __future__ import annotations

from ..models import REMOTE, Job
from ..text import html_to_text, parse_datetime
from .base import Source, SourceResult, describe_error, section_enabled

SEARCH = "https://himalayas.app/jobs/api/search"
PAGE_SIZE = 20
MAX_PAGES_FOR_RANGE = 25  # 500 jobs per query: a safety stop for very long ranges


class HimalayasSource(Source):
    name = "himalayas"

    def __init__(self, queries: list[str], limit: int = 100, country: str | None = "LB"):
        self.queries = queries
        self.limit = limit
        self.country = country

    def fetch(self, http) -> SourceResult:
        """Newest first. Daily: up to `limit` jobs per query. With `since` (a
        date-range run): keep paging until the page reaches jobs older than
        `since`, so the whole range is covered however busy it was."""
        result = SourceResult(self.name)
        for query in self.queries:
            fetched, page = 0, 1
            while True:
                params = {"q": query, "sort": "recent", "page": page}
                if self.country:
                    params["country"] = self.country
                try:
                    data = http.get_json(SEARCH, params=params)
                except Exception as exc:
                    result.errors.append(f'query "{query}" page {page}: {describe_error(exc)}')
                    break
                raw_jobs = data.get("jobs") or []
                jobs = [parse_job(raw) for raw in raw_jobs]
                if self.since is None:
                    jobs = jobs[: self.limit - fetched]
                result.jobs.extend(jobs)
                fetched += len(raw_jobs)
                # A page can hold fewer than PAGE_SIZE jobs mid-way, so only an
                # empty page or the reported total ends the query.
                if not raw_jobs or fetched >= (data.get("totalCount") or 0):
                    break
                if self.since is not None:
                    oldest = min((j.posted_at for j in jobs if j.posted_at), default=None)
                    if (oldest and oldest < self.since) or page >= MAX_PAGES_FOR_RANGE:
                        break
                elif fetched >= self.limit or page >= self.limit // PAGE_SIZE + 1:
                    break
                page += 1
        return result


def parse_job(raw: dict) -> Job:
    # An empty locationRestrictions list means Himalayas does not know, not
    # "any country": it shows "Worldwide" for US-only roles too (Medallion,
    # 2026-09-27). Left empty, the description decides.
    allowed = [r for r in raw.get("locationRestrictions") or [] if r]
    offsets = [float(o) for o in raw.get("timezoneRestrictions") or [] if isinstance(o, (int, float))]
    period = (raw.get("salaryPeriod") or "").lower()
    link = raw.get("applicationLink") or raw.get("guid") or ""
    return Job(
        source="himalayas",
        source_job_id=raw.get("guid") or link,
        source_url=link,
        company=raw.get("companyName") or "",
        title=raw.get("title") or "",
        description=html_to_text(raw.get("description")) or raw.get("excerpt") or "",
        application_url=link,
        location_raw=", ".join(allowed) or None,
        allowed_locations=allowed,
        allowed_utc_offsets=offsets,
        remote_status=REMOTE,
        employment_type=raw.get("employmentType"),
        salary_min=raw.get("minSalary") or None,
        salary_max=raw.get("maxSalary") or None,
        salary_currency=raw.get("currency") if raw.get("minSalary") or raw.get("maxSalary") else None,
        salary_period="year" if period in ("annual", "yearly", "year") else (period or None),
        tags=[str(c) for c in raw.get("categories") or []],
        posted_at=parse_datetime(raw.get("pubDate")),
    )


def from_config(section) -> HimalayasSource | None:
    if not section_enabled(section) or not section.get("queries"):
        return None
    return HimalayasSource(section["queries"], int(section.get("limit", 100)), section.get("country", "LB"))
