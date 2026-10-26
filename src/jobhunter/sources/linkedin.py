"""LinkedIn's public (logged-out) job search: the pages linkedin.com/jobs shows without an account.

GET /jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=&location=&f_TPR=r<seconds>&start=N
returns 10 job cards (title, company, location, posting day); GET /jobs-guest/jobs/api/jobPosting/<id>
returns one job's page with its full description. No key. Checked 2026-10-21 (docs/research):

- Logged out, only keywords, location and f_TPR (posted within N seconds) work. The remote (f_WT)
  and level (f_E) filters are ignored, so location=Worldwide gives on-site jobs from everywhere.
  Searches are by place: the UAE and Qatar (relocation), Lebanon, and the UK/NL with "visa
  sponsorship" in the keywords (the visa list).
- About one request a second gets HTTP 429, so every request waits `pause` seconds first. That
  makes this the slowest source (a few minutes a run), and it is never fetched twice in a run.
- LinkedIn's terms forbid automated access; the user chose to use it anyway (2026-10-21), at
  this low volume. Only titles with one of `queries` get their page fetched and are kept.
"""

from __future__ import annotations

import html
import re
import time

from ..models import UNKNOWN, Job
from ..text import html_to_text, normalize_words, parse_datetime, parse_relative_age, utcnow
from .base import Source, SourceResult, describe_error, enabled_entries, parse_each, section_enabled

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
POSTING = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
VIEW = "https://www.linkedin.com/jobs/view/{id}"
PAGE_SIZE = 10

_CARD = re.compile(r'data-entity-urn="urn:li:jobPosting:(\d+)"(.*?)</li>', re.S)
_CARD_TITLE = re.compile(r'base-search-card__title">(.*?)</h3>', re.S)
_CARD_COMPANY = re.compile(r'base-search-card__subtitle">(.*?)</h4>', re.S)
_CARD_LOCATION = re.compile(r'job-search-card__location">(.*?)</span>', re.S)
_CARD_DATE = re.compile(r'<time[^>]*datetime="([\d-]+)"')
_DESCRIPTION = re.compile(r'show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>', re.S)
_POSTED_AGO = re.compile(r'posted-time-ago__text[^>]*>(.*?)</span>', re.S)
_CRITERIA = re.compile(
    r'job-criteria-subheader">(.*?)</h3>\s*<span class="description__job-criteria-text[^>]*>(.*?)</span>', re.S)


def _text(pattern: re.Pattern, page: str) -> str:
    """The first match, tags dropped, entities decoded, spaces squeezed."""
    m = pattern.search(page)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).split()) if m else ""


class LinkedInSource(Source):
    name = "linkedin"
    refetch = False  # slow and rate-limited: a second pass would mostly get 429s

    def __init__(self, searches: list[dict], queries: list[str], hours: int = 24, max_pages: int = 5,
                 pause: float = 2.5):
        self.searches = searches
        self.queries = [normalize_words(q) for q in queries if normalize_words(q)]
        self.hours = hours
        self.max_pages = max_pages
        self.pause = pause

    def wanted(self, title: str) -> bool:
        words = f" {normalize_words(title)} "
        return not self.queries or any(f" {q} " in words for q in self.queries)

    def _get(self, http, url: str, params: dict | None = None) -> str:
        if self.pause:
            time.sleep(self.pause)
        return http.get_text(url, params)

    def fetch(self, http) -> SourceResult:
        result = SourceResult(self.name)
        now = utcnow()
        seconds = int(((now - self.since).total_seconds() if self.since else self.hours * 3600))
        cards: dict[str, dict] = {}
        for search in self.searches:
            label = f'"{search["keywords"]}" in {search["location"]}'
            for page in range(int(search.get("max_pages", self.max_pages))):
                params = {"keywords": search["keywords"], "location": search["location"],
                          "f_TPR": f"r{seconds}", "start": page * PAGE_SIZE}
                try:
                    found = parse_cards(self._get(http, SEARCH, params))
                except Exception as exc:
                    result.errors.append(f"{label} page {page + 1}: {describe_error(exc)}")
                    break
                for card in found:
                    if self.wanted(card["title"]):
                        cards.setdefault(card["id"], card)
                if len(found) < PAGE_SIZE:
                    break
        result.jobs += parse_each(list(cards.values()), lambda card: self._job(http, card, now, result.errors),
                                  result.errors)
        return result

    def _job(self, http, card: dict, now, errors: list[str]) -> Job:
        """A card plus its job page. When the page fails, the card alone is kept."""
        try:
            page = self._get(http, POSTING.format(id=card["id"]))
        except Exception as exc:
            errors.append(f"job {card['id']}: {describe_error(exc)}")
            page = ""
        return parse_job(card, page, now)


def parse_cards(page: str) -> list[dict]:
    cards = []
    for job_id, body in _CARD.findall(page):
        date = _CARD_DATE.search(body)
        cards.append({
            "id": job_id,
            "title": _text(_CARD_TITLE, body),
            "company": _text(_CARD_COMPANY, body),
            "location": _text(_CARD_LOCATION, body),
            "date": date.group(1) if date else None,
        })
    return cards


def parse_job(card: dict, page: str, now) -> Job:
    """A card plus its job page. Without the page (it failed) the job keeps an empty description."""
    m = _DESCRIPTION.search(page)
    description = html_to_text(m.group(1)) if m else ""
    criteria = {" ".join(html.unescape(k).split()): " ".join(html.unescape(v).split())
                for k, v in _CRITERIA.findall(page)}
    # The card gives only the day; the page says "3 hours ago", which is closer.
    posted = parse_relative_age(_text(_POSTED_AGO, page), now) or parse_datetime(card.get("date"))
    url = VIEW.format(id=card["id"])
    return Job(
        source="linkedin",
        source_job_id=card["id"],
        source_url=url,
        company=card.get("company") or "",
        title=card.get("title") or "",
        description=description,
        application_url=url,
        location_raw=card.get("location") or None,
        remote_status=UNKNOWN,
        employment_type=criteria.get("Employment type"),
        tags=[v for k, v in criteria.items() if k == "Seniority level"],
        posted_at=posted,
    )


def from_config(section) -> LinkedInSource | None:
    if not section_enabled(section):
        return None
    searches = [s for s in enabled_entries(section.get("searches")) if s.get("keywords") and s.get("location")]
    if not searches:
        return None
    return LinkedInSource(searches, section.get("queries") or [], int(section.get("hours", 24)),
                          int(section.get("max_pages", 5)), float(section.get("pause", 2.5)))
