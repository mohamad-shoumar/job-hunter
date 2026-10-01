"""Sending (through a fake SMTP sender) and reading replies and bounces (through a fake inbox)."""

import email
from datetime import timedelta
from email.message import EmailMessage
from email.policy import default as default_policy

import pytest

from jobhunter import tracking
from jobhunter.config import OutreachConfig
from jobhunter.contacts import save_manual_contact
from jobhunter.mailer import (
    GmailInbox, InboxMessage, MailAccount, NotSent, SendError, Unsure, bounce_info, build_message, is_auto_reply,
    new_message_id, scan_inbox, send_for_job,
)
from jobhunter.pitch import edit_draft, load_profile
from jobhunter.store import JobStore
from jobhunter.text import iso

from .conftest import FIXTURES, NOW, ROOT, store_job

PROFILE = load_profile(FIXTURES / "profile" / "master_profile.md")
ME = MailAccount("me@gmail.com", "app-password", "Mohamad Shoumar")
CONFIG = OutreachConfig()
BODY = "Hi Ana,\n\nI saw you're hiring. I built RESTful APIs in Python.\n\nMohamad Shoumar"


class FakeSender:
    def __init__(self, error=None):
        self.sent: list[EmailMessage] = []
        self.error = error

    def send(self, msg):
        if self.error:
            raise self.error
        self.sent.append(msg)


def ready_job(store, filters, email="ana@acme.io", company="Acme", source_job_id="1") -> int:
    job_id = store_job(store, filters, company=company, source_job_id=source_job_id)
    save_manual_contact(store, job_id, "Ana Ruiz", email, "CEO", NOW)
    edit_draft(store, job_id, "Python backend role at Acme", BODY, PROFILE, NOW)
    return job_id


def send(store, job_id, sender, when=NOW, **kwargs):
    version = tracking.get_application(store, job_id)["draft_version"]
    return send_for_job(store, job_id, sender, ME, PROFILE, CONFIG, when, draft_version=version, **kwargs)


def test_message_ids_do_not_leak_the_mac_s_name():
    mid = new_message_id()
    assert mid.startswith("<") and mid.endswith("@gmail.com>")
    msg = build_message(ME, "ana@acme.io", "Re: hi", "Body", mid, in_reply_to="<a@gmail.com>",
                        references=["<a@gmail.com>", "<b@gmail.com>"])
    assert msg["From"] == "Mohamad Shoumar <me@gmail.com>" and msg["In-Reply-To"] == "<a@gmail.com>"
    assert msg["References"] == "<a@gmail.com> <b@gmail.com>" and msg.get_content_type() == "multipart/alternative"
    assert msg.get_body(("plain",)).get_content().strip() == "Body" and msg.get_body(("html",)) is not None


def test_sending_records_the_email_and_starts_the_follow_up_timer(filters):
    store = JobStore(":memory:")
    job_id = ready_job(store, filters)
    sender = FakeSender()
    result = send(store, job_id, sender, seq=0)
    assert result["to"] == "ana@acme.io" and len(sender.sent) == 1
    assert sender.sent[0].get_body(("plain",)).get_content().strip().startswith("Hi Ana,")
    app = tracking.get_application(store, job_id)
    assert app["stage"] == tracking.REACHED_OUT and app["emailed_at"] == iso(NOW)
    assert app["next_follow_up_at"] == iso(tracking.add_business_days(NOW, 4))


def test_a_double_click_does_not_send_twice(filters):
    store = JobStore(":memory:")
    job_id = ready_job(store, filters)
    sender = FakeSender()
    send(store, job_id, sender, seq=0)
    with pytest.raises(SendError, match="sent already"):
        send(store, job_id, sender, seq=0)
    with pytest.raises(SendError) as err:  # the follow-up is not due yet
        send(store, job_id, sender, seq=1)
    assert err.value.confirm == "early" and len(sender.sent) == 1


def test_the_follow_up_replies_in_the_thread(filters):
    store = JobStore(":memory:")
    job_id = ready_job(store, filters)
    sender = FakeSender()
    send(store, job_id, sender)
    later = tracking.add_business_days(NOW, 5)
    send(store, job_id, sender, when=later, seq=1)
    first, follow = sender.sent
    assert follow["Subject"] == "Re: Python backend role at Acme" and follow["In-Reply-To"] == first["Message-ID"]
    assert tracking.get_application(store, job_id)["follow_ups"] == 1


def test_a_changed_draft_is_not_sent(filters):
    store = JobStore(":memory:")
    job_id = ready_job(store, filters)
    with pytest.raises(SendError, match="draft changed"):
        send_for_job(store, job_id, FakeSender(), ME, PROFILE, CONFIG, NOW, draft_version=0)


def test_a_refused_send_can_be_retried_and_an_unclear_one_waits(filters):
    store = JobStore(":memory:")
    job_id = ready_job(store, filters)
    with pytest.raises(SendError, match="Not sent"):
        send(store, job_id, FakeSender(NotSent("Gmail refused the login")))
    assert tracking.get_application(store, job_id)["emailed_at"] is None
    with pytest.raises(SendError, match="did not confirm"):
        send(store, job_id, FakeSender(Unsure("timeout")))
    assert store.conn.execute("SELECT state FROM sent_mail ORDER BY id DESC").fetchone()[0] == "sending"
    with pytest.raises(SendError, match="already sent"):  # blocked until the inbox check decides
        send(store, job_id, FakeSender())


def test_guessed_addresses_and_second_emails_at_a_company_need_a_yes(filters):
    store = JobStore(":memory:")
    job_id = ready_job(store, filters)
    store.conn.execute("UPDATE contacts SET email_status = 'guessed'")
    with pytest.raises(SendError) as err:
        send(store, job_id, FakeSender())
    assert err.value.confirm == "guessed"
    send(store, job_id, FakeSender(), confirm={"guessed"})
    other = store_job(store, filters, company="Acme", source_job_id="2", title="Python Engineer")
    edit_draft(store, other, "Another role", BODY, PROFILE, NOW)
    store.conn.execute("UPDATE applications SET contact_id = (SELECT id FROM contacts) WHERE job_id = ?", (other,))
    with pytest.raises(SendError) as err:
        send(store, other, FakeSender(), confirm={"guessed"})
    assert err.value.confirm == "same_company" and "ana@acme.io" in str(err.value)


def test_the_daily_cap_and_blocked_drafts_stop_sending(filters):
    store = JobStore(":memory:")
    job_id = ready_job(store, filters)
    store.conn.execute("UPDATE applications SET draft_blocked = 1")
    with pytest.raises(SendError, match="problems"):
        send(store, job_id, FakeSender())
    store.conn.execute("UPDATE applications SET draft_blocked = 0")
    config = OutreachConfig(daily_send_cap=0)
    version = tracking.get_application(store, job_id)["draft_version"]
    with pytest.raises(SendError, match="Daily limit"):
        send_for_job(store, job_id, FakeSender(), ME, PROFILE, config, NOW, draft_version=version)


def test_a_test_send_goes_to_you_and_counts_for_nothing(filters):
    store = JobStore(":memory:")
    job_id = ready_job(store, filters)
    sender = FakeSender()
    send(store, job_id, sender, test=True)
    assert sender.sent[0]["To"] == "me@gmail.com" and sender.sent[0]["Subject"].startswith("[test] ")
    app = tracking.get_application(store, job_id)
    assert app["emailed_at"] is None and tracking.sends_today(store, NOW)["total"] == 0
    send(store, job_id, sender, seq=0)  # the real one still goes out
    assert sender.sent[1]["To"] == "ana@acme.io"


# --- reading the inbox ---------------------------------------------------------------


def mail(sender, subject, in_reply_to=None, message_id=None, extra=None, body="Thanks, let's talk.\n\nOn Mon, Ana wrote:\n> hi"):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ME.address
    msg["Subject"] = subject
    msg["Date"] = "Mon, 28 Sep 2026 10:00:00 +0000"
    msg["Message-ID"] = message_id or new_message_id()
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    for k, v in (extra or {}).items():
        msg[k] = v
    msg.set_content(body)
    return msg


def dsn(status, recipient, original_id):
    """A delivery report as Gmail's mailer-daemon sends it, parsed from raw text like IMAP bytes."""
    raw = f"""From: Mail Delivery Subsystem <mailer-daemon@googlemail.com>
To: me@gmail.com
Subject: Delivery Status Notification (Failure)
Message-ID: {new_message_id()}
MIME-Version: 1.0
Content-Type: multipart/report; report-type=delivery-status; boundary="b1"

--b1
Content-Type: text/plain; charset=UTF-8

Address not found

--b1
Content-Type: message/delivery-status

Reporting-MTA: dns; googlemail.com

Final-Recipient: rfc822; {recipient}
Action: failed
Status: {status}

--b1
Content-Type: text/rfc822-headers

Message-ID: {original_id}
To: {recipient}
Subject: Python backend role

--b1--
"""
    return email.message_from_string(raw, policy=default_policy)


class FakeInbox:
    def __init__(self, messages, threads=None):
        self.messages = {uid: (m, thread) for uid, (m, thread) in enumerate(messages, start=100)}
        self.threads = threads or {}
        self.uidvalidity = "7"

    def open_all_mail(self):
        return "[Gmail]/All Mail"

    def find(self, message_id):
        return self.threads.get(message_id)

    def search(self, after_uid, since):
        return [u for u in self.messages if u > after_uid]

    def headers(self, uids):
        return [InboxMessage(u, self.messages[u][1], self.messages[u][0]) for u in uids]

    def full(self, uid):
        return self.messages[uid][0]


def sent_job(store, filters, **kwargs):
    job_id = ready_job(store, filters, **kwargs)
    sender = FakeSender()
    send(store, job_id, sender)
    return job_id, sender.sent[0]["Message-ID"]


def test_a_reply_moves_the_job_and_a_second_scan_changes_nothing(filters):
    store = JobStore(":memory:")
    job_id, mid = sent_job(store, filters)
    inbox = FakeInbox([(mail("Ana Ruiz <ana@acme.io>", "Re: Python backend role at Acme", in_reply_to=mid), "t1")])
    result = scan_inbox(store, inbox, ME, CONFIG, NOW + timedelta(days=1))
    app = tracking.get_application(store, job_id)
    assert result.replies == 1 and app["stage"] == tracking.REPLIED and app["reply_snippet"] == "Thanks, let's talk."
    assert app["next_follow_up_at"] is None
    assert scan_inbox(store, inbox, ME, CONFIG, NOW + timedelta(days=1)).replies == 0
    assert len([e for e in tracking.events_for(store, job_id) if e["kind"] == "replied"]) == 1


def test_your_own_mail_and_out_of_office_are_not_replies(filters):
    store = JobStore(":memory:")
    job_id, mid = sent_job(store, filters)
    inbox = FakeInbox([
        (mail(ME.address, "Re: Python backend role at Acme", in_reply_to=mid), "t1"),
        (mail("ana@acme.io", "Automatic reply: Python backend role", in_reply_to=mid), "t1"),
        (mail("ana@acme.io", "Re: role", in_reply_to=mid, extra={"Auto-Submitted": "auto-replied"}), "t1"),
    ])
    result = scan_inbox(store, inbox, ME, CONFIG, NOW)
    assert (result.replies, result.auto_replies) == (0, 2)
    assert tracking.get_application(store, job_id)["stage"] == tracking.REACHED_OUT


def test_a_colleague_at_the_company_is_a_probable_reply(filters):
    store = JobStore(":memory:")
    job_id, _ = sent_job(store, filters)
    inbox = FakeInbox([(mail("Kim Ho <kim@acme.io>", "Your note to Ana"), "t9")])
    result = scan_inbox(store, inbox, ME, CONFIG, NOW)
    assert result.probable == 1 and tracking.get_application(store, job_id)["stage"] == tracking.REPLIED


def test_a_permanent_bounce_marks_the_address_and_a_delay_does_not(filters):
    store = JobStore(":memory:")
    job_id, mid = sent_job(store, filters)
    status, recipient, ids = bounce_info(dsn("5.1.1", "ana@acme.io", mid))
    assert (status, recipient, ids) == ("5.1.1", "ana@acme.io", {mid})
    scan_inbox(store, FakeInbox([(dsn("4.4.7", "ana@acme.io", mid), "t1")]), ME, CONFIG, NOW)
    assert store.conn.execute("SELECT email_status FROM contacts").fetchone()[0] == "manual"
    result = scan_inbox(store, FakeInbox([(dsn("4.4.7", "ana@acme.io", mid), "t1"),
                                          (dsn("5.1.1", "ana@acme.io", mid), "t1")]), ME, CONFIG, NOW)
    assert result.bounces == 1
    assert store.conn.execute("SELECT email_status FROM contacts").fetchone()[0] == "bounced"
    assert tracking.get_application(store, job_id)["next_follow_up_at"] is None


def test_your_reply_to_a_test_email_is_only_noted(filters):
    store = JobStore(":memory:")
    job_id = ready_job(store, filters)
    sender = FakeSender()
    send(store, job_id, sender, test=True)
    test_id = sender.sent[0]["Message-ID"]
    inbox = FakeInbox([(mail(ME.address, "Re: [test] Python backend role", in_reply_to=test_id, body="Looks good"), "t1")])
    result = scan_inbox(store, inbox, ME, CONFIG, NOW)
    assert result.test_replies == 1
    assert tracking.get_application(store, job_id)["stage"] == tracking.NEW
    assert any("Reply to your test email: Looks good" in e["detail"] for e in tracking.events_for(store, job_id))


def test_an_unclear_send_is_settled_by_gmail_s_copy(filters):
    store = JobStore(":memory:")
    job_id = ready_job(store, filters)
    with pytest.raises(SendError):
        send(store, job_id, FakeSender(Unsure("timeout")))
    mid = store.conn.execute("SELECT message_id FROM sent_mail").fetchone()[0]
    result = scan_inbox(store, FakeInbox([], threads={mid: "t1"}), ME, CONFIG, NOW + timedelta(minutes=1))
    assert result.resolved == [f"#{job_id}: it went out"]
    assert tracking.get_application(store, job_id)["emailed_at"] is not None

    store = JobStore(":memory:")
    job_id = ready_job(store, filters)
    with pytest.raises(SendError):
        send(store, job_id, FakeSender(Unsure("timeout")))
    result = scan_inbox(store, FakeInbox([]), ME, CONFIG, NOW + timedelta(minutes=30))
    assert "did not go out" in result.resolved[0]
    send(store, job_id, FakeSender())  # now it can be sent again


def test_auto_reply_headers():
    assert is_auto_reply(mail("a@b.co", "Out of Office: back Monday"))
    assert is_auto_reply(mail("a@b.co", "Hello", extra={"Precedence": "auto_reply"}))
    assert not is_auto_reply(mail("a@b.co", "Re: Python role", extra={"Auto-Submitted": "no"}))


class FakeImap:
    """Just enough of imaplib.IMAP4 for GmailInbox's parsing."""

    def __init__(self):
        self.commands = []

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\All \\HasNoChildren) "/" "[Gmail]/Tous les messages"']

    def select(self, name, readonly=False):
        self.commands.append(("select", name, readonly))
        return "OK", [b"3"]

    def response(self, name):
        return name, [b"42"]

    def uid(self, command, *args):
        self.commands.append((command, *args))
        if command == "SEARCH":
            return "OK", [b"100 101"]
        raw = mail("ana@acme.io", "Re: hi").as_bytes()
        return "OK", [(b"1 (UID 101 X-GM-THRID 1790 BODY[HEADER.FIELDS (FROM)] {%d}" % len(raw), raw), b")"]


def test_gmail_inbox_opens_all_mail_read_only_in_any_language():
    imap = FakeImap()
    inbox = GmailInbox(ME, imap=imap)
    assert inbox.open_all_mail() == "[Gmail]/Tous les messages" and inbox.uidvalidity == "42"
    assert ("select", '"[Gmail]/Tous les messages"', True) in imap.commands
    assert inbox.search(100, NOW) == [101]  # "101:*" can return the newest message again
    [message] = inbox.headers([101])
    assert (message.uid, message.thread_id, str(message.headers["From"])) == (101, "1790", "ana@acme.io")
    assert any("BODY.PEEK" in " ".join(map(str, c)) for c in imap.commands)


def test_the_cv_is_attached_unless_you_pick_none(filters, tmp_path):
    (tmp_path / "Shoumar_Resume_General.pdf").write_bytes(b"%PDF-1.4 cv")
    config = OutreachConfig(cv_dir=str(tmp_path))
    store = JobStore(":memory:")
    job_id = ready_job(store, filters)
    sender = FakeSender()
    version = tracking.get_application(store, job_id)["draft_version"]
    send_for_job(store, job_id, sender, ME, PROFILE, config, NOW, draft_version=version)
    [attachment] = list(sender.sent[0].iter_attachments())
    assert attachment.get_filename() == "Shoumar_Resume_General.pdf" and attachment.get_content() == b"%PDF-1.4 cv"
    other = ready_job(store, filters, company="Beta", email="bo@beta.io", source_job_id="2")
    store.conn.execute("UPDATE applications SET cv_file = 'none' WHERE job_id = ?", (other,))
    sender = FakeSender()
    version = tracking.get_application(store, other)["draft_version"]
    send_for_job(store, other, sender, ME, PROFILE, config, NOW, draft_version=version)
    assert list(sender.sent[0].iter_attachments()) == []
