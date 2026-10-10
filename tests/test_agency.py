from jobhunter.agency import AgencyRules
from jobhunter.classify import classify
from jobhunter.models import REJECTED, SHORTLISTED

from .conftest import NOW, make_job


def _classify(filters, **overrides):
    overrides.setdefault("allowed_locations", ["Worldwide"])  # shortlisted unless it is an agency
    return classify(make_job(**overrides), filters, NOW)


def test_a_listed_agency_is_rejected_by_name(filters):
    result = _classify(filters, company="Proxify AB")
    assert result.status == REJECTED and result.reject_code == "agency"
    assert result.reject_reason == 'Staffing agency or talent marketplace on your list: "Proxify"'
    assert _classify(filters, company="Jobs for Humanity").reject_code == "agency"


def test_a_name_word_is_matched_as_a_whole_word(filters):
    result = _classify(filters, company="HAN IT Staffing Inc.")
    assert result.reject_code == "agency"
    assert result.reject_reason == 'Company name says it is an agency ("staffing"): "HAN IT Staffing Inc."'
    assert _classify(filters, company="Talentuch").status == SHORTLISTED  # "talent" inside a word
    assert _classify(filters, company="Five Rings LLC - Careers").status == SHORTLISTED


def test_an_agency_phrase_in_the_posting_is_quoted(filters):
    description = "About the role.\nWe are hiring on behalf of our client, a fintech in Berlin. You will build APIs."
    result = _classify(filters, company="Somebody GmbH", description=description)
    assert result.reject_code == "agency"
    assert result.reject_reason == ('Posting is written by an agency: '
                                    '"We are hiring on behalf of our client, a fintech in Berlin."')


def test_phrases_real_companies_use_are_not_agency_signs(filters):
    for text in ("We serve our clients across Europe.", "Join our talent pool for future roles.",
                 "Not the right fit? Join our Talent Network."):
        assert _classify(filters, description=text).status == SHORTLISTED, text


def test_not_agencies_wins_over_a_name_word():
    rules = AgencyRules.from_dict({"name_words": ["talent"], "not_agencies": ["Talent Inc"]})
    assert rules.check("Talent", "") is None
    assert rules.check("Top Talent", "") is not None
