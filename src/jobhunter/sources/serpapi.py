"""Google Jobs through SerpApi (serpapi.com). Needs SERPAPI_API_KEY; skipped without it.

Google Jobs collects postings from LinkedIn, company sites and job boards, so
this is the legal way to see LinkedIn-sourced jobs without scraping LinkedIn.
Each search costs one SerpApi credit per page.

Google shows remote jobs with the location "Anywhere". That means "work from
home", NOT "hires worldwide" - so it is not passed on as a location.

The posted age, "Work from home", schedule and salary usually arrive only as
plain strings in `extensions` (["2 days ago", "82K–111K a year", "Work from
home", "Full-time"]); `detected_extensions` is often nearly empty (checked
against a real response, 2026-09-27).
"""

from __future__ import annotations

import os
import re

from ..identity import ats_key_from_url
from ..models import REMOTE, UNKNOWN, Job
from ..text import clean_text, parse_relative_age, utcnow
from .base import Source, SourceResult, describe_error, section_enabled

API = "https://serpapi.com/search.json"


class SerpApiSource(Source):
    name = "serpapi"

    def __init__(self, queries: list[str], pages_per_query: int = 1, engine: str = "google_jobs", params: dict | None = None):
        self.queries = queries
        self.pages_per_query = pages_per_query
        self.engine = engine
        self.params = params or {}

    def fetch(self, http) -> SourceResult:
        result = SourceResult(self.name)
        api_key = os.environ.get("SERPAPI_API_KEY")
        if not api_key:
            result.notes.append("SERPAPI_API_KEY is not set; source skipped")
            return result
        now = utcnow()
        for query in self.queries:
            token = None
            for page in range(self.pages_per_query):
                params = {"engine": self.engine, "q": query, "hl": "en", "api_key": api_key, **self.params}
                if token:
                    params["next_page_token"] = token
                try:
                    data = http.get_json(API, params=params)
                except Exception as exc:
                    result.errors.append(f'query "{query}" page {page + 1}: {describe_error(exc)}')
                    break
                if data.get("error"):
                    if "hasn't returned any results" not in data["error"]:
                        result.errors.append(f'query "{query}": {data["error"]}')
                    break
                result.jobs.extend(parse_job(raw, now) for raw in data.get("jobs_results") or [])
                token = (data.get("serpapi_pagination") or {}).get("next_page_token")
                if not token:
                    break
        return result


_SCHEDULES = re.compile(r"\b(?:full-time|part-time|contractor|internship|temp work|per diem)\b", re.I)
_PAY = re.compile(r"\d.*\b(?:a|an|per)\s+(?:year|hour|month|week|day)\b", re.I)


def _extension(extensions: list[str], pattern: re.Pattern) -> str | None:
    return next((e for e in extensions if pattern.search(e)), None)


def parse_job(raw: dict, now) -> Job:
    links = [o.get("link") for o in raw.get("apply_options") or [] if o.get("link")]
    application_url = next((u for u in links if ats_key_from_url(u)), links[0] if links else raw.get("share_link"))
    detected = raw.get("detected_extensions") or {}
    plain = [str(e) for e in raw.get("extensions") or []]
    extensions = {
        "posted_at": detected.get("posted_at") or _extension(plain, re.compile(r"\bago\b", re.I)),
        "work_from_home": detected.get("work_from_home") or bool(_extension(plain, re.compile(r"work from home", re.I))),
        "schedule_type": detected.get("schedule_type") or _extension(plain, _SCHEDULES),
        "salary": detected.get("salary") or _extension(plain, _PAY),
    }
    location = (raw.get("location") or "").strip()
    is_anywhere = location.lower() in ("anywhere", "remote", "")
    highlights = []
    for block in raw.get("job_highlights") or []:
        highlights.append(block.get("title") or "")
        highlights += [f"- {item}" for item in block.get("items") or []]
    return Job(
        source="serpapi",
        source_job_id=raw.get("job_id") or application_url or "",
        source_url=raw.get("share_link") or application_url or "",
        company=raw.get("company_name") or "",
        title=raw.get("title") or "",
        description=clean_text("\n".join([raw.get("description") or ""] + highlights)),
        application_url=application_url,
        location_raw=None if is_anywhere else location,
        remote_status=REMOTE if extensions.get("work_from_home") or location.lower() == "anywhere" else UNKNOWN,
        employment_type=extensions.get("schedule_type"),
        salary_raw=extensions.get("salary"),
        posted_at=parse_relative_age(extensions.get("posted_at"), now),
    )


def from_config(section) -> SerpApiSource | None:
    if not section_enabled(section) or not section.get("queries"):
        return None
    return SerpApiSource(
        section["queries"],
        int(section.get("pages_per_query", 1)),
        section.get("engine", "google_jobs"),
        section.get("params"),
    )
