"""One role stored twice: which copy stays and which is rejected `duplicate_role` (duplicates.py)."""

from datetime import timedelta

from jobhunter import pipeline
from jobhunter.duplicates import duplicates, fold, place_words, same_place
from jobhunter.identity import fingerprint
from jobhunter.models import DUPLICATE_ROLE, REJECTED, SHORTLISTED, VISA_LIST
from jobhunter.sources import SourceResult
from jobhunter.store import JobStore
from jobhunter.tracking import set_stage
from jobhunter.store.lists import role_copies, roles_with_copies

from .conftest import NOW, make_job, store_job


def test_a_location_keeps_only_the_words_that_say_where_it_is():
    assert place_words("London (hybrid), United Kingdom") == {"london", "united", "kingdom"}
    assert place_words("Remote") == set()
    assert place_words("Worldwide") == set()


def test_the_same_city_written_two_ways_is_one_place():
    assert same_place("London", "London, UK")
    assert same_place("London, United Kingdom", "London, England, United Kingdom")
    assert same_place("London (hybrid)", "London (hybrid), United Kingdom")
    assert same_place("Bristol, UK", "Bristol, United Kingdom")
    assert same_place("Amsterdam", "Amsterdam, Netherlands")


def test_two_cities_are_not_one_place():
    # Resonance posts "Applied AI Engineer" in London and in Berlin: two jobs, two visa routes.
    assert not same_place("London, United Kingdom", "Berlin")
    assert not same_place("Amsterdam, Netherlands", "Lisbon, Portugal")


def test_remote_matches_remote_but_never_a_named_place():
    assert same_place("Remote", "Worldwide")
    assert not same_place("Remote - India", "Remote")
    assert not same_place("Remote", "London")


# --- which copy stays ------------------------------------------------------------------


def copies(store, filters, places, **overrides):
    """One role posted once per entry in `places`, each its own posting (its own ATS id)."""
    ids = []
    for i, (place, posted) in enumerate(places):
        ids.append(store_job(store, filters, source_job_id=f"copy-{i}", location_raw=place,
                             application_url=f"https://job-boards.greenhouse.io/acme/jobs/{i}",
                             posted_at=NOW - timedelta(days=posted), **overrides))
    return ids


def test_the_newest_posting_is_kept_when_you_have_done_nothing(filters):
    store = JobStore(":memory:")
    old, new = copies(store, filters, [("London, UK", 5), ("London", 1)])
    found = duplicates(role_copies(store, fingerprint("Acme", make_job().title)))
    assert [(d.job_id, d.kept_id) for d in found] == [(old, new)]
    assert "the newest posting of this role" in found[0].reason


def test_the_copy_you_acted_on_is_kept_even_when_it_is_older(filters):
    store = JobStore(":memory:")
    old, new = copies(store, filters, [("London, UK", 5), ("London", 1)])
    set_stage(store, old, "reached_out", NOW)
    found = duplicates(role_copies(store, fingerprint("Acme", make_job().title)))
    assert [(d.job_id, d.kept_id) for d in found] == [(new, old)]
    assert "it is under Reached out" in found[0].reason


def test_a_copy_you_acted_on_is_never_rejected(filters):
    """Rejecting it would put a job you applied to under Rejected, with a red chip in Tracked."""
    store = JobStore(":memory:")
    old, new = copies(store, filters, [("London, UK", 5), ("London", 1)])
    set_stage(store, old, "reached_out", NOW)
    set_stage(store, new, "closed", NOW, reason="skipped")
    assert duplicates(role_copies(store, fingerprint("Acme", make_job().title))) == []


def test_a_dated_copy_is_kept_over_an_undated_one(filters):
    """An undated job sorts by the day it was found, and the date lookup may reject it later."""
    store = JobStore(":memory:")
    undated = store_job(store, filters, source_job_id="a", location_raw="London", posted_at=None,
                        application_url="https://job-boards.greenhouse.io/acme/jobs/1")
    dated = store_job(store, filters, source_job_id="b", location_raw="London, UK",
                      application_url="https://job-boards.greenhouse.io/acme/jobs/2",
                      posted_at=NOW - timedelta(days=3))
    found = duplicates(role_copies(store, fingerprint("Acme", make_job().title)))
    assert [(d.job_id, d.kept_id) for d in found] == [(undated, dated)]


def test_a_role_you_skipped_does_not_come_back_when_it_is_posted_again(filters):
    store = JobStore(":memory:")
    skipped, fresh = copies(store, filters, [("London, UK", 10), ("London", 1)])  # both still inside the age limit
    set_stage(store, skipped, "closed", NOW, reason="skipped")
    found = duplicates(role_copies(store, fingerprint("Acme", make_job().title)))
    assert [(d.job_id, d.kept_id) for d in found] == [(fresh, skipped)]
    assert "you skipped it" in found[0].reason


def test_the_same_role_in_another_city_is_a_job_of_its_own(filters):
    store = JobStore(":memory:")
    copies(store, filters, [("London, United Kingdom", 1), ("Berlin", 1)])
    assert duplicates(role_copies(store, fingerprint("Acme", make_job().title))) == []


def test_the_reason_names_the_job_that_was_kept(filters):
    store = JobStore(":memory:")
    old, new = copies(store, filters, [("London, UK", 5), ("London", 1)])
    reason = duplicates(role_copies(store, fingerprint("Acme", make_job().title)))[0].reason
    assert f"job #{new}" in reason and "Acme" in reason and "London" in reason


# --- writing it down -------------------------------------------------------------------


def test_folding_rejects_every_copy_but_one_and_leaves_the_second_run_nothing_to_do(filters):
    store = JobStore(":memory:")
    old, new = copies(store, filters, [("London, UK", 5), ("London", 1)])
    assert len(fold(store, fingerprint("Acme", make_job().title))) == 1
    row = store.get(old)
    assert row["status"] == REJECTED and row["reject_code"] == DUPLICATE_ROLE
    assert store.get(new)["status"] == SHORTLISTED
    # Worked out again from the stored jobs, so running it twice changes nothing.
    assert fold(store, fingerprint("Acme", make_job().title)) == []
    assert roles_with_copies(store) == []


def test_a_copy_already_rejected_never_swallows_a_posting_the_rules_kept(filters):
    """A twin rejected as `too_old` or for its country is not a copy that can be kept."""
    store = JobStore(":memory:")
    store_job(store, filters, source_job_id="old", location_raw="London, UK", status=REJECTED,
              reject_code="too_old", application_url="https://job-boards.greenhouse.io/acme/jobs/1")
    kept = store_job(store, filters, source_job_id="new", location_raw="London",
                     application_url="https://job-boards.greenhouse.io/acme/jobs/2")
    assert fold(store, fingerprint("Acme", make_job().title)) == []
    assert store.get(kept)["status"] == SHORTLISTED


def test_a_visa_list_copy_is_folded_like_any_other(filters):
    store = JobStore(":memory:")
    first = store_job(store, filters, source_job_id="a", location_raw="London", status=VISA_LIST,
                      application_url="https://job-boards.greenhouse.io/acme/jobs/1",
                      posted_at=NOW - timedelta(days=5))
    second = store_job(store, filters, source_job_id="b", location_raw="London, UK", status=VISA_LIST,
                       application_url="https://job-boards.greenhouse.io/acme/jobs/2")
    assert [d.job_id for d in fold(store, fingerprint("Acme", make_job().title))] == [first]
    assert store.get(second)["status"] == VISA_LIST


# --- in a run --------------------------------------------------------------------------


def ingest(store, filters, *jobs, now=NOW):
    summary = pipeline.RunSummary(run_id=store.start_run(now), started_at=now.isoformat())
    pipeline.ingest(store, [SourceResult("test", list(jobs))], filters, summary.run_id, now, summary)
    return summary


def test_a_second_posting_of_one_role_is_rejected_as_it_comes_in(filters):
    """Two ATS ids, one role: dedup keeps them apart (identity.py), the duplicate rule picks one."""
    store = JobStore(":memory:")
    first = make_job(source_job_id="a", location_raw="London", allowed_locations=["Worldwide"],
                     application_url="https://job-boards.greenhouse.io/acme/jobs/1",
                     posted_at=NOW - timedelta(days=5))
    second = make_job(source_job_id="b", location_raw="London, UK", allowed_locations=["Worldwide"],
                      application_url="https://job-boards.greenhouse.io/acme/jobs/2")
    summary = ingest(store, filters, first, second)
    rows = {r["source_job_id"]: r for r in store.conn.execute(
        "SELECT j.status, j.reject_code, s.source_job_id FROM jobs j JOIN sightings s ON s.job_id = j.id")}
    assert rows["a"]["status"] == REJECTED and rows["a"]["reject_code"] == DUPLICATE_ROLE
    assert rows["b"]["status"] == SHORTLISTED
    # The run's counts say what the stored rows say.
    assert summary.reject_codes[DUPLICATE_ROLE] == 0  # the new job won; the older row was folded
    assert len(summary.duplicates) == 1


def test_the_new_listing_is_the_one_rejected_when_an_older_copy_is_kept(filters):
    store = JobStore(":memory:")
    ingest(store, filters, make_job(source_job_id="a", location_raw="London", allowed_locations=["Worldwide"],
                                    application_url="https://job-boards.greenhouse.io/acme/jobs/1"))
    summary = ingest(store, filters, make_job(source_job_id="b", location_raw="London, UK",
                                              allowed_locations=["Worldwide"],
                                              posted_at=NOW - timedelta(days=5),
                                              application_url="https://job-boards.greenhouse.io/acme/jobs/2"))
    assert summary.reject_codes[DUPLICATE_ROLE] == 1
    assert summary.new_by_status[REJECTED] == 1 and summary.new_by_status[SHORTLISTED] == 0


def test_two_different_roles_at_one_company_are_both_kept(filters):
    store = JobStore(":memory:")
    ingest(store, filters,
           make_job(source_job_id="a", title="Backend Engineer", allowed_locations=["Worldwide"]),
           make_job(source_job_id="b", title="Platform Engineer", allowed_locations=["Worldwide"]))
    statuses = [r["status"] for r in store.conn.execute("SELECT status FROM jobs")]
    assert statuses == [SHORTLISTED, SHORTLISTED]
