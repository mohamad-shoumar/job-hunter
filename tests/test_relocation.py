import pytest

from jobhunter.classify import classify, gulf_quote_adds_evidence
from jobhunter.config import Filters
from jobhunter.extract import enrich
from jobhunter.models import HYBRID, ONSITE, REJECTED, REMOTE, SHORTLISTED, AiCheck

from .conftest import FIXTURES, NOW, make_job


@pytest.fixture
def floor_filters(monkeypatch):
    monkeypatch.setenv("RELOCATION_MIN_MONTHLY_USD", "4200")
    return Filters.load(FIXTURES / "filters.json")


def _classify(filters, **overrides):
    job = make_job(**overrides)
    enrich(job)
    return classify(job, filters, NOW)


def test_an_onsite_job_in_dubai_is_shortlisted_with_what_to_ask(filters):
    result = _classify(filters, remote_status=ONSITE, allowed_locations=["Dubai - United Arab Emirates"])
    assert result.status == SHORTLISTED and result.eligibility.code == "relocation"
    assert result.eligibility.reasons[0] == (
        'On-site in "Dubai - United Arab Emirates", a country you would move to (the UAE or Qatar). '
        "Ask about visa sponsorship and a remote interview")


def test_onsite_elsewhere_is_still_rejected(filters):
    # London, Berlin and the rest of the visa list's countries are judged by visa.py (test_visa.py).
    for place in ("Riyadh, Saudi Arabia", "Kuwait City", "Paris, France"):
        result = _classify(filters, remote_status=ONSITE, allowed_locations=[place])
        assert result.reject_code == "not_remote", place


def test_remote_for_people_in_the_uae_counts_as_moving_there(filters):
    result = _classify(filters, remote_status=REMOTE, title="Backend Engineer (Remote, UAE)")
    assert result.status == SHORTLISTED
    assert result.eligibility.reasons[0].startswith('Remote, for people living in "Remote, UAE"')
    # A region that includes Lebanon stays a remote job open to Lebanon.
    emea = _classify(filters, allowed_locations=["EMEA", "Dubai"])
    assert emea.eligibility.code == "region_ok"


def test_a_region_narrowed_to_the_uae_is_judged_as_moving_there(filters):
    # "Middle East" in the title, "UAE" as the location: limited to people living there.
    result = _classify(filters, remote_status=REMOTE, title="Backend Engineer (Middle East)", allowed_locations=["UAE"])
    assert result.status == SHORTLISTED and result.eligibility.code == "relocation"
    assert result.eligibility.reasons[0].startswith('Remote, for people living in "UAE"')


def test_lebanon_listed_wins(filters):
    result = _classify(filters, remote_status=HYBRID, allowed_locations=["Dubai", "Beirut, Lebanon"])
    assert result.eligibility.code == "lebanon_listed"


def test_a_visa_offer_is_quoted(filters):
    text = "We build APIs with Python.\nWe offer a relocation package and visa sponsorship for the right person."
    result = _classify(filters, remote_status=HYBRID, allowed_locations=["Doha, Qatar"], description=text)
    assert result.status == SHORTLISTED and result.eligibility.code == "relocation_offered"
    assert result.eligibility.reasons[0] == ('Hybrid in "Doha, Qatar", a country you would move to; the posting '
                                             'offers: "We offer a relocation package and visa sponsorship for the right person."')


def test_nationals_only_or_a_visa_you_already_hold_is_rejected(filters):
    title = _classify(filters, remote_status=ONSITE, allowed_locations=["Abu Dhabi"],
                      title="Software Engineer - UAE National")
    assert title.status == REJECTED and title.reject_code == "local_only"
    for sentence in ("Candidates must have a transferable visa.", "This role is open to UAE Nationals only.",
                     "We do not sponsor visas for this role.",
                     "Role: Integration Engineer ( UAE-Based Candidates only)"):  # FR Consultancy, 2026-10-30
        result = _classify(filters, remote_status=ONSITE, allowed_locations=["Dubai"],
                           description=f"Python APIs.\n{sentence}")
        assert result.reject_code == "local_only", sentence
        assert result.reject_reason == f'Only for people already in the country: "{sentence}"'


def test_wanting_someone_already_there_is_a_note_not_a_rejection(filters):
    text = "Python and FastAPI.\nImmediate joiners preferred."
    result = _classify(filters, remote_status=ONSITE, allowed_locations=["Dubai"], description=text)
    assert result.status == SHORTLISTED
    assert result.eligibility.reasons[1] == ('Ask before applying, it may want someone already there: '
                                             '"Immediate joiners preferred."')


def test_pay_under_the_floor_for_moving_is_rejected(floor_filters):
    low = _classify(floor_filters, remote_status=ONSITE, allowed_locations=["Dubai"],
                    description="Python APIs. Salary: AED 10,000 - 14,000 plus housing.")
    assert low.reject_code == "below_relocation_pay"
    assert low.reject_reason == 'Pays "AED 10,000 - 14,000", about $3,812 a month, under your $4,200 for moving'
    ok = _classify(floor_filters, remote_status=ONSITE, allowed_locations=["Dubai"],
                   description="Python APIs. Salary: AED 20,000 - 28,000 plus housing.")
    assert ok.status == SHORTLISTED and ok.eligibility.reasons[-1] == "Pay: about $7,624 a month"


def test_no_floor_set_means_pay_is_not_checked(filters):
    result = _classify(filters, remote_status=ONSITE, allowed_locations=["Dubai"],
                       description="Python APIs. Salary: AED 9,000 - 10,000.")
    assert result.status == SHORTLISTED


def test_gulf_pay_without_a_period_is_monthly():
    job = make_job(description="Package: QAR 18,000 - 22,000 all inclusive.")
    enrich(job)
    assert (job.salary_min, job.salary_max, job.salary_currency, job.salary_period) == (18000, 22000, "QAR", "month")
    yearly = make_job(description="Package: AED 240,000 - 300,000.")
    enrich(yearly)
    assert yearly.salary_period == "year"


def test_a_sentence_that_refuses_sponsorship_is_not_an_offer(filters):
    for sentence in ("We do not provide visa sponsorship for this role.", "There is no relocation package."):
        result = _classify(filters, remote_status=ONSITE, allowed_locations=["Dubai"],
                           description=f"Python APIs.\n{sentence}")
        assert result.reject_code == "local_only", sentence
        assert result.reject_reason == f'Only for people already in the country: "{sentence}"'


def test_a_role_for_nationals_named_only_in_the_text_is_rejected(filters):
    # Emirates NBD through freehire: the title is plain "Software Engineer", the text says who it is for
    text = "The Software Engineer (UAE National) will be responsible for developing high-quality applications."
    result = _classify(filters, title="Software Engineer", description=text, remote_status=ONSITE,
                       allowed_locations=["United Arab Emirates"])
    assert result.status == REJECTED and result.reject_code == "local_only"
    assert "(UAE National)" in result.eligibility.reasons[0]


def test_a_national_allowance_or_bank_is_not_a_nationals_only_rule(filters):
    text = "Benefits: housing allowance, UAE National Allowance. Partnership with Qatar National Bank."
    result = _classify(filters, description=text, remote_status=ONSITE, allowed_locations=["Dubai"])
    assert result.status == SHORTLISTED


# --- Kuwait and Bahrain: companies you would work for remotely, not move to (gulf.py) ---------


def test_a_remote_job_listed_in_kuwait_is_kept_for_the_ai_check(filters):
    result = _classify(filters, remote_status=REMOTE, allowed_locations=["Kuwait City, Kuwait"])
    assert result.status == SHORTLISTED and result.eligibility.code == "gulf_remote"
    assert result.eligibility.reasons[0] == (
        'Remote, listed in "Kuwait City, Kuwait": a country you would work for from Lebanon, '
        "not move to (Kuwait or Bahrain). Can they hire someone living in Lebanon?")


def test_a_remote_job_listed_in_bahrain_is_kept(filters):
    for place in ("Bahrain", "Manama, Bahrain", "Seef, Bahrain", "Remote - Kuwait"):
        result = _classify(filters, remote_status=REMOTE, allowed_locations=[place])
        assert result.status == SHORTLISTED and result.eligibility.code == "gulf_remote", place


def test_onsite_or_hybrid_in_kuwait_or_bahrain_is_still_rejected(filters):
    # You would work for them, not move there: only remote counts (your call 2026-11-13).
    for status in (ONSITE, HYBRID):
        for place in ("Kuwait City, Kuwait", "Manama, Bahrain"):
            result = _classify(filters, remote_status=status, allowed_locations=[place])
            assert result.reject_code == "not_remote", (status, place)


def test_a_job_that_does_not_say_whether_it_is_remote_is_not_kept(filters):
    result = _classify(filters, remote_status="unknown", allowed_locations=["Kuwait City, Kuwait"])
    assert result.status == REJECTED and result.reject_code == "location_restricted"


def test_kuwait_next_to_another_country_is_still_rejected(filters):
    for place in ("Bahrain; India", "Kuwait, US", "Remote - KSA, Kuwait", "Kuwait or Europe"):
        result = _classify(filters, remote_status=REMOTE, allowed_locations=[place])
        assert result.status == REJECTED and result.reject_code == "location_restricted", place
    # "US", "UK" and "UAE" only count in capitals, so the places are cut from the text as written.
    # The UK is a visa-list country, so this one is rejected by the visa rules instead.
    uk = _classify(filters, remote_status=REMOTE, allowed_locations=["Bahrain; UK"])
    assert uk.status == REJECTED and uk.eligibility.code == "no_visa_evidence"


def test_a_remote_kuwait_job_that_wants_someone_already_there_is_rejected(filters):
    text = "Python APIs.\nCandidates must hold a transferable visa; we do not sponsor."
    result = _classify(filters, remote_status=REMOTE, allowed_locations=["Kuwait"], description=text)
    assert result.status == REJECTED and result.reject_code == "local_only"
    assert "transferable visa" in result.reject_reason


def test_a_remote_kuwait_job_whose_text_names_another_country_is_rejected(filters):
    text = "Python APIs.\nYou must be based in India for this role."
    result = _classify(filters, remote_status=REMOTE, allowed_locations=["Kuwait"], description=text)
    assert result.status == REJECTED and result.reject_code == "location_restricted"
    assert "based in India" in result.reject_reason


def _with_check(filters, quote, reason="The careers page says so.", verdict="cannot_hire"):
    """A remote Kuwait job whose AI check quotes a page: the description itself says nothing about where."""
    check = AiCheck(verdict, reason, quote, "https://example.com/careers", verified=True)
    return _classify(filters, remote_status=REMOTE, allowed_locations=["Kuwait City, Kuwait"],
                     description="Python APIs.", ai_check=check)


def test_the_ai_check_cannot_reject_a_kuwait_job_on_its_location_alone(filters):
    # The rules kept it knowing where it is listed, and the model is told a country list means
    # "cannot hire": quoting the location back is not an answer.
    result = _with_check(filters, "Kuwait City, Kuwait")
    assert result.status == SHORTLISTED and result.eligibility.code == "gulf_remote"
    assert "only repeats the location the rules already read" in result.eligibility.reasons[-1]


def test_the_ai_check_still_rejects_a_kuwait_job_on_a_real_rule(filters):
    for quote in ("You must be based in Kuwait for this role.", "We do not sponsor visas.",
                  "This role is open to candidates in India only.", "Kuwait residents only."):
        result = _with_check(filters, quote)
        assert result.status == REJECTED and result.reject_code == "ai_cannot_hire", quote


def test_a_residency_rule_in_the_posting_itself_rejects_it_without_the_ai_check(filters):
    result = _classify(filters, remote_status=REMOTE, allowed_locations=["Kuwait City, Kuwait"],
                       description="Python APIs. You must be based in Kuwait for this role.")
    assert result.status == REJECTED and result.reject_code == "location_restricted"


def test_the_ai_check_can_still_clear_a_kuwait_job(filters):
    result = _with_check(filters, "We hire across the Middle East.", verdict="can_hire")
    assert result.status == SHORTLISTED and result.eligibility.code == "ai_can_hire"


def test_a_nationals_only_title_in_kuwait_is_rejected(filters):
    result = _classify(filters, remote_status=REMOTE, title="Software Engineer - Kuwaiti National Only",
                       allowed_locations=["Kuwait City, Kuwait"])
    assert result.status == REJECTED and result.reject_code == "local_only"


def test_a_region_narrowed_to_kuwait_is_kept_not_a_conflict(filters):
    # "Remote, MENA" with the location Kuwait City: the narrower rule applies, and for these
    # countries that is the remote-only list, not a rejection.
    result = _classify(filters, remote_status=REMOTE, title="Backend Engineer (Remote, MENA)",
                       allowed_locations=["Kuwait City, Kuwait"])
    assert result.status == SHORTLISTED and result.eligibility.code == "gulf_remote"


def test_a_kuwait_job_the_text_doubts_is_kept_on_this_list_too(filters):
    # Not `conflict`: the code is what stops the AI check rejecting it on the location alone.
    result = _classify(filters, remote_status=REMOTE, allowed_locations=["Kuwait City, Kuwait"],
                       description="Python APIs. This role is globally remote.")
    assert result.status == SHORTLISTED and result.eligibility.code == "gulf_remote"
    assert "The posting also says:" in result.eligibility.reasons[1]
    check = AiCheck("cannot_hire", "The posting is for Kuwait.", "Kuwait City, Kuwait",
                    "https://example.com/job", verified=True)
    kept = _classify(filters, remote_status=REMOTE, allowed_locations=["Kuwait City, Kuwait"],
                     description="Python APIs. This role is globally remote.", ai_check=check)
    assert kept.status == SHORTLISTED and kept.eligibility.code == "gulf_remote"


def test_the_guard_covers_the_quotes_an_ats_posting_gives(filters):
    # PagesChecker formats a Greenhouse/Lever/Ashby posting as "Location: <name>".
    for quote in ("Location: Kuwait City, Kuwait", "Remote - Kuwait", "Kuwait City, Al Asimah, Kuwait",
                  "Manama, Capital Governorate, Bahrain"):
        assert not gulf_quote_adds_evidence(quote, filters.gulf_remote), quote
        assert _with_check(filters, quote).status == SHORTLISTED, quote
