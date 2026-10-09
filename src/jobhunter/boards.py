"""Watched boards: the public job board of every company that gets a shortlisted job.

A shortlisted job means the company has shown it can hire from Lebanon, so
its other openings are worth reading at the source: earlier than a job site
reposts them, and with the board's own location line. After each run, code
looks for that company's Greenhouse, Lever or Ashby board and, when it finds
one, adds it to the `watched_boards` table; from the next run on it is
fetched like a board in config/sources.json.

How a board is found, with the evidence kept as `reason`:

1. The job's own links: a link to jobs.ashbyhq.com/<slug>/..., jobs.lever.co/<slug>/...
   or job-boards.greenhouse.io/<slug>/jobs/... names the board.
2. Otherwise a guess: slugs made from the company name (and its domain, when
   outreach found one) are tried on the three public APIs. A guessed board is
   taken only when it lists the shortlisted job's title, or (Greenhouse) names
   the same company, so a generic slug that belongs to someone else is not.

Job sites, agencies (skip_companies in config/outreach.json, companies marked
as a job board in the app) and blocked companies are never watched. A company
whose guess found nothing is tried again after `retry_after_days`. A board you
remove (`jobhunter boards --remove kind:slug`) stays removed. The settings are
the "watch_boards" section of config/sources.json; without it nothing is watched.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from .config import Filters, OutreachConfig
from .identity import company_key, title_key
from .models import SHORTLISTED
from .sources import ashby, greenhouse, lever
from .sources.base import Source
from .store import JobStore
from .text import iso, parse_datetime

log = logging.getLogger(__name__)

KINDS = ("greenhouse", "lever", "ashby")
APIS = {"greenhouse": greenhouse.API, "lever": lever.API, "ashby": ashby.API}
SOURCE_CLASSES = {"greenhouse": greenhouse.GreenhouseSource, "lever": lever.LeverSource, "ashby": ashby.AshbySource}
CONFIG_SECTIONS = {"greenhouse": "greenhouse_boards", "lever": "lever_boards", "ashby": "ashby_boards"}

_BOARD_LINKS = [
    (re.compile(r"(?:job-boards|boards)\.greenhouse\.io/(?!embed/)([\w-]+)/jobs/\d+", re.I), "greenhouse"),
    (re.compile(r"greenhouse\.io/embed/job_board\?(?:[^#]*&)?for=([\w-]+)", re.I), "greenhouse"),
    (re.compile(r"//jobs\.lever\.co/([\w.-]+)/[0-9a-f]{8}-", re.I), "lever"),  # jobs.eu.lever.co has another API
    (re.compile(r"jobs\.ashbyhq\.com/([^/?#\s]+)/[0-9a-f]{8}-", re.I), "ashby"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS watched_boards (
    kind TEXT NOT NULL,
    slug TEXT NOT NULL,
    company TEXT NOT NULL,
    company_key TEXT NOT NULL,
    from_job_id INTEGER,
    reason TEXT NOT NULL,
    added_at TEXT NOT NULL,
    removed_at TEXT,
    PRIMARY KEY (kind, slug)
);
CREATE INDEX IF NOT EXISTS watched_boards_company ON watched_boards (company_key);

-- Companies whose board was guessed and not found, so they are not tried every day.
CREATE TABLE IF NOT EXISTS board_probes (
    company_key TEXT PRIMARY KEY,
    probed_at TEXT NOT NULL,
    note TEXT
);
"""


@dataclass
class WatchConfig:
    """The "watch_boards" section of config/sources.json."""

    enabled: bool = False
    max_probes_per_run: int = 10
    retry_after_days: int = 30

    @classmethod
    def from_sources(cls, sources_config: dict) -> WatchConfig:
        section = sources_config.get("watch_boards")
        if not isinstance(section, dict):
            return cls()
        return cls(enabled=bool(section.get("enabled", True)),
                   max_probes_per_run=int(section.get("max_probes_per_run", 10)),
                   retry_after_days=int(section.get("retry_after_days", 30)))


@dataclass
class Board:
    kind: str
    slug: str
    company: str
    reason: str
    from_job_id: int | None = None

    @property
    def name(self) -> str:
        return f"{self.kind}:{self.slug}"


@dataclass
class WatchRun:
    added: list[dict] = field(default_factory=list)
    probed: int = 0
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def ensure_schema(store: JobStore) -> None:
    store.conn.executescript(SCHEMA)


def board_from_links(urls) -> tuple[str, str, str] | None:
    """(kind, slug, url) of the first link that names a public board."""
    for url in urls:
        for pattern, kind in _BOARD_LINKS:
            m = pattern.search(url or "")
            if m:
                return kind, m.group(1), url
    return None


def slug_guesses(company: str, domain: str | None = None) -> list[str]:
    """'Dual Entry Inc.' -> ['dualentry', 'dual-entry']; a domain adds its first label."""
    words = company_key(company).split()
    guesses = ["".join(words), "-".join(words)]
    if domain:
        guesses.append(domain.lower().removeprefix("www.").split(".")[0])
    return [g for g in dict.fromkeys(guesses) if len(g) >= 3]


def _postings(kind: str, data) -> list[dict]:
    if kind == "lever":
        return data if isinstance(data, list) else []
    jobs = (data or {}).get("jobs") if isinstance(data, dict) else None
    return [j for j in jobs or [] if j.get("isListed", True)]


def _posting_title(kind: str, posting: dict) -> str:
    return (posting.get("text") if kind == "lever" else posting.get("title")) or ""


def check_board(http, kind: str, slug: str, company: str, title: str) -> str | None:
    """Why this board is the company's (quotable), or None. Network errors and 404s count as no board."""
    try:
        data = http.get_json(APIS[kind].format(token=slug), params={"mode": "json"} if kind == "lever" else None)
    except Exception:
        return None
    postings = _postings(kind, data)
    wanted = title_key(title)
    for posting in postings:
        if wanted and title_key(_posting_title(kind, posting)) == wanted:
            return f'{kind}:{slug} lists "{_posting_title(kind, posting).strip()}", the shortlisted job\'s title'
    if kind == "greenhouse":
        for posting in postings:
            name = posting.get("company_name") or ""
            if name and company_key(name) == company_key(company):
                return f'{kind}:{slug} names the company "{name}"'
    return None


def find_board(http, job, domain: str | None = None, urls=()) -> tuple[Board | None, bool]:
    """(the board, whether the APIs were probed). Links first; a guess only when no link names one."""
    linked = board_from_links([job["application_url"], job["source_url"], *urls])
    if linked:
        kind, slug, url = linked
        return Board(kind, slug, job["company"], f"job #{job['id']} links to its posting there: {url}", job["id"]), False
    for slug in slug_guesses(job["company"], domain):
        for kind in KINDS:
            reason = check_board(http, kind, slug, job["company"], job["title"])
            if reason:
                return Board(kind, slug, job["company"], f"{reason} (job #{job['id']})", job["id"]), True
    return None, True


def configured_boards(sources_config: dict) -> set[str]:
    """'kind:slug' (lowercase) of every board config/sources.json lists, enabled or not."""
    found = set()
    for kind, section in CONFIG_SECTIONS.items():
        for entry in sources_config.get(section) or []:
            if isinstance(entry, dict) and entry.get("board_token"):
                found.add(f"{kind}:{entry['board_token'].lower()}")
    return found


def watched(store: JobStore, include_removed: bool = False) -> list:
    ensure_schema(store)
    where = "" if include_removed else " WHERE removed_at IS NULL"
    return store.conn.execute(f"SELECT * FROM watched_boards{where} ORDER BY added_at, kind, slug").fetchall()


def add_watched_sources(sources: list[Source], store: JobStore, sources_config: dict) -> int:
    """Add the watched boards to the matching config source (or a new one). Returns how many were added."""
    configured = configured_boards(sources_config)
    by_name = {s.name: s for s in sources}
    added = 0
    for row in watched(store):
        if f"{row['kind']}:{row['slug'].lower()}" in configured:
            continue
        entry = {"company": row["company"], "board_token": row["slug"]}
        source = by_name.get(row["kind"])
        if source is None:
            source = by_name[row["kind"]] = SOURCE_CLASSES[row["kind"]]([])
            sources.append(source)
        source.boards.append(entry)
        added += 1
    return added


def _never_watch(key: str, filters: Filters, outreach: OutreachConfig, job_boards: set[str]) -> bool:
    return (not key or key in filters.blocked_companies or key in job_boards
            or any(company_key(s) == key for s in outreach.skip_companies))


def watch_shortlisted(store: JobStore, http, sources_config: dict, filters: Filters, outreach: OutreachConfig,
                      now: datetime, config: WatchConfig | None = None) -> WatchRun:
    """Look for the board of each shortlisted job's company that has none yet (newest jobs first)."""
    config = config or WatchConfig.from_sources(sources_config)
    run = WatchRun()
    ensure_schema(store)
    configured = configured_boards(sources_config)
    known = {r["company_key"] for r in watched(store, include_removed=True)}
    known_boards = {f"{r['kind']}:{r['slug'].lower()}" for r in watched(store, include_removed=True)}
    job_boards = {r["key"] for r in store.conn.execute("SELECT key FROM companies WHERE is_job_board = 1")}
    domains = {r["key"]: r["domain"] for r in store.conn.execute("SELECT key, domain FROM companies")}
    retry_before = now - timedelta(days=config.retry_after_days)
    probes = {r["company_key"]: parse_datetime(r["probed_at"])
              for r in store.conn.execute("SELECT * FROM board_probes")}
    rows = store.conn.execute("SELECT * FROM jobs WHERE status = ? ORDER BY id DESC", (SHORTLISTED,)).fetchall()
    done: set[str] = set()
    for job in rows:
        key = company_key(re.sub(r"https?://\S+", " ", job["company"] or ""))
        if key in done or key in known or _never_watch(key, filters, outreach, job_boards):
            continue
        done.add(key)
        sightings = [s["source_url"] for s in store.sightings_for([job["id"]])[job["id"]]]
        linked = board_from_links([job["application_url"], job["source_url"], *sightings])
        if not linked:
            last = probes.get(key)
            if last and last > retry_before:
                continue
            if run.probed >= config.max_probes_per_run:
                run.notes.append("probe limit reached; the other companies wait for the next run")
                break
        try:
            board, probed = find_board(http, job, domains.get(key), sightings)
        except Exception as exc:  # one company must not stop the rest
            log.exception("board lookup failed for %s", job["company"])
            run.errors.append(f"{job['company']}: {type(exc).__name__}: {exc}")
            continue
        run.probed += probed
        if board is None:
            store.conn.execute(
                "INSERT INTO board_probes (company_key, probed_at, note) VALUES (?, ?, ?) "
                "ON CONFLICT (company_key) DO UPDATE SET probed_at = excluded.probed_at, note = excluded.note",
                (key, iso(now), f"no board found for job #{job['id']}"))
            continue
        if board.name.lower() in configured or board.name.lower() in known_boards:
            continue  # already fetched from config/sources.json, or one you removed
        store.conn.execute(
            "INSERT INTO watched_boards (kind, slug, company, company_key, from_job_id, reason, added_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (board.kind, board.slug, board.company, key, board.from_job_id, board.reason, iso(now)))
        known_boards.add(board.name.lower())
        run.added.append({"board": board.name, "company": board.company, "reason": board.reason})
    store.commit()
    return run


def remove(store: JobStore, name: str, now: datetime) -> bool:
    """Stop watching 'kind:slug'. The row stays (removed), so the board is never added again."""
    ensure_schema(store)
    kind, _, slug = name.partition(":")
    cur = store.conn.execute(
        "UPDATE watched_boards SET removed_at = ? WHERE kind = ? AND lower(slug) = lower(?) AND removed_at IS NULL",
        (iso(now), kind.strip().lower(), slug.strip()))
    store.commit()
    return cur.rowcount > 0
