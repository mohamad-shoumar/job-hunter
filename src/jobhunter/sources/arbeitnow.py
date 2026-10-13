"""Arbeitnow job board API: jobs in Germany, the Netherlands and the UK. Public, no key.

GET <site>/api/job-board-api?page=N, newest first, with full descriptions.
Terms: free, "please do not abuse", link back to Arbeitnow (the report links
each job's Arbeitnow page). Checked 2026-10-13.

- No country field: the site's domain says it (arbeitnow.nl -> Netherlands).
  arbeitnow.com mixes in jobs from the other sites, so each job's own URL decides.
- `visa_sponsorship=true` narrows the list, but the flag is set per company,
  not per job: flagged postings say "We do not provide visa sponsorship" too.
  So it only trims what is fetched; the posting's own words decide (visa.py).
- UK and NL descriptions are sometimes HTML-escaped twice.

Most jobs are not software roles (and in German), and every fetched job is
stored, so only titles with one of `queries` are kept.
"""

from __future__ import annotations

import html
from datetime import timedelta
from urllib.parse import urlsplit

from ..models import ONSITE, REMOTE, Job
from ..text import html_to_text, normalize_words, parse_datetime, utcnow
from .base import Source, SourceResult, describe_error, enabled_entries, section_enabled

API = "{site}/api/job-board-api"
COUNTRY_BY_DOMAIN = {
    "arbeitnow.com": "Germany", "arbeitnow.de": "Germany", "arbeitnow.co.uk": "United Kingdom",
    "arbeitnow.nl": "Netherlands", "arbeitnow.fr": "France", "arbeitnow.ch": "Switzerland",
}
MAX_PAGES_FOR_RANGE = 30


class ArbeitnowSource(Source):
    name = "arbeitnow"

    def __init__(self, sites: list[dict], queries: list[str], lookback_hours: int = 36, max_pages: int = 10):
        self.sites = sites
        self.queries = [normalize_words(q) for q in queries if normalize_words(q)]
        self.lookback_hours = lookback_hours
        self.max_pages = max_pages

    def wanted(self, title: str) -> bool:
        words = f" {normalize_words(title)} "
        return not self.queries or any(f" {q} " in words for q in self.queries)

    def fetch(self, http) -> SourceResult:
        """Each site newest first, until a page reaches jobs older than the look-back (or `since`)."""
        result = SourceResult(self.name)
        stop_at = self.since or utcnow() - timedelta(hours=self.lookback_hours)
        max_pages = MAX_PAGES_FOR_RANGE if self.since else self.max_pages
        for site in self.sites:
            url = API.format(site=site["site"].rstrip("/"))
            kept = 0
            for page in range(1, int(site.get("max_pages", max_pages)) + 1):
                params = {"page": page}
                if site.get("visa_sponsorship"):
                    params["visa_sponsorship"] = "true"
                try:
                    data = http.get_json(url, params=params)
                except Exception as exc:
                    result.errors.append(f"{site['site']} page {page}: {describe_error(exc)}")
                    break
                raw_jobs = data.get("data") or []
                jobs = [parse_job(raw) for raw in raw_jobs]
                wanted = [j for j in jobs if self.wanted(j.title)]
                result.jobs.extend(wanted)
                kept += len(wanted)
                # The site's own jobs are newest first; the ones mixed in from other sites are not.
                own = [j for j in jobs if _domain(j.source_url) == _domain(site["site"])] or jobs
                oldest = min((j.posted_at for j in own if j.posted_at), default=None)
                if not raw_jobs or not (data.get("links") or {}).get("next") or (oldest and oldest < stop_at):
                    break
            if not kept:
                result.notes.append(f"{site['site']}: no matching titles")
        return result


def _domain(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


def _description(value: str | None) -> str:
    text = value or ""
    if "&lt;" in text and text.count("&lt;") > text.count("<"):  # escaped twice
        text = html.unescape(text)
    return html_to_text(text)


def parse_job(raw: dict) -> Job:
    url = raw.get("url") or ""
    country = COUNTRY_BY_DOMAIN.get(_domain(url))
    location = " ".join((raw.get("location") or "").split())
    remote = bool(raw.get("remote"))
    place = location
    # "Berlin" on arbeitnow.com is Berlin, Germany. A remote job's country is unknown: it is left to the posting.
    if country and not remote and normalize_words(country) not in normalize_words(location):
        place = f"{location}, {country}" if location else country
    return Job(
        source="arbeitnow",
        source_job_id=raw.get("slug") or url,
        source_url=url,
        company=(raw.get("company_name") or "").strip(),
        title=" ".join((raw.get("title") or "").split()),
        description=_description(raw.get("description")),
        application_url=url or None,
        location_raw=place or None,
        allowed_locations=[place] if place and not remote else [],
        remote_status=REMOTE if remote else ONSITE,
        tags=[str(t) for t in (raw.get("tags") or []) + (raw.get("job_types") or [])],
        posted_at=parse_datetime(raw.get("created_at")),
    )


def from_config(section) -> ArbeitnowSource | None:
    if not section_enabled(section):
        return None
    sites = enabled_entries(section.get("sites"))
    if not sites:
        return None
    return ArbeitnowSource(sites, section.get("queries") or [], int(section.get("lookback_hours", 36)),
                           int(section.get("max_pages", 10)))
