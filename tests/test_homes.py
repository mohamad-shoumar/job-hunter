"""Home countries other than Lebanon (homes.py): the same rules, judged against another place."""

import pytest

from jobhunter.config import Filters
from jobhunter.eligibility import assess_eligibility
from jobhunter.geo import LEBANON_HOME, REGION_OK, RESTRICTED, TIMEZONE_OK, UNKNOWN, classify_place, timezone_signal
from jobhunter.homes import HOMES, home_from
from jobhunter.models import ELIGIBLE, LIKELY, NOT_ELIGIBLE

from .conftest import make_job

# (home, its own place, a region that includes it, a region that does not, a UTC window that fits)
CASES = [
    ("EG", "Remote - Cairo", "Remote (MENA)", "Remote - Southeast Asia", "UTC+1 to UTC+3"),
    ("PK", "Lahore, Pakistan", "Remote, APAC", "Remote - Southeast Asia", "UTC+4 to UTC+6"),
    ("IN", "Bengaluru, India", "Remote - South Asia", "Remote (EMEA)", "UTC+5 to UTC+6"),
    ("NG", "Lagos, Nigeria", "Remote (EMEA)", "Remote - APAC", "UTC+0 to UTC+2"),
    ("KE", "Nairobi", "Remote - Africa", "Remote - LATAM", "UTC+2 to UTC+4"),
    ("BR", "São Paulo, Brazil", "Remote - LATAM", "Remote - North America", "UTC-4 to UTC-2"),
    ("AR", "Buenos Aires", "Remote (Latin America)", "Remote - Europe", "UTC-5 to UTC-3"),
    ("CO", "Bogotá, Colombia", "Remote - Americas", "Remote - EMEA", "UTC-6 to UTC-4"),
    ("PH", "Manila, Philippines", "Remote - South East Asia", "Remote - East Asia", "UTC+7 to UTC+9"),
]


@pytest.mark.parametrize("code, own, region, other, window", CASES)
def test_each_home_reads_its_own_places(code, own, region, other, window):
    home = HOMES[code]
    listed = assess_eligibility(make_job(location_raw=own), home=home)
    assert (listed.verdict, listed.code) == (ELIGIBLE, "home_listed")
    assert listed.reasons[0].startswith(f"{home.name} is listed")

    assert classify_place(region, field=True, home=home).kind == REGION_OK
    fits = assess_eligibility(make_job(location_raw=region), home=home)
    assert (fits.verdict, fits.code) == (LIKELY, "region_ok")
    assert f"Region includes {home.name}" in fits.reasons[0]

    assert classify_place(other, field=True, home=home).kind == RESTRICTED
    assert assess_eligibility(make_job(location_raw=other), home=home).verdict == NOT_ELIGIBLE

    assert timezone_signal(window, home)
    assert classify_place(f"Remote ({window})", field=True, home=home).kind == TIMEZONE_OK


@pytest.mark.parametrize("code", sorted(set(HOMES) - {"LB"}))
def test_lebanon_is_a_foreign_place_for_the_other_homes(code):
    home = HOMES[code]
    assert classify_place("Remote - Beirut, Lebanon", field=True, home=home).kind == RESTRICTED
    result = assess_eligibility(make_job(location_raw="Remote - Lebanon"), home=home)
    assert result.verdict == NOT_ELIGIBLE
    assert not any("Lebanon is listed" in r for r in result.reasons)


def test_a_wider_region_does_not_hide_a_narrower_one():
    # Pakistan is in Asia, not in Southeast or East Asia.
    pk = HOMES["PK"]
    assert classify_place("Remote - Asia", field=True, home=pk).kind == REGION_OK
    assert classify_place("Southeast Asia", field=True, home=pk).kind == RESTRICTED
    assert classify_place("East Asia", field=True, home=pk).kind == RESTRICTED
    # ...while the Philippines is in Southeast Asia, however it is spelled.
    ph = HOMES["PH"]
    assert classify_place("South East Asia", field=True, home=ph).kind == REGION_OK
    assert classify_place("South Asia", field=True, home=ph).kind == RESTRICTED


def test_us_time_zones_fit_a_home_near_them_only():
    assert classify_place("Remote (EST hours)", field=True, home=HOMES["CO"]).kind == TIMEZONE_OK
    assert classify_place("Remote (Eastern Time)", field=True, home=HOMES["BR"]).kind == TIMEZONE_OK
    assert classify_place("Remote (EST hours)", field=True, home=LEBANON_HOME).kind == RESTRICTED
    # "est. 2015" in prose is not a time zone.
    assert timezone_signal("Founded est. 2015 in Bogotá", HOMES["CO"]) is None


def test_european_hours_fit_only_homes_near_them():
    assert timezone_signal("Must work CET hours", HOMES["NG"])
    assert timezone_signal("Must work CET hours", HOMES["EG"])
    assert timezone_signal("Must work CET hours", HOMES["IN"]) is None
    assert timezone_signal("Must work CET hours", HOMES["BR"]) is None


def test_description_names_the_home():
    eg = HOMES["EG"]
    job = make_job(location_raw="Remote", description="We have an engineering hub in Cairo and hire across the region.")
    result = assess_eligibility(job, home=eg)
    assert (result.verdict, result.code) == (LIKELY, "description_home")
    assert "Description mentions Egypt" in result.reasons[0]
    # A demonym in prose is not a place: "Indian Ocean" says nothing about India.
    prose = make_job(location_raw="Remote", description="Our office overlooks the Indian Ocean.")
    assert assess_eligibility(prose, home=HOMES["IN"]).code != "description_home"


def test_lebanon_keeps_its_codes_and_wording():
    result = assess_eligibility(make_job(location_raw="Beirut, Lebanon"))
    assert (result.verdict, result.code) == (ELIGIBLE, "lebanon_listed")
    assert result.reasons[0].startswith("Lebanon is listed")
    assert classify_place("Remote", field=True).kind == UNKNOWN


def test_filters_pick_the_home():
    assert Filters.from_dict({}).home is LEBANON_HOME
    assert Filters.from_dict({"home": "eg"}).home.name == "Egypt"
    with pytest.raises(ValueError, match="unknown home country"):
        home_from("ZZ")


def test_a_region_word_inside_a_country_name_is_not_that_region():
    eg = HOMES["EG"]
    assert classify_place("South Africa", field=True, home=eg).kind == RESTRICTED
    assert classify_place("Remote - Africa", field=True, home=eg).kind == REGION_OK


def test_only_us_time_zones_near_the_home_fit():
    br = HOMES["BR"]
    assert classify_place("Remote (Pacific Time)", field=True, home=br).kind == RESTRICTED
    assert classify_place("Remote (PST)", field=True, home=br).kind == RESTRICTED
    assert classify_place("Remote (EST)", field=True, home=br).kind == TIMEZONE_OK
    assert classify_place("REMOTE (AMER or EMEA time zones)", field=True, home=br).kind == REGION_OK
