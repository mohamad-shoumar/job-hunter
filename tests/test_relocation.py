import pytest

from jobhunter.classify import classify
from jobhunter.config import Filters
from jobhunter.extract import enrich
from jobhunter.models import HYBRID, ONSITE, REJECTED, REMOTE, SHORTLISTED

from .conftest import NOW, ROOT, make_job


@pytest.fixture
def floor_filters(monkeypatch):
    monkeypatch.setenv("RELOCATION_MIN_MONTHLY_USD", "4200")
    return Filters.load(ROOT / "config" / "filters.json")


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
    for place in ("Riyadh, Saudi Arabia", "Kuwait City", "London"):
        result = _classify(filters, remote_status=ONSITE, allowed_locations=[place])
        assert result.reject_code == "not_remote", place


def test_remote_for_people_in_the_uae_counts_as_moving_there(filters):
    result = _classify(filters, remote_status=REMOTE, title="Backend Engineer (Remote, UAE)")
    assert result.status == SHORTLISTED
    assert result.eligibility.reasons[0].startswith('Remote, for people living in "Remote, UAE"')
    # A region that includes Lebanon stays a remote job open to Lebanon.
    emea = _classify(filters, allowed_locations=["EMEA", "Dubai"])
    assert emea.eligibility.code == "region_ok"


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
                     "We do not sponsor visas for this role."):
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
