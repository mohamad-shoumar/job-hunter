"""freehire.me: an open-source aggregator of ~450 job sources and ~180 ATS platforms (strelov1/freehire).

Public JSON API, no key. `/api/v1/agent/jobs/search` returns each posting's full text (the web
search, `/api/v1/jobs/search`, cuts it at ~1000 characters, too short for the visa, 401(k) and
years rules). `q` takes up to 5 alternatives joined by an uppercase OR, and `title:` keeps an
alternative to the title, so the target words are searched 5 at a time. It is one person's
project, best effort and no SLA: every request waits `pause` seconds, and a broken search costs
only itself. Research: docs/research/2026-11-13-freehire-as-a-source.md.

- Dates: freehire re-dates postings. Against the same posting stored from its own board (42
  matched by ATS id), `posted_at` was a median 18 days late, `created_at` (when freehire first
  indexed it) a median 0 days. So a job is dated by the earlier of the two.
- `skip_sources` are freehire's own sources left out. `whatjobs-*` re-posts with the company
  name rewritten ("Qrusible Talent Network" -> "Qrusible"), which hid an agency from agency.py
  and brought back a job already rejected under its other name, and its links are a whatjobs
  page, not the employer's form. hh, habr_career and the like are postings in Russian or Spanish.
- No location given stays unknown (never "Worldwide"). The location is the posting's own
  `location`, else the cities freehire resolved. Its country codes are never used: they can be
  wrong ("Toronto, Canada" and "Bucharest" came tagged as the UK), which would put a job on the
  visa list on a guess. A city-only posting the rules cannot place is left `unclear`.
- A company name with its legal form glued on ("eworgmbh") gets the space back ("ewor gmbh"), so
  agency.py and blocked_companies still recognise it. Demo postings ATS vendors leave public
  ("GoCo Demo Account", "Software Engineer Demo Job") are left out.
"""

from __future__ import annotations

import re
import time

from ..models import HYBRID, ONSITE, REMOTE, UNKNOWN, Job
from ..text import normalize_words, parse_datetime, utcnow
from .base import Source, SourceResult, describe_error, parse_each, section_enabled

API = "https://freehire.me/api/v1/agent/jobs/search"
JOB_PAGE = "https://freehire.me/jobs/{slug}"
PAGE_SIZE = 50
MAX_ALTERNATIVES = 5  # the API refuses a 6th OR

_WORK_MODE = {"remote": REMOTE, "hybrid": HYBRID, "onsite": ONSITE}

_GLUED_LEGAL_FORM = re.compile(r"(?<=[a-z])(gmbh|ltd|llc|inc)$")
_DEMO = re.compile(r"\bdemo (?:account|job|company)\b", re.I)


def query_groups(queries: list[str]) -> list[str]:
    """["python", "backend", ...] -> ['title:"python" OR title:"backend" ...'], 5 words a group."""
    words = [q.strip().replace('"', "") for q in queries if q.strip()]
    return [" OR ".join(f'title:"{w}"' for w in words[i:i + MAX_ALTERNATIVES])
            for i in range(0, len(words), MAX_ALTERNATIVES)]


class FreehireSource(Source):
    name = "freehire"

    def __init__(self, searches: list[dict], queries: list[str], days: int = 2, max_pages: int = 4,
                 skip_sources: list[str] | None = None, pause: float = 1.0):
        self.searches = [s for s in searches if s.get("enabled", True)]
        self.queries = [normalize_words(q) for q in queries if normalize_words(q)]
        self.groups = query_groups(queries)
        self.days = days
        self.max_pages = max_pages
        self.skip_sources = [s.lower() for s in (skip_sources or [])]
        self.pause = pause

    def wanted(self, title: str) -> bool:
        words = f" {normalize_words(title)} "
        return not self.queries or any(f" {q} " in words for q in self.queries)

    def skipped(self, raw: dict) -> bool:
        source = (raw.get("source") or "").lower()
        if _DEMO.search(f"{raw.get('company') or ''} {raw.get('title') or ''}"):
            return True
        return not (raw.get("company") or "").strip() or any(
            source == s or (s.endswith("*") and source.startswith(s[:-1])) for s in self.skip_sources)

    def window(self) -> int:
        """Days to ask for: `days`, or back to the start of a date-range run."""
        if self.since:
            return max(self.days, (utcnow() - self.since).days + 1)
        return self.days

    def fetch(self, http) -> SourceResult:
        result = SourceResult(self.name)
        seen: set[str] = set()
        skipped = 0
        for search in self.searches:
            label = search.get("name") or ",".join(search.get("countries") or []) or search.get("work_mode", "")
            filters = {k: search[k] for k in ("countries", "regions", "cities", "work_mode") if search.get(k)}
            days = int(search.get("days", self.window()))
            for number, group in enumerate(self.groups, 1):
                for page in range(self.max_pages):
                    params = {**filters, "q": group, "posted_within_days": days, "limit": PAGE_SIZE,
                              "offset": page * PAGE_SIZE, "description_format": "text"}
                    try:
                        if self.pause:
                            time.sleep(self.pause)
                        data = http.get_json(API, params=params)
                    except Exception as exc:
                        result.errors.append(f"{label} words {number} page {page + 1}: {describe_error(exc)}")
                        break
                    raw_jobs = data.get("data") or []
                    fresh = []
                    for raw in raw_jobs:
                        slug = raw.get("public_slug")
                        if slug in seen:
                            continue
                        seen.add(slug)
                        if self.skipped(raw):
                            skipped += 1
                            continue
                        fresh.append(raw)
                    jobs = parse_each(fresh, parse_job, result.errors, f"{label} words {number}", key="public_slug")
                    result.jobs.extend(j for j in jobs if self.wanted(j.title))
                    total = (data.get("meta") or {}).get("total") or 0
                    if len(raw_jobs) < PAGE_SIZE or (page + 1) * PAGE_SIZE >= total:
                        break
        if skipped:
            result.notes.append(f"{skipped} postings from skipped sources or with no company left out")
        return result


def parse_job(raw: dict) -> Job:
    slug = raw["public_slug"]
    dates = [d for d in (parse_datetime(raw.get("created_at")), parse_datetime(raw.get("posted_at"))) if d]
    location = (raw.get("location") or "").strip() or ", ".join(raw.get("cities") or [])
    enrichment = raw.get("enrichment") or {}
    low, high = enrichment.get("salary_min"), enrichment.get("salary_max")
    return Job(
        source="freehire",
        source_job_id=slug,
        source_url=JOB_PAGE.format(slug=slug),
        company=company_name(raw.get("company")),
        title=(raw.get("title") or "").strip(),
        description=raw.get("description") or "",
        application_url=raw.get("url") or None,
        location_raw=location or None,
        remote_status=_WORK_MODE.get(raw.get("work_mode") or "", UNKNOWN),
        employment_type=enrichment.get("employment_type"),
        salary_min=float(low) if low else None,
        salary_max=float(high) if high else None,
        salary_currency=enrichment.get("salary_currency") if low or high else None,
        tags=list(raw.get("skills") or []),
        posted_at=min(dates) if dates else None,
    )


def company_name(name: str | None) -> str:
    """"eworgmbh" -> "ewor gmbh"; any other name as given."""
    name = (name or "").strip()
    return _GLUED_LEGAL_FORM.sub(r" \1", name) if name.islower() and " " not in name else name


def from_config(section) -> FreehireSource | None:
    if not section_enabled(section):
        return None
    return FreehireSource(section.get("searches") or [], section.get("queries") or [],
                          int(section.get("days", 2)), int(section.get("max_pages", 4)),
                          section.get("skip_sources") or [], float(section.get("pause", 1.0)))

