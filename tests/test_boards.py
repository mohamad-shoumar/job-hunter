"""Watched boards: the public board of each company that gets a shortlisted job (boards.py)."""

from datetime import timedelta

from jobhunter import boards, cli, pipeline
from jobhunter.config import Filters, OutreachConfig, Paths
from jobhunter.models import SHORTLISTED
from jobhunter.sources import build_sources, greenhouse, himalayas, lever
from jobhunter.store import JobStore

from .conftest import NOW, FakeHttp, fixture_json, store_job

WATCH = {"watch_boards": {"enabled": True, "max_probes_per_run": 10, "retry_after_days": 30}}


def shortlisted(store, filters, **overrides):
    values = dict(company="Fingerprint", title="AI Engineer", allowed_locations=["Worldwide"])
    job_id = store_job(store, filters, **{**values, **overrides})
    assert store.get(job_id)["status"] == SHORTLISTED
    return job_id


def watch(store, http, filters, config=WATCH, outreach=None, now=NOW):
    return boards.watch_shortlisted(store, http, config, filters, outreach or OutreachConfig(), now)


def test_a_board_named_in_the_jobs_own_link_is_watched_without_any_request(filters):
    store = JobStore(":memory:")
    job_id = shortlisted(store, filters, company="DualEntry", title="Backend Engineer",
                         application_url="https://jobs.ashbyhq.com/dualentry/5eca795c-48dd-496a-be23-2181068a5450")
    http = FakeHttp({})
    run = watch(store, http, filters)
    assert http.calls == []
    assert run.added == [{"board": "ashby:dualentry", "company": "DualEntry",
                          "reason": f"job #{job_id} links to its posting there: "
                                    "https://jobs.ashbyhq.com/dualentry/5eca795c-48dd-496a-be23-2181068a5450"}]
    assert [(r["kind"], r["slug"], r["from_job_id"]) for r in boards.watched(store)] == [("ashby", "dualentry", job_id)]


def test_a_guessed_board_is_kept_only_when_it_lists_the_jobs_title(filters):
    store = JobStore(":memory:")
    job_id = shortlisted(store, filters)  # Fingerprint, "AI Engineer"; the GitLab fixture lists "AI Engineer"
    http = FakeHttp({greenhouse.API.format(token="fingerprint"): fixture_json("greenhouse_gitlab.json")})
    run = watch(store, http, filters)
    assert run.added[0]["board"] == "greenhouse:fingerprint"
    assert run.added[0]["reason"] == (f'greenhouse:fingerprint lists "AI Engineer", the shortlisted job\'s title '
                                      f"(job #{job_id})")
    assert run.probed == 1


def test_a_guessed_board_of_another_company_is_not_watched_and_not_retried_for_a_month(filters):
    store = JobStore(":memory:")
    shortlisted(store, filters, title="Backend Engineer")  # not on the board below, and GitLab is not Fingerprint
    http = FakeHttp({greenhouse.API.format(token="fingerprint"): fixture_json("greenhouse_gitlab.json"),
                     lever.API.format(token="fingerprint"): {"ok": False, "error": "Document not found"}})
    run = watch(store, http, filters)  # Ashby is not in the routes: an error, so no board
    assert run.added == [] and boards.watched(store) == []
    assert len(http.calls) == 3
    again = watch(store, http, filters, now=NOW + timedelta(days=5))
    assert again.probed == 0 and len(http.calls) == 3
    watch(store, http, filters, now=NOW + timedelta(days=31))
    assert len(http.calls) == 6


def test_a_greenhouse_board_that_names_the_company_is_watched(filters):
    store = JobStore(":memory:")
    shortlisted(store, filters, company="GitLab", title="Backend Engineer")
    http = FakeHttp({greenhouse.API.format(token="gitlab"): fixture_json("greenhouse_gitlab.json")})
    run = watch(store, http, filters)
    assert run.added[0]["board"] == "greenhouse:gitlab"
    assert run.added[0]["reason"].startswith('greenhouse:gitlab names the company "GitLab"')


def test_job_sites_agencies_and_blocked_companies_are_never_watched(filters):
    store = JobStore(":memory:")
    link = "https://jobs.ashbyhq.com/{}/5eca795c-48dd-496a-be23-2181068a545{}"
    shortlisted(store, filters, company="Proxify AB", application_url=link.format("proxify", 1), source_job_id="1")
    shortlisted(store, filters, company="Board Co", application_url=link.format("boardco", 2), source_job_id="2")
    shortlisted(store, filters, company="Acme", application_url=link.format("acme", 3), source_job_id="3")
    store.conn.execute("INSERT INTO companies (key, name, is_job_board) VALUES ('board', 'Board Co', 1)")
    # Blocked after it was shortlisted (before `reclassify` rejects it).
    filters.blocked_companies = Filters.from_dict({"blocked_companies": [{"name": "Acme"}]}).blocked_companies
    run = watch(store, FakeHttp({}), filters, outreach=OutreachConfig(skip_companies=["Proxify"]))
    assert run.added == []


def test_a_board_already_in_the_config_or_removed_by_you_is_not_added(filters):
    store = JobStore(":memory:")
    shortlisted(store, filters, company="Percona",
                application_url="https://jobs.ashbyhq.com/percona/99ee2a07-7925-4b8e-9b3c-fb5e43cacc50")
    config = {**WATCH, "ashby_boards": [{"company": "Percona", "board_token": "percona"}]}
    assert watch(store, FakeHttp({}), filters, config=config).added == []

    store = JobStore(":memory:")
    shortlisted(store, filters, company="DualEntry",
                application_url="https://jobs.ashbyhq.com/dualentry/5eca795c-48dd-496a-be23-2181068a5450")
    assert watch(store, FakeHttp({}), filters).added
    assert boards.remove(store, "ashby:DualEntry", NOW)
    assert boards.watched(store) == [] and watch(store, FakeHttp({}), filters).added == []


def test_watched_boards_join_the_sources_and_skip_duplicates(filters):
    store = JobStore(":memory:")
    boards.ensure_schema(store)
    for kind, slug, company in [("ashby", "dualentry", "DualEntry"), ("greenhouse", "fingerprint", "Fingerprint"),
                                ("ashby", "percona", "Percona")]:
        store.conn.execute("INSERT INTO watched_boards (kind, slug, company, company_key, reason, added_at) "
                           "VALUES (?, ?, ?, ?, 'test', '2026-09-25')", (kind, slug, company, company.lower()))
    config = {"ashby_boards": [{"company": "Percona", "board_token": "percona"}]}
    sources, _ = build_sources(config)
    assert boards.add_watched_sources(sources, store, config) == 2
    by_name = {s.name: s for s in sources}
    assert [b["board_token"] for b in by_name["ashby"].boards] == ["percona", "dualentry"]
    assert by_name["greenhouse"].boards == [{"company": "Fingerprint", "board_token": "fingerprint"}]


def test_build_sources_does_not_call_watch_boards_a_source():
    sources, notes = build_sources(WATCH)
    assert sources == [] and notes == []


def test_the_daily_run_watches_and_then_fetches_the_board(tmp_path, filters):
    (tmp_path / "config").mkdir()
    raw = fixture_json("himalayas_search.json")["jobs"][0]
    raw.update(companyName="Fingerprint", title="AI Engineer", locationRestrictions=["Worldwide"],
               pubDate=int(NOW.timestamp()) - 3600, applicationLink="https://himalayas.app/companies/fp/jobs/ai")
    board = fixture_json("greenhouse_gitlab.json")
    http = FakeHttp({himalayas.SEARCH: lambda params: {"jobs": [raw]} if params["page"] == 1 else {"jobs": []},
                     greenhouse.API.format(token="fingerprint"): board})
    config = {**WATCH, "himalayas": {"queries": ["backend"], "limit": 20}}
    summary, reports = pipeline.run(Paths(tmp_path), config, filters, http=http, now=NOW, ai=False, outreach=False)
    assert summary.new_by_status[SHORTLISTED] == 1
    assert [a["board"] for a in summary.boards["added"]] == ["greenhouse:fingerprint"]
    assert "**Boards now watched**" in reports[0].read_text()
    assert "greenhouse" not in summary.sources

    summary2, _ = pipeline.run(Paths(tmp_path), config, filters, http=http, now=NOW + timedelta(days=1),
                               ai=False, outreach=False)
    assert summary2.sources["greenhouse"].fetched == 2  # the board's own jobs, fetched like a configured board
    assert summary2.boards["added"] == []


def test_the_boards_command_lists_and_removes(tmp_path, capsys, filters):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "sources.json").write_text("{}")
    (tmp_path / "config" / "filters.json").write_text("{}")
    store = JobStore(tmp_path / "data" / "jobs.sqlite")
    shortlisted(store, filters, company="DualEntry",
                application_url="https://jobs.ashbyhq.com/dualentry/5eca795c-48dd-496a-be23-2181068a5450")
    watch(store, FakeHttp({}), filters)
    store.close()
    assert cli.main(["--home", str(tmp_path), "boards"]) == 0
    assert "ashby:dualentry" in capsys.readouterr().out
    assert cli.main(["--home", str(tmp_path), "boards", "--remove", "ashby:dualentry"]) == 0
    assert cli.main(["--home", str(tmp_path), "boards"]) == 0
    assert "no watched boards yet" in capsys.readouterr().out


def test_slug_guesses_and_board_links():
    assert boards.slug_guesses("Dual Entry Inc.", "www.dualentry.com") == ["dualentry", "dual-entry"]
    assert boards.slug_guesses("Circle.so") == ["circle"]
    assert boards.board_from_links(["https://job-boards.greenhouse.io/tensorops/jobs/123"])[:2] == ("greenhouse", "tensorops")
    assert boards.board_from_links(["https://jobs.lever.co/metabase/5eca795c-48dd-496a-be23-2181068a5450"])[:2] == (
        "lever", "metabase")
    assert boards.board_from_links(["https://acme.com/careers?gh_jid=123", None]) is None
