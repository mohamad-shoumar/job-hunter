"""Board discovery: visa job sites that point to company boards the daily run doesn't read yet.

EuropeVisaJobs (an open feed, CC BY 4.0, which asks for about one request a second) and The Stack
(a keyless public search) list visa and relocation jobs across Europe. Neither is a job source here:
EuropeVisaJobs gives no posting text, only its own visa quote, and The Stack rewrites each posting
and marks every job as sponsoring. Stored as jobs, their words would put jobs on the visa list on a
third party's say-so, with no language check. So they are used to find companies instead: a listing
with a target-role title in a visa-list country links to the employer's own posting, and when that
link names a Greenhouse, Lever or Ashby board the daily run doesn't fetch yet, the board is added to
`watched_boards`, the reason naming the site and the listing (at most `max_new_per_run` a run, so a
first run spreads its load). The two sites' listings are taken in turn, so they share that limit:
read one after the other, EuropeVisaJobs' 1,400 listings filled it before The Stack's were looked at
(2026-11-15: 15 boards of 15 from EuropeVisaJobs). Each run counts every site's listings, target
titles and boards (`by_site`), so a site that quietly returns nothing shows as 0. From the next run
the board's real postings are read and judged by the usual rules, like any watched board (boards.py).

A link on the company's own site that only carries a Greenhouse job id (`?gh_jid=`) names no board:
slugs made from the company name are tried, and a board is kept only when it lists the same title
(`boards.check_board`), within the watch_boards probe limit; a company with no match is not tried
again for `retry_after_days`. Links to Workday, SuccessFactors, Personio and other boards the app
can't read are counted, not followed. Blocked companies, agencies, job sites and boards you removed
are never added.

Only The Stack's keyless search is used: no sign-in, no CV, no email. Its replies also carry a
`next_step` text addressed to AI assistants; it is never read. Settings: the "discover_boards"
section of config/sources.json; without it nothing runs. `jobhunter discover --dry-run` shows what a
run would add.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .boards import (
    CONFIG_SECTIONS, WatchConfig, board_from_links, check_board, configured_boards, never_watch, slug_guesses,
)
from .config import Filters, OutreachConfig
from .identity import company_key
from .relevance import check_title
from .sources.base import describe_error
from .store import JobStore
from .store.companies import job_board_keys
from .store.watched import add_watched_board, board_probes, record_probe, watched_boards
from .text import parse_datetime

log = logging.getLogger(__name__)

EUROPEVISAJOBS_FEED = "https://europevisajobs.com/feed.json"
THE_STACK = "https://mcp.trythestack.co"
# search_jobs takes 1-25 a page (its tool schema and developers/api.md); it gives `next_offset` for the next page.
STACK_PAGE = 25

# The visa list's country codes as each site writes them. The Stack takes English country names.
_EVJ_CODES = {"uk": "GB"}
_STACK_NAMES = {"nl": "Netherlands", "de": "Germany", "fi": "Finland", "uk": "United Kingdom", "ie": "Ireland",
                "es": "Spain", "it": "Italy"}
_GH_JID = re.compile(r"[?&]gh_jid=\d+", re.I)
_UNREADABLE = [(kind, re.compile(pattern, re.I)) for kind, pattern in (
    ("workday", r"myworkdayjobs\.com|workday\.com"), ("successfactors", r"successfactors|sapsf"),
    ("personio", r"personio\."), ("join", r"\bjoin\.com"), ("recruitee", r"recruitee\.com"),
    ("workable", r"workable\.com"), ("smartrecruiters", r"smartrecruiters\.com"), ("teamtailor", r"teamtailor\.com"),
    ("lever (EU)", r"jobs\.eu\.lever\.co"), ("job site", r"arbeitnow\.|linkedin\.com|indeed\."))]


@dataclass
class DiscoverConfig:
    """The "discover_boards" section of config/sources.json."""

    enabled: bool = False
    europevisajobs: bool = True
    the_stack: bool = True
    the_stack_days: int = 7  # The Stack's listings posted in the last N days
    max_stack_pages: int = 5  # STACK_PAGE (25) listings a page, per country
    max_new_per_run: int = 15  # boards added in one run; the rest follow on the next runs

    @classmethod
    def from_sources(cls, sources_config: dict) -> DiscoverConfig:
        section = sources_config.get("discover_boards")
        if not isinstance(section, dict):
            return cls()
        return cls(enabled=bool(section.get("enabled", True)),
                   europevisajobs=bool(section.get("europevisajobs", True)),
                   the_stack=bool(section.get("the_stack", True)),
                   the_stack_days=int(section.get("the_stack_days", 7)),
                   max_stack_pages=int(section.get("max_stack_pages", 5)),
                   max_new_per_run=int(section.get("max_new_per_run", 15)))


@dataclass
class Listing:
    site: str
    company: str
    title: str
    country: str  # the visa list's name for it
    url: str  # the employer's application link, as the site gives it


@dataclass
class DiscoverRun:
    listed: int = 0  # listings in a visa-list country
    wanted: int = 0  # of those, target-role titles
    added: list[dict] = field(default_factory=list)
    probed: int = 0
    unreadable: Counter = field(default_factory=Counter)  # wanted listings on boards the app can't read, by kind
    # Per site read this run: {"listed": n, "wanted": n, "added": n}. A site that failed or found nothing shows 0.
    by_site: dict[str, dict[str, int]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"listed": self.listed, "wanted": self.wanted, "added": self.added, "probed": self.probed,
                "unreadable": dict(self.unreadable), "by_site": self.by_site, "notes": self.notes,
                "errors": self.errors}



def site_line(by_site: dict[str, dict[str, int]]) -> str:
    """'EuropeVisaJobs 1,343 listed, 300 target, 8 boards; The Stack 120 listed, 66 target, 7 boards'."""
    return "; ".join(f"{site} {n['listed']:,} listed, {n['wanted']:,} target, {n['added']} boards"
                     for site, n in by_site.items())


def _site(run: DiscoverRun, site: str, listed: int) -> None:
    run.by_site[site] = {"listed": listed, "wanted": 0, "added": 0}


def in_turn(found: list[Listing]) -> list[Listing]:
    """The sites' listings taken one each in turn, each site keeping its own order."""
    queues: dict[str, list[Listing]] = {}
    for listing in found:
        queues.setdefault(listing.site, []).append(listing)
    longest = max((len(q) for q in queues.values()), default=0)
    return [q[i] for i in range(longest) for q in queues.values() if i < len(q)]


def europevisajobs(http, countries: dict[str, str]) -> list[Listing]:
    """`countries`: EuropeVisaJobs' country code -> the visa list's country name. One request: the whole feed."""
    data = http.get_json(EUROPEVISAJOBS_FEED) or {}
    out = []
    for job in data.get("jobs") or []:
        country = countries.get((job.get("country_code") or "").upper())
        if country:
            out.append(Listing("EuropeVisaJobs", job.get("company") or "", job.get("title") or "", country,
                               job.get("apply_url") or ""))
    return out


def the_stack(http, countries: dict[str, str], days: int, max_pages: int = 5) -> list[Listing]:
    """`countries`: The Stack's English country name -> the visa list's name. Reads only each reply's jobs."""
    out = []
    for name, country in countries.items():
        offset = 0
        for _ in range(max_pages):
            arguments = {"country": name, "posted_within_days": days, "limit": STACK_PAGE, "offset": offset}
            body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "search_jobs", "arguments": arguments}}
            reply = http.post_json(THE_STACK, body, headers={"Accept": "application/json, text/event-stream"}) or {}
            found = (reply.get("result") or {}).get("structuredContent") or {}
            out += [Listing("The Stack", job.get("company") or "", job.get("title") or "", country,
                            job.get("apply_url") or "") for job in found.get("jobs") or []]
            offset = found.get("next_offset")
            if not offset:
                break
    return out


def unreadable_kind(url: str) -> str:
    for kind, pattern in _UNREADABLE:
        if pattern.search(url or ""):
            return kind
    return "company site" if url else "no link"


def listings(http, filters: Filters, config: DiscoverConfig, run: DiscoverRun) -> list[Listing]:
    countries = filters.visa.countries if filters.visa else []
    found: list[Listing] = []
    if config.europevisajobs:
        codes = {_EVJ_CODES.get(c.code, c.code.upper()): c.name for c in countries}
        site: list[Listing] = []
        try:
            site = europevisajobs(http, codes)
        except Exception as exc:  # one site down must not stop the other
            run.errors.append(f"EuropeVisaJobs: {describe_error(exc)}")
        _site(run, "EuropeVisaJobs", len(site))
        found += site
    if config.the_stack:
        names = {_STACK_NAMES[c.code]: c.name for c in countries if c.code in _STACK_NAMES}
        site = []
        try:
            site = the_stack(http, names, config.the_stack_days, config.max_stack_pages)
        except Exception as exc:
            run.errors.append(f"The Stack: {describe_error(exc)}")
        _site(run, "The Stack", len(site))
        found += site
    return found


def discover(store: JobStore, http, sources_config: dict, filters: Filters, outreach: OutreachConfig,
             now: datetime, config: DiscoverConfig | None = None, watch: WatchConfig | None = None,
             dry_run: bool = False) -> DiscoverRun:
    """Watch the boards the two sites point to. `dry_run` reports what would be added and writes nothing."""
    config = config or DiscoverConfig.from_sources(sources_config)
    watch = watch or WatchConfig.from_sources(sources_config)
    run = DiscoverRun()
    if not filters.visa:
        run.notes.append("no visa_list countries in config/filters.json: nothing to look for")
        return run
    found = in_turn(listings(http, filters, config, run))
    run.listed = len(found)
    configured = configured_boards(sources_config)
    rows = watched_boards(store, include_removed=True)
    known = {f"{r['kind']}:{r['slug'].lower()}" for r in rows}
    # A company that already has a board, watched or in config/sources.json, needs no guess.
    watched_companies = {r["company_key"] for r in rows} | {
        company_key(entry.get("company") or "") for section in CONFIG_SECTIONS.values()
        for entry in sources_config.get(section) or [] if isinstance(entry, dict)}
    job_boards = job_board_keys(store)
    retry_before = now - timedelta(days=watch.retry_after_days)
    probes = {r["company_key"]: parse_datetime(r["probed_at"]) for r in board_probes(store)}
    guessed: set[str] = set()
    for listing in found:
        if not check_title(listing.title, filters)[0]:
            continue
        run.wanted += 1
        run.by_site[listing.site]["wanted"] += 1
        key = company_key(listing.company)
        if never_watch(key, filters, outreach, job_boards) or filters.agencies.check(listing.company, ""):
            continue
        if len(run.added) >= config.max_new_per_run:
            if not any(n.startswith("board limit") for n in run.notes):
                run.notes.append(f"board limit ({config.max_new_per_run}) reached; the rest are added on the next runs")
            continue
        what = f'{listing.site} lists "{listing.title.strip()}" ({listing.country})'
        linked = board_from_links([listing.url])
        if linked:
            kind, slug, url = linked
            reason = f"{what} with a link to its posting there: {url}"
        elif _GH_JID.search(listing.url):
            if key in guessed or key in watched_companies:
                continue
            guessed.add(key)
            last = probes.get(key)
            if last and last > retry_before:
                continue
            if run.probed >= watch.max_probes_per_run:
                if "probe limit reached" not in " ".join(run.notes):
                    run.notes.append("probe limit reached; the other companies wait for the next run")
                continue
            hit = None
            for slug in slug_guesses(listing.company):
                run.probed += 1
                why = check_board(http, "greenhouse", slug, listing.company, listing.title, whose="the same title")
                if why:
                    hit = slug, why
                    break
            if hit is None:
                if not dry_run:
                    record_probe(store, key, now, f"no board found for {what}")
                continue
            kind, (slug, why) = "greenhouse", hit
            reason = f"{what}; {why}"
        else:
            run.unreadable[unreadable_kind(listing.url)] += 1
            continue
        name = f"{kind}:{slug}".lower()
        if name in configured or name in known:
            continue  # already fetched, or a board you removed
        if not dry_run:
            add_watched_board(store, kind, slug, listing.company, key, None, reason, now)
        known.add(name)
        run.added.append({"board": f"{kind}:{slug}", "company": listing.company, "reason": reason})
        run.by_site[listing.site]["added"] += 1
    if not dry_run:
        store.commit()
    return run
