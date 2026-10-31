"""Rejection emails close the job they are about (rejections.py), through a fake inbox."""

from datetime import timedelta
from email.message import EmailMessage

from jobhunter import tracking
from jobhunter.config import OutreachConfig
from jobhunter.mailer import MailAccount, check_inbox
from jobhunter.models import CLOSED, NEW, REACHED_OUT
from jobhunter.rejections import name_keys, names_company, rejection_sentence
from jobhunter.store import JobStore
from jobhunter.store.applications import events_for, get_application

from .conftest import NOW, store_job

ME = MailAccount("me@gmail.com", "app-password", "Me")
CONFIG = OutreachConfig()
LATER = NOW + timedelta(days=3)


def letter(sender, subject, body, date="Mon, 28 Sep 2026 10:00:00 +0000", message_id=None, html=False):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ME.address
    msg["Subject"] = subject
    msg["Date"] = date
    msg["Message-ID"] = message_id or f"<{abs(hash((sender, subject, body)))}@mail.example>"
    if html:
        msg.set_content(body, subtype="html")
    else:
        msg.set_content(body)
    return msg


class FakeInbox:
    def __init__(self, messages):
        self.messages = dict(enumerate(messages, start=500))
        self.queries = []

    def open_all_mail(self):
        return "[Gmail]/All Mail"

    def search_raw(self, query):
        self.queries.append(query)
        return list(self.messages)

    def full(self, uid):
        return self.messages[uid]

    def close(self):
        pass


def applied(store, filters, company, title, stage=REACHED_OUT, source_job_id=None):
    job_id = store_job(store, filters, company=company, title=title, source_job_id=source_job_id or f"{company}-{title}")
    tracking.set_stage(store, job_id, stage, NOW, reason="skipped" if stage == CLOSED else None)
    store.commit()
    return job_id


NO = ("Hi Mohamad, Thank you for applying for the Senior Python Developer role. After careful consideration, "
      "we regret to inform you that we've decided to move forward with another candidate. Best wishes, Talent Team")


def test_the_sentences_that_say_no():
    for text in [
        "After reviewing your application, we've decided not to move forward for this position.",
        "Unfortunately, we will not be progressing your application any further.",
        "Unfortunately, we were not able to select your application for the shortlist this time.",
        "We have decided to pursue other candidates whose experience more closely aligns.",
        "We will unfortunately not be advancing you as we have made the careful decision.",
        "After careful consideration we have decided not to proceed together for this role.",
        "We regret to inform you that the position has been filled.",
    ]:
        assert rejection_sentence(f"Hi Mohamad. {text} Best, Team") == text, text


def test_thanks_and_maybes_are_not_a_no():
    for text in [
        "Thank you for applying! Our team will review your application and get back to you.",
        "We're excited to be moving forward with your application to the next stage.",
        "If we decide not to move forward, we will let you know by email.",
        "Should we not be moving forward, you will hear from us within two weeks.",
        "Unfortunately our office is closed on Friday.",
    ]:
        assert rejection_sentence(text) is None, text


def test_company_names_match_the_sender_and_subject_not_parts_of_words():
    assert names_company("CHAOS Industries greenhouse-mail Important information", "Chaosindustries")
    assert names_company("no-reply@fanduel.com fanduel Important information", "Fanduel")
    assert names_company("imc IMC - Update on your application", "Imc")
    assert not names_company("Otherwise we will keep your CV", "Wise")
    assert not names_company("Samsung Week is here", "Sia")
    assert names_company("Woven by Toyota hire.lever Thank you for your interest in Woven by Toyota's role",
                         "Woven By Toyota")
    assert name_keys("Codest Ltd. Company No. 12590542, VAT number: GB363431020")[-1] == "codest"
    assert name_keys("Confidential") == []


def test_a_rejection_closes_the_job_and_quotes_the_email(filters):
    store = JobStore(":memory:")
    job_id = applied(store, filters, "GoReel", "Senior Python Developer")
    inbox = FakeInbox([letter("GoReel <noreply@candidates.workablemail.com>", "Senior Python Developer - GoReel", NO)])
    result = check_inbox(store, ME, CONFIG, LATER, inbox=inbox)
    app = get_application(store, job_id)
    assert (app["stage"], app["closed_reason"]) == (CLOSED, "rejected")
    assert len(result.rejected) == 1 and "GoReel" in result.rejected[0]
    [event] = [e for e in events_for(store, job_id) if "Closed" in e["detail"]]
    assert "regret to inform you" in event["detail"] and 'names the role "Senior Python Developer"' in event["detail"]
    assert "after:2026/09/24" in inbox.queries[0]  # from a day before the oldest open application
    # A second check changes nothing and reports nothing.
    again = check_inbox(store, ME, CONFIG, LATER + timedelta(hours=12), inbox=inbox)
    assert again.rejected == [] and len([e for e in events_for(store, job_id) if "Closed" in e["detail"]]) == 1


def test_the_role_named_picks_the_job_and_a_closed_one_closes_nothing(filters):
    """Wayve: the Platform Integration rejection must not close Map & Route."""
    store = JobStore(":memory:")
    maps = applied(store, filters, "Wayve", "Software Engineer - Map & Route")
    platform = applied(store, filters, "Wayve", "Senior Software Engineer - Platform Integration")
    body = ("We've reviewed your application for Senior Software Engineer - Platform Integration, and on this "
            "occasion we won't be moving forward.")
    inbox = FakeInbox([letter("Wayve London Engineering <no-reply@ashbyhq.com>",
                              "Update on your application at Wayve - Senior Software Engineer - Platform Integration", body)])
    check_inbox(store, ME, CONFIG, LATER, inbox=inbox)
    assert get_application(store, platform)["stage"] == CLOSED
    assert get_application(store, maps)["stage"] == REACHED_OUT


def test_the_only_open_application_is_picked_when_no_role_is_named(filters):
    store = JobStore(":memory:")
    job_id = applied(store, filters, "Woven By Toyota", "Software Engineer - Calibration")
    body = "Thank you for your application. We will unfortunately not be advancing you at this time."
    inbox = FakeInbox([letter("Woven by Toyota <mail@hire.lever.co>", "Thank you for your interest in Woven by Toyota", body)])
    result = check_inbox(store, ME, CONFIG, LATER, inbox=inbox)
    assert get_application(store, job_id)["stage"] == CLOSED
    assert "the only open application there" in result.rejected[0]


def test_several_open_jobs_and_no_role_named_changes_nothing_and_says_so(filters):
    store = JobStore(":memory:")
    a = applied(store, filters, "Wise", "Software Engineer")
    b = applied(store, filters, "Wise", "Senior Backend Engineer - Risk Domain")
    body = "Thank you for your application. Unfortunately, we have decided not to move forward."
    result = check_inbox(store, ME, CONFIG, LATER, inbox=FakeInbox([letter("Wise <jobs@wise.com>", "Your Wise application", body)]))
    assert {get_application(store, a)["stage"], get_application(store, b)["stage"]} == {REACHED_OUT}
    assert result.rejected == [] and any("2 open applications there" in n for n in result.notes)


def test_no_close_from_job_boards_bodies_or_mail_before_you_applied(filters):
    store = JobStore(":memory:")
    job_id = applied(store, filters, "Lyst", "Software Engineer - Affiliate Operations", stage=NEW)
    inbox = FakeInbox([
        # A job alert from a board, naming the company.
        letter("LinkedIn <jobs-noreply@linkedin.com>", "Lyst is hiring", "Your application to Acme: we will not be moving forward."),
        # The company only in the body.
        letter("Acme <no-reply@ashbyhq.com>", "Update on your application", "We will not be moving forward. Lyst is our client."),
        # Before the application started.
        letter("Lyst <noreply@candidates.workablemail.com>", "Software Engineer - Lyst",
               "Your application: we will not be progressing your application.", date="Mon, 01 Jun 2026 10:00:00 +0000"),
    ])
    result = check_inbox(store, ME, CONFIG, LATER, inbox=inbox)
    assert get_application(store, job_id)["stage"] == NEW and result.rejected == []


def test_html_only_rejections_are_read(filters):
    store = JobStore(":memory:")
    job_id = applied(store, filters, "Graphcore", "Software Engineer - Triton")
    body = "<p>Hi Mohamad,</p><p>After reviewing your application, we regret to inform you that we have decided not to proceed further.</p>"
    check_inbox(store, ME, CONFIG, LATER, inbox=FakeInbox([
        letter("no-reply@graphcore.ai", "Update on your application to Graphcore", body, html=True)]))
    assert get_application(store, job_id)["stage"] == CLOSED


def test_a_dry_run_changes_nothing(filters):
    store = JobStore(":memory:")
    job_id = applied(store, filters, "GoReel", "Senior Python Developer")
    inbox = FakeInbox([letter("GoReel <noreply@candidates.workablemail.com>", "Senior Python Developer - GoReel", NO)])
    result = check_inbox(store, ME, CONFIG, LATER, inbox=inbox, dry_run=True)
    assert len(result.rejected) == 1 and get_application(store, job_id)["stage"] == REACHED_OUT
    # ...and the real run still finds it.
    assert len(check_inbox(store, ME, CONFIG, LATER, inbox=inbox).rejected) == 1


def test_turned_off_it_never_searches(filters):
    store = JobStore(":memory:")
    applied(store, filters, "GoReel", "Senior Python Developer")
    inbox = FakeInbox([letter("GoReel <noreply@candidates.workablemail.com>", "Senior Python Developer - GoReel", NO)])
    off = OutreachConfig(auto_close_rejections=False)
    result = check_inbox(store, ME, off, LATER, inbox=inbox)
    assert inbox.queries == [] and result.rejected == [] and result.notes == ["nothing sent yet"]


def test_entities_short_titles_and_one_company_spelled_two_ways(filters):
    """Wise wrote "we&rsquo;ve" and "Platform Engineer - Compute &nbsp;role" for "Platform Engineer - Compute - Python";
    the database has the company as both "SumUp" and "sumup"."""
    store = JobStore(":memory:")
    compute = applied(store, filters, "Wise", "Platform Engineer - Compute - Python")
    other = applied(store, filters, "Wise", "Senior Backend Engineer - Risk Domain")
    old = applied(store, filters, "sumup", "Backend Engineer", stage=CLOSED)
    sumup = applied(store, filters, "SumUp", "Senior Backend Engineer - Run & Grow")
    wise = ("Thanks for your application. We&rsquo;ve decided not to move forward with your application for the "
            "Platform Engineer - Compute &nbsp;role.")
    no = "Thank you for your application. We regret to inform you that we have decided not to move forward."
    result = check_inbox(store, ME, CONFIG, LATER, inbox=FakeInbox([
        letter("Wise <careers@wise.jobs>", "Important info about your application to Wise", wise),
        letter("SumUp <careers@sumup.com>", "Your application at sumup", no),
    ]))
    assert get_application(store, compute)["stage"] == CLOSED and get_application(store, other)["stage"] == REACHED_OUT
    assert get_application(store, sumup)["stage"] == CLOSED and get_application(store, old)["closed_reason"] == "skipped"
    assert all("&rsquo;" not in line for line in result.rejected)


def test_a_rejection_from_a_company_with_nothing_open_is_not_listed(filters):
    store = JobStore(":memory:")
    applied(store, filters, "Axmed", "Backend Engineer", stage=CLOSED)
    applied(store, filters, "GoReel", "Senior Python Developer")
    result = check_inbox(store, ME, CONFIG, LATER, inbox=FakeInbox([
        letter("Axmed <jobs@axmed.com>", "Your application", "Unfortunately, we are not going to progress your "
               "application. We have decided not to move forward.")]))
    assert result.rejected == [] and result.notes == []
