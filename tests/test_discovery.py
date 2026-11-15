"""Board discovery: EuropeVisaJobs and The Stack point to company boards to watch (discovery.py)."""

from datetime import timedelta

import pytest

from jobhunter import boards, discovery, pipeline
from jobhunter.config import Filters, OutreachConfig, Paths
from jobhunter.sources import ashby, greenhouse
from jobhunter.store import JobStore
from jobhunter.store.watched import watched_boards

from .conftest import NOW, FakeHttp, fixture_json

CONFIG = {"watch_boards": {"enabled": True, "max_probes_per_run": 10, "retry_after_days": 30},
          "discover_boards": {"enabled": True}}
EMPTY_SEARCH = {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": {"jobs": [], "next_offset": None}}}
OPTIVER = {"jobs": [{"title": "Software Engineer - Talent Tooling", "company_name": "Optiver"}]}


def stack_reply(body):
    """The trimmed real reply (German listings, with its `next_step` text) for Germany; nothing elsewhere."""
    country = body["params"]["arguments"]["country"]
    return fixture_json("thestack_search.json") if country == "Germany" else EMPTY_SEARCH


def routes(**overrides):
    return {discovery.EUROPEVISAJOBS_FEED: fixture_json("europevisajobs_feed.json"),
            discovery.THE_STACK: stack_reply,
            greenhouse.API.format(token="optiver"): OPTIVER, **overrides}


def discover(store, http, filters, config=CONFIG, outreach=None, now=NOW, dry_run=False):
    return discovery.discover(store, http, config, filters, outreach or OutreachConfig(), now, dry_run=dry_run)


def test_listings_with_target_titles_name_the_boards_to_watch(filters):
    store = JobStore(":memory:")
    run = discover(store, FakeHttp(routes()), filters)
    # The two sites' listings are taken in turn, each in its own order.
    assert [a["board"] for a in run.added] == ["ashby:wayve", "ashby:manex", "greenhouse:navvis", "greenhouse:optiver"]
    assert run.by_site == {"EuropeVisaJobs": {"listed": 4, "wanted": 3, "added": 3},
                           "The Stack": {"listed": 3, "wanted": 2, "added": 1}}
    assert {(r["kind"], r["slug"]) for r in watched_boards(store)} == {
        ("ashby", "wayve"), ("greenhouse", "navvis"), ("greenhouse", "optiver"), ("ashby", "manex")}
    reasons = {a["board"]: a["reason"] for a in run.added}
    # A link names the board; the job-boards.eu.greenhouse.io host counts too.
    assert reasons["greenhouse:navvis"] == ('EuropeVisaJobs lists "Software Engineer SLAM (F/M/D)" (Germany) with a '
                                            'link to its posting there: '
                                            'https://job-boards.eu.greenhouse.io/navvis/jobs/4840884101')
    # A ?gh_jid= link on the company's own site: the guessed board lists the same title.
    assert reasons["greenhouse:optiver"] == ('EuropeVisaJobs lists "Software Engineer - Talent Tooling" (the '
                                             'Netherlands); greenhouse:optiver lists "Software Engineer - Talent '
                                             'Tooling", the same title')
    assert reasons["ashby:manex"].startswith('The Stack lists "Software Engineer (f/m/d)" (Germany)')
    # Palantir's security title and SumUp's analyst title are not target roles; Akur8 is in France.
    assert (run.listed, run.wanted) == (7, 5)
    assert run.unreadable == {"successfactors": 1}  # Sonova: counted, not followed


def test_a_second_run_adds_nothing_and_a_board_you_removed_stays_out(filters):
    store = JobStore(":memory:")
    assert discover(store, FakeHttp(routes()), filters).added
    assert discover(store, FakeHttp(routes()), filters).added == []
    assert boards.remove(store, "ashby:wayve", NOW)
    assert discover(store, FakeHttp(routes()), filters).added == []
    config = {**CONFIG, "ashby_boards": [{"company": "Manex", "board_token": "manex"}]}
    fresh = JobStore(":memory:")
    assert "ashby:manex" not in [a["board"] for a in discover(fresh, FakeHttp(routes()), filters, config=config).added]


def test_blocked_companies_agencies_and_job_sites_are_not_watched(filters):
    store = JobStore(":memory:")
    store.conn.execute("INSERT INTO companies (key, name, is_job_board) VALUES ('navvis', 'NavVis', 1)")
    filters.blocked_companies = Filters.from_dict({"blocked_companies": [{"name": "Wayve"}]}).blocked_companies
    run = discover(store, FakeHttp(routes()), filters, outreach=OutreachConfig(skip_companies=["Optiver"]))
    assert [a["board"] for a in run.added] == ["ashby:manex"]


def test_a_guess_that_finds_no_board_waits_a_month(filters):
    store = JobStore(":memory:")
    other = {"jobs": [{"title": "Trader", "company_name": "Someone Else"}]}
    http = FakeHttp(routes(**{greenhouse.API.format(token="optiver"): other}))
    assert "greenhouse:optiver" not in [a["board"] for a in discover(store, http, filters).added]
    http = FakeHttp(routes())
    discover(store, http, filters, now=NOW + timedelta(days=5))
    assert greenhouse.API.format(token="optiver") not in [url for url, _ in http.calls]
    later = discover(store, FakeHttp(routes()), filters, now=NOW + timedelta(days=31))
    assert "greenhouse:optiver" in [a["board"] for a in later.added]


def test_at_most_max_new_per_run_boards_are_added_a_run_shared_between_the_sites(filters):
    # Read one after the other, EuropeVisaJobs' listings filled the limit before The Stack's were looked at
    # (2026-11-15: 15 of 15 boards from EuropeVisaJobs). Taken in turn, each site gets its share.
    store = JobStore(":memory:")
    config = {**CONFIG, "discover_boards": {"enabled": True, "max_new_per_run": 2}}
    first = discover(store, FakeHttp(routes()), filters, config=config)
    assert [a["board"] for a in first.added] == ["ashby:wayve", "ashby:manex"]
    assert {site: n["added"] for site, n in first.by_site.items()} == {"EuropeVisaJobs": 1, "The Stack": 1}
    assert first.notes == ["board limit (2) reached; the rest are added on the next runs"]
    assert [a["board"] for a in discover(store, FakeHttp(routes()), filters, config=config).added] == [
        "greenhouse:navvis", "greenhouse:optiver"]


def test_a_site_that_finds_nothing_or_fails_shows_zero(filters):
    nothing = {**routes(), discovery.THE_STACK: lambda body: EMPTY_SEARCH}
    run = discover(JobStore(":memory:"), FakeHttp(nothing), filters)
    assert run.by_site["The Stack"] == {"listed": 0, "wanted": 0, "added": 0}
    assert discovery.site_line(run.by_site) == ("EuropeVisaJobs 4 listed, 3 target, 3 boards; "
                                                "The Stack 0 listed, 0 target, 0 boards")
    down = discover(JobStore(":memory:"), FakeHttp(routes(**{discovery.THE_STACK: RuntimeError("down")})), filters)
    assert down.by_site["The Stack"]["listed"] == 0 and down.errors == ["The Stack: RuntimeError: down"]


def test_a_dry_run_writes_nothing(filters):
    store = JobStore(":memory:")
    run = discover(store, FakeHttp(routes()), filters, dry_run=True)
    assert len(run.added) == 4 and watched_boards(store) == []


def test_one_site_down_does_not_stop_the_other(filters):
    store = JobStore(":memory:")
    run = discover(store, FakeHttp(routes(**{discovery.EUROPEVISAJOBS_FEED: RuntimeError("down")})), filters)
    assert [a["board"] for a in run.added] == ["ashby:manex"]
    assert run.errors == ["EuropeVisaJobs: RuntimeError: down"]


def test_only_the_stack_jobs_are_read_never_its_next_step(filters):
    # The trimmed real reply carries a `next_step` text for AI assistants; nothing of it reaches the run.
    assert "next_step" in fixture_json("thestack_search.json")["result"]["structuredContent"]
    run = discover(JobStore(":memory:"), FakeHttp(routes()), filters)
    assert "Offer the user" not in str(run.to_dict())


def test_adding_a_board_by_hand_checks_it_first(filters):
    store = JobStore(":memory:")
    http = FakeHttp({ashby.API.format(token="manex"): {"jobs": [{"title": "Software Engineer"}]},
                     ashby.API.format(token="nobody"): {"jobs": []}})
    assert boards.add_by_hand(store, http, "ashby:manex", "Manex AI", NOW).startswith("now watching ashby:manex")
    assert [(r["kind"], r["slug"], r["company"]) for r in watched_boards(store)] == [("ashby", "manex", "Manex AI")]
    assert boards.add_by_hand(store, http, "ashby:manex", "", NOW) == "already watched: ashby:manex"
    with pytest.raises(SystemExit, match="no postings"):
        boards.add_by_hand(store, http, "ashby:nobody", "", NOW)
    with pytest.raises(SystemExit, match="kind:slug"):
        boards.add_by_hand(store, http, "workday:acme", "", NOW)
    boards.remove(store, "ashby:manex", NOW)
    with pytest.raises(SystemExit, match="stays removed"):
        boards.add_by_hand(store, http, "ashby:manex", "", NOW)


def test_the_daily_run_finds_the_boards_and_fetches_them_from_the_next_run(tmp_path, filters):
    (tmp_path / "config").mkdir()
    found = {ashby.API.format(token="wayve"): {"jobs": []}, ashby.API.format(token="manex"): {"jobs": []},
             greenhouse.API.format(token="navvis"): {"jobs": []}}
    http = FakeHttp(routes(**found))
    summary, reports = pipeline.run(Paths(tmp_path), CONFIG, filters,
                                    pipeline.RunOptions(http=http, now=NOW, ai=False, outreach=False))
    assert [a["board"] for a in summary.discovery.added] == [
        "ashby:wayve", "ashby:manex", "greenhouse:navvis", "greenhouse:optiver"]
    assert summary.to_dict()["discovery"]["unreadable"] == {"successfactors": 1}
    report = "".join(p.read_text() for p in reports)
    assert "**Boards found on visa job sites**" in report
    assert "- Per site: EuropeVisaJobs 4 listed, 3 target, 3 boards; The Stack 3 listed, 2 target, 1 boards" in report
    http.routes[greenhouse.API.format(token="optiver")] = {"jobs": []}  # OPTIVER only stubs the title check
    summary2, _ = pipeline.run(Paths(tmp_path), CONFIG, filters,
                               pipeline.RunOptions(http=http, now=NOW + timedelta(days=1), ai=False, outreach=False))
    assert {"ashby", "greenhouse"} <= set(summary2.sources) and summary2.discovery.added == []
    assert not summary2.sources["ashby"].errors and not summary2.sources["greenhouse"].errors
