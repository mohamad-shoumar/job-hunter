"""Dedup across sources, 'only new jobs', rejected jobs staying rejected, reports."""

import json
from datetime import timedelta

from jobhunter import pipeline
from jobhunter.config import Filters, Paths
from jobhunter.models import NEEDS_REVIEW, REJECTED, SHORTLISTED
from jobhunter.report import write_report
from jobhunter.sources import SourceResult
from jobhunter.sources import greenhouse, himalayas
from jobhunter.store import SCHEMA, JobStore

from .conftest import NOW, FakeHttp, fixture_json, make_job


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
    assert "## Shortlisted (1)" in text and "## Needs review (1)" in text and "## Rejected (3)" in text
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


def test_date_range_skips_jobs_not_listed_anymore(filters):
    store = JobStore(":memory:")
    ingest(store, filters, SourceResult("test", [make_job(source_job_id="closed", company="Gone", allowed_locations=["Worldwide"])]))
    summary = ingest(store, filters, SourceResult("test", [make_job(source_job_id="open", company="Here", allowed_locations=["Worldwide"])]))
    pipeline.assign_range(store, summary, filters, NOW, pipeline.local_day(NOW), pipeline.local_day(NOW))
    assert {r["company"]: r["report_date"] for r in store.all_jobs()} == {"Gone": None, "Here": TODAY}


def test_old_database_gets_the_new_columns(tmp_path):
    import sqlite3

    db = tmp_path / "old.sqlite"
    conn = sqlite3.connect(db)
    old_schema = SCHEMA.replace("    reported_at TEXT,\n    report_date TEXT,\n    ai_check_json TEXT\n", "    reported_at TEXT\n")
    assert old_schema != SCHEMA
    conn.executescript(old_schema)
    conn.close()
    assert "report_date" not in {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(jobs)")}
    store = JobStore(db)
    assert {"report_date", "ai_check_json"} <= {r["name"] for r in store.conn.execute("PRAGMA table_info(jobs)")}


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
    summary, reports = pipeline.run(paths, config, filters, http=http, now=NOW)
    assert summary.sources["greenhouse"].fetched == 2 and summary.sources["himalayas"].fetched == 3
    assert summary.new == 5
    assert [p.name for p in reports] == [f"{TODAY}.md"]
    text = reports[0].read_text()
    # Himalayas gives no location for it, so it waits for review rather than being shortlisted.
    review = text.split("## Needs review")[1].split("## Rejected")[0]
    assert "Backend Engineer (Senior+) — Miris" in review
    assert "| greenhouse | 2 | 2 | 0 |" in text

    tomorrow = NOW + timedelta(days=1)
    summary2, reports2 = pipeline.run(paths, config, filters, http=http, now=tomorrow)
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
    _, reports = pipeline.run(Paths(tmp_path), {"himalayas": {"queries": ["backend"]}}, filters, http=http, now=NOW,
                              date_range=(start, end))
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


def test_needs_review_status_for_unclear_eligibility(filters):
    store = JobStore(":memory:")
    ingest(store, filters, SourceResult("test", [make_job(location_raw="Remote")]))
    assert store.get(1)["status"] == NEEDS_REVIEW


def test_job_with_no_posting_date_is_not_shortlisted(filters):
    # Proxify #1495 came from Google Jobs with no date and was months old.
    store = JobStore(":memory:")
    ingest(store, filters, SourceResult("test", [make_job(posted_at=None, allowed_locations=["Worldwide"])]))
    row = store.get(1)
    assert row["status"] == NEEDS_REVIEW and row["eligibility"] != "unclear"
    assert "No posting date, so its age is unknown" in json.loads(row["relevance_reasons_json"])
    assert store.needs_ai_check() == []  # the AI Lebanon check has nothing to answer here


def test_six_years_is_too_senior(filters):
    store = JobStore(":memory:")
    ingest(store, filters, SourceResult("test", [make_job(required_yoe=6, allowed_locations=["Worldwide"])]))
    assert store.get(1)["reject_code"] == "too_senior"


def test_old_database_gets_the_outreach_tables(tmp_path):
    import sqlite3

    db = tmp_path / "old.sqlite"
    old_schema = SCHEMA.split("-- Outreach and tracking")[0]
    sqlite3.connect(db).executescript(old_schema)
    store = JobStore(db)
    tables = {r["name"] for r in store.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"companies", "contacts", "applications", "events", "sent_mail", "mail_seen", "kv"} <= tables
    assert store.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_reclassify_leaves_tracking_alone(tmp_path, filters):
    import shutil

    from jobhunter import cli, tracking

    from .conftest import ROOT, store_job

    shutil.copytree(ROOT / "config", tmp_path / "config")
    store = JobStore(tmp_path / "data" / "jobs.sqlite")
    job_id = store_job(store, filters)
    tracking.set_stage(store, job_id, tracking.SAVED, NOW)
    tracking.update_notes(store, job_id, "keep me", NOW)
    store.commit()
    store.close()
    assert cli.main(["--home", str(tmp_path), "reclassify"]) == 0
    row = tracking.get_application(JobStore(tmp_path / "data" / "jobs.sqlite"), job_id)
    assert (row["stage"], row["notes"]) == (tracking.SAVED, "keep me")


def test_a_failing_outreach_step_still_writes_the_reports(tmp_path, filters, monkeypatch):
    def broken(*args, **kwargs):
        raise ValueError("bad config/outreach.json")

    monkeypatch.setattr(pipeline, "run_outreach", broken)
    (tmp_path / "config").mkdir()
    http = FakeHttp({greenhouse.API.format(token="gitlab"): fixture_json("greenhouse_gitlab.json")})
    summary, reports = pipeline.run(Paths(tmp_path), {"greenhouse_boards": [{"company": "GitLab", "board_token": "gitlab"}]},
                                    filters, http=http, now=NOW)
    assert reports and reports[0].exists()
    assert summary.outreach["errors"] == ["outreach: ValueError: bad config/outreach.json"]
    assert "outreach: ValueError" in reports[0].read_text()


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
    assert classify(make_job(company="Acme Labs", allowed_locations=["Worldwide"]), filters, NOW).status == SHORTLISTED
