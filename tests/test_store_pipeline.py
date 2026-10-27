"""Dedup across sources, 'only new jobs', rejected jobs staying rejected, reports."""

import contextlib
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from jobhunter import boards, pipeline
from jobhunter import http as http_module
from jobhunter.ai_check import CheckRun
from jobhunter.config import Filters, Paths
from jobhunter.fitgrade import GradeRun
from jobhunter.models import CLOSED, NEEDS_REVIEW, REJECTED, SAVED, SHORTLISTED
from jobhunter.posted_date import DateRun
from jobhunter.report import write_report
from jobhunter.sources import Source, SourceResult
from jobhunter.sources import greenhouse, himalayas
from jobhunter.store import JobStore
from jobhunter.store.applications import get_application

from .conftest import NOW, FakeHttp, fixture_json, make_job, store_job


def ingest(store, filters, *results, now=NOW):
    summary = pipeline.RunSummary(run_id=store.start_run(now), started_at=now.isoformat())
    pipeline.ingest(store, list(results), filters, summary.run_id, now, summary)
    return summary


def job_count(store):
    return store.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]


def test_same_job_on_aggregator_and_ats_is_one_job(filters):
    store = JobStore(":memory:")
    ats = make_job(source="greenhouse", source_job_id="42", source_url="https://job-boards.greenhouse.io/acme/jobs/42",
                   application_url="https://job-boards.greenhouse.io/acme/jobs/42", allowed_locations=["Worldwide"])
    board = make_job(source="weworkremotely", source_job_id="wwr-1", source_url="https://weworkremotely.com/remote-jobs/acme-1",
                     company="Acme Inc.", title="Sr. Backend Engineer - Python",
                     application_url="https://boards.greenhouse.io/acme/jobs/42?gh_src=wwr")
    summary = ingest(store, filters, SourceResult("greenhouse", [ats]), SourceResult("weworkremotely", [board]))
    assert job_count(store) == 1 and summary.new == 1
    assert {s["source"] for s in store.sightings_for([1])[1]} == {"greenhouse", "weworkremotely"}


def test_fingerprint_merges_boards_without_ats_links(filters):
    store = JobStore(":memory:")
    a = make_job(source="remotive", source_job_id="r1", company="Acme GmbH", title="Backend Engineer (Remote)")
    b = make_job(source="himalayas", source_job_id="h1", company="acme", title="Back-end Engineer")
    ingest(store, filters, SourceResult("remotive", [a]), SourceResult("himalayas", [b]))
    assert job_count(store) == 1


def test_same_title_different_ats_postings_stay_separate(filters):
    store = JobStore(":memory:")
    emea = make_job(source="greenhouse", source_job_id="1", source_url="https://job-boards.greenhouse.io/acme/jobs/1",
                    allowed_locations=["EMEA"])
    us = make_job(source="greenhouse", source_job_id="2", source_url="https://job-boards.greenhouse.io/acme/jobs/2",
                  allowed_locations=["US"])
    ingest(store, filters, SourceResult("greenhouse", [emea, us]))
    assert job_count(store) == 2


def test_rerun_finds_nothing_new_and_rejected_jobs_stay_rejected(filters):
    store = JobStore(":memory:")
    good = make_job(source_job_id="good", allowed_locations=["Worldwide"])
    bad = make_job(source_job_id="bad", title="Account Executive", company="Other Co")
    first = ingest(store, filters, SourceResult("test", [good, bad]))
    assert first.new_by_status == {SHORTLISTED: 1, REJECTED: 1}
    later = NOW + timedelta(days=1)
    second = ingest(store, filters, SourceResult("test", [make_job(source_job_id="good", allowed_locations=["Worldwide"]),
                                                         make_job(source_job_id="bad", title="Account Executive", company="Other Co")]),
                    now=later)
    assert second.new == 0 and job_count(store) == 2
    assert store.get(2)["status"] == REJECTED
    assert store.get(1)["last_seen"] == later.isoformat()


def test_later_sighting_fills_missing_fields_and_prefers_ats_url(filters):
    store = JobStore(":memory:")
    ingest(store, filters, SourceResult("remotive", [make_job(source="remotive", source_job_id="r1", description="",
                                                                application_url="https://remotive.com/x")]))
    ingest(store, filters, SourceResult("lever", [make_job(
        source="lever", source_job_id="5eca795c-48dd-496a-be23-2181068a5450",
        application_url="https://jobs.lever.co/acme/5eca795c-48dd-496a-be23-2181068a5450",
        description="Full description.")]))
    row = store.get(1)
    assert row["description"] == "Full description."
    assert row["application_url"].startswith("https://jobs.lever.co/")
    assert row["ats_key"] == "lever:5eca795c-48dd-496a-be23-2181068a5450"


def test_old_postings_are_rejected_at_discovery(filters):
    store = JobStore(":memory:")
    ingest(store, filters, SourceResult("test", [make_job(posted_at=NOW - timedelta(days=90), allowed_locations=["Worldwide"])]))
    assert store.get(1)["reject_code"] == "too_old"


TODAY = pipeline.local_day(NOW).isoformat()


def daily(store, filters, *results, now=NOW):
    summary = ingest(store, filters, *results, now=now)
    return summary, pipeline.assign_daily(store, summary, now)


def test_daily_report_is_named_by_date_and_explains_rejections(tmp_path, filters):
    store = JobStore(":memory:")
    summary, days = daily(store, filters, SourceResult("test", [
        make_job(source_job_id="a", allowed_locations=["Worldwide"]),
        make_job(source_job_id="b", company="Beta", location_raw="Remote"),
        make_job(source_job_id="c", company="Gamma", title="Engineering Manager, Backend"),
        make_job(source_job_id="d", company="Delta", title="Backend Engineer", allowed_locations=["Remote - US"]),
        make_job(source_job_id="e", company="Epsilon", title="Account Executive"),
    ]))
    assert days == [TODAY]
    path = write_report(store, tmp_path, TODAY, summary.to_dict(), NOW)
    assert path.name == f"{TODAY}.md" and sorted(p.name for p in tmp_path.iterdir()) == [f"{TODAY}.md"]
    text = path.read_text()
    assert "## Shortlisted (2)" in text and "## Rejected (3)" in text
    assert "need review" not in text and "## Needs review" not in text  # none since 2026-10-27
    # every rejected job is listed with the exact word / place that rejected it
    assert '| Engineering Manager, Backend](https://example.com/jobs/1) | Gamma | Title contains \\"manager\\" |' not in text
    assert 'Gamma | Title contains "manager" |' in text
    assert 'Delta | Restricted to "Remote - US" |' in text
    assert "### Not a target role (1)" in text and "Account Executive" in text


def test_second_run_on_the_same_day_adds_to_the_same_file(tmp_path, filters):
    store = JobStore(":memory:")
    summary, _ = daily(store, filters, SourceResult("test", [make_job(source_job_id="a", allowed_locations=["Worldwide"])]))
    write_report(store, tmp_path, TODAY, summary.to_dict(), NOW)
    later = NOW + timedelta(hours=2)
    summary, _ = daily(store, filters, SourceResult("test", [
        make_job(source_job_id="a", allowed_locations=["Worldwide"]),
        make_job(source_job_id="b", company="Beta", allowed_locations=["EMEA"]),
    ]), now=later)
    text = write_report(store, tmp_path, TODAY, summary.to_dict(), later).read_text()
    assert "## Shortlisted (2)" in text  # the morning job is still there, plus the new one
    tomorrow = NOW + timedelta(days=1)
    summary, days = daily(store, filters, SourceResult("test", [make_job(source_job_id="a", allowed_locations=["Worldwide"])]),
                          now=tomorrow)
    text = write_report(store, tmp_path, days[0], summary.to_dict(), tomorrow).read_text()
    assert "## Shortlisted (0)" in text  # seen before: never repeated


def test_date_range_puts_each_job_on_its_posting_day(filters):
    store = JobStore(":memory:")
    start, end = pipeline.local_day(NOW - timedelta(days=6)), pipeline.local_day(NOW)
    jobs = [
        make_job(source_job_id="old", company="A", posted_at=NOW - timedelta(days=60), allowed_locations=["Worldwide"]),
        make_job(source_job_id="d2", company="B", posted_at=NOW - timedelta(days=2), allowed_locations=["Worldwide"]),
        make_job(source_job_id="d5", company="C", posted_at=NOW - timedelta(days=5), allowed_locations=["Worldwide"]),
        make_job(source_job_id="undated", company="D", posted_at=None, allowed_locations=["Worldwide"]),
    ]
    summary = ingest(store, filters, SourceResult("test", jobs))
    days = pipeline.assign_range(store, summary, filters, NOW, start, end)
    assert days == pipeline.days_between(start, end) and len(days) == 7
    by_company = {row["company"]: row["report_date"] for row in store.all_jobs()}
    assert by_company == {
        "A": None,  # posted before the range
        "B": pipeline.local_day(NOW - timedelta(days=2)).isoformat(),
        "C": pipeline.local_day(NOW - timedelta(days=5)).isoformat(),
        "D": end.isoformat(),  # no posting date: the last day
    }


def test_date_range_brings_back_jobs_rejected_only_for_age(filters):
    store = JobStore(":memory:")
    posted = NOW - timedelta(days=45)
    summary = ingest(store, filters, SourceResult("test", [make_job(posted_at=posted, allowed_locations=["Worldwide"])]))
    assert store.get(1)["reject_code"] == "too_old"
    day = pipeline.local_day(posted)
    pipeline.assign_range(store, summary, filters, NOW, day, day)
    assert store.get(1)["status"] == SHORTLISTED and store.get(1)["report_date"] == day.isoformat()


def test_a_lower_age_limit_reaches_daily_jobs_but_not_date_range_ones(filters):
    from jobhunter.classify import classify, recheck_age
    from jobhunter.store import row_to_job

    store = JobStore(":memory:")
    posted = NOW - timedelta(days=45)
    filters.max_posting_age_days = 90
    jobs = [make_job(source_job_id=name, company=name, posted_at=posted, allowed_locations=["Worldwide"])
            for name in ("Daily", "Range")]
    summary, _ = daily(store, filters, SourceResult("test", jobs[:1]))
    summary = ingest(store, filters, SourceResult("test", jobs[1:]))
    day = pipeline.local_day(posted)
    pipeline.assign_range(store, summary, filters, NOW, day, day)
    assert [r["status"] for r in store.all_jobs()] == [SHORTLISTED, SHORTLISTED]

    filters.max_posting_age_days = 30
    for row in store.all_jobs():
        store.update_classification(row["id"], classify(row_to_job(row), filters, NOW, check_age=recheck_age(row)))
    daily_job, range_job = store.all_jobs()
    assert daily_job["reject_code"] == "too_old"  # found by the daily run: judged again
    assert range_job["status"] == SHORTLISTED  # asked for by the date range, however old


def test_date_range_skips_jobs_not_listed_anymore(filters):
    store = JobStore(":memory:")
    ingest(store, filters, SourceResult("test", [make_job(source_job_id="closed", company="Gone", allowed_locations=["Worldwide"])]))
    summary = ingest(store, filters, SourceResult("test", [make_job(source_job_id="open", company="Here", allowed_locations=["Worldwide"])]))
    pipeline.assign_range(store, summary, filters, NOW, pipeline.local_day(NOW), pipeline.local_day(NOW))
    assert {r["company"]: r["report_date"] for r in store.all_jobs()} == {"Gone": None, "Here": TODAY}


def test_end_to_end_run(tmp_path, filters):
    (tmp_path / "config").mkdir()
    config = {
        "greenhouse_boards": [{"company": "GitLab", "board_token": "gitlab"}],
        "himalayas": {"queries": ["backend"], "limit": 20},
    }
    http = FakeHttp({
        greenhouse.API.format(token="gitlab"): fixture_json("greenhouse_gitlab.json"),
        himalayas.SEARCH: lambda params: fixture_json("himalayas_search.json") if params["page"] == 1 else {"jobs": []},
    })
    paths = Paths(tmp_path)
    summary, reports = pipeline.run(paths, config, filters, pipeline.RunOptions(http=http, now=NOW))
    assert summary.sources["greenhouse"].fetched == 2 and summary.sources["himalayas"].fetched == 3
    assert summary.new == 5
    assert [p.name for p in reports] == [f"{TODAY}.md"]
    text = reports[0].read_text()
    # Himalayas gives no location for it: shortlisted all the same, marked unclear.
    shortlisted = text.split("## Shortlisted")[1].split("## Visa list")[0]
    assert "Backend Engineer (Senior+) — Miris" in shortlisted and "unclear" in shortlisted
    assert "| greenhouse | 2 | 2 | 0 |" in text

    tomorrow = NOW + timedelta(days=1)
    summary2, reports2 = pipeline.run(paths, config, filters, pipeline.RunOptions(http=http, now=tomorrow))
    assert summary2.new == 0
    assert "## Shortlisted (0)" in reports2[0].read_text()
    runs = JobStore(paths.db_file).conn.execute("SELECT stats_json FROM runs ORDER BY id").fetchall()
    assert json.loads(runs[1]["stats_json"])["sources"]["himalayas"]["new"] == 0


def test_range_run_writes_one_file_per_day(tmp_path, filters):
    (tmp_path / "config").mkdir()
    seen_params = []

    def himalayas_page(params):
        seen_params.append(params)
        return fixture_json("himalayas_search.json") if params["page"] == 1 else {"jobs": []}

    http = FakeHttp({himalayas.SEARCH: himalayas_page})
    start, end = pipeline.local_day(NOW - timedelta(days=30)), pipeline.local_day(NOW)
    _, reports = pipeline.run(Paths(tmp_path), {"himalayas": {"queries": ["backend"]}}, filters,
                              pipeline.RunOptions(http=http, now=NOW, date_range=(start, end)))
    assert len(reports) == 31 and reports[0].name == f"{start}.md" and reports[-1].name == f"{end}.md"
    assert seen_params[0]["page"] == 1
    written = [p for p in reports if "— Miris" in p.read_text()]
    assert len(written) == 1  # the fixture's job landed on its posting day


def test_reclassify_surfaces_jobs_after_rules_change(filters):
    from jobhunter.classify import classify
    from jobhunter.store import row_to_job

    store = JobStore(":memory:")
    ingest(store, filters, SourceResult("test", [make_job(title="Platform Wizard", allowed_locations=["Worldwide"])]))
    assert store.get(1)["status"] == REJECTED
    filters.title_include.append("platform wizard")
    store.update_classification(1, classify(row_to_job(store.get(1)), filters, NOW))
    assert store.get(1)["status"] == SHORTLISTED
    assert [r["id"] for r in store.unreported()] == [1]


def test_unclear_eligibility_is_shortlisted_and_waits_for_the_ai_check(filters):
    # No review list since 2026-10-27: a job is rejected or shortlisted.
    store = JobStore(":memory:")
    ingest(store, filters, SourceResult("test", [make_job(location_raw="Remote")]))
    row = store.get(1)
    assert (row["status"], row["eligibility"]) == (SHORTLISTED, "unclear")
    assert [r["id"] for r in store.needs_ai_check()] == [1]


def test_job_with_no_posting_date_is_shortlisted_with_a_note_and_waits_for_the_date_lookup(filters):
    # Proxify #1495 came from Google Jobs with no date and was months old: the date lookup can reject such a one.
    store = JobStore(":memory:")
    ingest(store, filters, SourceResult("test", [make_job(posted_at=None, allowed_locations=["Worldwide"])]))
    row = store.get(1)
    assert row["status"] == SHORTLISTED and row["eligibility"] != "unclear"
    assert "No posting date, so its age is unknown" in json.loads(row["relevance_reasons_json"])
    assert [r["id"] for r in store.needs_date_check()] == [1]
    assert store.needs_ai_check() == []  # the AI Lebanon check has nothing to answer here


def test_jobs_left_in_needs_review_are_never_looked_up_or_checked(filters):
    # Judged before 2026-10-27: the user reviews them by hand.
    store = JobStore(":memory:")
    store_job(store, filters, status=NEEDS_REVIEW, location_raw="Remote", allowed_locations=[], posted_at=None)
    store.commit()
    assert store.needs_ai_check() == [] and store.needs_date_check() == []


def test_six_years_is_too_senior(filters):
    store = JobStore(":memory:")
    ingest(store, filters, SourceResult("test", [make_job(required_yoe=6, allowed_locations=["Worldwide"])]))
    assert store.get(1)["reject_code"] == "too_senior"


def test_reclassify_leaves_tracking_alone(tmp_path, filters):
    import shutil

    from jobhunter import cli, tracking

    from .conftest import ROOT, store_job

    # The shipped config/ on purpose: the CLI needs a whole project folder.
    shutil.copytree(ROOT / "config", tmp_path / "config")
    store = JobStore(tmp_path / "data" / "jobs.sqlite")
    job_id = store_job(store, filters)
    tracking.set_stage(store, job_id, SAVED, NOW)
    tracking.update_notes(store, job_id, "keep me", NOW)
    store.commit()
    store.close()
    assert cli.main(["--home", str(tmp_path), "reclassify"]) == 0
    row = get_application(JobStore(tmp_path / "data" / "jobs.sqlite"), job_id)
    assert (row["stage"], row["notes"]) == (SAVED, "keep me")


def test_reclassify_lets_the_web_app_save_while_it_runs(tmp_path, filters, monkeypatch):
    # It used to hold the write lock for the whole run (minutes), so Skip in
    # the web app failed with "database is locked".
    import shutil

    from jobhunter import cli, tracking

    from .conftest import ROOT, store_job

    # The shipped config/ on purpose: the CLI needs a whole project folder.
    shutil.copytree(ROOT / "config", tmp_path / "config")
    db = tmp_path / "data" / "jobs.sqlite"
    store = JobStore(db)
    ids = [store_job(store, filters, source_job_id=str(n), title=f"Backend Engineer {n}") for n in range(150)]
    store.commit()
    store.close()
    saved = []

    def classify_then_skip(job, *args, **kwargs):
        if len(saved) < 2 and job.source_job_id in ("5", "120"):  # in the first batch, and after one was saved
            web = JobStore(db, migrate=False)
            web.conn.execute("PRAGMA busy_timeout = 0")  # no waiting: fails at once if a write is open
            tracking.set_stage(web, ids[int(job.source_job_id)], CLOSED, NOW, reason="skipped")
            web.close()
            saved.append(job.source_job_id)
        return classify(job, *args, **kwargs)

    from jobhunter.classify import classify
    monkeypatch.setattr(cli, "classify", classify_then_skip)
    assert cli.main(["--home", str(tmp_path), "reclassify"]) == 0
    assert saved == ["5", "120"]
    store = JobStore(db)
    assert get_application(store, ids[120])["closed_reason"] == "skipped"
    assert store.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 150


def test_a_failing_outreach_step_still_writes_the_reports(tmp_path, filters, monkeypatch):
    def broken(*args, **kwargs):
        raise ValueError("bad config/outreach.json")

    monkeypatch.setattr(pipeline, "run_outreach", broken)
    (tmp_path / "config").mkdir()
    http = FakeHttp({greenhouse.API.format(token="gitlab"): fixture_json("greenhouse_gitlab.json")})
    summary, reports = pipeline.run(Paths(tmp_path), {"greenhouse_boards": [{"company": "GitLab", "board_token": "gitlab"}]},
                                    filters, pipeline.RunOptions(http=http, now=NOW))
    assert reports and reports[0].exists()
    assert summary.outreach["errors"] == ["outreach: ValueError: bad config/outreach.json"]
    assert "outreach: ValueError" in reports[0].read_text()


FAKE_MODEL = SimpleNamespace(label="fake-model", config=SimpleNamespace(lookback_days=1))


@pytest.mark.parametrize("module, step, field, label, result_type, options", [
    (pipeline, "date_check_days", "date_check", "posting dates", DateRun, {"date_finder": FAKE_MODEL}),
    (pipeline, "ai_check_days", "ai_check", "AI check", CheckRun, {"ai_checker": FAKE_MODEL}),
    (pipeline, "grade_recent", "fit_grade", "fit grade", GradeRun, {"fit_grader": FAKE_MODEL}),
    (boards, "watch_shortlisted", "boards", "boards", boards.WatchRun, {}),
], ids=["dates", "ai_check", "fit_grade", "boards"])
def test_a_failing_optional_step_is_recorded_as_its_own_result_with_an_error(
        tmp_path, filters, monkeypatch, module, step, field, label, result_type, options):
    def broken(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(module, step, broken)
    (tmp_path / "config").mkdir()
    http = FakeHttp({greenhouse.API.format(token="gitlab"): fixture_json("greenhouse_gitlab.json")})
    config = {"greenhouse_boards": [{"company": "GitLab", "board_token": "gitlab"}]}
    if field == "boards":
        config["watch_boards"] = {"enabled": True}
    summary, reports = pipeline.run(Paths(tmp_path), config, filters,
                                    pipeline.RunOptions(http=http, now=NOW, outreach=False, **options))
    result = getattr(summary, field)
    assert isinstance(result, result_type) and result.errors == [f"{label}: ValueError: boom"]
    assert getattr(result, "model", "fake-model") == "fake-model"  # the report names the model it would have used
    # The run went on: its stats keep the step's usual keys, and the reports show the error.
    assert JobStore(Paths(tmp_path).db_file).last_run_stats()[field] == result.to_dict()
    assert reports and f"{label}: ValueError: boom" in reports[0].read_text()


def test_the_outreach_step_runs_without_any_keys(tmp_path, filters):
    from jobhunter.outreach import run_outreach

    from .conftest import store_job

    store = JobStore(":memory:")
    job_id = store_job(store, filters)
    summary = run_outreach(store, Paths(tmp_path), [job_id], NOW)
    assert summary["errors"] == [] and summary["contacts"] is None
    assert any("HUNTER_API_KEY" in n for n in summary["notes"])


def test_a_blocked_company_is_rejected_with_its_reason(filters):
    from jobhunter.classify import classify

    filters.blocked_companies = Filters.from_dict(
        {"blocked_companies": [{"name": "Acme Inc.", "why": "US-only roles"}]}).blocked_companies
    open_job = make_job(company="ACME", allowed_locations=["Worldwide"])  # would be shortlisted otherwise
    result = classify(open_job, filters, NOW)
    assert result.status == REJECTED and result.reject_code == "blocked_company"
    assert result.reject_reason == 'Company is on your blocked list: "Acme Inc." (US-only roles)'
    linked = make_job(company="Acme https://acme.example", allowed_locations=["Worldwide"])  # Hacker News style
    assert classify(linked, filters, NOW).reject_code == "blocked_company"
    assert classify(make_job(company="Acme Labs", allowed_locations=["Worldwide"]), filters, NOW).status == SHORTLISTED


def test_a_401k_means_a_us_hire_whatever_the_location_says(filters):
    """Alloy, 2026-10-19: "Anywhere in the World" on the board, a 401(k) in the benefits."""
    from jobhunter.classify import classify

    text = "We build APIs with Python.\nBenefits:\n- 401k with 100% match up to 4% of annual employee compensation"
    result = classify(make_job(description=text, allowed_locations=["Anywhere in the World"]), filters, NOW)
    assert result.status == REJECTED and result.reject_code == "us_benefits"
    assert result.reject_reason == ('Offers a 401(k), a US-only retirement plan, so it hires in the US: '
                                    '"- 401k with 100% match up to 4% of annual employee compensation"')
    # A title that is not a target keeps its own reason; pay that reads "401K" is not a plan.
    assert classify(make_job(title="Account Executive", description=text), filters, NOW).reject_code == "title_not_target"
    pay = make_job(description="Python APIs. Salary 401K–500K a year.", allowed_locations=["Worldwide"])
    assert classify(pay, filters, NOW).status == SHORTLISTED


def test_skip_leaves_a_source_out_of_the_run(tmp_path, filters):
    (tmp_path / "config").mkdir()
    config = {
        "greenhouse_boards": [{"company": "GitLab", "board_token": "gitlab"}],
        "himalayas": {"queries": ["backend"], "limit": 20},
    }
    http = FakeHttp({greenhouse.API.format(token="gitlab"): fixture_json("greenhouse_gitlab.json")})
    summary, _ = pipeline.run(Paths(tmp_path), config, filters, pipeline.RunOptions(
        skip={"himalayas", "serpapi"}, http=http, now=NOW, ai=False, outreach=False))
    assert set(summary.sources) == {"greenhouse"} and summary.new == 2
    assert "--skip: no enabled source named serpapi" in summary.config_notes


class _Flaky(Source):
    """Fails to connect on its first fetch (the Mac just woke up), works on the second."""

    def __init__(self, name, refetch=True):
        self.name, self.refetch, self.tries = name, refetch, 0

    def fetch(self, http):
        self.tries += 1
        if self.tries == 1:
            return SourceResult(self.name, [make_job(source=self.name, source_job_id="a")],
                                errors=["Careem (careem): ConnectError for https://boards-api.greenhouse.io/x"])
        return SourceResult(self.name, [make_job(source=self.name, source_job_id="b")])


def test_a_source_that_could_not_connect_is_fetched_again(monkeypatch):
    monkeypatch.setattr(pipeline.clock, "sleep", lambda seconds: None)
    flaky, paid = _Flaky("greenhouse"), _Flaky("serpapi", refetch=False)
    fine = _Flaky("himalayas")
    fine.tries = 1  # already past its failing try
    results = pipeline.fetch_all([flaky, paid, fine], http=None)
    assert (flaky.tries, paid.tries, fine.tries) == (2, 1, 2)
    assert [j.source_job_id for j in results[0].jobs] == ["a", "b"] and results[0].errors == []
    assert results[0].notes == ["fetched again after 1 error(s) the first time"]
    assert results[1].errors and [j.source_job_id for j in results[1].jobs] == ["a"]  # credits are not spent twice


def test_waiting_for_the_network(monkeypatch):
    attempts = []

    def connect(address, timeout):
        attempts.append(address)
        if len(attempts) < 3:
            raise OSError("nodename nor servname provided, or not known")
        return contextlib.nullcontext()

    monkeypatch.setattr(http_module.socket, "create_connection", connect)
    monkeypatch.setattr(http_module.time, "sleep", lambda seconds: None)
    assert http_module.wait_for_network(timeout=60) is not None and len(attempts) == 3
    attempts.clear()
    monkeypatch.setattr(http_module.socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    assert http_module.wait_for_network(timeout=0) is None
