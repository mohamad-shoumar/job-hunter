"""Gmail through an app password: SMTP to send, IMAP to read replies and bounces.

Setup: turn on 2-Step Verification, create an app password at
myaccount.google.com/apppasswords, then put GMAIL_ADDRESS and
GMAIL_APP_PASSWORD in .env. Nothing here ever turns on smtplib/imaplib debug
output, because it would print the login line.

Sending happens only when you click Send in `jobhunter serve`, never from the
daily run. Each email is a plain-text message with a Message-ID made here and
saved before the SMTP call; a unique index on (job, step) makes a second
click fail instead of sending twice. If the SMTP call ends without a clear
answer, the row stays "sending" and the next inbox check looks the
Message-ID up in Gmail: found means it went out, missing means it did not.

The inbox check opens All Mail read-only (by its \\All flag, since its name
depends on the account language), peeks without marking anything read, and
remembers the last message it saw. A message counts as:
  - a reply: in the thread of one of our emails (In-Reply-To/References or
    Gmail's thread id) and not from you, or from someone at the company's
    domain after the send ("probable reply");
  - an auto-reply: the same, but marked automatic (out of office): logged,
    no stage change;
  - a bounce: a delivery report with a permanent failure (5.x.x) for one of
    our emails; a 4.x.x delay is not a bounce.
"""

from __future__ import annotations

import email
import imaplib
import logging
import os
import re
import smtplib
import socket
import sqlite3
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.message import EmailMessage, Message
from email.policy import default as default_policy
from email.utils import formataddr, formatdate, make_msgid, parseaddr, parsedate_to_datetime
from pathlib import Path

from . import tracking
from .config import OutreachConfig
from .contacts import _WEBMAIL, chosen_contact, clean_company_name
from .pitch import Profile, cv_for, follow_up, to_html, to_plain
from .store import JobStore
from .text import iso, parse_datetime

log = logging.getLogger(__name__)

SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 465
IMAP_HOST = "imap.gmail.com"
UNSURE_AFTER = timedelta(minutes=10)
_HEADERS = ("FROM", "TO", "SUBJECT", "DATE", "MESSAGE-ID", "IN-REPLY-TO", "REFERENCES", "AUTO-SUBMITTED",
            "X-AUTOREPLY", "X-AUTORESPOND", "PRECEDENCE", "CONTENT-TYPE", "X-FAILED-RECIPIENTS")
_AUTO_SUBJECT = re.compile(
    r"^\s*(?:automatic reply|auto(?:matic)?[- ]?reply|autoreply|auto-response|out of (?:the )?office|ooo\b|"
    r"away from (?:the )?office|on vacation|abwesen|réponse automatique|respuesta automática|absence)", re.I)
_BOUNCE_FROM = re.compile(r"mailer-daemon|postmaster|mail delivery", re.I)


@dataclass(frozen=True)
class MailAccount:
    address: str
    password: str
    name: str = ""


def mail_account(name: str = "") -> MailAccount | None:
    address = os.environ.get("GMAIL_ADDRESS", "").strip()
    password = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    return MailAccount(address.lower(), password, name) if address and password else None


class SendError(tracking.TrackingError):
    """Shown to you as is. `confirm` names what you must confirm to go ahead (guessed, same_company)."""

    def __init__(self, message: str, confirm: str | None = None):
        super().__init__(message)
        self.confirm = confirm


# --- building and sending --------------------------------------------------------


def new_message_id() -> str:
    # The default domain is this Mac's hostname ("...MacBook-Pro.local"); use Gmail's instead.
    return make_msgid(domain="gmail.com")


def build_message(account: MailAccount, to: str, subject: str, body: str, message_id: str,
                  in_reply_to: str | None = None, references: list[str] | None = None,
                  attachment: Path | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((account.name, account.address)) if account.name else account.address
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = " ".join(references)
    msg.set_content(to_plain(body))  # plain text, utf-8
    msg.add_alternative(to_html(body), subtype="html")  # same words; "LinkedIn" is a link
    if attachment:
        msg.add_attachment(attachment.read_bytes(), maintype="application", subtype="pdf", filename=attachment.name)
    return msg


class NotSent(Exception):
    """The server said no: nothing went out."""


class Unsure(Exception):
    """The connection ended without a clear answer: it may or may not have gone out."""


class SmtpSender:
    def __init__(self, account: MailAccount):
        self.account = account

    def send(self, msg: EmailMessage) -> None:
        try:
            smtp = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context(), timeout=30)
        except (OSError, smtplib.SMTPException) as exc:
            raise NotSent(f"could not reach Gmail ({type(exc).__name__})") from None
        try:
            try:
                smtp.login(self.account.address, self.account.password)
            except smtplib.SMTPAuthenticationError:
                raise NotSent("Gmail refused the login: check GMAIL_ADDRESS and GMAIL_APP_PASSWORD") from None
            try:
                refused = smtp.send_message(msg)
            except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError,
                    smtplib.SMTPHeloError, smtplib.SMTPNotSupportedError) as exc:
                raise NotSent(f"Gmail refused it ({type(exc).__name__})") from None
            except (smtplib.SMTPServerDisconnected, socket.timeout, TimeoutError, OSError) as exc:
                raise Unsure(type(exc).__name__) from None
            if refused:
                raise NotSent(f"Gmail refused {', '.join(refused)}")
        finally:
            try:
                smtp.quit()
            except (smtplib.SMTPException, OSError):
                pass


# --- the send flow ------------------------------------------------------------------


def _contact(store: JobStore, job: sqlite3.Row, app: sqlite3.Row, config: OutreachConfig) -> sqlite3.Row | None:
    if app["contact_id"]:
        return store.conn.execute("SELECT * FROM contacts WHERE id = ?", (app["contact_id"],)).fetchone()
    return chosen_contact(store, job, config)


def _sent(store: JobStore, job_id: int) -> list[sqlite3.Row]:
    return store.conn.execute(
        "SELECT * FROM sent_mail WHERE job_id = ? AND kind != 'test' AND state = 'sent' ORDER BY seq", (job_id,)
    ).fetchall()


@dataclass
class Outgoing:
    kind: str  # first | follow_up | test
    seq: int
    to: str
    subject: str
    body: str
    contact: sqlite3.Row | None
    guessed: bool
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    attachment: Path | None = None


def outgoing(store: JobStore, job_id: int, test: bool, account: MailAccount, profile: Profile,
             config: OutreachConfig) -> Outgoing:
    """What Send would send right now: the first email, the next follow-up, or a test of either."""
    job = store.get(job_id)
    app = tracking.get_application(store, job_id)
    if job is None or app is None or not app["body"]:
        raise SendError("There is no email draft for this job yet.")
    contact = _contact(store, job, app, config)
    sent = _sent(store, job_id)
    company, _ = clean_company_name(job["company"])
    if not sent:
        if not contact or not contact["email"]:
            if not test:
                raise SendError("No email address for this job's contact yet.")
        elif contact["email_status"] in ("bounced", "invalid") and not test:
            raise SendError(f"{contact['email']} bounced or is invalid: pick another contact.")
        to = account.address if test else contact["email"]
        attachment = cv_for(config, company, app["cv_file"])  # None when "No CV" is picked or no PDF exists
        if attachment is not None and not attachment.is_file():
            raise SendError(f"The CV {attachment.name} is missing: pick another in the email box.")
        out = Outgoing("first", 0, to, app["subject"] or f"{job['title']} role", app["body"], contact,
                       guessed=bool(contact and contact["email_status"] == "guessed"), attachment=attachment)
    else:
        seq = len(sent)
        if seq > len(config.follow_up_business_days):
            raise SendError("Both follow-ups were sent already.")
        if app["replied_at"]:
            raise SendError("They replied: answer in Gmail instead of sending a follow-up.")
        first = sent[0]
        subject, body = follow_up(seq, first["subject"], contact, company, job["title"], profile)
        out = Outgoing("follow_up", seq, account.address if test else first["to_addr"], subject, body, contact,
                       guessed=bool(first["guessed"]), in_reply_to=sent[-1]["message_id"],
                       references=[r["message_id"] for r in sent])
    if test:
        out.kind = "test"
        out.subject = f"[test] {out.subject}"
    return out


def send_for_job(store: JobStore, job_id: int, sender, account: MailAccount, profile: Profile,
                 config: OutreachConfig, now: datetime, draft_version: int, test: bool = False,
                 confirm: set[str] | None = None, seq: int | None = None) -> dict:
    """`draft_version` and `seq` are what the page showed: a double click, or a page opened before a send,
    is refused instead of sending the next step."""
    confirm = confirm or set()
    app = tracking.get_application(store, job_id)
    if app is None or app["draft_version"] != draft_version:
        raise SendError("The draft changed since this page loaded. Check it again before sending.")
    out = outgoing(store, job_id, test, account, profile, config)
    if seq is not None and out.seq != seq:
        raise SendError("That email was sent already. Reload to see what is next.")
    if not test and out.kind == "follow_up" and "early" not in confirm:
        due = parse_datetime(app["next_follow_up_at"])
        if due and due > now:
            raise SendError(f"Follow-up {out.seq} is not due until {tracking.local_day(due)}. Send it now anyway?",
                            confirm="early")
    if not test:
        if out.kind == "first" and app["draft_blocked"]:
            raise SendError("The draft has problems (see the warnings). Edit it before sending.")
        counts = tracking.sends_today(store, now)
        if counts["total"] >= config.daily_send_cap:
            raise SendError(f"Daily limit reached ({config.daily_send_cap} emails). It protects your Gmail from "
                            "being flagged as spam; send the rest tomorrow.")
        if out.guessed and out.kind == "first":
            if counts["guessed"] >= config.daily_guessed_cap:
                raise SendError(f"Daily limit for guessed addresses reached ({config.daily_guessed_cap}).")
            if "guessed" not in confirm:
                raise SendError(f"{out.to} is a guess, not a found address. A bounce hurts your Gmail's "
                                "reputation. Send anyway?", confirm="guessed")
        if out.kind == "first" and out.contact and "same_company" not in confirm:
            earlier = tracking.company_contacted(store, out.contact["company_key"], job_id)
            if earlier:
                e = earlier[-1]
                raise SendError(f"You already emailed {e['to_addr']} at this company on {e['sent_at'][:10]} "
                                f"about \"{e['title']}\". Email about this job too?", confirm="same_company")
    message_id = new_message_id()
    try:
        cur = store.conn.execute(
            """
            INSERT INTO sent_mail (job_id, contact_id, kind, seq, message_id, in_reply_to, to_addr, subject, body,
                                   guessed, state, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'sending', ?)
            """,
            (job_id, out.contact["id"] if out.contact else None, out.kind, out.seq, message_id, out.in_reply_to,
             out.to, out.subject, out.body, 1 if out.guessed else 0, iso(now)),
        )
        store.commit()  # saved before the network call: the unique index now blocks a second send
    except sqlite3.IntegrityError:
        store.conn.rollback()
        raise SendError("This email was already sent (or is being sent).") from None
    row_id = cur.lastrowid
    msg = build_message(account, out.to, out.subject, out.body, message_id, out.in_reply_to, out.references,
                        out.attachment)
    try:
        sender.send(msg)
    except NotSent as exc:
        store.conn.execute("UPDATE sent_mail SET state = 'failed', error = ? WHERE id = ?", (str(exc), row_id))
        store.commit()
        raise SendError(f"Not sent: {exc}") from None
    except Unsure as exc:
        store.conn.execute("UPDATE sent_mail SET error = ? WHERE id = ?", (f"unsure: {exc}", row_id))
        store.commit()
        raise SendError("Gmail did not confirm the send. Check inbox in a minute: it will show whether it "
                        "went out. Don't send again before that.") from None
    _mark_sent(store, row_id, now, config)
    store.commit()
    return {"sent": True, "to": out.to, "kind": out.kind, "seq": out.seq, "message_id": message_id}


def _mark_sent(store: JobStore, row_id: int, when: datetime, config: OutreachConfig) -> None:
    row = store.conn.execute("SELECT * FROM sent_mail WHERE id = ?", (row_id,)).fetchone()
    store.conn.execute("UPDATE sent_mail SET state = 'sent', sent_at = ?, error = NULL WHERE id = ?",
                       (iso(when), row_id))
    if row["kind"] == "test":
        tracking.add_event(store, row["job_id"], "test", f"Test email sent to you: {row['subject']}", when)
    else:
        tracking.record_sent(store, row["job_id"], row["seq"], row["to_addr"], when, config)


# --- reading the inbox ----------------------------------------------------------------


@dataclass
class InboxMessage:
    uid: int
    thread_id: str | None
    headers: Message


def _parse_fetch(data) -> list[tuple[bytes, bytes]]:
    """imaplib FETCH output -> (metadata line, literal) pairs."""
    return [(item[0], item[1]) for item in data or [] if isinstance(item, tuple) and len(item) == 2]


class GmailInbox:
    def __init__(self, account: MailAccount, imap=None):
        self.imap = imap or imaplib.IMAP4_SSL(IMAP_HOST, ssl_context=ssl.create_default_context(), timeout=60)
        if imap is None:
            try:
                self.imap.login(account.address, account.password)
            except imaplib.IMAP4.error:
                raise RuntimeError("Gmail refused the IMAP login: check GMAIL_APP_PASSWORD and that IMAP is on") from None
        self.uidvalidity: str | None = None

    def close(self) -> None:
        try:
            self.imap.logout()
        except (imaplib.IMAP4.error, OSError):
            pass

    def open_all_mail(self) -> str:
        typ, boxes = self.imap.list()
        name = None
        for line in boxes or []:
            text = line.decode() if isinstance(line, bytes) else str(line)
            if "\\All" in text:
                m = re.search(r'"([^"]+)"\s*$', text) or re.search(r"(\S+)\s*$", text)
                name = m.group(1) if m else None
                break
        if not name:
            raise RuntimeError("could not find Gmail's All Mail folder")
        typ, _ = self.imap.select(f'"{name}"', readonly=True)
        if typ != "OK":
            raise RuntimeError(f"could not open {name}")
        validity = self.imap.response("UIDVALIDITY")[1]
        self.uidvalidity = (validity[0].decode() if validity and validity[0] else None)
        return name

    def search(self, after_uid: int, since: datetime) -> list[int]:
        typ, data = self.imap.uid("SEARCH", None, "UID", f"{after_uid + 1}:*", "SINCE", since.strftime("%d-%b-%Y"))
        uids = [int(x) for x in (data[0] or b"").split()] if typ == "OK" and data else []
        return sorted(u for u in uids if u > after_uid)  # "n:*" returns the newest message even when n is past it

    def headers(self, uids: list[int]) -> list[InboxMessage]:
        found = []
        for start in range(0, len(uids), 200):
            chunk = ",".join(str(u) for u in uids[start:start + 200])
            typ, data = self.imap.uid("FETCH", chunk, f"(UID X-GM-THRID BODY.PEEK[HEADER.FIELDS ({' '.join(_HEADERS)})])")
            for meta, literal in _parse_fetch(data):
                uid = re.search(rb"UID (\d+)", meta)
                thread = re.search(rb"X-GM-THRID (\d+)", meta)
                if uid:
                    found.append(InboxMessage(int(uid.group(1)), thread.group(1).decode() if thread else None,
                                              email.message_from_bytes(literal, policy=default_policy)))
        return found

    def full(self, uid: int) -> Message | None:
        typ, data = self.imap.uid("FETCH", str(uid), "(BODY.PEEK[])")
        pairs = _parse_fetch(data)
        return email.message_from_bytes(pairs[0][1], policy=default_policy) if pairs else None

    def find(self, message_id: str) -> str | None:
        """Gmail's thread id for one of our own messages, or None when Gmail has no copy of it."""
        typ, data = self.imap.uid("SEARCH", None, "X-GM-RAW", f'"rfc822msgid:{message_id.strip("<>")}"')
        uids = (data[0] or b"").split() if typ == "OK" and data else []
        if not uids:
            return None
        typ, data = self.imap.uid("FETCH", uids[-1].decode(), "(X-GM-THRID)")
        for item in data or []:
            line = item[0] if isinstance(item, tuple) else item
            m = re.search(rb"X-GM-THRID (\d+)", line or b"")
            if m:
                return m.group(1).decode()
        return ""


def is_auto_reply(headers: Message) -> bool:
    auto = (headers.get("Auto-Submitted") or "").strip().lower()
    if auto and auto != "no":
        return True
    if headers.get("X-Autoreply") or headers.get("X-Autorespond"):
        return True
    if (headers.get("Precedence") or "").strip().lower() in ("auto_reply", "bulk", "junk"):
        return True
    return bool(_AUTO_SUBJECT.search(str(headers.get("Subject") or "")))


def _refs(headers: Message) -> set[str]:
    text = f"{headers.get('In-Reply-To') or ''} {headers.get('References') or ''}"
    return set(re.findall(r"<[^<>\s]+>", text))


def _text_of(msg: Message) -> str:
    part = msg.get_body(preferencelist=("plain", "html")) if hasattr(msg, "get_body") else None
    try:
        text = part.get_content() if part else ""
    except (LookupError, ValueError):
        text = ""
    text = re.sub(r"<[^>]+>", " ", text)
    lines = []
    for line in text.splitlines():
        if line.startswith(">") or re.match(r"^\s*On .+ wrote:\s*$", line):
            break
        lines.append(line)
    return " ".join(" ".join(lines).split())[:400]


def _as_text(part) -> str:
    try:
        return part.as_string() if hasattr(part, "as_string") else str(part)
    except (AttributeError, LookupError, ValueError):
        return ""


def bounce_info(msg: Message) -> tuple[str | None, str | None, set[str]]:
    """(status like "5.1.1", failed recipient, Message-IDs of the bounced email) from a delivery report."""
    status = recipient = None
    ids: set[str] = set()
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype == "message/delivery-status":
            payload = part.get_payload()
            blocks = payload if isinstance(payload, list) else [payload]
            for block in blocks:
                text = _as_text(block)
                m = re.search(r"^Status:\s*([245]\.\d+\.\d+)", text, re.M | re.I)
                status = status or (m.group(1) if m else None)
                m = re.search(r"^(?:Final|Original)-Recipient:\s*(?:rfc822;)?\s*<?([^>\s]+@[^>\s]+)>?", text, re.M | re.I)
                recipient = recipient or (m.group(1).lower() if m else None)
        elif ctype in ("message/rfc822", "text/rfc822-headers", "message/rfc822-headers"):
            ids |= set(re.findall(r"^Message-ID:\s*(<[^>]+>)", _as_text(part), re.M | re.I))
    if not recipient and msg.get("X-Failed-Recipients"):
        recipient = str(msg["X-Failed-Recipients"]).strip().lower()
    if not status:
        m = re.search(r"\b([245]\.\d\.\d{1,3})\b", _as_text(msg))
        status = m.group(1) if m else None
    return status, recipient, ids


@dataclass
class ScanResult:
    scanned: int = 0
    replies: int = 0
    probable: int = 0
    auto_replies: int = 0
    bounces: int = 0
    test_replies: int = 0
    resolved: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower() if "@" in address else ""


def scan_inbox(store: JobStore, inbox: GmailInbox, account: MailAccount, config: OutreachConfig,
               now: datetime) -> ScanResult:
    result = ScanResult()
    ours = {r["message_id"]: r for r in store.conn.execute("SELECT * FROM sent_mail WHERE state != 'failed'")}
    if not ours:
        result.notes.append("nothing sent yet")
        return result
    inbox.open_all_mail()
    # 1. Sends that ended without a clear answer: Gmail's Sent copy decides.
    for row in [r for r in ours.values() if r["state"] == "sending"]:
        thread = inbox.find(row["message_id"])
        if thread is not None:
            store.conn.execute("UPDATE sent_mail SET thread_id = ? WHERE id = ?", (thread or None, row["id"]))
            _mark_sent(store, row["id"], parse_datetime(row["created_at"]), config)
            result.resolved.append(f"#{row['job_id']}: it went out")
        elif now - parse_datetime(row["created_at"]) > UNSURE_AFTER:
            store.conn.execute("UPDATE sent_mail SET state = 'failed', error = 'Gmail has no copy: not sent' "
                               "WHERE id = ?", (row["id"],))
            result.resolved.append(f"#{row['job_id']}: it did not go out; you can send it again")
    store.commit()
    ours = {r["message_id"]: r for r in store.conn.execute("SELECT * FROM sent_mail WHERE state = 'sent'")}
    # 2. Gmail thread ids of our sent emails.
    for row in ours.values():
        if not row["thread_id"]:
            thread = inbox.find(row["message_id"])
            if thread:
                store.conn.execute("UPDATE sent_mail SET thread_id = ? WHERE id = ?", (thread, row["id"]))
    store.commit()
    ours = {r["message_id"]: r for r in store.conn.execute("SELECT * FROM sent_mail WHERE state = 'sent'")}
    if not ours:
        return result
    threads: dict[str, sqlite3.Row] = {}
    for row in sorted(ours.values(), key=lambda r: r["kind"] == "test"):  # a real email wins a shared thread
        if row["thread_id"]:
            threads.setdefault(row["thread_id"], row)
    domains: dict[str, sqlite3.Row] = {}
    for row in ours.values():
        d = _domain(row["to_addr"])
        if row["kind"] != "test" and d and d not in _WEBMAIL and d != _domain(account.address):
            domains.setdefault(d, row)
    # 3. New mail since the last check.
    if store.get_kv("imap_uidvalidity") != inbox.uidvalidity:
        store.set_kv("imap_uidvalidity", inbox.uidvalidity)
        store.set_kv("imap_last_uid", "0")
    last_uid = int(store.get_kv("imap_last_uid") or 0)
    since = min(parse_datetime(r["sent_at"]) for r in ours.values()) - timedelta(days=1)
    uids = inbox.search(last_uid, since)
    for message in inbox.headers(uids):
        result.scanned += 1
        _handle(store, inbox, message, ours, threads, domains, account, now, result)
        last_uid = max(last_uid, message.uid)
    store.set_kv("imap_last_uid", str(last_uid))
    store.commit()
    return result


def _handle(store: JobStore, inbox: GmailInbox, message: InboxMessage, ours: dict, threads: dict, domains: dict,
            account: MailAccount, now: datetime, result: ScanResult) -> None:
    h = message.headers
    message_id = str(h.get("Message-ID") or "").strip()
    if message_id in ours:
        return  # our own sent copy
    key = message_id or f"uid:{inbox.uidvalidity}:{message.uid}"
    if store.conn.execute("SELECT 1 FROM mail_seen WHERE message_key = ?", (key,)).fetchone():
        return
    sender = parseaddr(str(h.get("From") or ""))[1].lower()
    subject = str(h.get("Subject") or "")
    try:
        when = parsedate_to_datetime(str(h.get("Date"))) if h.get("Date") else now
    except (TypeError, ValueError):
        when = now
    kind, job_id = "other", None
    refs = _refs(h) & set(ours)
    linked = [ours[r] for r in refs]
    if not linked and message.thread_id in threads:
        linked = [threads[message.thread_id]]
    real = [r for r in linked if r["kind"] != "test"]
    if _BOUNCE_FROM.search(sender) or "multipart/report" in str(h.get("Content-Type") or "").lower():
        full = inbox.full(message.uid)
        status, recipient, bounced_ids = bounce_info(full) if full else (None, None, set())
        hit = [ours[i] for i in bounced_ids if i in ours] or real or \
            [r for r in ours.values() if recipient and r["to_addr"].lower() == recipient]
        hit = [r for r in hit if r["kind"] != "test"]
        if hit and status and status.startswith("5"):
            job_id = hit[0]["job_id"]
            if tracking.record_bounce(store, job_id, hit[0]["to_addr"], f"status {status}", now, ref=key):
                result.bounces += 1
            kind = "bounce"
        elif hit:
            job_id, kind = hit[0]["job_id"], "delayed"
    elif sender == account.address:
        tests = [r for r in linked if r["kind"] == "test"]
        if tests and not real:
            job_id, kind = tests[0]["job_id"], "test_reply"
            full = inbox.full(message.uid)
            if tracking.add_event(store, job_id, "test", f"Reply to your test email: {_text_of(full) if full else subject}",
                                  now, ref=key):
                result.test_replies += 1
        else:
            kind = "mine"  # your own mail, e.g. a reply you wrote in Gmail
    else:
        probable = False
        if not real:
            match = domains.get(_domain(sender))
            if match and parse_datetime(match["sent_at"]) <= when:
                real, probable = [match], True
        if real:
            job_id = real[0]["job_id"]
            if is_auto_reply(h):
                kind = "auto_reply"
                if tracking.record_auto_reply(store, job_id, sender, subject, now, ref=key):
                    result.auto_replies += 1
            else:
                kind = "probable_reply" if probable else "reply"
                full = inbox.full(message.uid)
                snippet = _text_of(full) if full else subject
                if tracking.record_reply(store, job_id, when, sender, snippet, now, ref=key, probable=probable):
                    result.probable += probable
                    result.replies += not probable
    store.conn.execute("INSERT OR IGNORE INTO mail_seen (message_key, job_id, kind, seen_at) VALUES (?, ?, ?, ?)",
                       (key, job_id, kind, iso(now)))


def check_inbox(store: JobStore, account: MailAccount, config: OutreachConfig, now: datetime,
                inbox: GmailInbox | None = None) -> ScanResult:
    """Scan, then close as ghosted what waited long enough. Opens (and closes) its own IMAP connection."""
    has_mail = store.conn.execute("SELECT 1 FROM sent_mail WHERE state != 'failed' LIMIT 1").fetchone()
    result = ScanResult()
    if has_mail:
        own = inbox is None
        inbox = inbox or GmailInbox(account)
        try:
            result = scan_inbox(store, inbox, account, config, now)
        finally:
            if own:
                inbox.close()
    else:
        result.notes.append("nothing sent yet")
    ghosted = tracking.apply_ghosting(store, now, config)
    if ghosted:
        result.notes.append(f"{len(ghosted)} closed as ghosted")
    store.commit()
    return result
