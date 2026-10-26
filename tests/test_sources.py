"""Adapters against trimmed real responses (tests/fixtures), through a fake HTTP client."""

import json
from datetime import datetime, timezone

import httpx

from jobhunter.extract import enrich
from jobhunter.models import HYBRID, REMOTE
from jobhunter.sources import build_sources
from jobhunter.sources import (
    ashby,
    custom_page,
    euremotejobs,
    greenhouse,
    hackernews,
    himalayas,
    jobicy,
    lever,
    linkedin,
    nodesk,
    remoteok,
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


def _hn(text):
    return hackernews.parse_comment({"id": 7, "text": text, "created_at": None})


def test_hackernews_place_or_url_field_is_never_the_title():
    # Trimmed from the October 2026 thread: the second field is a place, the role is later or in the body.
    albs = _hn("Albs | Freiburg, Germany | ONSITE or HYBRID | Full-time | Member of Technical Staff (Senior &#x2F; Staff)"
               "<p>Albs is an AI research lab in stealth.")
    assert [j.title for j in albs] == ["Member of Technical Staff (Senior / Staff)"]
    assert albs[0].allowed_locations == ["Freiburg, Germany", "ONSITE or HYBRID"]

    yeet = _hn("yeet | Chicago, IL &#x2F; Remote | Full-Time<p>Building a dynamic runtime on top of the Linux BPF "
               "sub-system. Looking for extremely talented &#x2F; passionate Rust developers &#x2F; Backend Engineers "
               "with a deep interest in Linux internals, Distributed Systems, Dev Tools, Great Developer Experiences.")
    assert [j.title for j in yeet] == ["Rust developers", "Backend Engineers"]
    assert {j.location_raw for j in yeet} == {"Chicago, IL / Remote"}
    assert [j.source_job_id for j in yeet] == ["7-0", "7-1"]


def test_hackernews_reads_a_role_list_from_the_body():
    sundream = _hn(
        "Sundream Studio | Multiple Roles | Full-time &#x2F; Contract | NYC &#x2F; Remote"
        "<p>Sundream Studio is an AI filmmaking app.<p>We’re hiring:"
        "<p>• AI Video Content Creators — make films, ads, and tutorials with Sundream."
        "<p>• Software Engineer — build the assistant, generation infrastructure, and editing tools."
        "<p>• Go-to-Market — help filmmakers discover Sundream."
        "<p>• Engineering Manager — lead technical execution, grow the engineering team."
        "<p>Reach out directly at stefan@sundream.studio with the role you’re interested in."
    )
    assert [j.title for j in sundream] == ["Software Engineer", "Engineering Manager"]
    assert sundream[0].location_raw == "NYC / Remote"

    # A place written after a listed role is that job's location; links and salaries are not part of the title.
    coder = _hn(
        "Coder | <a href=\"https:&#x2F;&#x2F;coder.com&#x2F;\">https:&#x2F;&#x2F;coder.com&#x2F;</a> | Multiple roles | "
        "Full-time<p>All positions are fully remote in the countries listed.<p>Engineering"
        "<p>[1]Senior Software Engineer I (Agentic Engineering) - US"
        "<p>[2]Staff Software Engineer (AI Governance) - UK&#x2F;Ireland&#x2F;Poland"
        "<p>- Senior Full Stack Engineer ($150k-$200k) https:&#x2F;&#x2F;jobs.ashbyhq.com&#x2F;coder&#x2F;1"
    )
    assert [(j.title, j.location_raw) for j in coder] == [
        ("Senior Software Engineer I (Agentic Engineering)", "US"),
        ("Staff Software Engineer (AI Governance)", "UK/Ireland/Poland"),
        ("Senior Full Stack Engineer", None),
    ]


def test_hackernews_without_any_role_keeps_an_honest_field():
    clickhouse = _hn("ClickHouse | Remote | Full-time | https:&#x2F;&#x2F;clickhouse.com&#x2F;"
                     "<p>ClickHouse Labs is an applied research group.")
    assert [j.title for j in clickhouse] == ["Remote"]  # nothing names a role: rejected as before, not invented
    apex = _hn("Apex Space | Multiple Roles | Full-Time | Onsite | Los Angeles, CA | apexspace.com"
               "<p>We're hiring everything from technicians to all sorts of engineers: thermal, mechanical.")
    assert [j.title for j in apex] == ["Multiple Roles"]


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


def test_getro_reads_investor_boards_with_their_own_filters():
    from jobhunter.sources import getro

    url = getro.API.format(id=9266)
    bodies = []

    def search(body):
        bodies.append(body)
        return fixture_json("getro_search.json") if body["query"] == "engineer" else {"results": {"jobs": []}}

    board = {"name": "Hub71", "collection_id": 9266, "filters": {"searchable_locations": ["United Arab Emirates"]}}
    result = getro.GetroSource([board], ["engineer", "python"]).fetch(FakeHttp({url: search}))
    assert [b["query"] for b in bodies] == ["engineer", "python"]
    assert bodies[0]["filters"] == {"searchable_locations": ["United Arab Emirates"]} and bodies[0]["page"] == 0
    qashio, sentinel, worldremit = result.jobs
    assert (qashio.company, qashio.title) == ("Qashio", "Full-stack Engineer (AI-native)")
    assert qashio.remote_status == "onsite" and qashio.allowed_locations == ["Dubai - United Arab Emirates"]
    assert qashio.application_url == "https://careers.qashio.com/jobs/8357928-full-stack-engineer-ai-native"
    assert qashio.posted_at.year == 2026 and "Next.js" in qashio.tags and qashio.salary_min is None
    # "Remote" next to a country is the work mode, not a place to live.
    assert sentinel.remote_status == REMOTE and sentinel.allowed_locations == ["United States"]
    assert (sentinel.salary_min, sentinel.salary_max, sentinel.salary_currency, sentinel.salary_period) == (
        156000, 215000, "USD", "year")
    assert worldremit.allowed_locations == ["United Kingdom"] and worldremit.salary_currency is None


def test_getro_isolates_a_broken_board():
    from jobhunter.sources import getro

    bad, ok = getro.API.format(id=1), getro.API.format(id=9266)
    http = FakeHttp({bad: http_error(bad, 500), ok: fixture_json("getro_search.json")})
    source = getro.GetroSource([{"name": "Gone", "collection_id": 1}, {"name": "Hub71", "collection_id": 9266}], ["x"])
    result = source.fetch(http)
    assert result.errors == ["Gone (1) 'x': HTTP 500 from https://api.getro.com/api/v2/collections/1/search/jobs"]
    assert len(result.jobs) == 3


def test_serpapi_city_queries_run_on_their_day_with_their_location(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "secret")
    from jobhunter.text import utcnow

    today = utcnow().date().toordinal() % 3
    queries = ["python remote"] + [
        {"q": "backend engineer", "location": city, "every_days": 3, "day": day}
        for day, city in enumerate(["Dubai,Dubai,United Arab Emirates", "Abu Dhabi,Abu Dhabi,United Arab Emirates",
                                    "Doha,Doha Municipality,Qatar"])
    ]
    http = FakeHttp({serpapi.API: {"jobs_results": []}})
    serpapi.SerpApiSource(queries).fetch(http)
    sent = [(p["q"], p.get("location")) for _, p in http.calls]
    city = queries[1 + today]["location"]
    assert sent == [("python remote", None), ("backend engineer", city)]


def test_arbeitnow_country_from_the_site_and_twice_escaped_descriptions():
    from jobhunter.sources import arbeitnow

    data = fixture_json("arbeitnow.json")
    jobs = {j.company: j for j in (arbeitnow.parse_job(raw) for raw in data["data"])}
    assert jobs["sumup"].location_raw == "Berlin, Germany" and jobs["sumup"].allowed_locations == ["Berlin, Germany"]
    assert jobs["Deliveroo"].location_raw == "London, England, United Kingdom"  # already says the country
    assert jobs["Blocktech"].location_raw == "Amsterdam, Netherlands"
    # A remote job's country is unknown: arbeitnow.com is not "remote for people in Germany".
    assert jobs["Kairos Project"].remote_status == REMOTE and jobs["Kairos Project"].allowed_locations == []
    # sumup's description came escaped twice: it reads as text, not as "<p>" tags.
    assert "<p>" not in jobs["sumup"].description and "&lt;" not in jobs["sumup"].description
    assert "The MarTech team builds the marketing" in jobs["sumup"].description
    assert jobs["Terraquantum"].posted_at.isoformat().startswith("2026-10-07")


def test_arbeitnow_keeps_wanted_titles_and_stops_at_the_look_back():
    from datetime import datetime, timezone

    from jobhunter.sources import arbeitnow

    data = fixture_json("arbeitnow.json")
    pages = []

    def respond(params):
        pages.append(params)
        page = dict(data)
        if params["page"] > 1:  # older jobs further down
            page["data"] = [dict(raw, created_at=raw["created_at"] - 30 * 86400) for raw in data["data"]]
        return page

    url = arbeitnow.API.format(site="https://www.arbeitnow.com")
    source = arbeitnow.ArbeitnowSource([{"site": "https://www.arbeitnow.com", "visa_sponsorship": True}],
                                       ["backend", "python", "software"], max_pages=5)
    source.since = datetime(2026, 10, 1, tzinfo=timezone.utc)
    result = source.fetch(FakeHttp({url: respond}))
    assert [p["page"] for p in pages] == [1, 2] and pages[0]["visa_sponsorship"] == "true"
    titles = {j.title for j in result.jobs}
    assert "Recruiter" not in titles and "Senior Backend Engineer - MarTech" in titles


def test_workable_searches_each_country_and_reads_the_three_text_parts():
    from jobhunter.sources import workable

    calls = []

    def respond(params):
        calls.append(dict(params))
        data = fixture_json("workable_search.json")
        if "pageToken" in params:
            data = dict(data, jobs=[], nextPageToken=None)
        return data

    source = workable.WorkableSource(["python"], ["Netherlands", "United Kingdom"], day_range=3, max_pages=2)
    result = source.fetch(FakeHttp({workable.API: respond}))
    assert [(c["location"], c.get("pageToken")) for c in calls] == [
        ("Netherlands", None), ("Netherlands", "tok2"), ("United Kingdom", None), ("United Kingdom", "tok2")]
    assert calls[0]["day_range"] == 3
    jobs = {j.company: j for j in result.jobs}
    assert jobs["payabl."].remote_status == REMOTE and jobs["payabl."].allowed_locations == ["Netherlands"]
    assert jobs["OrganOx"].location_raw.startswith("Oxford") and jobs["OrganOx"].remote_status == "onsite"
    assert jobs["Informed Solutions"].remote_status == HYBRID
    assert "<p>" not in jobs["OrganOx"].description and jobs["OrganOx"].posted_at is not None


def test_jobicy_keeps_target_titles_and_its_hiring_region():
    data = fixture_json("jobicy.json")
    result = jobicy.JobicySource(["software engineer"]).fetch(FakeHttp({jobicy.API: data}))
    assert [(j.title, j.company, j.allowed_locations) for j in result.jobs] == [
        ("Staff Software Engineer", "saas.group", ["EMEA"])]
    job = result.jobs[0]
    assert job.application_url == job.source_url and job.source_url.startswith("https://jobicy.com/jobs/")
    assert job.posted_at.isoformat() == "2026-10-21T03:15:12+00:00"
    everything = jobicy.JobicySource([]).fetch(FakeHttp({jobicy.API: data}))
    assert everything.jobs[2].allowed_locations == ["USA"] and everything.jobs[2].salary_min == 170000


def test_euremotejobs_reads_the_job_page_of_target_titles_only(monkeypatch):
    monkeypatch.setattr(euremotejobs, "utcnow", lambda: datetime(2026, 10, 21, 12, tzinfo=timezone.utc))
    listing = fixture_json("euremotejobs_listings.json")
    page = fixture_text("euremotejobs_job.html")
    http = FakeHttp({euremotejobs.LISTINGS: listing,
                     "https://euremotejobs.com/job/security-architect-2/": page,
                     "https://euremotejobs.com/job/platform-engineer-compute/": http_error("x", 500)})
    result = euremotejobs.EuRemoteJobsSource(["architect", "platform engineer"]).fetch(http)
    by_title = {j.title: j for j in result.jobs}
    assert set(by_title) == {"Security Architect", "Platform Engineer – Compute"}  # not the finance manager
    netbox = by_title["Security Architect"]
    assert netbox.company == "NetBox Labs" and netbox.allowed_locations == ["UK", "US"]
    assert netbox.application_url.startswith("https://jobs.ashbyhq.com/netboxlabs/")
    assert "NetBox Labs builds NetBox" in netbox.description
    supabase = by_title["Platform Engineer – Compute"]  # its page failed: the listing row is kept
    assert supabase.company == "Supabase" and supabase.allowed_locations == ["Worldwide"]
    assert supabase.description == "" and len(result.errors) == 1


def test_linkedin_fetches_pages_of_target_titles_only(monkeypatch):
    monkeypatch.setattr(linkedin, "utcnow", lambda: datetime(2026, 10, 21, 12, tzinfo=timezone.utc))
    posting = linkedin.POSTING.format(id="4478986376")
    http = FakeHttp({linkedin.SEARCH: fixture_text("linkedin_search.html"), posting: fixture_text("linkedin_job.html")})
    source = linkedin.LinkedInSource([{"keywords": "backend engineer", "location": "United Arab Emirates"}],
                                     ["back end developer", "backend"], pause=0)
    result = source.fetch(http)
    assert http.calls[0][1] == {"keywords": "backend engineer", "location": "United Arab Emirates",
                                "f_TPR": "r86400", "start": 0}
    assert len(http.calls) == 2  # 2 cards (< 10): one search page; the lead role's page is never read
    [job] = result.jobs
    assert (job.title, job.company, job.location_raw) == ("Back End Developer", "Confidential",
                                                          "Dubai, United Arab Emirates")
    assert job.source_url == job.application_url == "https://www.linkedin.com/jobs/view/4478986376"
    assert "Mid-Level .NET Backend Developer" in job.description
    assert job.tags == ["Associate"] and job.posted_at.date().isoformat() == "2026-10-21"


def test_a_malformed_posting_costs_only_itself_not_its_board_or_the_others():
    broken = fixture_json("lever_metabase.json")
    broken[0]["categories"] = "broken"  # not the object Lever sends
    acme, metabase = lever.API.format(token="acme"), lever.API.format(token="metabase")
    http = FakeHttp({acme: broken, metabase: fixture_json("lever_metabase.json")})
    boards = [{"company": "Acme", "board_token": "acme"}, {"company": "Metabase", "board_token": "metabase"}]
    result = lever.LeverSource(boards).fetch(http)
    assert result.errors == [
        "Acme (acme) job 5eca795c-48dd-496a-be23-2181068a5450: AttributeError: 'str' object has no attribute 'get'"]
    assert [(j.company, j.title) for j in result.jobs] == [
        ("Acme", "CI Engineer"), ("Metabase", "Analytics Engineer"), ("Metabase", "CI Engineer")]


def test_a_posting_without_an_id_is_named_by_its_place_and_the_next_page_is_still_read():
    from jobhunter.sources import workable

    def respond(params):
        data = fixture_json("workable_search.json")
        if "pageToken" in params:
            return dict(data, nextPageToken=None)
        del data["jobs"][1]["id"]
        return data

    result = workable.WorkableSource(["python"], ["Netherlands"]).fetch(FakeHttp({workable.API: respond}))
    assert result.errors == ["\"python\" in Netherlands page 1 item 2: KeyError: 'id'"]
    assert [j.company for j in result.jobs] == ["payabl.", "Informed Solutions", "payabl.", "OrganOx", "Informed Solutions"]


def test_custom_page_with_a_link_that_is_not_a_url_costs_only_that_page():
    http = FakeHttp({
        "https://bad.example/jobs": '<a href="http://[broken/jobs/x">x</a>',
        "https://x.example/jobs": '<a href="https://x.example/jobs/tpm">TPM</a>',
        "https://x.example/jobs/tpm": "<html><body><h1>Technical Product Manager</h1></body></html>",
    })
    pages = [{"company": "Bad", "url": "https://bad.example/jobs", "job_link_pattern": "/jobs/"},
             {"company": "X", "url": "https://x.example/jobs", "job_link_pattern": "/jobs/[a-z]+$"}]
    result = custom_page.CustomPageSource(pages).fetch(http)
    assert result.errors == ["Bad: ValueError: Invalid IPv6 URL"]
    assert [j.title for j in result.jobs] == ["Technical Product Manager"]
