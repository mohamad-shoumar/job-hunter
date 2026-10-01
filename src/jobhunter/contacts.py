"""Who to email about a job, with proof: company size, the right person, their email.

Looked up once per company (tables `companies` and `contacts`), so a second
job at the same company costs nothing.

  1. Job boards and staffing agencies (skip list in config/outreach.json, or
     marked in the app) are skipped: nobody there hires for the role, so the
     job says "apply through the link".
  2. Domain: from the job's own links and description (the company's site,
     not an ATS or job board), else Hunter's free Domain Finder, but only when
     it returns a company with the same name.
  3. Hunter Email Count (free): does Hunter know anyone there at all?
  4. Size: Hunter Company Enrichment ("11-50").
  5. Who to target, in plain code: at most 50 people -> CEO/founder, then CTO;
     bigger -> head of engineering, engineering manager, recruiter, HR.
  6. People: Hunter Domain Search, filtered to those roles. Every email comes
     with the pages Hunter saw it on (the proof) and a verification status.
  7. Nobody found: Claude can search the web for the person (names count as
     confirmed only when the API's own search results show them), then Hunter
     Email Finder, else a pattern guess shown as "guessed".

Credits are measured from Hunter's free /account call before and after each
company, and the daily run spreads what is left over the days until the reset.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

from . import tracking
from .config import OutreachConfig
from .hunter import Account, Hunter, HunterError
from .identity import company_key
from .llm import Usage, error_line, find_quote, forced_tool_choice, pages_read, plain
from .store import JobStore
from .text import iso, parse_datetime, strip_accents

log = logging.getLogger(__name__)

ROLE_LABELS = {
    "ceo": "CEO", "founder": "Founder", "cto": "CTO", "eng_lead": "Head of engineering",
    "eng_manager": "Engineering manager", "recruiter": "Recruiter", "hr": "HR", "other": "Other",
}
# First match wins, so "Co-founder & CTO" is a CTO and "Founder & CEO" a CEO.
_ROLE_PATTERNS = [
    ("cto", r"\bcto\b|\bchief technology\b|\bchief technical\b"),
    ("ceo", r"\bceo\b|\bchief executive\b|\bmanaging director\b|^president\b"),
    ("founder", r"\bfounder\b"),  # "co-founder" too; not "owner" ("Product Owner")
    ("hr", r"\bhr\b|\bhuman resources\b|\bhead of people\b|\bchief people\b|\bpeople (?:ops|operations|partner|team)\b"),
    ("recruiter", r"\brecruit|\btalent\b|\bsourc(?:er|ing)\b"),
    ("eng_lead", r"\b(?:head|vp|vice president|director|svp|evp)\b[\w\s,&-]{0,20}?\b(?:engineering|technology|software|"
                 r"development|tech|r ?& ?d|platform)\b"),
    ("eng_manager", r"\b(?:engineering|software|development|backend|platform)\s+(?:team\s+)?manager\b"
                    r"|\bmanager,?\s+(?:of\s+)?(?:software\s+)?engineering\b|\b(?:tech|technical|engineering|team)\s+lead\b"),
]
_ROLE_RES = [(role, re.compile(pattern, re.I)) for role, pattern in _ROLE_PATTERNS]

# About what one company costs: size (0.2) + one domain search (1).
CREDITS_PER_COMPANY = 1.2
LOCK_MINUTES = 10

# Links that belong to job boards, ATSs and platforms, never to the employer.
_NOT_COMPANY = {
    "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "himalayas.app", "weworkremotely.com",
    "remoteok.com", "remoteok.io", "remotive.com", "linkedin.com", "indeed.com", "glassdoor.com", "google.com",
    "notion.site", "notion.so", "notion.com", "join.com", "bamboohr.com", "breezy.hr", "recruitee.com",
    "smartrecruiters.com", "jobvite.com", "teamtailor.com", "personio.de", "personio.com", "myworkdayjobs.com",
    "workday.com", "icims.com", "wellfound.com", "angel.co", "ycombinator.com", "workatastartup.com",
    "github.com", "gitlab.com", "youtube.com", "twitter.com", "x.com", "facebook.com", "instagram.com",
    "medium.com", "calendly.com", "forms.gle", "typeform.com", "bit.ly", "t.co", "crunchbase.com",
    "builtin.com", "dice.com", "ziprecruiter.com", "monster.com", "simplyhired.com", "jobleads.com",
    "learn4good.com", "tealhq.com", "jobmesh.io", "career.io", "remotejobs.org", "euremotejobs.com",
    "up2staff.com", "nodesk.co", "dedyn.io", "my-board.org", "hackernews.com", "algolia.com",
    "britishcouncil.org", "wikipedia.org", "apple.com", "microsoft.com", "amazon.com", "loom.com",
    "zoom.us", "slack.com", "discord.gg", "discord.com", "docs.google.com", "airtable.com", "gem.com",
    "rippling.com", "deel.com", "remote.com", "oysterhr.com", "pinpointhq.com", "jazzhr.com",
    "applytojob.com", "freshteam.com", "zohorecruit.com", "hire.lever.co", "keka.com", "trakstar.com",
}
_TWO_PART_TLDS = {"co.uk", "com.au", "co.il", "com.br", "co.jp", "co.nz", "co.za", "com.mx", "com.sg", "com.tr",
                  "co.in", "com.cn", "org.uk", "ac.uk", "com.lb", "com.ar", "co.kr"}
_WEBMAIL = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com", "proton.me",
            "protonmail.com", "aol.com", "live.com", "me.com", "gmx.com", "gmx.de", "mail.com", "yandex.com"}
_GENERIC_WORDS = {
    "labs", "lab", "group", "global", "software", "technologies", "technology", "tech", "digital", "solutions",
    "systems", "app", "apps", "the", "and", "studio", "studios", "media", "health", "capital", "partners",
    "consulting", "services", "mobility", "school", "online", "data", "cloud", "network", "ventures", "team",
    "remote", "jobs", "careers", "company", "international", "operations", "limited", "holdings", "platform",
}
_URL_RE = re.compile(r"https?://[^\s)\]>\"'<,]+|\bwww\.[a-z0-9.-]+\.[a-z]{2,}[^\s)\]>\"'<,]*", re.I)


# --- plain rules --------------------------------------------------------------


def role_of(position: str | None) -> str:
    text = strip_accents(position or "").lower()
    for role, pattern in _ROLE_RES:
        if pattern.search(text):
            return role
    return "other"


def size_upper_bound(size_range: str | None, size_count: int | None = None) -> int | None:
    """The top of Hunter's size range: "11-50" -> 50, "10K+" -> 10000. An exact count wins."""
    if size_count:
        return int(size_count)
    numbers = []
    for value, k in re.findall(r"(\d+(?:\.\d+)?)\s*([kK])?", size_range or ""):
        numbers.append(int(float(value) * (1000 if k else 1)))
    return max(numbers) if numbers else None


def targets_for(size_range: str | None, size_count: int | None, config: OutreachConfig) -> tuple[list[str], str]:
    """(roles to try, in order; the sentence the app shows for why)."""
    upper = size_upper_bound(size_range, size_count)
    small = config.small_company_targets
    names = " / ".join(ROLE_LABELS[r] for r in small[:2])
    size_text = f"{size_count} people" if size_count else f"{size_range} people" if size_range else ""
    if upper is None:
        return small, f"Size unknown, so trying the {names} first: most remote startups are small."
    if upper <= config.small_company_max_employees:
        return small, f"{size_text}: small enough to email the {names} directly."
    large = config.large_company_targets
    return large, (f"{size_text}: over {config.small_company_max_employees}, so the "
                   f"{ROLE_LABELS[large[0]].lower()} first, then {ROLE_LABELS[large[-1]]}.")


def clean_company_name(name: str) -> tuple[str, list[str]]:
    """'WorkHero https://workhero.pro' -> ('WorkHero', ['https://workhero.pro'])."""
    urls = _URL_RE.findall(name or "")
    cleaned = " ".join(_URL_RE.sub(" ", name or "").split()).strip(" -–|,:")
    return cleaned or name, urls


def registrable_domain(host: str) -> str:
    parts = host.lower().strip(".").split(".")
    if parts and parts[0] == "www":
        parts = parts[1:]
    if len(parts) >= 3 and ".".join(parts[-2:]) in _TWO_PART_TLDS:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _host(url: str) -> str:
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _names_match(label: str, key: str) -> bool:
    compact = key.replace(" ", "")
    if not compact or not label:
        return False
    if label == compact or (len(compact) >= 3 and compact in label) or (len(label) >= 4 and label in compact):
        return True
    return any(len(w) >= 4 and w not in _GENERIC_WORDS and w in label for w in key.split())


def domain_from_links(name: str, texts: list[str]) -> str | None:
    """The company's own domain among the links in its name, job URLs and description."""
    cleaned, name_urls = clean_company_name(name)
    key = company_key(cleaned)
    urls = list(name_urls)
    for text in texts:
        urls += _URL_RE.findall(text or "")
    seen = []
    for url in urls:
        domain = registrable_domain(_host(url))
        if not domain or "." not in domain or domain in seen:
            continue
        seen.append(domain)
        if domain in _NOT_COMPANY or domain in _WEBMAIL or any(domain.endswith("." + d) for d in _NOT_COMPANY):
            continue
        if _names_match(domain.split(".")[0], key):
            return domain
    return None


def _name_part(value: str | None) -> str:
    return re.sub(r"[^a-z]", "", strip_accents(value or "").lower())


def split_name(full_name: str) -> tuple[str, str]:
    words = [w for w in re.split(r"\s+", (full_name or "").strip()) if w and not w.endswith(".")] or [full_name]
    return words[0], words[-1] if len(words) > 1 else ""


def guess_email(first: str, last: str, domain: str, pattern: str | None, small: bool) -> str | None:
    """From Hunter's known pattern for the domain, else first@ (small companies) or first.last@."""
    f, l = _name_part(first), _name_part(last)
    if not f or not domain:
        return None
    if not pattern:
        pattern = "{first}" if small or not l else "{first}.{last}"
    if ("{last}" in pattern or "{l}" in pattern) and not l:
        pattern = "{first}"
    local = pattern.replace("{first}", f).replace("{last}", l).replace("{f}", f[:1]).replace("{l}", l[:1])
    return f"{local}@{domain}"


def _email_status(verification: dict | None, accept_all: bool | None = None) -> str:
    status = (verification or {}).get("status")
    if status == "valid":
        return "verified"
    if status == "accept_all" or accept_all:
        return "accept_all"
    if status == "invalid":
        return "invalid"
    return "found"


def rank_contacts(contacts: list, targets: list[str]) -> list:
    """Best first: a target role (in target order), a usable email, Hunter's confidence."""
    def key(c):
        role = c["role"]
        position = targets.index(role) if role in targets else len(targets) + list(ROLE_LABELS).index(role)
        email = c["email"] and c["email_status"] not in ("bounced", "invalid")
        return (c["source"] != "manual", position, not email, -(c["confidence"] or 0), c["id"] if "id" in c.keys() else 0)
    return sorted(contacts, key=key)


# --- storage ------------------------------------------------------------------


def job_company(store: JobStore, job: sqlite3.Row, now: datetime) -> sqlite3.Row:
    """The job's `companies` row, created on first use."""
    name, _ = clean_company_name(job["company"])
    key = company_key(name) or name.lower()
    row = store.conn.execute("SELECT * FROM companies WHERE key = ?", (key,)).fetchone()
    if row is None:
        store.conn.execute("INSERT INTO companies (key, name) VALUES (?, ?)", (key, name))
        row = store.conn.execute("SELECT * FROM companies WHERE key = ?", (key,)).fetchone()
    return row


def company_contacts(store: JobStore, key: str) -> list[sqlite3.Row]:
    return store.conn.execute("SELECT * FROM contacts WHERE company_key = ? ORDER BY id", (key,)).fetchall()


def _update_company(store: JobStore, key: str, **values) -> None:
    assignments = ", ".join(f"{k} = :{k}" for k in values)
    store.conn.execute(f"UPDATE companies SET {assignments} WHERE key = :key", {**values, "key": key})


def save_contact(store: JobStore, key: str, now: datetime, **values) -> int:
    """Insert or update (same company and email, else same name). Returns the contact id."""
    email = (values.get("email") or "").lower() or None
    values["email"] = email
    existing = None
    if email:
        existing = store.conn.execute(
            "SELECT id FROM contacts WHERE company_key = ? AND lower(email) = ?", (key, email)).fetchone()
    if existing is None:
        existing = store.conn.execute(
            "SELECT id FROM contacts WHERE company_key = ? AND lower(full_name) = lower(?)",
            (key, values["full_name"])).fetchone()
    if existing:
        current = store.conn.execute("SELECT * FROM contacts WHERE id = ?", (existing["id"],)).fetchone()
        if current["email_status"] == "bounced" and current["email"] == email:
            values.pop("email_status", None)  # a bounce is a fact; a later lookup does not undo it
        assignments = ", ".join(f"{k} = :{k}" for k in values)
        store.conn.execute(f"UPDATE contacts SET {assignments} WHERE id = :id", {**values, "id": existing["id"]})
        return existing["id"]
    values.setdefault("first_name", split_name(values["full_name"])[0])
    values.setdefault("last_name", split_name(values["full_name"])[1])
    values.setdefault("role", role_of(values.get("position")))
    values["created_at"] = iso(now)
    columns = ", ".join(["company_key", *values])
    marks = ", ".join(["?"] * (len(values) + 1))
    cur = store.conn.execute(f"INSERT INTO contacts ({columns}) VALUES ({marks})", [key, *values.values()])
    return cur.lastrowid


def skip_list_match(name: str, config: OutreachConfig) -> bool:
    key = company_key(clean_company_name(name)[0])
    return any(company_key(s) == key for s in config.skip_companies)


def set_job_board(store: JobStore, key: str, is_job_board: bool) -> None:
    _update_company(store, key, is_job_board=1 if is_job_board else 0,
                    note="Marked as a job board or agency in the app" if is_job_board else None)


def set_domain(store: JobStore, key: str, domain: str) -> None:
    domain = registrable_domain(_host(domain.strip())) if domain.strip() else None
    _update_company(store, key, domain=domain, domain_source="manual" if domain else None)


def save_manual_contact(store: JobStore, job_id: int, full_name: str, email: str, position: str,
                        now: datetime) -> int:
    job = store.get(job_id)
    company = job_company(store, job, now)
    email = email.strip().lower()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", email):
        raise tracking.TrackingError(f"not an email address: {email}")
    contact_id = save_contact(
        store, company["key"], now, full_name=full_name.strip() or email, position=position.strip() or None,
        role=role_of(position), email=email or None, email_status="manual" if email else None,
        source="manual", verified=1,
    )
    tracking.ensure_application(store, job_id, now)
    store.conn.execute("UPDATE applications SET contact_id = ?, updated_at = ? WHERE job_id = ?",
                       (contact_id, iso(now), job_id))
    tracking.add_event(store, job_id, "contact", f"Contact set by hand: {full_name} <{email}>", now)
    return contact_id


def chosen_contact(store: JobStore, job: sqlite3.Row, config: OutreachConfig) -> sqlite3.Row | None:
    """The contact picked for this job (by hand or by a draft), else the best one for the company."""
    app = tracking.get_application(store, job["id"])
    if app and app["contact_id"]:
        row = store.conn.execute("SELECT * FROM contacts WHERE id = ?", (app["contact_id"],)).fetchone()
        if row:
            return row
    name, _ = clean_company_name(job["company"])
    company = store.conn.execute("SELECT * FROM companies WHERE key = ?", (company_key(name),)).fetchone()
    if not company:
        return None
    targets, _ = targets_for(company["size_range"], company["size_count"], config)
    ranked = rank_contacts(company_contacts(store, company["key"]), targets)
    return ranked[0] if ranked else None


# --- Claude backup --------------------------------------------------------------

FALLBACK_SYSTEM = """\
You help a software engineer find the right person to email about an open \
role. Search the web, then call record_people once.

Find people who currently hold one of these roles at the company, best first: \
{targets}. Also note the company's own website domain, and its employee count \
if a result states it.

Rules:
- Only list a person when a search result shows their name and current title \
together, for example a LinkedIn result titled "Jane Doe - CTO - Acme | \
LinkedIn", or the company's team page.
- quote: copied character for character from that search result's title or \
text, containing the name and the title. Do not paraphrase or join parts.
- source_url: the result the quote comes from.
- employees: copied exactly as a result states it (e.g. "11-50 employees"), \
with employees_url; empty when no result says.
- Never guess a name, a title or an email address. No match: an empty list.
"""

RECORD_PEOPLE = {
    "name": "record_people",
    "description": "Record what the search found, once.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "The company's website domain, or empty."},
            "employees": {"type": "string", "description": "Employee count exactly as a result states it, or empty."},
            "employees_url": {"type": "string"},
            "people": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "title": {"type": "string"},
                        "quote": {"type": "string"},
                        "source_url": {"type": "string"},
                    },
                    "required": ["name", "title", "quote", "source_url"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["domain", "employees", "employees_url", "people"],
        "additionalProperties": False,
    },
}
_MAX_REQUESTS = 4


@dataclass
class WebPerson:
    name: str
    title: str
    quote: str
    source_url: str
    verified: bool


@dataclass
class WebResult:
    domain: str | None = None
    employees: str | None = None
    people: list[WebPerson] = field(default_factory=list)
    cost_usd: float = 0.0


def claude_people(client, model: str, max_searches: int, company: str, job: sqlite3.Row, targets: list[str],
                  domain: str | None) -> WebResult:
    system = FALLBACK_SYSTEM.format(targets=", ".join(ROLE_LABELS[t] for t in targets))
    links = ", ".join(dict.fromkeys(u for u in (job["application_url"], job["source_url"]) if u)) or "none"
    messages: list[dict] = [{"role": "user", "content": "\n".join([
        f"Company: {company}", f"Website: {domain or 'unknown'}", f"Open role: {job['title']}", f"Links: {links}",
        "", "From the job posting:", (job["description"] or "")[:1500],
    ])}]
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": max_searches}, RECORD_PEOPLE]
    usage = Usage()
    pages: list[tuple[str, str]] = []
    answer = None
    tool_choice = {"type": "auto"}
    for _ in range(_MAX_REQUESTS):
        response = client.messages.create(model=model, max_tokens=2048, system=system, tools=tools,
                                          tool_choice=tool_choice, messages=messages)
        usage.add(response.usage)
        blocks = [plain(b) for b in response.content]
        pages += list(pages_read(blocks, search_titles=True))
        answer = next((b.get("input") for b in blocks
                       if b.get("type") == "tool_use" and b.get("name") == "record_people"), None)
        if answer is not None:
            break
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "pause_turn":
            messages.append({"role": "user", "content": "Call record_people now with what you found."})
            tool_choice = forced_tool_choice(model, "record_people")
    result = WebResult(cost_usd=usage.cost(model) or 0.0)
    if answer is None:
        return result
    domain_text = registrable_domain(_host(str(answer.get("domain") or ""))) if answer.get("domain") else ""
    result.domain = domain_text if "." in domain_text else None
    employees = " ".join(str(answer.get("employees") or "").split())
    if employees and find_quote(employees, pages, str(answer.get("employees_url") or "")):
        result.employees = employees  # only a count the search results really show
    for person in answer.get("people") or []:
        name = " ".join(str(person.get("name") or "").split())
        quote = " ".join(str(person.get("quote") or "").split())
        if not name:
            continue
        found_at = find_quote(quote, pages, str(person.get("source_url") or ""))
        name_in_quote = all(w.lower() in quote.lower() for w in name.split())
        result.people.append(WebPerson(
            name=name, title=" ".join(str(person.get("title") or "").split()), quote=quote,
            source_url=found_at or str(person.get("source_url") or ""), verified=bool(found_at and name_in_quote),
        ))
    return result


# --- the lookup -------------------------------------------------------------------


@dataclass
class Lookup:
    company: str
    status: str  # found | nobody | job_board | no_domain | reused | busy | error
    note: str = ""
    credits: float = 0.0
    cost_usd: float = 0.0


class ContactFinder:
    def __init__(self, config: OutreachConfig, hunter: Hunter | None, claude=None):
        self.config = config
        self.hunter = hunter
        self.claude = claude
        self._hunter_off: str | None = None if hunter else "no HUNTER_API_KEY"
        self._account: Account | None = None

    def account(self, refresh: bool = False) -> Account | None:
        if self.hunter is None or self._hunter_off and not refresh:
            return self._account
        if self._account is None or refresh:
            try:
                self._account = self.hunter.account()
            except HunterError as exc:
                self._hunter_off = str(exc)
                return None
        return self._account

    def _hunter_ok(self) -> bool:
        if self._hunter_off:
            return False
        account = self.account()
        if account and account.remaining is not None \
                and account.remaining - self.config.hunter_reserve_credits < CREDITS_PER_COMPANY:
            self._hunter_off = f"Hunter credits low ({account.remaining:g} left, reserve {self.config.hunter_reserve_credits:g})"
            return False
        return True

    def _hunter_call(self, fn, *args):
        try:
            return fn(*args)
        except HunterError as exc:
            if exc.fatal:
                self._hunter_off = str(exc)
            raise

    def lookup(self, store: JobStore, job: sqlite3.Row, now: datetime, use_claude: bool = True,
               force: bool = False) -> Lookup:
        company = job_company(store, job, now)
        key, name = company["key"], company["name"]
        if company["is_job_board"] or skip_list_match(job["company"], self.config):
            if not company["is_job_board"]:
                _update_company(store, key, is_job_board=1, note="On the skip list in config/outreach.json")
                store.commit()
            return Lookup(name, "job_board", "Job board or agency: apply through the link.")
        if company["lookup_state"] == "done" and not force:
            return Lookup(name, "reused", company["note"] or "")
        started = parse_datetime(company["lookup_started_at"])
        stale = iso(now - timedelta(minutes=LOCK_MINUTES))
        claimed = store.conn.execute(
            "UPDATE companies SET lookup_state = 'running', lookup_started_at = ? WHERE key = ? "
            "AND (lookup_state IS NULL OR lookup_state != 'running' OR lookup_started_at < ?)",
            (iso(now), key, stale),
        ).rowcount
        store.commit()  # release the write lock before any network call
        if not claimed:
            return Lookup(name, "busy", f"already being looked up (since {iso(started)})")
        before = self.account(refresh=True) if self.hunter and not self._hunter_off else None
        result = Lookup(name, "nobody")
        try:
            self._run(store, job, company, now, use_claude, result)
            state = "done"
        except Exception as exc:  # noqa: BLE001 - one company's failure never stops the others
            log.warning("contact lookup for %s failed: %s", name, error_line(exc))
            result.status, result.note, state = "error", error_line(exc), "failed"
        after = self.account(refresh=True) if before else None
        if before and after and before.remaining is not None and after.remaining is not None:
            result.credits = round(max(0.0, before.remaining - after.remaining), 2)
        current = store.conn.execute("SELECT credits, cost_usd FROM companies WHERE key = ?", (key,)).fetchone()
        _update_company(store, key, lookup_state=state, looked_up_at=iso(now), note=result.note,
                        credits=(current["credits"] or 0) + result.credits,
                        cost_usd=(current["cost_usd"] or 0) + result.cost_usd)
        store.commit()
        return result

    def _run(self, store: JobStore, job: sqlite3.Row, company: sqlite3.Row, now: datetime, use_claude: bool,
             result: Lookup) -> None:
        key, name = company["key"], company["name"]
        domain = company["domain"] or domain_from_links(job["company"], [
            job["application_url"] or "", job["source_url"] or "", job["description"] or ""])
        if domain and not company["domain"]:
            _update_company(store, key, domain=domain, domain_source="links")
        notes = []
        if not domain and self._hunter_ok():
            matches = self._hunter_call(self.hunter.domain_finder, name)
            same = [m for m in matches if company_key(m.get("company_name") or "") == key and m.get("domain")]
            if same:
                domain = same[0]["domain"]
                _update_company(store, key, domain=domain, domain_source="hunter")
            elif matches:
                notes.append(f"Hunter suggests {matches[0].get('domain')} ({matches[0].get('company_name')}); "
                             "set the domain in the app if that is right")
        size_range, size_count = company["size_range"], company["size_count"]
        found_people = False
        if domain and self._hunter_ok():
            count = self._hunter_call(self.hunter.email_count, domain)
            if (count.get("total") or 0) > 0:
                if not size_range:
                    info = self._hunter_call(self.hunter.company, domain) or {}
                    metrics = info.get("metrics") or {}
                    size_range, size_count = metrics.get("employees"), metrics.get("employeesCount")
                    if size_range or size_count:
                        _update_company(store, key, size_range=size_range, size_count=size_count)
                found_people = self._hunter_people(store, key, domain, size_range, size_count, count, now)
            else:
                notes.append("Hunter knows no emails at this domain")
        elif self._hunter_off and self.hunter is not None:
            notes.append(self._hunter_off)
        targets, _ = targets_for(size_range, size_count, self.config)
        if not self._has_target(store, key, targets) and use_claude and self.claude is not None:
            self._claude_people(store, job, key, name, domain, targets, size_range, size_count, now, result)
            found_people = found_people or bool(company_contacts(store, key))
        if not domain and not company_contacts(store, key):
            result.status = "no_domain"
            notes.insert(0, "Could not find the company's website")
        elif self._has_target(store, key, targets):
            result.status = "found"
        elif company_contacts(store, key):
            result.status = "found"
            notes.append("Nobody in the target roles; showing who Hunter knows")
        result.note = "; ".join(notes)

    def _has_target(self, store: JobStore, key: str, targets: list[str]) -> bool:
        return any(c["role"] in targets and c["email_status"] != "bounced" for c in company_contacts(store, key))

    def _hunter_people(self, store: JobStore, key: str, domain: str, size_range, size_count, count: dict,
                       now: datetime) -> bool:
        targets, _ = targets_for(size_range, size_count, self.config)
        small = targets == self.config.small_company_targets
        departments = count.get("department") or {}
        seniority = count.get("seniority") or {}
        if small:
            if not (seniority.get("executive") or departments.get("executive")):
                return False
            data = self._hunter_call(self.hunter.domain_search, domain, "executive", None)
        else:
            if not any(departments.get(d) for d in ("it", "hr", "management", "executive")):
                return False
            data = self._hunter_call(self.hunter.domain_search, domain, "senior,executive", "it,hr,management,executive")
        _update_company(store, key, email_pattern=data.get("pattern"), accept_all=1 if data.get("accept_all") else 0)
        for email in data.get("emails") or []:
            full = " ".join(x for x in (email.get("first_name"), email.get("last_name")) if x) or email.get("value")
            sources = email.get("sources") or []
            save_contact(
                store, key, now, full_name=full, first_name=email.get("first_name"), last_name=email.get("last_name"),
                position=email.get("position"), role=role_of(email.get("position")), email=email.get("value"),
                email_status=_email_status(email.get("verification"), data.get("accept_all")),
                confidence=email.get("confidence"), linkedin_url=_linkedin(email.get("linkedin")), source="hunter",
                evidence_url=sources[0].get("uri") if sources else None,
                evidence_quote=f"Hunter saw this email on {len(sources)} page(s)" if sources else None,
                verified=1 if sources else 0,
            )
        return bool(data.get("emails"))

    def _claude_people(self, store, job, key, name, domain, targets, size_range, size_count, now, result) -> None:
        web = claude_people(self.claude, self.config.fallback_model, self.config.fallback_max_searches,
                            name, job, targets, domain)
        result.cost_usd += web.cost_usd
        if web.domain and not domain:
            domain = web.domain
            _update_company(store, key, domain=domain, domain_source="web")
        if web.employees and not size_range:
            size_range = web.employees.replace("employees", "").strip()
            _update_company(store, key, size_range=size_range)
            targets, _ = targets_for(size_range, size_count, self.config)
        small = targets == self.config.small_company_targets
        company = store.conn.execute("SELECT * FROM companies WHERE key = ?", (key,)).fetchone()
        ranked = sorted(web.people, key=lambda p: (not p.verified, targets.index(role_of(p.title))
                                                   if role_of(p.title) in targets else 99))
        for n, person in enumerate(ranked):
            first, last = split_name(person.name)
            email, status, confidence = None, None, None
            if n == 0 and domain:  # only the best person costs an Email Finder credit
                found = None
                if self._hunter_ok():
                    try:
                        found = self._hunter_call(self.hunter.email_finder, domain, first, last)
                    except HunterError as exc:
                        log.info("email finder: %s", exc)
                if found:
                    email, confidence = found["email"], found.get("score")
                    status = _email_status(found.get("verification"), found.get("accept_all"))
                else:
                    email, status = guess_email(first, last, domain, company["email_pattern"], small), "guessed"
            save_contact(
                store, key, now, full_name=person.name, first_name=first, last_name=last, position=person.title,
                role=role_of(person.title), email=email, email_status=status if email else None,
                confidence=confidence, source="claude", evidence_url=person.source_url,
                evidence_quote=person.quote, verified=1 if person.verified else 0,
            )


def _linkedin(value: str | None) -> str | None:
    if not value:
        return None
    return value if value.startswith("http") else f"https://www.linkedin.com/in/{value.strip('/')}"


def verify_email(store: JobStore, hunter: Hunter, contact_id: int) -> str:
    """Hunter Email Verifier on click (0.5 credit). Returns the new status."""
    contact = store.conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    if not contact or not contact["email"]:
        raise tracking.TrackingError("this contact has no email to verify")
    data = hunter.email_verifier(contact["email"])
    status = {"valid": "verified", "accept_all": "accept_all", "invalid": "invalid"}.get(data.get("status"),
                                                                                           contact["email_status"])
    store.conn.execute("UPDATE contacts SET email_status = ? WHERE id = ?", (status, contact_id))
    return status


# --- many jobs at once (daily run, `jobhunter contacts`) --------------------------


def days_to_reset(reset_date: str | None, now: datetime) -> int:
    try:
        reset = date.fromisoformat(str(reset_date)[:10])
    except (TypeError, ValueError):
        return 30
    return max(1, (reset - now.astimezone().date()).days)


def run_budget(account: Account | None, now: datetime, config: OutreachConfig) -> int:
    """How many companies today may cost Hunter credits: what is left, spread over the days to the reset."""
    if account is None or account.remaining is None:
        return config.max_companies_per_run
    allowance = account.remaining - config.hunter_reserve_credits
    if allowance < CREDITS_PER_COMPANY:
        return 0
    per_day = allowance / CREDITS_PER_COMPANY / days_to_reset(account.reset_date, now)
    return max(1, min(config.max_companies_per_run, int(per_day)))


@dataclass
class ContactRun:
    looked_up: int = 0
    found: int = 0
    skipped: int = 0
    credits: float = 0.0
    cost_usd: float = 0.0
    waiting: int = 0
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    found_job_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"looked_up": self.looked_up, "found": self.found, "skipped": self.skipped,
                "credits": round(self.credits, 2), "cost_usd": round(self.cost_usd, 3), "waiting": self.waiting,
                "notes": self.notes, "errors": self.errors}


def find_contacts(store: JobStore, finder: ContactFinder, jobs: list[sqlite3.Row], now: datetime,
                  limit: int | None, use_claude: bool, on_result=None) -> ContactRun:
    """Look up the companies of `jobs` (best fit first), each company once, at most `limit` new companies."""
    run = ContactRun()
    jobs = sorted(jobs, key=lambda r: (-r["fit_score"], -r["id"]))
    done_keys: set[str] = set()
    new_lookups = 0
    for job in jobs:
        key = job_company(store, job, now)["key"]
        if key in done_keys:
            if chosen_contact(store, job, finder.config):
                run.found_job_ids.append(job["id"])
            continue
        company = store.conn.execute("SELECT * FROM companies WHERE key = ?", (key,)).fetchone()
        fresh = company["lookup_state"] != "done" and not company["is_job_board"]
        if fresh and limit is not None and new_lookups >= limit:
            run.waiting += 1
            continue
        done_keys.add(key)
        lookup = finder.lookup(store, job, now, use_claude=use_claude)
        if lookup.status in ("job_board",):
            run.skipped += 1
        elif lookup.status == "error":
            run.errors.append(f"{lookup.company}: {lookup.note}")
        elif lookup.status != "reused":
            new_lookups += 1
            run.looked_up += 1
        run.credits += lookup.credits
        run.cost_usd += lookup.cost_usd
        if lookup.status in ("found", "reused") and chosen_contact(store, job, finder.config):
            run.found += lookup.status == "found"
            run.found_job_ids.append(job["id"])
        if on_result:
            on_result(job, lookup)
    if finder._hunter_off and finder.hunter is not None:
        run.notes.append(finder._hunter_off)
    if run.waiting:
        run.notes.append(f"{run.waiting} companies left for later (credit budget); use Find contact or `jobhunter contacts`")
    return run


def build_finder(config: OutreachConfig) -> tuple[ContactFinder | None, str | None]:
    import os

    from .llm import anthropic_client

    hunter = Hunter(os.environ["HUNTER_API_KEY"]) if os.environ.get("HUNTER_API_KEY") else None
    claude = anthropic_client()
    if hunter is None and claude is None:
        return None, "contacts skipped: set HUNTER_API_KEY (and/or ANTHROPIC_API_KEY) in .env"
    note = None if hunter else "contacts: no HUNTER_API_KEY, so only Claude web search (no emails beyond guesses)"
    return ContactFinder(config, hunter, claude), note
