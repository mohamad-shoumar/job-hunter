"""We Work Remotely category RSS feeds.

Each item carries a `region` ("Anywhere in the World", "North America Only")
and, when the employer restricts it, a `country` list. The country list is the
real rule: WWR shows "Anywhere in the World" as the region even on jobs whose
country list is just the US.
"""

from __future__ import annotations

import re

from ..identity import find_ats_url
from ..models import REMOTE, Job
from ..text import html_to_text, parse_datetime
from .base import Source, SourceResult, describe_error, section_enabled
from .feeds import parse_feed_items

DEFAULT_FEEDS = [
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
]
_FLAG = re.compile("[\U0001F1E6-\U0001F1FF]")
_HEADQUARTERS = re.compile(r"Headquarters:\s*</strong>\s*([^<]+)", re.I)


class WeWorkRemotelySource(Source):
    name = "weworkremotely"

    def __init__(self, feeds: list[str] | None = None, limit: int = 200):
        self.feeds = feeds or DEFAULT_FEEDS
        self.limit = limit

    def fetch(self, http) -> SourceResult:
        result = SourceResult(self.name)
        for feed in self.feeds:
            try:
                items = parse_feed_items(http.get_text(feed))
            except Exception as exc:
                result.errors.append(f"{feed}: {describe_error(exc)}")
                continue
            for item in items:
                if len(result.jobs) >= self.limit:
                    return result
                result.jobs.append(parse_item(item))
        return result


def _split_list(value: str) -> list[str]:
    value = _FLAG.sub("", value or "")
    return [part.strip() for part in re.split(r",\s*|\s+and\s+", value) if part.strip()]


def parse_item(item: dict) -> Job:
    company, _, title = (item.get("title") or "").partition(": ")
    if not title:
        company, title = "", company
    description_html = item.get("description") or ""
    region = (item.get("region") or "").strip()
    countries = _split_list(item.get("country") or "")
    hq = _HEADQUARTERS.search(description_html)
    link = item.get("link") or item.get("guid") or ""
    return Job(
        source="weworkremotely",
        source_job_id=item.get("guid") or link,
        source_url=link,
        company=company.strip(),
        title=title.strip(),
        description=html_to_text(description_html),
        application_url=find_ats_url(description_html) or link,
        company_location=hq.group(1).strip() if hq else None,
        location_raw="; ".join(filter(None, [region, ", ".join(countries)])) or None,
        allowed_locations=countries or ([region] if region else []),
        remote_status=REMOTE,
        employment_type=item.get("type"),
        tags=_split_list(item.get("skills") or "") + [item.get("category") or ""],
        posted_at=parse_datetime(item.get("pubDate")),
    )


def from_config(section) -> WeWorkRemotelySource | None:
    if not section_enabled(section):
        return None
    return WeWorkRemotelySource(section.get("feeds"), int(section.get("limit", 200)))
