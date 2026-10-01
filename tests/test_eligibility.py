from jobhunter.eligibility import assess_eligibility
from jobhunter.models import ELIGIBLE, HYBRID, LIKELY, NOT_ELIGIBLE, ONSITE, UNCLEAR, UNKNOWN

from .conftest import make_job


def verdict(**kwargs):
    return assess_eligibility(make_job(**kwargs))


def test_how_the_team_works_is_not_who_is_hired():
    team = verdict(location_raw="Remote", description="Work in a collaborative, agile and globally distributed environment.")
    assert team.verdict == UNCLEAR
    hiring = verdict(location_raw="Remote", description="We hire globally and pay in USD.")
    assert (hiring.verdict, hiring.code) == (LIKELY, "description_positive")


def test_lebanon_listed_wins_over_everything():
    a = verdict(allowed_locations=["Lebanon", "Egypt"], remote_status=HYBRID)
    assert (a.verdict, a.code) == (ELIGIBLE, "lebanon_listed")


def test_onsite_and_hybrid_are_rejected():
    assert verdict(remote_status=ONSITE, location_raw="Berlin").verdict == NOT_ELIGIBLE
    assert verdict(remote_status=HYBRID, location_raw="Dubai").code == "not_remote"


def test_worldwide_is_eligible():
    assert verdict(allowed_locations=["Worldwide"]).verdict == ELIGIBLE


def test_region_with_lebanon_is_likely():
    assert verdict(allowed_locations=["EMEA"]).verdict == LIKELY


def test_list_of_places_is_an_or():
    # One positive alternative is enough.
    assert verdict(allowed_locations=["United States", "EMEA"]).verdict == LIKELY


def test_restricted_places_are_rejected():
    a = verdict(allowed_locations=["USA", "Canada"])
    assert (a.verdict, a.code) == (NOT_ELIGIBLE, "location_restricted")
    assert "USA" in a.reasons[0]


def test_plain_remote_is_not_international():
    a = verdict(location_raw="Remote", description="Great team.")
    assert (a.verdict, a.code) == (UNCLEAR, "no_location_info")


def test_description_residency_rule_rejects_when_location_is_silent():
    a = verdict(location_raw="Remote", description="You must be located in the United States to be considered.")
    assert (a.verdict, a.code) == (NOT_ELIGIBLE, "residency_required")


def test_worldwide_field_contradicted_by_description_is_unclear():
    a = verdict(allowed_locations=["Worldwide"], description="Candidates must be based in the UK.")
    assert (a.verdict, a.code) == (UNCLEAR, "conflict")


def test_title_restriction_contradicts_worldwide_field():
    a = verdict(title="Backend Engineer (US only)", allowed_locations=["Worldwide"])
    assert a.verdict == UNCLEAR


def test_restriction_questioned_by_employer_of_record_is_unclear():
    a = verdict(allowed_locations=["Europe"], description="We hire anywhere through Deel.")
    assert (a.verdict, a.code) == (UNCLEAR, "conflict")


def test_company_boilerplate_does_not_override_the_postings_own_location():
    a = verdict(
        allowed_locations=["Remote, Poland"],
        description="Country Hiring Guidelines: GitLab hires new team members in countries around the world.",
    )
    assert (a.verdict, a.code) == (NOT_ELIGIBLE, "location_restricted")


def test_employer_of_record_alone_is_likely():
    a = verdict(location_raw="Remote", description="We employ people through Remote.com as an EOR.")
    assert (a.verdict, a.code) == (LIKELY, "eor")


def test_timezone_in_description_is_likely():
    a = verdict(location_raw="Remote", description="Our team works in European time zones.")
    assert a.verdict == LIKELY


def test_security_clearance_rejects():
    a = verdict(location_raw="Remote", description="Requires an active security clearance.")
    assert a.verdict == NOT_ELIGIBLE


def test_us_based_employees_boilerplate_is_not_a_restriction():
    a = verdict(
        allowed_locations=["Global Remote"],
        description="We participate in E-Verify, which confirms employment authorization of newly hired U.S. based employees.",
    )
    assert a.verdict == ELIGIBLE


def test_work_from_anywhere_in_the_us_is_not_worldwide():
    a = verdict(location_raw="Remote", description="Work from anywhere in the US.")
    assert a.verdict != ELIGIBLE and a.verdict != LIKELY


def test_himalayas_timezone_window_without_lebanon():
    worldwide = verdict(allowed_locations=["Worldwide"], allowed_utc_offsets=[-8, -7, -6, -5])
    assert worldwide.verdict == UNCLEAR
    silent = verdict(location_raw=None, allowed_utc_offsets=[-8, -5], description="")
    assert (silent.verdict, silent.code) == (NOT_ELIGIBLE, "timezone_restricted")


def test_unknown_remote_status_is_not_treated_as_onsite():
    assert verdict(remote_status=UNKNOWN, allowed_locations=["Worldwide"]).verdict == ELIGIBLE


def test_long_country_list_in_description_is_read():
    # Lithic on We Work Remotely: region "Anywhere in the World", but the text names the countries.
    rule = (
        "This is a remote position. However, candidates must be located in the United States, "
        "Canada (Ontario or British Columbia), Netherlands, Poland, or Czech Republic."
    )
    a = verdict(allowed_locations=["Anywhere in the World"], description=rule)
    assert (a.verdict, a.code) == (UNCLEAR, "conflict")
    assert "Czech Republic" in a.reasons[0]
    silent = verdict(location_raw="Remote", description=rule)
    assert (silent.verdict, silent.code) == (NOT_ELIGIBLE, "residency_required")


def test_work_from_anywhere_perk_is_not_worldwide_hiring():
    perk = "Benefits for Full-Time US Employees:\n- Work From Anywhere: work from anywhere in the world 4-weeks each year"
    assert verdict(location_raw="Remote", description=perk).code == "no_location_info"
    hiring = verdict(location_raw="Remote", description="We hire globally and offer 30 days of paid leave.")
    assert hiring.code == "description_positive"


def test_globally_remote_role_questions_a_city_location():
    # Canonical through Google Jobs: location "Dubai", text says the role is global.
    a = verdict(location_raw="Dubai", description="Location: this is a Globally remote role")
    assert (a.verdict, a.code) == (UNCLEAR, "conflict")
