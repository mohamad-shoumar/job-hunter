"""Himalayas search API. Public, no key: himalayas.app/api

The search endpoint takes `country=LB` and then only returns jobs whose
location restrictions include Lebanon or are empty. Empty often just means
Himalayas does not know, so those jobs carry no location and the local rules
decide from the description.

`pubDate` is not always the posting date: Himalayas re-lists old jobs with a new
`pubDate` and leaves `expiryDate` alone (on 2026-11-01 it re-listed about 70% of
its jobs, Hivex's from mid-October among them). A listing runs a whole number of
days, almost always 60: so a `pubDate` that is not a whole number of days before
`expiryDate` was moved, and the job was first listed about 60 days before it
expires (`listed_at`, checked against 49 stored jobs: 40 exact, the rest within
2 days or later than the real date).
"""

from __future__ import annotations

from datetime import timedelta

from ..models import REMOTE, DateCheck, Job
from ..text import html_to_text, iso, parse_datetime
from .base import Source, SourceResult, describe_error, parse_each, section_enabled

SEARCH = "https://himalayas.app/jobs/api/search"
PAGE_SIZE = 20
MAX_PAGES_FOR_RANGE = 25  # 500 jobs per query: a safety stop for very long ranges
LISTING_DAYS = 60  # how long Himalayas lists a job (120 of 130 first listings checked on 2026-11-02)
WHOLE_DAY_SLACK = 60  # seconds: a first listing's span is a whole number of days to within ~30s
RELISTED = "himalayas"  # DateCheck.found_by for a date read from expiryDate


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
                jobs = parse_each(raw_jobs, parse_job, result.errors, f'query "{query}" page {page}', key="guid")
                if self.since is None:
                    jobs = jobs[: self.limit - fetched]
                result.jobs.extend(jobs)
                fetched += len(raw_jobs)
                # A page can hold fewer than PAGE_SIZE jobs mid-way, so only an
                # empty page or the reported total ends the query.
                if not raw_jobs or fetched >= (data.get("totalCount") or 0):
                    break
                if self.since is not None:
                    # The API orders by pubDate, re-listings' moved one too: page by that, not by listed_at.
                    oldest = min(filter(None, (parse_datetime(r.get("pubDate")) for r in raw_jobs)), default=None)
                    if (oldest and oldest < self.since) or page >= MAX_PAGES_FOR_RANGE:
                        break
                elif fetched >= self.limit or page >= self.limit // PAGE_SIZE + 1:
                    break
                page += 1
        return result


def listed_at(raw: dict):
    """(when the job was first listed, the evidence when that is not `pubDate`, else None)."""
    pub, expiry = parse_datetime(raw.get("pubDate")), parse_datetime(raw.get("expiryDate"))
    if not pub or not expiry or expiry <= pub:
        return pub, None
    span = (expiry - pub).total_seconds()
    off = span % 86400
    if min(off, 86400 - off) <= WHOLE_DAY_SLACK:
        return pub, None
    first = min(pub, expiry - timedelta(days=LISTING_DAYS))
    reason = (f"Himalayas re-listed it: its pubDate is {span / 86400:.1f} days before its expiryDate, not a whole "
              f"number of days, so it was first listed about {LISTING_DAYS} days before it expires.")
    quote = f"pubDate {iso(pub)}, expiryDate {iso(expiry)}"
    return first, DateCheck(iso(first), quote, raw.get("guid") or "", RELISTED, reason)


def parse_job(raw: dict) -> Job:
    # An empty locationRestrictions list means Himalayas does not know, not
    # "any country": it shows "Worldwide" for US-only roles too (Medallion,
    # 2026-09-27). Left empty, the description decides.
    allowed = [r for r in raw.get("locationRestrictions") or [] if r]
    offsets = [float(o) for o in raw.get("timezoneRestrictions") or [] if isinstance(o, (int, float))]
    period = (raw.get("salaryPeriod") or "").lower()
    link = raw.get("applicationLink") or raw.get("guid") or ""
    posted_at, date_check = listed_at(raw)
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
        posted_at=posted_at,
        date_check=date_check,
    )


def from_config(section) -> HimalayasSource | None:
    if not section_enabled(section) or not section.get("queries"):
        return None
    return HimalayasSource(section["queries"], int(section.get("limit", 100)), section.get("country", "LB"))
