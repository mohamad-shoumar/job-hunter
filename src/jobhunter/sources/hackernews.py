"""Hacker News "Ask HN: Who is hiring?" - the latest monthly thread, via the Algolia API.

Top-level comments follow a loose convention on their first line:
"Company | Role(s) | Location | REMOTE | Salary | URL". This adapter reads that
line; a comment that does not follow it (no "|") is skipped. A comment that
lists several roles becomes one job per role, so each title is judged alone.
"""

from __future__ import annotations

import html
import re

from ..extract import extract_salary
from ..geo import UNKNOWN as PLACE_UNKNOWN
from ..geo import classify_place
from ..identity import ats_key_from_url
from ..models import HYBRID, ONSITE, REMOTE, UNKNOWN, Job
from ..text import html_to_text, parse_datetime
from .base import Source, SourceResult, describe_error, section_enabled

SEARCH = "https://hn.algolia.com/api/v1/search_by_date"
ITEM = "https://hn.algolia.com/api/v1/items/{id}"

_ROLE_WORDS = re.compile(
    r"\b(?:engineers?|developers?|programmers?|scientists?|architects?|leads?|managers?|designers?|sre|devops|"
    r"analysts?|researchers?|cto|founding|head of|swe|interns?|specialists?)\b",
    re.I,
)
_LOCATION_WORDS = re.compile(r"\b(?:remote|onsite|on-site|on site|hybrid|in[- ]office|anywhere|worldwide|global)\b", re.I)
_ONSITE_WORDS = re.compile(r"\b(?:onsite|on-site|on site|in[- ]office|in person)\b", re.I)
_ROLE_LIST_SPLIT = re.compile(r"\s*[,;]\s*|\s+/\s+|\s+&\s+|\s+and\s+", re.I)


class HackerNewsSource(Source):
    name = "hackernews"

    def __init__(self, limit: int = 400):
        self.limit = limit

    def _threads(self, hits: list[dict]) -> list[dict]:
        """The latest thread; with `since`, every monthly thread that overlaps the range."""
        threads = [h for h in hits if (h.get("title") or "").lower().startswith("ask hn: who is hiring")]
        threads.sort(key=lambda h: h.get("created_at") or "", reverse=True)
        if not threads or self.since is None:
            return threads[:1]
        month_start = self.since.replace(day=1, hour=0, minute=0, second=0).isoformat()[:10]
        # A thread opens on the 1st; the one opened in the range's first month covers its start.
        return [t for t in threads if (t.get("created_at") or "")[:10] >= month_start] or threads[:1]

    def fetch(self, http) -> SourceResult:
        result = SourceResult(self.name)
        try:
            hits = http.get_json(SEARCH, params={"tags": "story,author_whoishiring", "hitsPerPage": 12}).get("hits") or []
        except Exception as exc:
            result.errors.append(describe_error(exc))
            return result
        threads = self._threads(hits)
        if not threads:
            result.errors.append("no 'Who is hiring?' thread found")
            return result
        skipped = 0
        for story in threads:
            try:
                thread = http.get_json(ITEM.format(id=story["objectID"]))
            except Exception as exc:
                result.errors.append(f"{story.get('title')}: {describe_error(exc)}")
                continue
            result.notes.append(f"thread: {story.get('title')}")
            for comment in (thread.get("children") or [])[: self.limit]:
                if not comment.get("text"):
                    continue
                jobs = parse_comment(comment)
                skipped += not jobs
                result.jobs.extend(jobs)
        if skipped:
            result.notes.append(f"{skipped} comments skipped (no 'Company | Role | ...' first line)")
        return result


_PART_REMOTE = re.compile(r"\b(?:part(?:ly|ially)?[- ]remote|remote days?|days? remote|hybrid)\b", re.I)


def _remote_status(first_line: str, body: str) -> str:
    low = first_line.lower()
    # "ONSITE (part remote)" is hybrid; "REMOTE or ONSITE" is remote.
    if _PART_REMOTE.search(low) and not re.search(r"\bremote\b(?!\s*days?)", _PART_REMOTE.sub(" ", low)):
        return HYBRID
    if "remote" in low:
        return REMOTE
    if _ONSITE_WORDS.search(low):
        return ONSITE
    # Posts that never mention remote work are onsite roles.
    return UNKNOWN if "remote" in body.lower() else ONSITE


def parse_comment(comment: dict) -> list[Job]:
    text_html = comment["text"]
    first_line = html_to_text(re.split(r"<p>", text_html, maxsplit=1)[0])
    segments = [s.strip() for s in first_line.split("|") if s.strip()]
    if len(segments) < 2:
        return []
    body = html_to_text(text_html)
    company = re.sub(r"\s*\(?https?://\S+\)?", "", segments[0]).strip(" -:,") or segments[0]
    role_index = next((i for i, s in enumerate(segments[1:], 1) if _ROLE_WORDS.search(s)), 1)
    roles_text = segments[role_index]
    others = [s for i, s in enumerate(segments) if i not in (0, role_index)]
    location_parts = [s for s in others if _LOCATION_WORDS.search(s) or classify_place(s).kind != PLACE_UNKNOWN]
    location = " | ".join(location_parts)

    roles = [r for r in _ROLE_LIST_SPLIT.split(roles_text) if r.strip()]
    role_like = [r.strip() for r in roles if _ROLE_WORDS.search(r)]
    titles = role_like[:8] if len(role_like) >= 2 else [roles_text]

    links = [html.unescape(u) for u in re.findall(r'href="([^"]+)"', text_html)]
    application_url = next((u for u in links if ats_key_from_url(u)), links[0] if links else None)
    salary = extract_salary(first_line) or {}
    comment_id = str(comment["id"])
    url = f"https://news.ycombinator.com/item?id={comment_id}"
    return [
        Job(
            source="hackernews",
            source_job_id=comment_id if len(titles) == 1 else f"{comment_id}-{i}",
            source_url=url,
            company=company,
            title=title,
            description=body,
            application_url=application_url or url,
            location_raw=location or None,
            allowed_locations=location_parts,
            remote_status=_remote_status(first_line, body),
            posted_at=parse_datetime(comment.get("created_at")),
            **salary,
        )
        for i, title in enumerate(titles)
    ]


def from_config(section) -> HackerNewsSource | None:
    if not section_enabled(section):
        return None
    return HackerNewsSource(int(section.get("limit", 400)))
