"""Company careers systems used in the Gulf and Lebanon: Teamtailor, BambooHR, SmartRecruiters, Pinpoint."""

from datetime import timedelta

from jobhunter.models import HYBRID, ONSITE, REMOTE
from jobhunter.sources import bamboohr, build_sources, pinpoint, smartrecruiters, teamtailor
from jobhunter.text import utcnow

from .conftest import FakeHttp, fixture_json, fixture_text


def test_teamtailor_reads_the_feed_of_a_subdomain_or_a_custom_domain():
    assert teamtailor.feed_url({"board_token": "spidersilk"}) == "https://spidersilk.teamtailor.com/jobs.rss"
    assert teamtailor.feed_url({"site": "careers.calo.app"}) == "https://careers.calo.app/jobs.rss"
    url = "https://spidersilk.teamtailor.com/jobs.rss"
    board = {"company": "spiderSilk", "board_token": "spidersilk"}
    fde, backend = teamtailor.TeamtailorSource([board]).fetch(FakeHttp({url: fixture_text("teamtailor_spidersilk.rss")})).jobs
    assert (fde.company, fde.title) == ("spiderSilk", "Forward Deployed Engineer - Silkrunner")
    assert fde.allowed_locations == ["Dubai, United Arab Emirates"]
    assert fde.remote_status == ONSITE  # Teamtailor's "none": not remote at all
    assert fde.source_url == "https://spidersilk.teamtailor.com/jobs/8108539-forward-deployed-engineer-silkrunner"
    assert fde.posted_at.isoformat() == "2026-07-22T11:37:08+00:00"
    assert fde.description and "<" not in fde.description
    assert backend.title == "Senior Software Engineer (Backend)"


def test_teamtailor_isolates_a_broken_site():
    from .test_sources import http_error

    bad = "https://gone.teamtailor.com/jobs.rss"
    result = teamtailor.TeamtailorSource([{"company": "Gone", "board_token": "gone"}]).fetch(FakeHttp({bad: http_error(bad)}))
    assert result.errors == [f"Gone ({bad}): HTTP 404 from {bad}"] and result.jobs == []


def test_bamboohr_takes_the_description_date_and_country_from_each_job_page():
    board = {"company": "Toters", "board_token": "toters"}
    routes = {
        bamboohr.LIST.format(token="toters"): fixture_json("bamboohr_toters_list.json"),
        bamboohr.DETAIL.format(token="toters", id="565"): fixture_json("bamboohr_toters_detail.json"),
        bamboohr.DETAIL.format(token="toters", id="119"): RuntimeError("down"),
    }
    result = bamboohr.BambooHRSource([board]).fetch(FakeHttp(routes))
    backend, account = result.jobs
    assert (backend.title, backend.company) == ("Staff Backend Engineer", "Toters")
    assert backend.allowed_locations == ["Metn, Lebanon"] and backend.remote_status == HYBRID
    assert backend.posted_at.date().isoformat() == "2025-10-01" and "Backend" in backend.description
    assert backend.application_url == "https://toters.bamboohr.com/careers/565"
    # A job page that fails still gives the job from the list, without its country.
    assert account.allowed_locations == ["Najaf"] and account.remote_status == ONSITE and account.posted_at is None
    assert result.errors == ["Toters job 119: RuntimeError: down"]


def test_smartrecruiters_pages_by_country_and_skips_descriptions_of_old_postings():
    listing = fixture_json("smartrecruiters_list.json")
    # Make the instashop posting fresh and the backend one old, whatever today is.
    now = utcnow()
    listing["content"][0]["releasedDate"] = (now - timedelta(days=200)).isoformat()
    listing["content"][1]["releasedDate"] = (now - timedelta(days=3)).isoformat()
    api = smartrecruiters.API.format(id="deliveryhero")
    calls = []

    def postings(params):
        calls.append(params)
        return listing if params.get("country") == "ae" else {"content": [], "totalFound": 0}

    routes = {api: postings, f"{api}/744000154064000": fixture_json("smartrecruiters_detail.json")}
    board = {"company": "Delivery Hero", "board_token": "deliveryhero", "countries": ["ae", "qa"]}
    result = smartrecruiters.SmartRecruitersSource([board]).fetch(FakeHttp(routes))
    assert [c["country"] for c in calls] == ["ae", "qa"] and calls[0]["offset"] == 0
    assert result.errors == [] and result.notes == ["Delivery Hero (deliveryhero, qa): board has no open jobs"]
    old, fresh = result.jobs
    assert old.title == "Senior Software Engineer- Backend" and old.description == ""
    assert old.allowed_locations == ["Dubai, Dubai, United Arab Emirates"] and old.remote_status == ONSITE
    assert "instashop" in fresh.description
    assert fresh.application_url.startswith("https://jobs.smartrecruiters.com/DeliveryHero/744000154064000")


def test_pinpoint_reads_every_job_with_its_description():
    url = pinpoint.API.format(token="tabby")
    jobs = pinpoint.PinpointSource([{"company": "Tabby", "board_token": "tabby"}]).fetch(
        FakeHttp({url: fixture_json("pinpoint_tabby.json")})).jobs
    remote, dubai = jobs
    assert remote.title == "Senior Data Engineer" and remote.remote_status == REMOTE
    assert remote.allowed_locations == ["Belgrade"]  # "Remote" in the country slot is not a place
    assert dubai.allowed_locations == ["Dubai, UAE"] and dubai.remote_status == ONSITE
    assert dubai.posted_at is None and dubai.salary_min is None and "Tabby" in dubai.description


def test_the_company_board_sections_are_built():
    sources, notes = build_sources({
        "teamtailor_boards": [{"company": "A", "board_token": "a"}],
        "bamboohr_boards": [{"company": "B", "board_token": "b"}],
        "smartrecruiters_boards": [{"company": "C", "board_token": "c"}],
        "pinpoint_boards": [{"company": "D", "board_token": "d", "enabled": False}],
    })
    assert [s.name for s in sources] == ["teamtailor", "bamboohr", "smartrecruiters"] and notes == []


def test_a_company_board_keeps_jobs_listed_for_longer(filters):
    from jobhunter.classify import classify

    from .conftest import NOW, make_job

    def status(source, days):
        job = make_job(source=source, allowed_locations=["Worldwide"], posted_at=NOW - timedelta(days=days))
        return classify(job, filters, NOW)

    assert status("teamtailor", 60).status == "shortlisted"
    assert status("greenhouse", 60).status == "shortlisted"
    assert status("himalayas", 60).reject_code == "too_old"
    old = status("teamtailor", 120)
    assert old.reject_code == "too_old" and old.reject_reason == "Posted 120 days before it was found (limit 90)"
