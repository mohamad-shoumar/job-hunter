"""Visa-sponsorship sites as visa evidence, the new countries, and Germany's silent postings (2026-11-16)."""

from jobhunter import discovery, pipeline
from jobhunter.classify import classify
from jobhunter.config import OutreachConfig
from jobhunter.extract import enrich
from jobhunter.models import ONSITE, REJECTED, REMOTE, VISA_LIST
from jobhunter.sponsor_sites import SiteEntry, SponsorSites, import_csv
from jobhunter.store import JobStore
from jobhunter.visa import VisaRules

from .conftest import NOW, FakeHttp, make_job, store_job
from .test_discovery import CONFIG, routes

COUNTRIES = {
    "nl": {"name": "the Netherlands", "places": ["Netherlands", "Amsterdam"]},
    "de": {"name": "Germany", "places": ["Germany", "Berlin", "Munich"]},
    "uk": {"name": "the UK", "places": ["United Kingdom", "London"]},
    "pl": {"name": "Poland", "places": ["Poland", "Warsaw"]},
    "ca": {"name": "Canada", "places": ["Canada", "Toronto"]},
    "au": {"name": "Australia", "places": ["Australia", "Sydney"]},
}
TEXT = "We build APIs with Python, FastAPI and PostgreSQL on AWS. You will own services end to end."


def rules(tmp_path, **extra):
    visa = VisaRules.from_dict({"countries": COUNTRIES, "languages": ["german", "polish", "danish"], **extra})
    visa.sites = SponsorSites.load(tmp_path)
    return visa


def judge(filters, visa, **overrides):
    filters.visa = visa
    overrides.setdefault("remote_status", ONSITE)
    overrides.setdefault("description", TEXT)
    job = enrich(make_job(**overrides))
    return classify(job, filters, NOW)


def test_a_role_the_stack_lists_counts_as_visa_evidence_and_only_that_role(filters, tmp_path):
    visa = rules(tmp_path)
    visa.sites.add(SiteEntry("The Stack", "Prima GmbH", "de", "Senior Backend Engineer (Python)", "", "2026-11-10"))
    kept = judge(filters, visa, company="Prima", allowed_locations=["Berlin, Germany"])
    assert kept.status == VISA_LIST and kept.eligibility.code == "sponsor_site"
    assert kept.eligibility.reasons[0] == (
        'On-site in "Berlin, Germany", Germany; The Stack, a visa-sponsorship job site, lists "Senior Backend '
        'Engineer (Python)" at Prima GmbH (seen 2026-11-10). The posting does not mention visas: ask')
    # The Stack marks every job "visa: yes": another title at the company, or another country, proves nothing.
    other = judge(filters, visa, company="Prima", title="Platform Engineer", allowed_locations=["Berlin, Germany"])
    assert other.reject_code == "no_visa_evidence"
    assert judge(filters, visa, company="Prima", allowed_locations=["Amsterdam"]).reject_code == "no_visa_evidence"


def test_a_company_on_a_sponsor_list_counts_for_every_role_but_never_against_a_refusal(filters, tmp_path):
    visa = rules(tmp_path)
    visa.sites.add(SiteEntry("JobDelulu", "TicketSwap", "nl", seen="2026-11-16"))
    kept = judge(filters, visa, company="TicketSwap", title="Backend Engineer", allowed_locations=["Amsterdam"])
    assert kept.eligibility.code == "sponsor_site"
    assert "TicketSwap is on JobDelulu's list of visa-sponsoring employers" in kept.eligibility.reasons[0]
    refused = judge(filters, visa, company="TicketSwap", allowed_locations=["Amsterdam"],
                    description=TEXT + " Unfortunately we are unable to offer visa sponsorship.")
    assert refused.reject_code == "no_sponsor"
    # A remote role for people living there rarely comes with a visa, as with the registers.
    remote = judge(filters, visa, company="TicketSwap", remote_status=REMOTE, allowed_locations=["Netherlands"])
    assert remote.status == REJECTED


def test_germany_keeps_postings_silent_about_visas_and_nowhere_else(filters, tmp_path):
    visa = rules(tmp_path, silent_ok=["de"])
    kept = judge(filters, visa, allowed_locations=["Munich, Germany"])
    assert kept.status == VISA_LIST and kept.eligibility.code == "visa_silent"
    assert "says nothing about visas either way" in kept.eligibility.reasons[0]
    assert judge(filters, visa, allowed_locations=["London, United Kingdom"]).reject_code == "no_visa_evidence"
    german = judge(filters, visa, allowed_locations=["Munich, Germany"],
                   description=TEXT + " Fluent German (C1) is required.")
    assert german.reject_code == "language_required"


def test_canada_and_australia_are_their_own_countries_and_us_states_stay_out(tmp_path):
    visa = rules(tmp_path)
    assert visa.place_in(["London, Ontario"])[1].code == "ca"
    assert visa.place_in(["Toronto, ON"])[1].code == "ca"
    assert visa.place_in(["Sydney NSW, Australia"])[1].code == "au"
    assert visa.place_in(["Seattle, WA"]) is None and visa.place_in(["Dublin, OH"]) is None
    assert visa.place_in(["London, United Kingdom"])[1].code == "uk"
    # Without Canada on the list, a Canadian London is still not the UK's.
    assert VisaRules.from_dict({"countries": {"uk": COUNTRIES["uk"]}}).place_in(["London, Ontario"]) is None


def test_a_posting_written_in_polish_needs_polish(filters, tmp_path):
    polish = ("Szukamy osoby, która dołączy do naszego zespołu. Praca w zespole jest dla nas ważna, oraz "
              "rozwój. Jesteś osobą, która lubi wyzwania? Nie czekaj, dołącz do nas, będzie fajnie. ") * 3
    result = judge(filters, rules(tmp_path), allowed_locations=["Warsaw, Poland"], description=polish)
    assert result.reject_code == "language_required" and result.eligibility.reasons[0].startswith("Written in Polish")


def test_import_a_company_country_csv(tmp_path):
    csv = tmp_path / "employers.csv"
    csv.write_text("Company,Country\nTicketSwap,Netherlands\nn8n,Germany / United Kingdom\nHydrosat,Greece / Other EU\n")
    sites = SponsorSites.load(tmp_path)
    codes = {"netherlands": "nl", "germany": "de", "united kingdom": "uk"}
    assert import_csv(sites, csv, "JobDelulu", codes, NOW) == (3, ["Greece", "Other EU"])
    sites.save()
    again = SponsorSites.load(tmp_path)
    assert again.find("n8n GmbH", "Anything", "uk").site == "JobDelulu"
    assert import_csv(again, csv, "JobDelulu", codes, NOW)[0] == 0  # nothing twice


def test_discovery_saves_the_stack_roles_and_keeps_jobs_it_had_rejected(filters, tmp_path):
    store = JobStore(":memory:")
    filters.visa.sites = SponsorSites.load(tmp_path)
    job_id = store_job(store, filters, company="Manex AI", title="Software Engineer (f/m/d)",
                       remote_status=ONSITE, allowed_locations=["Munich, Germany"], description=TEXT)
    assert store.get(job_id)["reject_code"] == "no_visa_evidence"
    run = discovery.discover(store, FakeHttp(routes()), CONFIG, filters, OutreachConfig(), NOW)
    assert SponsorSites.load(tmp_path).find("Manex AI", "Software Engineer (f/m/d)", "de")
    assert "manex" in " ".join(run.new_site_companies)
    kept = pipeline.rejudge_sponsor_sites(store, filters, NOW, run.new_site_companies)
    assert [(k["job_id"], k["status"]) for k in kept] == [(job_id, VISA_LIST)]
    assert store.get(job_id)["reject_code"] is None
    # A dry run saves nothing.
    fresh = tmp_path / "dry"
    filters.visa.sites = SponsorSites.load(fresh)
    discovery.discover(JobStore(":memory:"), FakeHttp(routes()), CONFIG, filters, OutreachConfig(), NOW, dry_run=True)
    assert not (fresh / "sites.json").exists()


def test_the_fit_score_counts_a_site_listing_as_a_track_record(filters, tmp_path):
    from jobhunter import rubric

    visa = rules(tmp_path, silent_ok=["de"])
    visa.sites.add(SiteEntry("JobDelulu", "TicketSwap", "nl", seen="2026-11-16"))
    filters.visa = visa
    store = JobStore(":memory:")
    listed = store_job(store, filters, company="TicketSwap", remote_status=ONSITE, allowed_locations=["Amsterdam"],
                       description=TEXT)
    silent = store_job(store, filters, remote_status=ONSITE, allowed_locations=["Berlin"], description=TEXT)
    points, why = rubric.visa_points(store.get(listed))
    assert points == rubric.TRACK_RECORD and why.startswith("TicketSwap is on JobDelulu's list")
    assert rubric.visa_points(store.get(silent))[0] == rubric.UNCONFIRMED


def test_a_job_in_two_countries_is_judged_in_each(filters, tmp_path):
    # Spotify, "Stockholm, Sweden" and "London, UK": Sweden keeps no sponsor list, the UK register keeps it.
    from jobhunter.sponsors import Registers, Sponsor

    visa = VisaRules.from_dict({"countries": {"se": {"name": "Sweden", "places": ["Sweden", "Stockholm"]},
                                              "uk": COUNTRIES["uk"]}})
    visa.registers = Registers.from_rows("uk", [Sponsor("uk", "Spotify Limited", "London", "Skilled Worker")])
    result = judge(filters, visa, company="Spotify", allowed_locations=["Stockholm, Sweden", "London, UK"])
    assert result.status == VISA_LIST and result.eligibility.code == "visa_register"
