"""Posting dates for undated jobs: the page's own datePosted first, then a web search whose quote code checks."""

import json
from datetime import timedelta

from jobhunter import pipeline
from jobhunter.ai_check import AiCheckConfig
from jobhunter.classify import classify
from jobhunter.config import Paths
from jobhunter.models import REJECTED, SHORTLISTED
from jobhunter.posted_date import FOUND_ON_PAGE, DateFinder, build_finder, date_in, date_links, date_on_page, find_dates
from jobhunter.store import JobStore, row_to_job
from jobhunter.text import iso

from .conftest import NOW, FakeHttp, make_job

PAGE = "https://jobgether.com/offer/42-backend-engineer"
JSON_LD = ('<html><head><script type="application/ld+json">{"@type": "JobPosting", "title": "Backend Engineer", '
           '"datePosted": "2026-09-20T08:00:00Z"}</script></head><body>Backend Engineer</body></html>')
NO_DATE = "<html><body><h1>Backend Engineer</h1><p>Remote</p></body></html>"
BOARD = "https://dailyremote.com/remote-job/backend-engineer-1"


class FakeModel:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = []

    def ask(self, system, messages, schema, usage, example, max_tokens=4096):
        self.asked.append(messages[0]["content"])
        return self.answers.pop(0)


def finder(http, model=None):
    return DateFinder(AiCheckConfig(enabled=True, workers=1), http, model, "claude-code" if model else FOUND_ON_PAGE)


def answer(quote="Posted 3 days ago", url=BOARD, found=True):
    return {"found": found, "reason": "The board shows when it was posted.", "quote": quote, "source_url": url}


def undated(**overrides):
    """Open worldwide but undated: shortlisted with a note, and the date lookup's to judge."""
    return make_job(**{"allowed_locations": ["Worldwide"], "posted_at": None, "application_url": PAGE, **overrides})


def test_code_reads_the_date_a_quote_states():
    assert date_in('"datePosted": "2026-09-02"', NOW).date().isoformat() == "2026-09-02"
    assert date_in("Posted on September 2, 2026", NOW).date().isoformat() == "2026-09-02"
    assert date_in("Date posted: 2nd Sept 2026", NOW).date().isoformat() == "2026-09-02"
    assert date_in("Posted 5 days ago", NOW) == NOW - timedelta(days=5)
    assert date_in("Just posted", NOW) == NOW and date_in("Posted yesterday", NOW) == NOW - timedelta(days=1)
    assert date_in("Posted on December 2, 2026", NOW) is None  # in the future
    assert date_in("Apply before the deadline", NOW) is None
    assert date_in("See the remark 2, 2026 notes", NOW) is None  # "mar" inside a word is no month


def test_real_page_forms_a_javascript_date_and_linkedins_age_line():
    # Jobgether's JSON-LD (2026-10-22) and a logged-out LinkedIn job page.
    js = '<script>{"datePosted":"Wed Sep 02 2026 09:30:32 GMT+0000 (Coordinated Universal Time)"}</script>'
    assert date_on_page(js, NOW)[1].date().isoformat() == "2026-09-02"
    linkedin = '<span class="posted-time-ago__text topcard__flavor--metadata">\n  3 weeks ago\n</span>'
    assert date_on_page(linkedin, NOW) == ("3 weeks ago", NOW - timedelta(days=21))


def test_a_regional_linkedin_link_is_read_in_english():
    # ae.linkedin.com answered in Arabic ("٣ شهر"), which code cannot read.
    job = undated(application_url="https://ae.linkedin.com/jobs/view/ai-engineer-at-acme-4440611818?trk=x")
    assert date_links(job, 3) == ["https://example.com/jobs/1", "https://www.linkedin.com/jobs/view/ai-engineer-at-acme-4440611818"]
    google = undated(source_url="https://www.google.com/search?ibp=htl%3Bjobs&q=python")
    assert date_links(google, 3) == [PAGE]


def test_the_pages_own_date_posted_is_used_without_a_search():
    model = FakeModel()
    check = finder(FakeHttp({PAGE: JSON_LD}), model).find(undated(), NOW)
    assert (check.posted_at, check.found_by, check.source_url) == ("2026-09-20T08:00:00+00:00", FOUND_ON_PAGE, PAGE)
    assert check.quote == '"datePosted": "2026-09-20T08:00:00Z"'
    assert model.asked == []


def test_a_web_search_date_counts_only_when_code_finds_the_quote_on_the_page():
    http = FakeHttp({PAGE: NO_DATE, BOARD: "<p>Backend Engineer</p><p>Posted 3 days ago</p>"})
    model = FakeModel(answer())
    check = finder(http, model).find(undated(), NOW)
    assert check.posted_at == iso(NOW - timedelta(days=3)) and check.found_by == "claude-code"
    assert "Company: Acme" in model.asked[0]

    unseen = finder(FakeHttp({PAGE: NO_DATE, BOARD: "<p>Backend Engineer</p>"}), FakeModel(answer())).find(undated(), NOW)
    assert unseen.posted_at is None and "not found on the page" in unseen.reason
    # The model's quote must hold the date: code never takes its word for one.
    no_date = FakeModel(answer(quote="Backend Engineer at Acme"))
    vague = finder(FakeHttp({PAGE: NO_DATE, BOARD: "<p>Backend Engineer at Acme</p>"}), no_date).find(undated(), NOW)
    assert vague.posted_at is None and "no date code can read" in vague.reason


def test_without_a_web_model_only_the_pages_are_read():
    check = finder(FakeHttp({PAGE: NO_DATE})).find(undated(), NOW)
    assert check.posted_at is None and check.found_by == FOUND_ON_PAGE


def test_a_found_date_shortlists_a_fresh_job_rejects_an_old_one_and_survives_reclassify(filters):
    store = JobStore(":memory:")
    ids = {}
    for name in ("fresh", "old"):
        job = undated(source_job_id=name, company=f"{name} co", application_url=f"https://jobgether.com/offer/{name}")
        job.first_seen = NOW
        cls = classify(job, filters, NOW)
        assert cls.status == SHORTLISTED
        ids[name] = store.insert(job, cls, None, NOW)
    store.commit()
    http = FakeHttp({"https://jobgether.com/offer/fresh": JSON_LD,
                     "https://jobgether.com/offer/old": JSON_LD.replace("2026-09-20", "2026-08-01")})
    run = find_dates(store, finder(http), [store.get(i) for i in ids.values()], filters, NOW)
    assert run.checked == 2 and run.status_changes == {"shortlisted -> rejected": 1}

    fresh, old = store.get(ids["fresh"]), store.get(ids["old"])
    assert fresh["status"] == SHORTLISTED and fresh["posted_at"] == "2026-09-20T08:00:00+00:00"
    assert json.loads(fresh["date_check_json"])["source_url"] == "https://jobgether.com/offer/fresh"
    assert any(r.startswith("Posting date 2026-09-20 found on a page") for r in json.loads(fresh["relevance_reasons_json"]))
    assert old["status"] == REJECTED and old["reject_code"] == "too_old"
    assert classify(row_to_job(fresh), filters, NOW).status == SHORTLISTED


def test_daily_run_looks_up_dates_before_the_ai_check(tmp_path, filters):
    (tmp_path / "config").mkdir()
    paths = Paths(tmp_path)
    store = JobStore(paths.db_file)
    job = undated()
    job.first_seen = NOW
    job_id = store.insert(job, classify(job, filters, NOW), None, NOW)
    store.set_report_date([job_id], pipeline.local_day(NOW).isoformat())
    store.commit()
    store.close()
    summary, _ = pipeline.run(paths, {}, filters, pipeline.RunOptions(
        http=FakeHttp({}), now=NOW, outreach=False, date_finder=finder(FakeHttp({PAGE: JSON_LD}))))
    assert summary.date_check.checked == 1 and summary.date_check.found == {"found by page": 1}
    store = JobStore(paths.db_file)
    assert store.get(job_id)["status"] == SHORTLISTED


def test_build_finder_follows_the_ai_check_config(tmp_path):
    config = tmp_path / "ai_check.json"
    assert build_finder(config) == (None, None)  # no file: off
    config.write_text('{"enabled": true, "find_dates": false}')
    assert build_finder(config) == (None, None)
    config.write_text('{"enabled": true, "model": "deepseek-v4-pro", "web_model": ""}')
    found, note = build_finder(config)
    assert found.model is None and note is None
