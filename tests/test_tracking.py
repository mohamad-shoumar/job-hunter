"""Stages, the timeline, follow-up dates, ghosting and the Today view."""

from datetime import datetime, timedelta, timezone

import pytest

from jobhunter import tracking
from jobhunter.config import OutreachConfig
from jobhunter.store import JobStore
from jobhunter.text import iso

from .conftest import NOW, store_job

CONFIG = OutreachConfig()


@pytest.fixture
def store():
    return JobStore(":memory:")


def test_business_days_skip_the_weekend():
    friday = datetime(2026, 9, 25, 9, tzinfo=timezone.utc)
    assert friday.weekday() == 4
    assert tracking.add_business_days(friday, 1).weekday() == 0  # Monday
    assert tracking.add_business_days(friday, 4) == datetime(2026, 10, 1, 9, tzinfo=timezone.utc)  # Thursday


def test_a_new_row_is_silent_and_stage_changes_are_logged(store, filters):
    job_id = store_job(store, filters)
    row = tracking.ensure_application(store, job_id, NOW)
    assert row["stage"] == tracking.NEW and tracking.events_for(store, job_id) == []
    tracking.set_stage(store, job_id, tracking.SAVED, NOW)
    tracking.set_stage(store, job_id, tracking.CLOSED, NOW, reason="skipped")
    assert [e["detail"] for e in tracking.events_for(store, job_id)] == ["New → Saved", "Saved → Closed (skipped)"]


def test_closing_needs_a_reason_and_stages_are_checked(store, filters):
    job_id = store_job(store, filters)
    with pytest.raises(tracking.TrackingError):
        tracking.set_stage(store, job_id, tracking.CLOSED, NOW)
    with pytest.raises(tracking.TrackingError):
        tracking.set_stage(store, job_id, "hired", NOW)


def test_applying_moves_a_new_job_to_reached_out(store, filters):
    job_id = store_job(store, filters)
    row = tracking.mark_applied(store, job_id, NOW, NOW)
    assert row["stage"] == tracking.REACHED_OUT and row["applied_at"] == iso(NOW)


def test_follow_ups_are_scheduled_then_stop(store, filters):
    job_id = store_job(store, filters)
    tracking.record_sent(store, job_id, 0, "ceo@acme.com", NOW, CONFIG)
    row = tracking.get_application(store, job_id)
    assert row["stage"] == tracking.REACHED_OUT and row["emailed_at"] == iso(NOW)
    assert row["next_follow_up_at"] == iso(tracking.add_business_days(NOW, 4))
    tracking.record_sent(store, job_id, 1, "ceo@acme.com", NOW + timedelta(days=6), CONFIG)
    assert tracking.get_application(store, job_id)["next_follow_up_at"] == iso(
        tracking.add_business_days(NOW + timedelta(days=6), 7))
    tracking.record_sent(store, job_id, 2, "ceo@acme.com", NOW + timedelta(days=16), CONFIG)
    row = tracking.get_application(store, job_id)
    assert row["next_follow_up_at"] is None and row["follow_ups"] == 2


def test_a_reply_cancels_follow_ups_once(store, filters):
    job_id = store_job(store, filters)
    tracking.record_sent(store, job_id, 0, "ceo@acme.com", NOW, CONFIG)
    assert tracking.record_reply(store, job_id, NOW, "ceo@acme.com", "Sounds good, let's talk", NOW, ref="<r1>")
    assert not tracking.record_reply(store, job_id, NOW, "ceo@acme.com", "Sounds good", NOW, ref="<r1>")
    row = tracking.get_application(store, job_id)
    assert row["stage"] == tracking.REPLIED and row["next_follow_up_at"] is None
    assert row["reply_snippet"] == "Sounds good, let's talk"


def test_ghosting_after_the_whole_schedule_even_without_follow_ups(store, filters):
    job_id = store_job(store, filters)
    tracking.record_sent(store, job_id, 0, "ceo@acme.com", NOW, CONFIG)
    last_day = tracking.ghost_date(NOW, CONFIG)
    assert last_day == tracking.add_business_days(NOW, 4 + 7 + 7)
    assert tracking.apply_ghosting(store, last_day - timedelta(hours=1), CONFIG) == []
    assert tracking.apply_ghosting(store, last_day, CONFIG) == [job_id]
    row = tracking.get_application(store, job_id)
    assert (row["stage"], row["closed_reason"]) == (tracking.CLOSED, "ghosted")
    # Moved back by hand: it is not ghosted a second time.
    tracking.set_stage(store, job_id, tracking.REACHED_OUT, last_day)
    assert tracking.apply_ghosting(store, last_day + timedelta(days=5), CONFIG) == []
    # A late reply still counts.
    tracking.record_reply(store, job_id, last_day, "ceo@acme.com", "Sorry for the delay", last_day, ref="<late>")
    assert tracking.get_application(store, job_id)["stage"] == tracking.REPLIED


def test_a_bounce_marks_the_address_and_stops_follow_ups(store, filters):
    job_id = store_job(store, filters)
    store.conn.execute("INSERT INTO companies (key, name) VALUES ('acme', 'Acme')")
    store.conn.execute("INSERT INTO contacts (company_key, full_name, role, email, email_status, source, created_at) "
                       "VALUES ('acme', 'Jo', 'ceo', 'jo@acme.com', 'guessed', 'claude', ?)", (iso(NOW),))
    tracking.record_sent(store, job_id, 0, "jo@acme.com", NOW, CONFIG)
    assert tracking.record_bounce(store, job_id, "jo@acme.com", "status 5.1.1", NOW, ref="<b1>")
    assert store.conn.execute("SELECT email_status FROM contacts").fetchone()[0] == "bounced"
    assert tracking.get_application(store, job_id)["next_follow_up_at"] is None


def test_today_lists_what_needs_doing(store, filters):
    waiting = store_job(store, filters, source_job_id="1", company="Acme")
    fresh = store_job(store, filters, source_job_id="2", company="Beta")
    tracking.record_sent(store, waiting, 0, "ceo@acme.com", NOW, CONFIG)
    later = tracking.add_business_days(NOW, 5)
    view = tracking.today(store, later, CONFIG)
    assert [r["job_id"] for r in view["follow_ups_due"]] == [waiting]
    assert [r["id"] for r in view["new_jobs"]] == [fresh]
    tracking.set_stage(store, fresh, tracking.SAVED, NOW)
    assert tracking.today(store, later, CONFIG)["new_jobs"] == []


def test_send_counts_leave_out_tests_and_failures(store, filters):
    job_id = store_job(store, filters)
    for n, (kind, state, guessed) in enumerate([("first", "sent", 1), ("test", "sent", 0), ("follow_up", "failed", 0)]):
        store.conn.execute(
            "INSERT INTO sent_mail (job_id, kind, seq, message_id, to_addr, subject, body, guessed, state, created_at) "
            "VALUES (?, ?, ?, ?, 'a@b.co', 's', 'b', ?, ?, ?)", (job_id, kind, n, f"<m{n}>", guessed, state, iso(NOW)))
    assert tracking.sends_today(store, NOW) == {"total": 1, "guessed": 1}
    assert tracking.sends_today(store, NOW + timedelta(days=1)) == {"total": 0, "guessed": 0}


def test_stats_count_replies_by_role(store, filters):
    job_id = store_job(store, filters)
    store.conn.execute("INSERT INTO companies (key, name, size_range) VALUES ('acme', 'Acme', '11-50')")
    store.conn.execute("INSERT INTO contacts (id, company_key, full_name, role, email, source, created_at) "
                       "VALUES (7, 'acme', 'Jo', 'ceo', 'jo@acme.com', 'hunter', ?)", (iso(NOW),))
    store.conn.execute(
        "INSERT INTO sent_mail (job_id, contact_id, kind, seq, message_id, to_addr, subject, body, state, created_at, "
        "sent_at) VALUES (?, 7, 'first', 0, '<m>', 'jo@acme.com', 's', 'b', 'sent', ?, ?)", (job_id, iso(NOW), iso(NOW)))
    tracking.record_sent(store, job_id, 0, "jo@acme.com", NOW, CONFIG)
    tracking.record_reply(store, job_id, NOW, "jo@acme.com", "Yes", NOW, ref="<r>")
    data = tracking.stats(store, NOW, CONFIG)
    assert data["by_role"] == {"ceo": {"emailed": 1, "replied": 1}}
    assert data["by_size"] == {"≤50": {"emailed": 1, "replied": 1}}
    assert data["stages"][tracking.REPLIED] == 1
