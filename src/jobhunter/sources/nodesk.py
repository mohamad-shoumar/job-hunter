"""NoDesk RSS feeds (nodesk.co). Small (about 10 items per feed) but cheap."""

from __future__ import annotations

from ..models import REMOTE, Job
from ..text import html_to_text, parse_datetime
from .base import Source, SourceResult, describe_error, section_enabled
from .feeds import parse_feed_items

DEFAULT_FEEDS = ["https://nodesk.co/remote-jobs/engineering/index.xml"]


class NoDeskSource(Source):
    name = "nodesk"

    def __init__(self, feeds: list[str] | None = None, limit: int = 100):
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
            result.jobs.extend(parse_item(item) for item in items[: max(0, self.limit - len(result.jobs))])
        return result


def parse_item(item: dict) -> Job:
    title, sep, company = (item.get("title") or "").rpartition(" at ")
    if not sep:  # no " at Company" suffix
        title, company = company, ""
    link = item.get("link") or item.get("guid") or ""
    return Job(
        source="nodesk",
        source_job_id=item.get("guid") or link,
        source_url=link,
        company=company.strip(),
        title=title.strip(),
        description=html_to_text(item.get("description")),
        application_url=link,
        remote_status=REMOTE,
        posted_at=parse_datetime(item.get("pubDate")),
    )


def from_config(section) -> NoDeskSource | None:
    if not section_enabled(section):
        return None
    return NoDeskSource(section.get("feeds"), int(section.get("limit", 100)))
