"""Teamtailor careers sites: the public RSS feed at <site>/jobs.rss, no key.

Used by many Gulf companies (Property Finder, Calo, Sarwa, Wego). A site is
either <slug>.teamtailor.com or the company's own domain (careers.calo.app).
Each item has the full description, a date, the work mode and the locations.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from ..extract import normalize_workplace
from ..models import ONSITE, REMOTE, Job
from ..text import html_to_text, parse_datetime
from .base import Source, SourceResult, describe_error, enabled_entries
from .feeds import _fix_entities, _local


# Teamtailor's own words: "none" is not remote at all, "fully" is fully remote.
_REMOTE_STATUS = {"none": ONSITE, "fully": REMOTE}


def feed_url(board: dict) -> str:
    site = board.get("site") or f"{board['board_token']}.teamtailor.com"
    return f"https://{site.removeprefix('https://').rstrip('/')}/jobs.rss"


class TeamtailorSource(Source):
    name = "teamtailor"

    def __init__(self, boards: list[dict]):
        self.boards = boards

    def fetch(self, http) -> SourceResult:
        result = SourceResult(self.name)
        for board in self.boards:
            try:
                items = parse_feed(http.get_text(feed_url(board)))
            except Exception as exc:
                result.errors.append(f"{board['company']} ({feed_url(board)}): {describe_error(exc)}")
                continue
            if not items:
                result.notes.append(f"{board['company']}: board has no open jobs")
            result.jobs.extend(parse_job(item, board) for item in items)
        return result


def parse_feed(xml_text: str) -> list[dict]:
    """Each <item> as its plain fields plus "locations": ["Dubai, United Arab Emirates", ...]."""
    items = []
    for node in ET.fromstring(_fix_entities(xml_text)).iter("item"):
        fields: dict = {"locations": []}
        for child in node:
            name = _local(child.tag)
            if name == "locations":
                for loc in child:
                    parts = {_local(p.tag): (p.text or "").strip() for p in loc}
                    place = ", ".join(v for v in (parts.get("city"), parts.get("country")) if v)
                    if place:
                        fields["locations"].append(place)
            else:
                fields.setdefault(name, (child.text or "").strip())
        items.append(fields)
    return items


def parse_job(item: dict, board: dict) -> Job:
    link = item.get("link") or ""
    locations = list(dict.fromkeys(item["locations"]))
    raw_status = (item.get("remoteStatus") or "").lower()
    return Job(
        source="teamtailor",
        source_job_id=item.get("guid") or link,
        source_url=link,
        company=board.get("company") or item.get("company_name") or "",
        title=(item.get("title") or "").strip(),
        description=html_to_text(item.get("description")),
        application_url=link or None,
        company_location=board.get("company_location"),
        location_raw=" / ".join(locations) or None,
        allowed_locations=locations,
        remote_status=_REMOTE_STATUS.get(raw_status) or normalize_workplace(raw_status),
        posted_at=parse_datetime(item.get("pubDate")),
    )


def from_config(section) -> TeamtailorSource | None:
    boards = enabled_entries(section)
    return TeamtailorSource(boards) if boards else None
