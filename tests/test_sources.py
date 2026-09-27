"""Adapters against trimmed real responses (tests/fixtures), through a fake HTTP client."""

import json

import httpx

from jobhunter.extract import enrich
from jobhunter.models import HYBRID, REMOTE
from jobhunter.sources import build_sources
from jobhunter.sources import (
    ashby,
    custom_page,
    greenhouse,
    hackernews,
    himalayas,
    lever,
    nodesk,
    remoteok,
    remotive,
    serpapi,
    weworkremotely,
)

from .conftest import FakeHttp, fixture_json, fixture_text


def http_error(url, status=404):
    request = httpx.Request("GET", url)
    return httpx.HTTPStatusError("error", request=request, response=httpx.Response(status, request=request))


def test_greenhouse_parses_and_isolates_a_broken_board():
    ok = greenhouse.API.format(token="gitlab")
    bad = greenhouse.API.format(token="nope")
    http = FakeHttp({ok: fixture_json("greenhouse_gitlab.json"), bad: http_error(bad)})
    source = greenhouse.GreenhouseSource(
        [{"company": "Nope", "board_token": "nope"}, {"company": "GitLab", "board_token": "gitlab"}]
    )
    result = source.fetch(http)
    assert result.errors == ["Nope (nope): HTTP 404 from https://boards-api.greenhouse.io/v1/boards/nope/jobs"]
    job = result.jobs[0]
    assert (job.source_job_id, job.company, job.title) == ("8556658002", "GitLab", "AI Engineer")
    assert job.location_raw == "Remote, Bangalore" and job.remote_status == REMOTE
    assert job.application_url == "https://job-boards.greenhouse.io/gitlab/jobs/8556658002"
    assert "GitLab" in job.description and "&lt;" not in job.description
    assert job.posted_at.isoformat() == "2026-05-22T13:16:29+00:00"


def test_lever_reports_missing_boards():
    ok = lever.API.format(token="metabase")
    missing = lever.API.format(token="gone")
    http = FakeHttp({ok: fixture_json("lever_metabase.json"), missing: {"ok": False, "error": "Document not found"}})
    result = lever.LeverSource([{"company": "Gone", "board_token": "gone"}, {"company": "Metabase", "board_token": "metabase"}]).fetch(http)
    assert result.errors == ["Gone (gone): Document not found"]
    job = result.jobs[1]
    assert job.title == "CI Engineer" and job.allowed_locations == ["Global Remote"]
    # Metabase states pay only in the text; enrich() reads it from there.
    assert job.salary_min is None
    enrich(job)
    assert (job.salary_min, job.salary_max, job.salary_currency, job.salary_period) == (116000, 213000, "USD", "year")


def test_ashby_locations_include_secondary_ones():
    url = ashby.API.format(token="percona")
    result = ashby.AshbySource([{"company": "Percona", "board_token": "percona"}]).fetch(FakeHttp({url: fixture_json("ashby_percona.json")}))
    job = result.jobs[0]
    assert job.allowed_locations[:3] == ["EMEA", "Bucharest", "Dublin"]
    assert job.remote_status == REMOTE and job.employment_type == "FullTime"


def _himalayas_page(first_epoch: int, count: int = 20) -> dict:
    """A page of `count` jobs, newest first, one hour apart."""
    return {
        "totalCount": 1000,
        "jobs": [
            {"guid": f"g{first_epoch - i}", "title": "Backend Engineer", "companyName": "X",
             "locationRestrictions": [], "pubDate": first_epoch - i * 3600}
            for i in range(count)
        ],
    }


def test_himalayas_daily_stops_at_the_limit():
    pages = []
    source = himalayas.HimalayasSource(["backend"], limit=40)
    source.fetch(FakeHttp({himalayas.SEARCH: lambda p: pages.append(p["page"]) or _himalayas_page(2_000_000_000)}))
    assert pages == [1, 2]


def test_himalayas_range_pages_until_it_passes_the_start():
    from datetime import datetime, timezone

    newest = int(datetime(2026, 9, 27, tzinfo=timezone.utc).timestamp())
    pages = []

    def respond(params):
        pages.append(params["page"])
        return _himalayas_page(newest - (params["page"] - 1) * 20 * 3600)  # 20 hours per page

    source = himalayas.HimalayasSource(["backend"], limit=40)
    source.since = datetime(2026, 9, 23, tzinfo=timezone.utc)  # 96 hours back; page 5 covers hours 80-99
    result = source.fetch(FakeHttp({himalayas.SEARCH: respond}))
    assert pages == [1, 2, 3, 4, 5]
    assert min(j.posted_at for j in result.jobs) < source.since  # reached past the start
    assert len(result.jobs) == 100  # not cut at `limit` (40) in a range run


def test_hackernews_range_reads_every_overlapping_thread():
    hits = {"hits": [
        {"objectID": "9", "title": "Ask HN: Who is hiring? (September 2026)", "created_at": "2026-09-01T15:00:00Z"},
        {"objectID": "8", "title": "Ask HN: Who wants to be hired? (September 2026)", "created_at": "2026-09-01T15:00:00Z"},
        {"objectID": "7", "title": "Ask HN: Who is hiring? (August 2026)", "created_at": "2026-08-03T15:00:00Z"},
        {"objectID": "5", "title": "Ask HN: Who is hiring? (July 2026)", "created_at": "2026-07-01T15:00:00Z"},
    ]}
    thread = {"children": [{"id": 1, "text": "Acme | Backend Engineer | REMOTE<p>x", "created_at": "2026-09-02T00:00:00Z"}]}
    routes = {hackernews.SEARCH: hits, hackernews.ITEM.format(id="9"): thread, hackernews.ITEM.format(id="7"): thread}
    from datetime import datetime, timezone

    daily = hackernews.HackerNewsSource().fetch(FakeHttp(routes))
    assert [n for n in daily.notes if n.startswith("thread")] == ["thread: Ask HN: Who is hiring? (September 2026)"]
    ranged = hackernews.HackerNewsSource()
    ranged.since = datetime(2026, 8, 28, tzinfo=timezone.utc)
    notes = [n for n in ranged.fetch(FakeHttp(routes)).notes if n.startswith("thread")]
    assert notes == ["thread: Ask HN: Who is hiring? (September 2026)", "thread: Ask HN: Who is hiring? (August 2026)"]


def test_serpapi_real_response_shape(monkeypatch):
    """Recorded 2026-09-27: dates, remote and schedule live in the plain `extensions` list."""
    monkeypatch.setenv("SERPAPI_API_KEY", "secret")
    from .conftest import NOW

    jobs = [serpapi.parse_job(raw, NOW) for raw in fixture_json("serpapi.json")["jobs_results"]]
    first, second = jobs[0], jobs[1]
    assert first.remote_status == REMOTE and first.location_raw is None  # "Anywhere" = work from home
    assert first.posted_at.date().isoformat() == "2026-09-23"  # "2 days ago" from NOW (Sep 25)
    assert first.employment_type == "Full-time"
    assert second.salary_raw == "82K–111K a year"


def test_himalayas_asks_for_lebanon_and_pages():
    seen = []

    def respond(params):
        seen.append(params)
        data = fixture_json("himalayas_search.json")
        return data if params["page"] == 1 else {"jobs": [], "totalCount": 3}

    result = himalayas.HimalayasSource(["backend"], limit=100).fetch(FakeHttp({himalayas.SEARCH: respond}))
    assert seen[0] == {"q": "backend", "sort": "recent", "page": 1, "country": "LB"}
    job = result.jobs[0]
    # Empty restrictions mean Himalayas does not know, not "any country".
    assert job.allowed_locations == [] and job.location_raw is None
    assert job.company == "Miris" and job.salary_currency == "USD" and job.salary_period == "year"


def test_remotive_splits_candidate_locations():
    result = remotive.RemotiveSource().fetch(FakeHttp({remotive.API: fixture_json("remotive.json")}))
    assert result.jobs[1].allowed_locations == ["USA", "Canada", "Argentina", "Mexico", "Peru"]
    assert result.jobs[1].salary_raw == "$90k - $105k"


def test_remoteok_skips_legal_notice_and_filters_locally():
    data = fixture_json("remoteok.json")
    everything = remoteok.RemoteOkSource().fetch(FakeHttp({remoteok.API: data}))
    assert len(everything.jobs) == len(data) - 1
    filtered = remoteok.RemoteOkSource(queries=["annotator"]).fetch(FakeHttp({remoteok.API: data}))
    assert [j.title for j in filtered.jobs] == ["Video Data Annotator"]
    assert any(j.title == "Mecánico Automotriz Diagnóstico y Presupuestos" for j in everything.jobs)


def test_weworkremotely_country_list_is_the_rule():
    feed = weworkremotely.DEFAULT_FEEDS[0]
    result = weworkremotely.WeWorkRemotelySource([feed]).fetch(FakeHttp({feed: fixture_text("wwr.rss")}))
    worldwide, us_only, north_america = result.jobs
    assert worldwide.allowed_locations == ["Anywhere in the World"]
    assert us_only.allowed_locations == ["Barbados", "United States of America"]
    assert north_america.allowed_locations == ["North America Only"]
    assert worldwide.company == "Iterable" and worldwide.title.startswith("[Evergreen] Account Executive")


def test_hackernews_reads_first_line_and_splits_roles():
    story_id = fixture_json("hn_item.json")["id"]
    http = FakeHttp({
        hackernews.SEARCH: fixture_json("hn_search.json"),
        hackernews.ITEM.format(id=story_id): fixture_json("hn_item.json"),
    })
    result = hackernews.HackerNewsSource().fetch(http)
    modash = result.jobs[0]
    assert (modash.company, modash.title, modash.location_raw) == ("Modash.io", "Senior Product Engineer", "Remote (Europe)")
    assert modash.application_url == "https://apply.workable.com/modash/j/C1507B65C3"
    assert modash.salary_currency == "EUR"
    neon = [j for j in result.jobs if j.company.startswith("Open Education")]
    assert len(neon) == 4 and {j.remote_status for j in neon} == {HYBRID}
    assert "1 comments skipped (no 'Company | Role | ...' first line)" in result.notes


def test_hackernews_remote_status_wording():
    def status(first_line):
        return hackernews.parse_comment({"id": 1, "text": first_line + "<p>Body", "created_at": None})[0].remote_status

    assert status("Acme | Engineer | Cologne | ONSITE (part remote)") == HYBRID
    assert status("Acme | Engineer | REMOTE or ONSITE") == REMOTE
    assert status("Acme | Engineer | Hybrid or Remote") == REMOTE
    assert status("Acme | Engineer | Berlin | 2 days remote") == HYBRID


def test_hackernews_company_drops_urls():
    job = hackernews.parse_comment({"id": 1, "text": "WorkHero https://workhero.pro | Senior SWE | REMOTE<p>x", "created_at": None})[0]
    assert job.company == "WorkHero"


def test_nodesk_tolerates_html_entities():
    feed = nodesk.DEFAULT_FEEDS[0]
    result = nodesk.NoDeskSource().fetch(FakeHttp({feed: fixture_text("nodesk.xml")}))
    assert [(j.title, j.company) for j in result.jobs][1] == ("Web Design and Marketing Partners", "B12")


def test_custom_page_prefers_json_ld():
    listing_url = "https://acme.example/jobs"
    job_url = "https://acme.example/jobs/backend-engineer"
    posting = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Backend Engineer",
        "description": "<p>Python and FastAPI.</p>",
        "datePosted": "2026-09-20",
        "jobLocationType": "TELECOMMUTE",
        "applicantLocationRequirements": [{"@type": "Country", "name": "Lebanon"}],
    }
    http = FakeHttp({
        listing_url: '<a href="/jobs/backend-engineer">Backend</a> <a href="/about">About</a>',
        job_url: f'<html><script type="application/ld+json">{json.dumps(posting)}</script><h1>Ignored</h1></html>',
    })
    page = {"company": "Acme", "url": listing_url, "job_link_pattern": r"/jobs/[a-z-]+$"}
    job = custom_page.CustomPageSource([page]).fetch(http).jobs[0]
    assert (job.title, job.remote_status, job.allowed_locations) == ("Backend Engineer", REMOTE, ["Lebanon"])
    assert job.description == "Python and FastAPI." and job.posted_at.day == 20


def test_custom_page_falls_back_to_h1_and_defaults():
    http = FakeHttp({
        "https://x.example/jobs": '<a href="https://x.example/jobs/tpm">TPM</a>',
        "https://x.example/jobs/tpm": "<html><body><nav>Menu</nav><h1>Technical Product Manager</h1><p>Remote team.</p></body></html>",
    })
    page = {"company": "X", "url": "https://x.example/jobs", "job_link_pattern": "/jobs/[a-z]+$",
            "default_location": "Remote", "default_workplace_type": "remote"}
    job = custom_page.CustomPageSource([page]).fetch(http).jobs[0]
    assert job.title == "Technical Product Manager" and job.location_raw == "Remote"
    assert "Menu" not in job.description


def test_serpapi_without_key_is_skipped(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    result = serpapi.SerpApiSource(["python"]).fetch(FakeHttp({}))
    assert result.jobs == [] and result.notes == ["SERPAPI_API_KEY is not set; source skipped"]


def test_serpapi_anywhere_is_not_a_location(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "secret")
    data = {"jobs_results": [{
        "job_id": "abc",
        "title": "Backend Engineer",
        "company_name": "Acme",
        "location": "Anywhere",
        "description": "Python.",
        "detected_extensions": {"work_from_home": True, "posted_at": "3 days ago", "schedule_type": "Full-time"},
        "apply_options": [
            {"title": "LinkedIn", "link": "https://www.linkedin.com/jobs/view/1"},
            {"title": "Greenhouse", "link": "https://boards.greenhouse.io/acme/jobs/42"},
        ],
    }]}
    job = serpapi.SerpApiSource(["python"]).fetch(FakeHttp({serpapi.API: data})).jobs[0]
    assert job.location_raw is None and job.remote_status == REMOTE
    assert job.application_url == "https://boards.greenhouse.io/acme/jobs/42"


def test_error_lines_never_include_query_strings():
    url = "https://serpapi.com/search.json?api_key=secret&q=x"
    from jobhunter.sources.base import describe_error

    assert "secret" not in describe_error(http_error(url, 401))


def test_build_sources_explains_unused_sections():
    sources, notes = build_sources({
        "greenhouse_boards": [{"company": "A", "board_token": "a"}, {"company": "B", "board_token": "b", "enabled": False}],
        "himalayas": {"enabled": False, "queries": ["x"]},
        "hiringcafe": {"enabled": True},
        "mystery": {},
    })
    assert [s.name for s in sources] == ["greenhouse"] and len(sources[0].boards) == 1
    assert any(n.startswith("hiringcafe: not implemented") for n in notes)
    assert "mystery: unknown config section, ignored" in notes
