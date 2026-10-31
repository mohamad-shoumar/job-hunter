"""Rejection emails: close the job they are about, quoting the sentence that says no.

Runs inside the inbox check (mailer.check_inbox), so in both daily runs and on `jobhunter inbox`.
Plain code, no model: every closed job's event quotes the email's sentence and says how the job
was picked, so a wrong match is easy to see and undo (drag it back in the app).

An email counts when:
  1. a sentence in it says no, by one of REJECTION phrases ("we have decided not to move forward",
     "we regret to inform you", "pursue other candidates"); a sentence with "if"/"should" ("if we
     decide not to move forward, we will let you know") never counts;
  2. it is about an application (a word like "application", "candidacy", "role" or "position");
  3. its sender or subject names a company you have an application with: never the body, where
     short names (Wise, IMC, Lyst) turn up by chance. Applicant systems send from their own domains
     (ashbyhq.com, greenhouse-mail.io), so the company is in the sender's name or the subject;
  4. it came after you started that application.

Which job: the one whose title the email names (the longest, when several do: "Senior Software
Engineer" beats "Software Engineer"); a title match on a job already closed closes nothing. With no
title named, the company's only open application; with several open, nothing changes and the email
is listed for you to decide.
"""

from __future__ import annotations

import html
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime

from . import tracking
from .contacts import clean_company_name
from .models import CLOSED
from .store import JobStore
from .store.applications import oldest_open_application, tracked_jobs
from .store.mail import is_seen, mark_seen
from .text import html_to_text, parse_datetime, strip_accents

log = logging.getLogger(__name__)

# Each is matched inside one sentence, case-insensitive.
REJECTION = [
    r"\bdecided not to (?:move|proceed|progress|advance|continue|pursue|take)",
    r"\bdecision not to (?:move|proceed|progress|advance|continue)",
    r"\b(?:will|shall|are|won't|cannot|can't|unable to|not able to)\b[^.]{0,25}\bnot\b[^.]{0,15}\b(?:be )?"
    r"(?:moving|move|proceeding|proceed|progressing|progress|advancing|advance|taking)\b[^.]{0,40}"
    r"\b(?:forward|further|ahead|you|your application|your candidacy)\b",
    r"\b(?:won't|will not|cannot|can't) be (?:moving|progressing|proceeding|advancing)\b",
    r"\bnot to (?:move|proceed|progress) (?:forward|further|with)\b",
    r"\bnot (?:be )?proceed(?:ing)? (?:further|with your)\b",
    r"\bmove forward with (?:an)?other candidates?\b",
    r"\b(?:pursue|progressing with|proceed with|move ahead with|moving forward with) (?:other|another) candidates?\b",
    r"\bnot (?:been )?(?:able to )?select(?:ed)? (?:your application|you)\b",
    r"\bnot been successful\b",
    r"\bregret to inform you\b",
    r"\bposition has (?:now )?been filled\b",
    r"\bno longer (?:being )?considered\b",
]
_REJECTION = re.compile("|".join(f"(?:{p})" for p in REJECTION), re.I)
# "If we decide not to move forward, we'll let you know" says nothing yet.
_CONDITIONAL = re.compile(r"\b(?:if|should|whether|in case|in the event)\b", re.I)
_ABOUT_APPLYING = re.compile(r"\b(?:application|applications|candidacy|candidates?|applying|applied|apply|role|position|vacancy)\b", re.I)
# Senders whose emails mention companies without being from them.
_NOT_EMPLOYERS = re.compile(r"linkedin|glassdoor|indeed|bayt|naukri|wellfound|otta|welcometothejungle|"
                            r"workable\.com$|jooble|himalayas|remoteok|weworkremotely", re.I)
# Company names that say nothing about who it is.
_PLACEHOLDER = {"confidential", "confidential jobs", "stealth", "stealth startup", "anonymous", "undisclosed"}
_LEGAL = re.compile(r"\b(?:ltd|limited|inc|llc|l\.l\.c|gmbh|ag|se|sa|sas|bv|b\.v|plc|co|corp|corporation|company|"
                    r"group|holding|holdings|fz|fze|fzco|fz-llc|dmcc|pvt|private)\b\.?", re.I)
# Gmail search: a broad net, read properly by the rules above.
GMAIL_QUERY = ('-from:me (application OR candidacy OR candidates OR applying OR applied OR role OR position OR vacancy) ("move forward" OR "moving forward" '
               'OR "regret" OR "unfortunately" OR "other candidates" OR "not proceed" OR "not to proceed" '
               'OR "progressing" OR "progress your" OR "not been successful" OR "not selected" OR "advancing" '
               'OR "been filled")')
MAX_QUOTE = 220


@dataclass
class Rejection:
    job_id: int | None
    company: str
    sentence: str
    how: str  # how the job was picked, or why none was


@dataclass
class RejectionScan:
    closed: list[str] = field(default_factory=list)  # one line per job closed (or that would be, on a dry run)
    unsure: list[str] = field(default_factory=list)  # rejections we could not tie to one open job
    checked: int = 0


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", strip_accents(text or "").lower())


def name_keys(company: str) -> list[str]:
    """The ways a sender or subject may write the company: 'Woven By Toyota' -> ['woven by toyota'],
    'Codest Ltd. Company No. 1259' -> ['codest'], 'Madar | مدار' -> ['madar']."""
    cleaned, _ = clean_company_name(company or "")
    first = re.split(r"\s+[|—–]\s+|\s+-\s+|,|\(", cleaned)[0]
    keys = []
    for name in (cleaned, first, _LEGAL.split(first)[0]):
        name = " ".join(_LEGAL.sub(" ", strip_accents(name).lower()).split()).strip(" .-")
        name = re.sub(r"\.(?:com|ai|io|co|net)$", "", name)
        if name and name not in _PLACEHOLDER and len(_squash(name)) >= 3 and name not in keys:
            keys.append(name)
    return keys


def names_company(text: str, company: str) -> bool:
    """True when `text` (a sender and subject) names the company. Long names match with spaces and
    case ignored ('CHAOS Industries' = 'Chaosindustries'); short ones only as whole words, so 'IMC'
    is found in 'IMC - Update' but 'Wise' never in 'Otherwise'."""
    lowered = strip_accents(text or "").lower()
    squashed = _squash(text)
    for key in name_keys(company):
        if len(_squash(key)) >= 7 and _squash(key) in squashed:
            return True
        words = re.findall(r"[a-z0-9]+", key)
        if words and re.search(r"(?<![a-z0-9])" + r"[^a-z0-9]*".join(words) + r"(?![a-z0-9])", lowered):
            return True
    return False


def body_text(msg: Message) -> str:
    """The message's text, plain part first, HTML turned to text, whitespace collapsed."""
    part = msg.get_body(preferencelist=("plain", "html")) if hasattr(msg, "get_body") else None
    try:
        text = part.get_content() if part else ""
    except (LookupError, ValueError):
        text = ""
    if part is not None and part.get_content_type() == "text/html":
        text = html_to_text(text)
    # Some plain parts still carry HTML entities ("we&rsquo;ve", "&nbsp;").
    return " ".join(html.unescape(text).replace("\u00a0", " ").split())[:8000]


def rejection_sentence(text: str) -> str | None:
    """The first sentence that says no, or None."""
    for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
        if _REJECTION.search(sentence) and not _CONDITIONAL.search(sentence):
            sentence = sentence.strip()
            return sentence if len(sentence) <= MAX_QUOTE else sentence[:MAX_QUOTE - 1].rstrip() + "…"
    return None


def title_forms(title: str) -> list[str]:
    """A title as an email may write it, squashed, longest first: 'Platform Engineer - Compute - Python'
    -> the whole, 'Platform Engineer - Compute', 'Platform Engineer'. Brackets and remote/location
    tails are often left out too."""
    forms = [title or ""]
    cut = re.split(r"\s*\(", forms[0])[0]
    forms.append(cut)
    parts = re.split(r"\s+[-–—|,]\s+", cut)
    forms += [" - ".join(parts[:n]) for n in range(len(parts) - 1, 0, -1)]
    squashed = []
    for form in forms:
        key = _squash(form)
        if len(key) >= 10 and key not in squashed:
            squashed.append(key)
    return squashed


def pick_job(company_jobs: list[sqlite3.Row], text: str) -> tuple[sqlite3.Row | None, str]:
    """The job an email is about, among one company's tracked jobs (open or closed)."""
    squashed = _squash(text)
    best: tuple[int, sqlite3.Row] | None = None
    for row in company_jobs:
        for form in title_forms(row["title"]):
            if form in squashed and (best is None or len(form) > best[0]):
                best = (len(form), row)
                break
    if best is not None:
        row = best[1]
        return row, f'it names the role "{row["title"]}"'
    open_jobs = [row for row in company_jobs if row["stage"] != CLOSED]
    if len(open_jobs) == 1:
        return open_jobs[0], "the only open application there"
    if not open_jobs:
        return None, "no open application there"
    return None, f"{len(open_jobs)} open applications there and the email names none of their roles"


def read_rejection(msg: Message, jobs: list[sqlite3.Row]) -> Rejection | None:
    """What one email says, or None when it is not a rejection about a company you applied to."""
    name, address = parseaddr(str(msg.get("From") or ""))
    domain = address.rsplit("@", 1)[-1].lower() if "@" in address else ""
    if _NOT_EMPLOYERS.search(domain):
        return None
    subject = str(msg.get("Subject") or "")
    text = body_text(msg)
    if not _ABOUT_APPLYING.search(f"{subject} {text}"):
        return None
    sentence = rejection_sentence(text)
    if not sentence:
        return None
    sent = _date(msg)
    who = f"{name} {domain.rsplit('.', 1)[0]} {subject}"
    # One company may be stored as "SumUp" and "sumup": grouped by the squashed name.
    by_company: dict[str, list[sqlite3.Row]] = {}
    for row in jobs:
        by_company.setdefault(_squash(row["company"]) or row["company"], []).append(row)
    matches = [rows for rows in by_company.values() if names_company(who, rows[-1]["company"])]
    if not matches:
        return None
    # "Wise" and "Wise Payments" both named: the longer name is the one meant.
    rows = max(matches, key=lambda r: len(_squash(r[0]["company"])))
    company = rows[-1]["company"]
    if sent is not None:
        rows = [r for r in rows if (parse_datetime(r["created_at"]) or sent) - timedelta(days=1) <= sent]
        if not rows:
            return None
    job, how = pick_job(rows, f"{subject} {text}")
    return Rejection(job["job_id"] if job is not None and job["stage"] != CLOSED else None, company, sentence,
                     how if job is None or job["stage"] != CLOSED else "that job is already closed")


def _date(msg: Message) -> datetime | None:
    try:
        sent = parsedate_to_datetime(str(msg.get("Date")))
    except (TypeError, ValueError):
        return None
    return sent.replace(tzinfo=UTC) if sent.tzinfo is None else sent  # "-0000" parses without a zone


def _key(msg: Message, uid: int) -> str:
    return "rejection:" + (str(msg.get("Message-ID") or "").strip() or f"uid:{uid}")


def scan_rejections(store: JobStore, inbox, now: datetime, lookback_days: int, dry_run: bool = False) -> RejectionScan:
    """Search Gmail for rejection emails since the oldest open application and close the jobs they
    are about. `inbox` is an open mailer.GmailInbox (All Mail selected). On a dry run nothing is
    written: the lines say what would close."""
    result = RejectionScan()
    oldest = parse_datetime(oldest_open_application(store))
    if oldest is None:
        return result
    since = max(oldest - timedelta(days=1), now - timedelta(days=lookback_days))
    jobs = tracked_jobs(store)
    for uid in inbox.search_raw(f"after:{since:%Y/%m/%d} {GMAIL_QUERY}"):
        msg = inbox.full(uid)
        if msg is None:
            continue
        key = _key(msg, uid)
        if is_seen(store, key):
            continue
        result.checked += 1
        found = read_rejection(msg, jobs)
        sent = _date(msg)
        day = f"{sent:%b %d}" if sent else "undated"
        if found is not None and found.job_id is not None:
            title = next(r["title"] for r in jobs if r["job_id"] == found.job_id)
            line = f'{found.company}, {title}: rejection email {day} ({found.how}): "{found.sentence}"'
            result.closed.append(line)
            if not dry_run:
                tracking.set_stage(store, found.job_id, CLOSED, now, reason="rejected",
                                   detail=f'rejection email {day}, {found.how}: "{found.sentence}"')
                jobs = tracked_jobs(store)
        elif found is not None and "open applications there" in found.how:
            result.unsure.append(f'{found.company}: rejection email {day} not applied ({found.how}): "{found.sentence}"')
        if not dry_run:
            mark_seen(store, key, found.job_id if found else None,
                      "rejection" if found and found.job_id else "rejection_other", now)
    if not dry_run:
        store.commit()
    return result
