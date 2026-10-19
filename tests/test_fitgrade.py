"""AI fit grade: examples from your own choices, sorting only, never a status change."""

import json

import pytest

from jobhunter import pipeline, tracking
from jobhunter.config import Paths
from jobhunter.fitgrade import (
    FitGradeConfig,
    FitGrader,
    build_grader,
    grade_jobs,
    grade_of,
    load_examples,
    profile_summary,
    to_grade,
)
from jobhunter.report import write_report
from jobhunter.sources import himalayas
from jobhunter.store import JobStore

from .conftest import FIXTURES, NOW, FakeHttp, fixture_json, store_job

PROFILE = FIXTURES / "profile" / "master_profile.md"


class FakeModel:
    """Answers each call from a function of the message, and keeps the messages."""

    def __init__(self, answer=lambda message: {"grade": 4, "reason": "A Python backend role, like the ones you applied to."}):
        self.answer = answer
        self.messages: list[str] = []

    def ask(self, system, messages, schema, usage, example, max_tokens=4096):
        message = messages[0]["content"]
        self.messages.append(message)
        usage.add({"input_tokens": 4000, "output_tokens": 40})
        return self.answer(message)


def grader(model=None, **config) -> FitGrader:
    return FitGrader(FitGradeConfig(enabled=True, workers=1, preferences="I want roles asking about 3 years.", **config),
                     model or FakeModel())


@pytest.fixture
def store():
    return JobStore(":memory:")


def open_jobs(store, filters, n=3) -> list[int]:
    ids = [store_job(store, filters, source_job_id=str(i), company=f"Co{i}", title=f"Backend Engineer {i}")
           for i in range(n)]
    store.set_report_date(ids, pipeline.local_day(NOW).isoformat())
    store.commit()
    return ids


def test_examples_are_your_applied_and_skipped_jobs_with_reasons(store, filters):
    applied, skipped, reasoned, reached = open_jobs(store, filters, 4)
    tracking.mark_applied(store, applied, NOW, NOW)
    tracking.set_stage(store, skipped, tracking.CLOSED, NOW, reason="skipped")
    tracking.set_stage(store, reasoned, tracking.CLOSED, NOW, reason="skipped", skip_reason="too_senior",
                       skip_note="wants 7 years of Go")
    tracking.set_stage(store, reached, tracking.REACHED_OUT, NOW)  # a stage you set by hand: not a like
    examples = load_examples(store, FitGradeConfig())
    assert [line.split('"')[1] for line in examples.liked] == ["Backend Engineer 0"]
    assert examples.skipped[0].endswith("| skipped: Too senior; wants 7 years of Go")  # a reason comes first
    assert examples.skipped[1].endswith("| skipped (no reason given)")
    assert examples.counts == "1 applied, 2 skipped"


def test_the_model_sees_profile_facts_but_no_contact_details():
    summary = profile_summary(PROFILE)
    assert summary.startswith("Target roles:")
    text = PROFILE.read_text()
    for label in ("Email", "Phone"):
        value = next(line.split(":", 1)[1].strip() for line in text.splitlines() if line.startswith(f"- {label}:"))
        assert value not in summary


def test_grades_are_saved_and_never_change_a_status(store, filters):
    ids = open_jobs(store, filters)
    before = {i: store.get(i)["status"] for i in ids}
    model = FakeModel()
    run = grade_jobs(store, grader(model), [store.get(i) for i in ids], PROFILE, NOW)
    assert run.graded == 3 and run.grades == {4: 3} and run.cost_usd > 0
    assert {i: store.get(i)["status"] for i in ids} == before
    grade = grade_of(store.get(ids[0]))
    assert grade["grade"] == 4 and grade["model"] == "deepseek-v4-flash" and grade["reason"].startswith("A Python")
    message = model.messages[0]
    assert "I want roles asking about 3 years." in message and "## The job to grade\nTitle: Backend Engineer" in message


def test_an_unusable_answer_is_an_error_and_saves_nothing(store, filters):
    (job_id,) = open_jobs(store, filters, 1)
    for answer in ({"grade": 9, "reason": "x"}, {"grade": 3, "reason": ""}, {}):
        run = grade_jobs(store, grader(FakeModel(lambda m, a=answer: a)), [store.get(job_id)], PROFILE, NOW)
        assert run.graded == 0 and run.errors and grade_of(store.get(job_id)) is None


def test_only_open_shown_ungraded_jobs_are_graded(store, filters):
    new, saved, skipped, graded, old = open_jobs(store, filters, 5)
    rejected = store_job(store, filters, source_job_id="r", title="Sales Manager")
    store.set_report_date([rejected], pipeline.local_day(NOW).isoformat())
    store.set_report_date([old], (pipeline.local_day(NOW) - pipeline.timedelta(days=10)).isoformat())
    tracking.set_stage(store, saved, tracking.SAVED, NOW)
    tracking.set_stage(store, skipped, tracking.CLOSED, NOW, reason="skipped")
    store.save_fit_grade(graded, {"grade": 2, "reason": "x"})
    assert {r["id"] for r in to_grade(store, NOW, 7)} == {new, saved}
    assert {r["id"] for r in to_grade(store, NOW, 7, regrade=True)} == {new, saved, graded}


def test_reports_list_the_best_grade_first(store, filters, tmp_path):
    low, high, ungraded = open_jobs(store, filters, 3)
    store.save_fit_grade(low, {"grade": 2, "reason": "Asks for 7+ years."})
    store.save_fit_grade(high, {"grade": 5, "reason": "Python backend, 3+ years."})
    store.commit()
    text = write_report(store, tmp_path, pipeline.local_day(NOW).isoformat(), None, NOW, 14).read_text()
    shortlisted = text.split("## Shortlisted")[1].split("## Needs review")[0]
    # A job with no grade yet sits in the middle (3), not below the 2/5 one.
    order = [shortlisted.index(f"Backend Engineer {i}") for i in (1, 2, 0)]
    assert order == sorted(order)
    assert "- **Fit grade:** 5/5 — Python backend, 3+ years." in shortlisted


def test_build_grader_is_off_without_config_or_key(tmp_path, monkeypatch):
    path = tmp_path / "fit_grade.json"
    assert build_grader(path) == (None, None)
    path.write_text(json.dumps({"enabled": True, "model": "deepseek-v4-flash"}))
    grader_, note = build_grader(path)
    assert grader_ is None and "DEEPSEEK_API_KEY" in note
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    assert build_grader(path)[0] is not None


def test_the_daily_run_grades_new_jobs_and_reports_them(tmp_path, filters):
    (tmp_path / "config").mkdir()
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "master_profile.md").write_text(PROFILE.read_text())
    http = FakeHttp({himalayas.SEARCH: lambda p: fixture_json("himalayas_search.json") if p["page"] == 1 else {"jobs": []}})
    model = FakeModel()
    summary, reports = pipeline.run(Paths(tmp_path), {"himalayas": {"queries": ["backend"]}}, filters, http=http,
                                    now=NOW, fit_grader=grader(model), outreach=False)
    shown = sum(n for status, n in summary.new_by_status.items() if status != "rejected")
    assert shown and summary.fit_grade["graded"] == shown == len(model.messages)
    assert "**Fit grades** (deepseek-v4-flash, learning from 0 applied, 0 skipped):" in reports[0].read_text()

    # Graded once: the next run does not pay again.
    pipeline.run(Paths(tmp_path), {"himalayas": {"queries": ["backend"]}}, filters, http=http, now=NOW,
                 fit_grader=grader(model), outreach=False)
    assert len(model.messages) == shown


def test_no_ai_flag_skips_the_grades(tmp_path, filters):
    (tmp_path / "config").mkdir()
    http = FakeHttp({himalayas.SEARCH: lambda p: fixture_json("himalayas_search.json") if p["page"] == 1 else {"jobs": []}})
    model = FakeModel()
    summary, _ = pipeline.run(Paths(tmp_path), {"himalayas": {"queries": ["backend"]}}, filters, http=http,
                              now=NOW, ai=False, fit_grader=grader(model), outreach=False)
    assert model.messages == [] and summary.fit_grade is None
