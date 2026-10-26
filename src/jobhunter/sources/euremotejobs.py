"""EU Remote Jobs (euremotejobs.com): remote jobs with Europe, EMEA or worldwide hiring. No key.

POST /jm-ajax/get_listings/ (the site's own WordPress job list) returns newest first, 100 a
page, as JSON with the list as HTML: title "X at Company", region classes, "Posted N hours
ago". Its RSS feed is empty. robots.txt blocks the site's search pages (?search_category=...),
so the whole list is read unfiltered and only titles with one of `queries` are kept; each of
those gets its job page read, whose schema.org JobPosting has the full description, posting
date and allowed countries. About 100 jobs a day, all kinds; ~4 non-senior engineering jobs a
day open worldwide or in EMEA (checked 2026-10-21).
"""

from __future__ import annotations

import html
import re
from datetime import timedelta

from ..models import REMOTE, Job
from ..text import html_to_text, normalize_words, parse_datetime, parse_relative_age, utcnow
from .base import Source, SourceResult, describe_error, parse_each, section_enabled
from .custom_page import job_posting, ld_locations

LISTINGS = "https://euremotejobs.com/jm-ajax/get_listings/"

_ITEM = re.compile(r'<li id="job_listing-(\d+)" class="([^"]*)" data-title="([^"]*)" data-href="([^"]*)"(.*?)</li>\s*(?=<li id="job_listing-|$)', re.S)
_COMPANY = re.compile(r'job_listing-company">\s*<strong>(.*?)</strong>', re.S)
_LOCATION = re.compile(r'job_listing-location[^>]*>(.*?)</div>', re.S)
_DATE = re.compile(r'job_listing-date">(.*?)<', re.S)
_REGION = re.compile(r"\bjob_listing_region-([a-z0-9-]+)")
_TITLE = re.compile(r'job_listing-title">(.*?)</h3>', re.S)
_APPLY = re.compile(r'href="([^"]+)"[^>]*class="application_button_link')
# Region classes in plain words, for the location rules: "remote-jobs-worldwide" -> "Worldwide".
_REGION_NAMES = {"remote-jobs-worldwide": "Worldwide", "remote-jobs-europe": "Europe", "remote-jobs-emea": "EMEA"}


def _clean(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())


class EuRemoteJobsSource(Source):
    name = "euremotejobs"

    def __init__(self, queries: list[str], lookback_hours: int = 36, max_pages: int = 3):
        self.queries = [normalize_words(q) for q in queries if normalize_words(q)]
        self.lookback_hours = lookback_hours
        self.max_pages = max_pages

    def wanted(self, title: str) -> bool:
        words = f" {normalize_words(title)} "
        return not self.queries or any(f" {q} " in words for q in self.queries)

    def fetch(self, http) -> SourceResult:
        result = SourceResult(self.name)
        now = utcnow()
        stop_at = self.since or now - timedelta(hours=self.lookback_hours)
        for page in range(1, self.max_pages + 1):
            body = {"per_page": 100, "orderby": "date", "order": "DESC", "page": page}
            try:
                data = http.post_form(LISTINGS, body)
            except Exception as exc:
                result.errors.append(f"page {page}: {describe_error(exc)}")
                break
            items = parse_listing(data.get("html") or "", now)
            fresh = [i for i in items if not (i["posted_at"] and i["posted_at"] < stop_at) and self.wanted(i["title"])]
            result.jobs += parse_each(fresh, lambda item: self._job(http, item, result.errors), result.errors,
                                      f"page {page}")
            oldest = min((i["posted_at"] for i in items if i["posted_at"]), default=None)
            if not items or page >= int(data.get("max_num_pages") or 0) or (oldest and oldest < stop_at):
                break
        return result

    def _job(self, http, item: dict, errors: list[str]) -> Job:
        """A listing row plus its job page. When the page fails, the row alone is kept."""
        try:
            page_html = http.get_text(item["url"])
        except Exception as exc:
            errors.append(f"{item['url']}: {describe_error(exc)}")
            page_html = ""
        return parse_job(item, page_html)


def parse_listing(page: str, now) -> list[dict]:
    items = []
    for job_id, classes, data_title, href, body in _ITEM.findall(page):
        title = _clean(m.group(1)) if (m := _TITLE.search(body)) else html.unescape(data_title)
        company = _clean(m.group(1)) if (m := _COMPANY.search(body)) else ""
        regions = [_REGION_NAMES.get(r, r.replace("-", " ").title()) for r in _REGION.findall(classes)]
        items.append({
            "id": job_id,
            "url": html.unescape(href),
            "title": title,
            "company": company,
            "location": _clean(m.group(1)) if (m := _LOCATION.search(body)) else "",
            "regions": regions,
            "posted_at": parse_relative_age(_clean(m.group(1)) if (m := _DATE.search(body)) else "", now),
        })
    return items


def parse_job(item: dict, page_html: str) -> Job:
    """A listing row plus its job page (empty when the page failed: the row alone is kept)."""
    posting = job_posting(page_html) or {}
    apply = _APPLY.search(page_html)
    allowed = ld_locations(posting) or item["regions"]
    return Job(
        source="euremotejobs",
        source_job_id=item["id"],
        source_url=item["url"],
        company=item["company"],
        title=item["title"],
        description=html_to_text(posting.get("description")),
        application_url=html.unescape(apply.group(1)) if apply else item["url"],
        location_raw=item["location"] or ", ".join(allowed) or None,
        allowed_locations=allowed,
        remote_status=REMOTE,
        posted_at=parse_datetime(posting.get("datePosted")) or item["posted_at"],
    )


def from_config(section) -> EuRemoteJobsSource | None:
    if not section_enabled(section):
        return None
    return EuRemoteJobsSource(section.get("queries") or [], int(section.get("lookback_hours", 36)),
                              int(section.get("max_pages", 3)))
