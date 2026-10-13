"""Government sponsor lists (sponsors.py), parsed from trimmed real files fetched 2026-10-13."""

from datetime import timedelta

from jobhunter import sponsors
from jobhunter.sponsors import Registers, name_keys, parse_ie, parse_nl, parse_uk

from .conftest import FIXTURES, NOW, FakeHttp, fixture_json, fixture_text

UK_CSV = ("https://assets.publishing.service.gov.uk/media/6acdecb2a57ddfe32196ab6b/"
          "SP_-_Worker_and_Temporary_Worker_Web_Register_-_2026-10-13.csv")
IE_2026 = "https://enterprise.gov.ie/en/publications/publication-files/employment-permits-issued-to-companies-2026.xlsx"


def test_uk_keeps_skilled_worker_rows_once_each():
    rows = parse_uk(fixture_text("sponsors_uk.csv"))
    assert all(r.detail.endswith(", Skilled Worker") for r in rows)
    monzo = [r for r in rows if r.name == "Monzo Bank Ltd"]
    assert len(monzo) == 1  # listed twice, as "London" and "London "
    assert monzo[0].quote() == "Monzo Bank Ltd, London, Worker (A rating), Skilled Worker"
    assert not [r for r in rows if "Charity" in r.detail or r.name == "MODE AGENCE LTD"]
    assert "AaruvikA Limited" in {r.name for r in rows}  # the leading space is gone


def test_nl_reads_the_html_table():
    rows = parse_nl(fixture_text("sponsors_nl.html"))
    assert len(rows) == 19
    assert rows[0].quote() == '"Aa-Dee" Machinefabriek en Staalbouw Nederland B.V., KvK 16051874'


def test_ie_reads_both_years_layouts_biggest_first():
    for year in (2026, 2025):
        rows = parse_ie((FIXTURES / f"sponsors_ie_{year}.xlsx").read_bytes(), year)
        assert rows and rows[0].name == "Google Ireland Limited"
        assert rows[0].detail.endswith(f"employment permits in {year}")
        assert not [r for r in rows if r.name.lower() in ("total", "grand total")]


def test_name_keys_drop_trailing_words_and_read_trading_names():
    assert {"stripe payments", "stripe"} <= name_keys("Stripe Payments UK Ltd")
    assert {"deliveroo", "roofoods"} <= name_keys("Roofoods Ltd t/a Deliveroo")
    assert "1password" in name_keys("AgileBits UK Ltd trading as 1Password")
    assert "picnic" in name_keys("Picnic International B.V.")
    assert "intercom" in name_keys("Intercom R&D Unlimited Company")
    assert "elevenlabs" in name_keys("Eleven Labs Ltd")
    # Only trailing words: "The Ramp" stays "ramp", never a prefix of something else.
    assert name_keys("Cloud Kitchen Partners Ltd") == {"cloud kitchen partners", "cloudkitchenpartners"}


def test_find_needs_the_town_for_a_one_word_name():
    registers = Registers.from_rows("uk", parse_uk(fixture_text("sponsors_uk.csv")))
    assert registers.find("uk", "GoCardless", ["London, United Kingdom"]).name == "GoCardless Limited"
    assert registers.find("uk", "GoCardless", ["Manchester"]) is None
    assert registers.find("uk", "1Password", ["Cambridge, UK"]).name == "AgileBits UK Ltd trading as 1Password"
    assert registers.find("nl", "GoCardless", ["London"]) is None


def test_update_saves_each_list_and_load_reads_it_back(tmp_path):
    ie_page = fixture_text("sponsors_ie_page.html")
    http = FakeHttp({
        sponsors.UK_CONTENT_API: fixture_json("sponsors_uk_content.json"),
        UK_CSV: fixture_text("sponsors_uk.csv"),
        sponsors.NL_REGISTER: fixture_text("sponsors_nl.html"),
        sponsors.IE_STATS.format(year=2026): ie_page,
        sponsors.IE_STATS.format(year=2025): ie_page.replace("2026", "2025"),
        IE_2026: (FIXTURES / "sponsors_ie_2026.xlsx").read_bytes(),
        IE_2026.replace("2026", "2025"): (FIXTURES / "sponsors_ie_2025.xlsx").read_bytes(),
    })
    done, errors = sponsors.update(http, tmp_path, NOW)
    assert errors == []
    assert done[0] == "uk: 13 employers from the UK register of licensed sponsors (updated 2026-10-13)"
    registers = Registers.load(tmp_path)
    assert registers.meta["nl"]["rows"] == 19
    google = registers.find("ie", "Google", ["Dublin"])
    assert google.quote() == "Google Ireland Limited, 254 employment permits in 2026"  # this year's first
    assert sponsors.stale(tmp_path, 7, NOW) == []
    assert sponsors.stale(tmp_path, 7, NOW + timedelta(days=8)) == ["uk", "nl", "ie"]


def test_a_failed_list_keeps_the_old_file(tmp_path):
    sponsors.save(tmp_path, "nl", parse_nl(fixture_text("sponsors_nl.html")), {"source": "x"}, NOW)
    done, errors = sponsors.update(FakeHttp({}), tmp_path, NOW, ["nl"])
    assert done == [] and errors == ["nl: RuntimeError: unexpected URL " + sponsors.NL_REGISTER]
    assert Registers.load(tmp_path).meta["nl"]["rows"] == 19
