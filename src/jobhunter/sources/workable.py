"""Workable's job search (jobs.workable.com): every company hiring through Workable. Public, no key.

GET https://jobs.workable.com/api/v1/jobs?query=...&location=<country>&day_range=N
20 jobs a page, `nextPageToken` for the next. Sorted by relevance, not date, so
`day_range` keeps a daily run to recent postings. Full text comes in three
parts (description, requirementsSection, benefitsSection). `locations` reads
like ["TELECOMMUTE", "Netherlands"]: TELECOMMUTE is the work mode, not a place.

For the visa list (visa.py): one search per query and country. Checked
2026-10-13: 57 of 805 target roles in the seven countries reached the list,
mostly through the UK and Dutch sponsor registers.
"""

from __future__ import annotations

from ..models import HYBRID, ONSITE, REMOTE, UNKNOWN, Job
from ..text import html_to_text, parse_datetime
from .base import Source, SourceResult, describe_error, parse_each, section_enabled

API = "https://jobs.workable.com/api/v1/jobs"
_WORKPLACE = {"remote": REMOTE, "hybrid": HYBRID, "on_site": ONSITE}
MAX_DAY_RANGE = 30


class WorkableSource(Source):
    name = "workable"

    def __init__(self, queries: list[str], countries: list[str], day_range: int = 3, max_pages: int = 2):
        self.queries = queries
        self.countries = countries
        self.day_range = day_range
        self.max_pages = max_pages

    def fetch(self, http) -> SourceResult:
        result = SourceResult(self.name)
        days = self.day_range
        if self.since is not None:  # a date-range run: reach back to its start
            from ..text import utcnow

            days = min(MAX_DAY_RANGE, max(days, (utcnow() - self.since).days + 1))
        for country in self.countries:
            for query in self.queries:
                token = None
                for page in range(self.max_pages):
                    params = {"query": query, "location": country, "day_range": days}
                    if token:
                        params["pageToken"] = token
                    label = f'"{query}" in {country} page {page + 1}'
                    try:
                        data = http.get_json(API, params=params)
                    except Exception as exc:
                        result.errors.append(f"{label}: {describe_error(exc)}")
                        break
                    result.jobs += parse_each(data.get("jobs") or [], parse_job, result.errors, label)
                    token = data.get("nextPageToken")
                    if not token:
                        break
        return result


def parse_job(raw: dict) -> Job:
    places = [p.strip() for p in raw.get("locations") or [] if p and p.strip() and p.strip().upper() != "TELECOMMUTE"]
    text = " ".join(raw.get(k) or "" for k in ("description", "requirementsSection", "benefitsSection"))
    return Job(
        source="workable",
        source_job_id=str(raw["id"]),
        source_url=raw.get("url") or "",
        company=((raw.get("company") or {}).get("title") or "").strip(),
        title=" ".join((raw.get("title") or "").split()),
        description=html_to_text(text),
        application_url=raw.get("url") or None,
        location_raw=" / ".join(places) or None,
        allowed_locations=places,
        remote_status=_WORKPLACE.get(raw.get("workplace") or "", UNKNOWN),
        employment_type=raw.get("employmentType") or None,
        posted_at=parse_datetime(raw.get("created")),
    )


def from_config(section) -> WorkableSource | None:
    if not section_enabled(section) or not section.get("queries") or not section.get("countries"):
        return None
    return WorkableSource(section["queries"], section["countries"], int(section.get("day_range", 3)),
                          int(section.get("max_pages", 2)))
