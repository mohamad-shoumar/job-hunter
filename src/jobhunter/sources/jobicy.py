"""Jobicy remote jobs API: jobicy.com/api/v2/remote-jobs (docs: jobi.cy/apidocs). Public, no key.

Newest first, up to 100 jobs a page, next pages through `cursor`; only the last ~7 days.
Terms (the API's own notice): credit Jobicy with a direct link and send every application
to the job URL it gives, so both links are the Jobicy page. `jobGeo` is the region the
company hires in ("Anywhere", "EMEA", "USA", "Canada, USA"). Checked 2026-10-21: about 3
"Anywhere" or "EMEA" developer jobs a day; 9 of 12 were already found through other sources.
"""

from __future__ import annotations

from datetime import timedelta

from ..models import REMOTE, Job
from ..text import html_to_text, normalize_words, parse_datetime, utcnow
from .base import Source, SourceResult, describe_error, parse_each, section_enabled

API = "https://jobicy.com/api/v2/remote-jobs"


class JobicySource(Source):
    name = "jobicy"

    def __init__(self, queries: list[str], industry: str = "dev", lookback_hours: int = 36, max_pages: int = 3):
        self.queries = [normalize_words(q) for q in queries if normalize_words(q)]
        self.industry = industry
        self.lookback_hours = lookback_hours
        self.max_pages = max_pages

    def wanted(self, title: str) -> bool:
        words = f" {normalize_words(title)} "
        return not self.queries or any(f" {q} " in words for q in self.queries)

    def fetch(self, http) -> SourceResult:
        result = SourceResult(self.name)
        stop_at = self.since or utcnow() - timedelta(hours=self.lookback_hours)
        cursor = None
        for page in range(1, self.max_pages + 1):
            params = {"count": 100, "industry": self.industry}
            if cursor:
                params["cursor"] = cursor
            try:
                data = http.get_json(API, params=params)
            except Exception as exc:
                result.errors.append(f"page {page}: {describe_error(exc)}")
                break
            raw_jobs = data.get("jobs") or []
            jobs = parse_each(raw_jobs, parse_job, result.errors, f"page {page}")
            result.jobs.extend(j for j in jobs if self.wanted(j.title))
            oldest = min((j.posted_at for j in jobs if j.posted_at), default=None)
            cursor = data.get("nextCursor")
            if not raw_jobs or not data.get("hasMore") or not cursor or (oldest and oldest < stop_at):
                break
        return result


def parse_job(raw: dict) -> Job:
    allowed = [p.strip() for p in (raw.get("jobGeo") or "").split(",") if p.strip()]
    low, high = raw.get("salaryMin"), raw.get("salaryMax")
    period = (raw.get("salaryPeriod") or "").lower()
    url = raw.get("url") or ""
    return Job(
        source="jobicy",
        source_job_id=str(raw.get("id") or url),
        source_url=url,
        company=raw.get("companyName") or "",
        title=html_to_text(raw.get("jobTitle")),
        description=html_to_text(raw.get("jobDescription")) or raw.get("jobExcerpt") or "",
        application_url=url,
        location_raw=", ".join(allowed) or None,
        allowed_locations=allowed,
        remote_status=REMOTE,
        salary_min=float(low) if low else None,
        salary_max=float(high) if high else None,
        salary_currency=raw.get("salaryCurrency") if low or high else None,
        salary_period="year" if period in ("yearly", "annual", "year") else (period or None),
        tags=[t for t in [raw.get("jobLevel")] if t],
        posted_at=parse_datetime(raw.get("pubDate")),
    )


def from_config(section) -> JobicySource | None:
    if not section_enabled(section):
        return None
    return JobicySource(section.get("queries") or [], section.get("industry", "dev"),
                        int(section.get("lookback_hours", 36)), int(section.get("max_pages", 3)))
