"""Hacker News "Ask HN: Who is hiring?" - the latest monthly thread, via the Algolia API.

Top-level comments follow a loose convention on their first line:
"Company | Role(s) | Location | REMOTE | Salary | URL". This adapter reads that
line; a comment that does not follow it (no "|") is skipped. A comment that
lists several roles becomes one job per role, so each title is judged alone.

The fields come in any order, so the role is the first field that names one
("Backend Engineer"), never a place, a URL or "Full-time". When no field does
("Acme | Remote | Full-time", "Acme | Multiple Roles | NYC"), the roles are read
from the body: a list of roles ("- Backend Engineer - US", "Software Engineer —
build the ..."), else role names in a hiring sentence ("looking for Rust
developers / Backend Engineers"). A place after a listed role ("- US") becomes
that job's location.
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
    r"analysts?|researchers?|cto|founding|head of|swe|interns?|specialists?|technical staff)\b",
    re.I,
)
_LOCATION_WORDS = re.compile(r"\b(?:remote|onsite|on-site|on site|hybrid|in[- ]office|anywhere|worldwide|global)\b", re.I)
_ONSITE_WORDS = re.compile(r"\b(?:onsite|on-site|on site|in[- ]office|in person)\b", re.I)
_ROLE_LIST_SPLIT = re.compile(r"\s*[,;]\s*|\s+/\s+|\s+&\s+|\s+and\s+", re.I)
MAX_ROLES = 12

# Header fields that are never the role.
_URL = re.compile(r"https?://|\bwww\.|^\S+\.(?:com|io|ai|co|net|org|dev|tech|app|xyz|inc|to|fm|so|cx|health)\b\S*$", re.I)
_EMPLOYMENT = re.compile(r"^\W*(?:full[- ]?time|part[- ]?time|ft|pt|contract|contractor|freelance|permanent|b2b|1099|w2)\b",
                         re.I)
_TIME_ZONE = re.compile(r"\b(?:utc|gmt|cet|cest|est|pst|[ecmp]t)\b|\btime ?zones?\b", re.I)
_MONEY = re.compile(r"[$€£]\s?\d|\d\s?(?:k|usd|eur|gbp|chf|cad)\b", re.I)

# Roles in the body: "- Rust Backend Engineers", "[2]Senior Engineer - US", "Software Engineer — build the ...".
_BULLET = re.compile(r"^\s*(?:[-*•·◦▪–]+|\[\d+\]|\d+[.)])\s*")
_ROLE_TAIL = re.compile(r"\s+[—–-]\s+|:\s+|\s+\|\s+")
_URL_IN_TEXT = re.compile(r"\(?\bhttps?://\S+\)?")
_NEXT_SENTENCE = re.compile(r"(?:(?<=[a-z]{3})|(?<=\)))\.\s+(?=[A-Z])")  # not after "Sr."
_MONEY_TAIL = re.compile(r"\s*\(?\s*[$€£]\s?\d.*$")
_NOT_A_ROLE_LINE = re.compile(
    r"^(?:we|we're|we’re|our|you|you'll|you’ll|i|i'm|i’m|if|the|this|these|please|apply|email|to|for|join|all|check|"
    r"learn|see|more|read|send|reach|happy|feel|note|and|a|an|in|at|about|looking|hiring|currently|contact|no)\b",
    re.I,
)
_HIRING_SENTENCE = re.compile(r"\b(?:hiring|looking for|seeking|searching for|need|join us as)\b", re.I)
_ROLE_PHRASE = re.compile(
    r"(?:(?:[A-Z][\w+#./-]*|(?i:senior|junior|mid-level|staff|lead|principal|founding|full[- ]?stack|back[- ]?end|"
    r"front[- ]?end|software|ai/ml|ai|ml|machine learning|data|platform|product|mobile|infrastructure|python|"
    r"applied|forward deployed))\s+){1,3}"
    r"(?i:engineers?|developers?|programmers?|scientists?|researchers?|designers?)\b(?!\s+[A-Z])"
)


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
    role_index = next((i for i, s in enumerate(segments[1:], 1) if _ROLE_WORDS.search(s) and not _URL.search(s)), None)
    others = [s for i, s in enumerate(segments) if i not in (0, role_index)]
    location_parts = [s for s in others if _is_place(s)]

    # (title, its own location or None), one per job.
    if role_index is not None:
        roles_text = segments[role_index]
        roles = [r for r in _ROLE_LIST_SPLIT.split(roles_text) if r.strip()]
        role_like = [r.strip() for r in roles if _ROLE_WORDS.search(r)]
        titles = [(t, None) for t in role_like[:MAX_ROLES]] if len(role_like) >= 2 else [(roles_text, None)]
    else:
        titles = _body_roles(body.split("\n")[1:]) or [(_fallback_title(segments), None)]

    links = [html.unescape(u) for u in re.findall(r'href="([^"]+)"', text_html)]
    application_url = next((u for u in links if ats_key_from_url(u)), links[0] if links else None)
    salary = extract_salary(first_line) or {}
    comment_id = str(comment["id"])
    url = f"https://news.ycombinator.com/item?id={comment_id}"
    jobs = []
    for i, (title, own_place) in enumerate(titles):
        places = [own_place] if own_place else location_parts
        jobs.append(Job(
            source="hackernews",
            source_job_id=comment_id if len(titles) == 1 else f"{comment_id}-{i}",
            source_url=url,
            company=company,
            title=title,
            description=body,
            application_url=application_url or url,
            location_raw=" | ".join(places) or None,
            allowed_locations=places,
            remote_status=_remote_status(first_line, body),
            posted_at=parse_datetime(comment.get("created_at")),
            **salary,
        ))
    return jobs


def _is_place(text: str) -> bool:
    return bool(_LOCATION_WORDS.search(text)) or classify_place(text).kind != PLACE_UNKNOWN


def _not_a_role(field: str) -> bool:
    """A header field that is a place, work mode, URL, contract type, time zone or salary."""
    return bool(_is_place(field) or _URL.search(field) or _EMPLOYMENT.search(field) or _TIME_ZONE.search(field)
                or _MONEY.search(field) or _ONSITE_WORDS.search(field))


def _fallback_title(segments: list[str]) -> str:
    """No role anywhere: an honest field ("Multiple Roles", "GenAI Tooling") rather than a place or URL."""
    plain = [s for s in segments[1:] if not _not_a_role(s)]
    return re.sub(r"\s*\(?https?://\S+\)?", "", plain[0]).strip() if plain else segments[1]


def _body_roles(lines: list[str]) -> list[tuple[str, str | None]]:
    """Roles listed in the body, each with the place written after it; else role names in a hiring sentence."""
    found: dict[str, tuple[str, str | None]] = {}
    for line in lines:
        bullet = _BULLET.match(line)
        text = _URL_IN_TEXT.sub("", line[bullet.end():] if bullet else line).strip()
        head, separator, tail = _split_once(text)
        head, tail = _clean_role(head), tail.strip(" :")
        if (not head or not _ROLE_WORDS.search(head) or len(head.split()) > 9 or head[-1] in ".!?,;"
                or _NOT_A_ROLE_LINE.match(head) or "@" in head):
            continue
        # A plain line is a role only when it is short or reads "Role — what you'd do", never a sentence.
        if not bullet and not (separator or len(text.split()) <= 9):
            continue
        place = tail if tail and len(tail.split()) <= 8 and _is_place(tail) else None
        found.setdefault(head.lower(), (head, place))
    if found:
        return list(found.values())[:MAX_ROLES]
    for sentence in re.split(r"(?<=[.!?:])\s+|\n", "\n".join(lines)):
        if _HIRING_SENTENCE.search(sentence):
            for match in _ROLE_PHRASE.finditer(sentence):
                role = match.group(0).strip()
                found.setdefault(role.lower(), (role, None))
    return list(found.values())[:MAX_ROLES]


def _clean_role(head: str) -> str:
    """'>> Product Engineer' -> 'Product Engineer'; drops a salary, a cut-off '(...' and a following sentence."""
    head = _NEXT_SENTENCE.split(head, maxsplit=1)[0]
    head = _MONEY_TAIL.sub("", head.strip().lstrip(">+*#~ ")).strip(" *")
    for opening, closing in ("()", "[]"):
        if head.count(opening) > head.count(closing):
            head = head[:head.rindex(opening)]
    return head.strip(" ,;:*-–—/")


def _split_once(text: str) -> tuple[str, str, str]:
    """'Senior Engineer — build X' -> ('Senior Engineer', '—', 'build X'); a dash inside a word stays."""
    match = _ROLE_TAIL.search(text)
    return (text[:match.start()], match.group(0), text[match.end():]) if match else (text, "", "")


def from_config(section) -> HackerNewsSource | None:
    if not section_enabled(section):
        return None
    return HackerNewsSource(int(section.get("limit", 400)))
