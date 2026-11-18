"""Fit score: 0-100 by the rubric (rubric.py), code adds up every part, sorting only, never a status change."""

import json

import pytest

from jobhunter import interviews, pipeline, rubric
from jobhunter.config import Paths
from jobhunter.fitgrade import (
    Context,
    FitGradeConfig,
    FitGrader,
    build_grader,
    grade_jobs,
    grade_of,
    profile_summary,
    rescore,
    score,
    to_grade,
)
from jobhunter.models import CLOSED, ONSITE, SAVED
from jobhunter.report import write_report
from jobhunter.sources import himalayas
from jobhunter.store import JobStore
from jobhunter.store.companies import interview_styles

from .conftest import FIXTURES, NOW, FakeHttp, fixture_json, store_job

PROFILE = FIXTURES / "profile" / "master_profile.md"
DESCRIPTION = ("We build APIs with Python, FastAPI and PostgreSQL on AWS. We offer private health insurance "
               "and a learning budget. Our process is a call, a take-home task and a system design chat.")


def answer(**changes) -> dict:
    base = {"seniority": "mid", "required_skills": ["Python", "PostgreSQL", "Rust", "AWS"], "domain": "transferable",
            "domain_why": "APIs, like their backend work.", "benefits_quote": "private health insurance and a learning budget",
            "equity_quote": "", "ai_culture": {"tag": "unknown", "why": "Nothing on tools.", "quote": ""},
            "reason": "A mid-level Python backend role."}
    return {**base, **changes}


class FakeModel:
    """Answers each call from a function of the message, and keeps the messages."""

    def __init__(self, reply=lambda message: answer()):
        self.reply = reply
        self.messages: list[str] = []

    def ask(self, system, messages, schema, usage, example, max_tokens=4096):
        message = messages[0]["content"]
        self.messages.append(message)
        usage.add({"input_tokens": 4000, "output_tokens": 40})
        return self.reply(message)


def grader(model=None, **config) -> FitGrader:
    return FitGrader(FitGradeConfig(enabled=True, workers=1, model="deepseek-v4-flash", **config), model or FakeModel())


@pytest.fixture
def store():
    return JobStore(":memory:")


def open_jobs(store, filters, n=3, **job) -> list[int]:
    job.setdefault("description", DESCRIPTION)
    ids = [store_job(store, filters, source_job_id=str(i), company=f"Co{i}", title=f"Backend Engineer {i}", **job)
           for i in range(n)]
    store.set_report_date(ids, pipeline.local_day(NOW).isoformat())
    store.commit()
    return ids


def context(filters, floors="") -> Context:
    found = Context.load(PROFILE, filters)
    found.floors = rubric.SalaryFloors.parse(floors)
    return found


# --- the parts code scores alone ----------------------------------------------------


def test_years_meet_or_fall_short_by_one_or_two():
    assert rubric.years_points(None, 3.3)[0] == 8
    assert [rubric.years_points(n, 3.3)[0] for n in (2, 3, 4, 5, 6)] == [8, 8, 5, 3, 0]


def test_skills_are_the_share_of_required_skills_the_profile_names():
    points, why = rubric.skills_points(["Python", "PostgreSQL", "Rust", "AWS"], {"python", "postgresql", "aws"}, "")
    assert points == 9 and why == "3 of 4 required skills (missing: Rust)"
    assert rubric.skills_points([], set(), "")[0] == 6
    # A skill outside the vocabulary counts when the profile text names it.
    assert rubric.skills_points(["Temporal"], set(), "Built workflows on Temporal.")[0] == 12
    # The model may name the profile's words for a skill; they count only when the profile has them.
    covered = [{"skill": "REST APIs", "profile_words": "API design"}, {"skill": "Go", "profile_words": "Golang services"}]
    assert rubric.skills_points(covered, set(), "API design, system design")[1] == "1 of 2 required skills (missing: Go)"


def test_ai_culture_points():
    native = rubric.Culture(rubric.AI_NATIVE, "They code with AI agents.", "we ship with Cursor", "posting")
    assert rubric.culture_points(native)[:2] == (20, rubric.AI_NATIVE)
    assert rubric.culture_points(rubric.Culture(rubric.TRADITIONAL, "LeetCode rounds.", "a LeetCode round"))[:2] == (
        0, rubric.TRADITIONAL)
    assert rubric.culture_points(rubric.Culture())[:2] == (10, rubric.UNKNOWN)
    assert rubric.culture_points(rubric.Culture(rubric.AI_NATIVE, "No quote."))[:2] == (10, rubric.UNKNOWN)
    # A stored answer from before 2026-11-18: live coding reads as traditional, the rest as unknown.
    assert rubric.Culture.from_dict({"live_coding": "yes", "quote": "HackerRank test"}).tag == rubric.TRADITIONAL
    assert rubric.Culture.from_dict({"live_coding": "no", "rounds": 3, "quote": "a take-home"}).tag == rubric.UNKNOWN


def test_salary_floors_come_from_env_and_compare_by_country(store, filters):
    floors = rubric.SalaryFloors.parse("uk=45000 GBP, default=30000 USD")  # made up
    uk = store.get(store_job(store, filters, source_job_id="uk", location_raw="London, United Kingdom",
                             remote_status=ONSITE, allowed_locations=[], title="Backend Engineer",
                             description="We offer visa sponsorship. Salary £55,000 - £65,000 per year.",
                             salary_min=55000, salary_max=65000, salary_currency="GBP", salary_period="year",
                             salary_raw="£55,000 - £65,000"))
    assert rubric.salary_points(uk, filters.visa, filters.relocation, floors)[0] == 7
    low = rubric.SalaryFloors.parse("uk=70000 GBP")
    assert rubric.salary_points(uk, filters.visa, filters.relocation, low)[0] == 0
    remote = store.get(store_job(store, filters, source_job_id="r", salary_min=3000, salary_max=4000,
                                 salary_currency="USD", salary_period="month", salary_raw="$3,000 - $4,000 a month"))
    assert rubric.salary_points(remote, filters.visa, filters.relocation, floors)[0] == 7  # 48k a year
    unstated = store.get(store_job(store, filters, source_job_id="n"))
    assert rubric.salary_points(unstated, filters.visa, filters.relocation, floors) == (0, "no pay stated")


def test_visa_rows_by_evidence(store, filters):
    def onsite(i, description):
        return store.get(store_job(store, filters, source_job_id=f"v{i}", location_raw="London, United Kingdom",
                                   remote_status=ONSITE, allowed_locations=[], title="Backend Engineer",
                                   description=description))

    both = onsite(1, "We offer visa sponsorship and relocation support.")
    visa_only = onsite(2, "Visa sponsorship is available for this role.")
    no_move = onsite(3, "Visa sponsorship available (no relocation support).")
    assert both["status"] == "visa_list" and rubric.visa_points(both)[0] == 30
    assert rubric.visa_points(visa_only)[0] == 27
    assert no_move["status"] == "visa_list" and rubric.visa_points(no_move)[0] == 27
    # A remote job the AI check found sponsors a visa (with its quote verified).
    remote = dict(store.get(store_job(store, filters, source_job_id="ai", allowed_locations=[])))
    remote["ai_check_json"] = json.dumps({"verdict": "sponsors_visa", "verified": True,
                                          "quote": "We sponsor visas for this role."})
    remote["eligibility"] = "likely"
    assert rubric.visa_points(remote)[0] == 27
    worldwide = store.get(store_job(store, filters, source_job_id="w"))
    assert rubric.visa_points(worldwide)[0] == 20  # remote, open worldwide: Lebanon included
    assert rubric.visa_points(worldwide, other_offer="x")[0] == 20  # a remote job is judged as remote
    # Another of the company's postings offering a visa is a track record.
    plain = dict(both)
    plain["description"], plain["eligibility_reasons_json"] = "We build APIs.", "[]"
    assert rubric.visa_points(plain, other_offer="We sponsor visas.")[0] == 23
    assert rubric.visa_points(plain)[0] == 15


# --- the model's parts, checked and added up by code -----------------------------------


def test_scores_are_saved_and_never_change_a_status(store, filters):
    ids = open_jobs(store, filters)
    before = {i: store.get(i)["status"] for i in ids}
    model = FakeModel()
    run = grade_jobs(store, grader(model), [store.get(i) for i in ids], PROFILE, NOW, filters)
    assert run.graded == 3 and run.cost_usd > 0
    assert {i: store.get(i)["status"] for i in ids} == before
    grade = grade_of(store.get(ids[0]))
    parts = {k: v[0] for k, v in grade["parts"].items()}
    # mid 15, 3 of 4 skills 9, no years stated 8, transferable 3, worldwide 20, no pay 0, benefits 1,
    # no equity 0, AI culture unknown 10.
    assert parts == {"seniority": 15, "skills": 9, "years": 8, "domain": 3, "visa": 20, "salary": 0, "benefits": 1,
                     "equity": 0, "culture": 10}
    assert grade["score"] == sum(parts.values()) == 66
    assert grade["culture"] == {"tag": "unknown", "why": "Nothing on tools."}
    assert grade["reason"] == "A mid-level Python backend role." and grade["answer"]["seniority"] == "mid"
    message = model.messages[0]
    assert "## Their profile (facts)" in message and "## The posting\nTitle: Backend Engineer" in message


def test_a_quote_not_in_the_posting_scores_nothing(store, filters):
    (job_id,) = open_jobs(store, filters, 1)
    row = store.get(job_id)
    made_up = answer(benefits_quote="unlimited paid vacation for everyone", equity_quote="generous stock options package",
                     ai_culture={"tag": "ai_native", "why": "Made up.", "quote": "we all code with Claude Code"})
    result = score(row, made_up, context(filters))
    parts = result["parts"]
    assert parts["benefits"][0] == parts["equity"][0] == 0 and parts["culture"][0] == 10
    assert result["culture"] == {"tag": "unknown", "why": "Not enough evidence either way."}


def test_the_posting_s_own_words_set_the_culture_tag(store, filters):
    (job_id,) = open_jobs(store, filters, 1)
    said = answer(ai_culture={"tag": "ai_native", "why": "They ship small and fast.",
                              "quote": "a call, a take-home task and a system design chat"})
    result = score(store.get(job_id), said, context(filters))
    assert result["culture"] == {"tag": "ai_native", "why": "They ship small and fast."}
    assert result["parts"]["culture"][0] == 20 and "(posting)" in result["parts"]["culture"][1]
    # A score saved before 2026-11-18 ("interview" in the answer, a "star") is read the new way.
    old = answer(interview={"live_coding": "yes", "rounds": None, "quote": "a call, a take-home task"})
    del old["ai_culture"]
    assert score(store.get(job_id), old, context(filters))["parts"]["culture"][0] == 0


def test_an_unusable_answer_is_an_error_and_saves_nothing(store, filters):
    (job_id,) = open_jobs(store, filters, 1)
    for bad in ({"seniority": "wizard", "domain": "direct", "reason": "x"}, answer(reason=""), {}):
        run = grade_jobs(store, grader(FakeModel(lambda m, a=bad: a)), [store.get(job_id)], PROFILE, NOW, filters)
        assert run.graded == 0 and run.errors and grade_of(store.get(job_id)) is None


def test_only_open_shown_unscored_jobs_are_scored_and_old_grades_count_as_none(store, filters):
    new, saved, skipped, scored, old, graded_1_to_5 = open_jobs(store, filters, 6)
    rejected = store_job(store, filters, source_job_id="r", title="Sales Manager")
    store.set_report_date([rejected], pipeline.local_day(NOW).isoformat())
    store.set_report_date([old], (pipeline.local_day(NOW) - pipeline.timedelta(days=10)).isoformat())
    from jobhunter import tracking

    tracking.set_stage(store, saved, SAVED, NOW)
    tracking.set_stage(store, skipped, CLOSED, NOW, reason="skipped")
    store.save_fit_grade(scored, {"score": 40, "parts": {}, "reason": "x"})
    store.save_fit_grade(graded_1_to_5, {"grade": 4, "reason": "before the rubric"})
    assert grade_of(store.get(graded_1_to_5)) is None
    assert {r["id"] for r in to_grade(store, NOW, 7)} == {new, saved, graded_1_to_5}
    assert {r["id"] for r in to_grade(store, NOW, 7, regrade=True)} == {new, saved, scored, graded_1_to_5}


def test_the_model_sees_profile_facts_but_no_contact_details():
    summary = profile_summary(PROFILE)
    assert summary.startswith("Target roles:")
    text = PROFILE.read_text()
    for label in ("Email", "Phone"):
        value = next(line.split(":", 1)[1].strip() for line in text.splitlines() if line.startswith(f"- {label}:"))
        assert value not in summary


def test_reports_list_the_best_score_first(store, filters, tmp_path):
    low, high, unscored = open_jobs(store, filters, 3)
    store.save_fit_grade(low, {"score": 30, "parts": {"years": [0, "x"]}, "reason": "Asks for 7+ years.",
                               "culture": {"tag": "traditional", "why": "LeetCode rounds."}})
    store.save_fit_grade(high, {"score": 82, "parts": {"years": [8, "x"]}, "reason": "Python backend.",
                                "culture": {"tag": "ai_native", "why": "They code with AI agents."}})
    store.commit()
    text = write_report(store, tmp_path, pipeline.local_day(NOW).isoformat(), None, NOW, 14).read_text()
    shortlisted = text.split("## Shortlisted")[1].split("## Needs review")[0]
    # A job with no score yet sits in the middle (50), not below the 30 one.
    order = [shortlisted.index(f"Backend Engineer {i}") for i in (1, 2, 0)]
    assert order == sorted(order)
    assert "- **Fit score:** 82/100 — Python backend.\n" in shortlisted
    assert "- **AI culture:** AI-Native — They code with AI agents." in shortlisted
    assert "- **Fit:**" not in shortlisted


def test_reports_show_one_job_per_company_and_name_the_rest(store, filters, tmp_path):
    """17 Palantir London roles came in one fetch (2026-10-21): the best one is shown, the rest named."""
    ids = [store_job(store, filters, source_job_id=f"p{i}", company="Palantir", title=f"Backend Engineer P{i}")
           for i in range(3)]
    other = store_job(store, filters, source_job_id="o", company="Monzo", title="Backend Engineer M")
    store.set_report_date([*ids, other], pipeline.local_day(NOW).isoformat())
    store.save_fit_grade(ids[1], {"score": 90, "parts": {}, "reason": "Python backend."})
    store.commit()
    text = write_report(store, tmp_path, pipeline.local_day(NOW).isoformat(), None, NOW, 14).read_text()
    shortlisted = text.split("## Shortlisted")[1].split("## Needs review")[0]
    assert "### 1. Backend Engineer P1 — Palantir" in shortlisted
    assert "### 2. Backend Engineer M — Monzo" in shortlisted
    assert (f"- **Also at Palantir (2 more):** Backend Engineer P0 (job #{ids[0]}); "
            f"Backend Engineer P2 (job #{ids[2]})") in shortlisted
    assert {store.get(i)["status"] for i in ids} == {"shortlisted"}


# --- the company interview lookup --------------------------------------------------------


class FakeLookup:
    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def ask(self, system, messages, schema, usage, example, max_tokens=4096):
        self.prompts.append(messages[0]["content"])
        return self.reply


HIRING_PAGE = "https://co0.example/how-we-hire"


def test_a_company_lookup_counts_only_when_code_finds_its_quote(store, filters):
    ids = open_jobs(store, filters, 2)
    grade_jobs(store, grader(), [store.get(i) for i in ids], PROFILE, NOW, filters)
    http = FakeHttp({HIRING_PAGE: "<p>How we build: every engineer here ships with Claude Code and Cursor.</p>"})
    good = interviews.InterviewFinder(FakeLookup({"tag": "ai_native", "why": "Their page says they code with AI.",
                                                  "quote": "every engineer here ships with Claude Code and Cursor.",
                                                  "source_url": HIRING_PAGE}), http, "m")
    config = FitGradeConfig(max_interview_lookups_per_run=1)
    run = interviews.look_up_interviews(store, good, config, PROFILE, NOW, filters)
    assert run.looked_up == 1 and run.found == 1
    looked = [i for i in ids if grade_of(store.get(i))["culture"]["tag"] == "ai_native"]
    assert len(looked) == 1
    after = grade_of(store.get(looked[0]))
    assert after["parts"]["culture"][0] == 20 and after["score"] == 76
    assert after["culture"]["why"] == "Their page says they code with AI."
    # Cached: the next run looks up the other company only.
    other = interviews.InterviewFinder(FakeLookup({"tag": "traditional", "why": "Made up.",
                                                   "quote": "a live coding round on HackerRank",
                                                   "source_url": HIRING_PAGE}), http, "m")
    run = interviews.look_up_interviews(store, other, config, PROFILE, NOW, filters)
    assert run.looked_up == 1 and run.found == 0  # its quote is not on the page
    assert len(interview_styles(store, ["co0", "co1"])) == 2
    assert [grade_of(store.get(i))["culture"]["tag"] for i in ids].count("unknown") == 1


def test_blocked_sites_are_never_fetched_and_old_lookups_are_done_again(store, filters):
    web = interviews.InterviewFinder(FakeLookup({"tag": "ai_native", "why": "r", "quote": "we use Copilot",
                                                 "source_url": "https://www.glassdoor.com/Interview/x"}), FakeHttp({}), "m")
    found = web.find("Nobody")
    assert found.answer is None and found.reason.startswith("Not used: that site blocks scripts")
    assert interviews.InterviewFinder(None, FakeHttp({}), "m").find("Nobody").answer is None
    # A row checked before 2026-11-18 asked about live coding only, so it is not fresh.
    from jobhunter.store.companies import save_interview_style

    later = interviews.CULTURE_FROM + pipeline.timedelta(days=1)
    (job_id,) = open_jobs(store, filters, 1)
    store.set_report_date([job_id], pipeline.local_day(later).isoformat())
    grade_jobs(store, grader(), [store.get(job_id)], PROFILE, later, filters)
    save_interview_style(store, "co0", "Co0", None, "m", "", "nothing", interviews.CULTURE_FROM - pipeline.timedelta(days=1))
    assert "co0" in interviews.companies_to_look_up(store, FitGradeConfig(), later)
    save_interview_style(store, "co0", "Co0", None, "m", "", "nothing", later)
    assert "co0" not in interviews.companies_to_look_up(store, FitGradeConfig(), later)


def test_a_track_record_needs_visa_offers_in_two_months(store, filters):
    from jobhunter.fitgrade import other_offer

    (job_id,) = open_jobs(store, filters, 1)
    offer = "We offer visa sponsorship for this role."
    store_job(store, filters, source_job_id="m1", company="Co0", title="Data Engineer", description=offer)
    assert other_offer(store, store.get(job_id)) is None  # one month only
    later = store_job(store, filters, source_job_id="m2", company="Co0", title="Platform Engineer", description=offer)
    store.conn.execute("UPDATE jobs SET first_seen = '2026-07-01T00:00:00+00:00' WHERE id = ?", (later,))
    assert "(2 months: 2026-07" in other_offer(store, store.get(job_id))


def test_rescore_needs_no_model(store, filters):
    (job_id,) = open_jobs(store, filters, 1)
    grade_jobs(store, grader(), [store.get(job_id)], PROFILE, NOW, filters)
    assert rescore(store, [store.get(job_id)], PROFILE, filters) == set()  # nothing changed


# --- config and the daily run -----------------------------------------------------------


def test_build_grader_is_off_without_config_or_key(tmp_path, monkeypatch):
    path = tmp_path / "fit_grade.json"
    assert build_grader(path) == (None, None)
    path.write_text(json.dumps({"enabled": True, "model": "deepseek-v4-flash"}))
    grader_, note = build_grader(path)
    assert grader_ is None and "DEEPSEEK_API_KEY" in note
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    assert build_grader(path)[0] is not None


def test_the_daily_run_scores_new_jobs_and_reports_them(tmp_path, filters):
    (tmp_path / "config").mkdir()
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "master_profile.md").write_text(PROFILE.read_text())
    http = FakeHttp({himalayas.SEARCH: lambda p: fixture_json("himalayas_search.json") if p["page"] == 1 else {"jobs": []}})
    model = FakeModel()
    summary, reports = pipeline.run(Paths(tmp_path), {"himalayas": {"queries": ["backend"]}}, filters,
                                    pipeline.RunOptions(http=http, now=NOW, fit_grader=grader(model), outreach=False))
    shown = sum(n for status, n in summary.new_by_status.items() if status != "rejected")
    assert shown and summary.fit_grade.graded == shown == len(model.messages)
    assert "**Fit scores** (deepseek-v4-flash):" in reports[0].read_text()

    # Scored once: the next run does not pay again.
    pipeline.run(Paths(tmp_path), {"himalayas": {"queries": ["backend"]}}, filters,
                 pipeline.RunOptions(http=http, now=NOW, fit_grader=grader(model), outreach=False))
    assert len(model.messages) == shown


def test_no_ai_flag_skips_the_scores(tmp_path, filters):
    (tmp_path / "config").mkdir()
    http = FakeHttp({himalayas.SEARCH: lambda p: fixture_json("himalayas_search.json") if p["page"] == 1 else {"jobs": []}})
    model = FakeModel()
    options = pipeline.RunOptions(http=http, now=NOW, ai=False, fit_grader=grader(model), outreach=False)
    summary, _ = pipeline.run(Paths(tmp_path), {"himalayas": {"queries": ["backend"]}}, filters, options)
    assert model.messages == [] and summary.fit_grade is None
