import pytest

from jobhunter.geo import (
    LEBANON,
    REGION_OK,
    RESTRICTED,
    TIMEZONE_OK,
    UNKNOWN,
    WORLDWIDE,
    classify_place,
    scan_title,
    timezone_signal,
    utc_offsets_allow_lebanon,
)


@pytest.mark.parametrize(
    "text, kind",
    [
        ("Beirut, Lebanon", LEBANON),
        ("Worldwide", WORLDWIDE),
        ("Anywhere in the World", WORLDWIDE),
        ("Global Remote", WORLDWIDE),
        ("REMOTE (worldwide)", WORLDWIDE),
        ("EMEA", REGION_OK),
        ("Europe, Middle East, Africa, Asia-Pacific (EMEA, APAC)", REGION_OK),
        ("Remote - Middle East", REGION_OK),
        ("Remote (UTC-1 to UTC+3)", TIMEZONE_OK),
        ("Remote, European time zones", TIMEZONE_OK),
        ("Remote (CET +/- 2 hours)", TIMEZONE_OK),
        ("Anywhere in the US", RESTRICTED),
        ("Remote - US", RESTRICTED),
        ("USA", RESTRICTED),
        ("Remote (Europe)", RESTRICTED),
        ("Remote - EU (CET)", RESTRICTED),  # a named place beats the time zone next to it
        ("Remote-North & South America", RESTRICTED),
        ("Northern America, LATAM, Europe, APAC", RESTRICTED),
        ("United Arab Emirates", RESTRICTED),
        ("North America Only", RESTRICTED),
        ("Remote", UNKNOWN),
        ("Flexible / Remote", UNKNOWN),
        ("Remote (async)", UNKNOWN),
        ("REMOTE (EU timezones)", TIMEZONE_OK),
        ("REMOTE (US+INTL for eng, US for product)", WORLDWIDE),
        # preferences are wishes, not rules
        ("Remote (US preferred)", UNKNOWN),
        ("Remote, PT/ET hours preferred", UNKNOWN),
        ("REMOTE (preferred Spain, UK, Poland, Romania)", UNKNOWN),
        ("REMOTE (US ONLY, LA/SF preferred)", RESTRICTED),
        ("REMOTE (US), NYC preferred", RESTRICTED),
        # "X or Remote": the remote option names no place
        ("NYC or Remote", UNKNOWN),
        ("San Francisco / REMOTE", UNKNOWN),
        ("REMOTE (US) or HYBRID", RESTRICTED),
        ("London, UK or NYC", RESTRICTED),
    ],
)
def test_classify_place(text, kind):
    assert classify_place(text, field=True).kind == kind


def test_leftover_words_restrict_only_in_location_fields():
    # "Bangalore" is in the city list, so pick a place that is not.
    assert classify_place("Remote, Tbilisi Region", field=True).kind == RESTRICTED
    assert classify_place("Remote, Tbilisi Region", field=False).kind == UNKNOWN


def test_lowercase_us_pronoun_is_not_the_country():
    assert classify_place("join us").kind == UNKNOWN
    assert classify_place("join US").kind == RESTRICTED


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Candidates must be within UTC-1 to UTC+3", True),
        ("GMT+0 to GMT+4 preferred", True),
        ("We work in EET", True),
        ("within 3 hours of CET", True),
        ("UTC-5 to UTC+1", False),
        ("(UTC+05:30) India", False),
        ("US Eastern hours", False),
    ],
)
def test_timezone_signal(text, expected):
    assert bool(timezone_signal(text)) is expected


def test_utc_offsets():
    assert utc_offsets_allow_lebanon([1, 2, 3])
    assert utc_offsets_allow_lebanon([3.0])
    assert not utc_offsets_allow_lebanon([-8, -7, -6, -5])


def test_scan_title_reads_qualifiers_only():
    assert [m.kind for m in scan_title("Content Reviewer - United States")] == [RESTRICTED]
    assert [m.kind for m in scan_title("Senior Solutions Engineer- LATAM")] == [RESTRICTED]
    assert scan_title("Full-Stack Engineer") == []
    assert [m.kind for m in scan_title("Backend Engineer (Remote, EMEA)")] == [REGION_OK]
    assert [m.kind for m in scan_title("Backend Engineer (Worldwide)")] == [WORLDWIDE]
    assert scan_title("Global Payments Engineer") == []
    assert scan_title("Backend Engineer (Python)") == []
