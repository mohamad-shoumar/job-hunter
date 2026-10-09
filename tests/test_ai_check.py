"""AI web check, through a fake Anthropic client that returns canned response blocks."""

import json
from types import SimpleNamespace

from jobhunter import pipeline
from jobhunter.ai_check import (
    JOB_DESCRIPTION,
    AiCheckConfig,
    AiChecker,
    PagesChecker,
    TwoStepChecker,
    WebChecker,
    build_checker,
    check_jobs,
    find_quote,
    job_links,
)
from jobhunter.classify import classify
from jobhunter.config import Paths
from jobhunter.models import (
    CANNOT_HIRE,
    ELIGIBLE,
    LIKELY,
    NEEDS_REVIEW,
    NOT_ELIGIBLE,
    REJECTED,
    SHORTLISTED,
    UNCLEAR,
    AiCheck,
)
from jobhunter.sources import himalayas
from jobhunter.store import JobStore, row_to_job

from .conftest import NOW, FakeHttp, fixture_json, make_job

PAGE_URL = "https://job-boards.greenhouse.io/acme/jobs/42"
PAGE_TEXT = "Senior Backend Engineer\n\n**Location:** Remote – United States\n\nAbout the role..."


def response(*blocks, stop_reason="tool_use", searches=1):
    usage = {"input_tokens": 20_000, "output_tokens": 500, "server_tool_use": {"web_search_requests": searches}}
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason, usage=usage)


def fetched(url=PAGE_URL, text=PAGE_TEXT):
    return {"type": "web_fetch_tool_result", "tool_use_id": "srv_2",
            "content": {"type": "web_fetch_result", "url": url,
                        "content": {"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": text}}}}


def verdict(verdict=CANNOT_HIRE, quote="Location: Remote - United States", url=PAGE_URL,
            reason="The Greenhouse posting lists Remote - United States only."):
    return {"type": "tool_use", "id": "tu_1", "name": "record_verdict",
            "input": {"verdict": verdict, "reason": reason, "quote": quote, "source_url": url}}


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item


def checker(client, **config):
    return AiChecker(AiCheckConfig(enabled=True, workers=1, **config), client)


def stored_unclear_job(store, filters, **overrides):
    """A remote job with no location anywhere: the rules say unclear."""
    job = make_job(**overrides)
    job.first_seen = NOW
    cls = classify(job, filters, NOW)
    assert cls.status == NEEDS_REVIEW
    job_id = store.insert(job, cls, None, NOW)
    store.commit()
    return job_id


def test_find_quote_ignores_case_and_punctuation_but_needs_three_words():
    pages = [("a", "Nothing here"), ("b", "**Location:** Remote – United States")]
    assert find_quote("location: remote - united states", pages) == "b"
    assert find_quote("Remote United", pages) is None  # two words prove nothing
    assert find_quote("Location: Remote - Canada", pages) is None
    assert find_quote("Remote – United States", pages + [("c", "Remote, United States")], stated_url="c") == "c"


def test_verified_cannot_hire_rejects_the_job_and_survives_reclassify(filters):
    store = JobStore(":memory:")
    job_id = stored_unclear_job(store, filters)
    client = FakeClient(response({"type": "server_tool_use", "id": "srv_2", "name": "web_fetch", "input": {}},
                                 fetched(), verdict()))
    run = check_jobs(store, checker(client), [store.get(job_id)], filters, NOW)

    row = store.get(job_id)
    assert row["status"] == REJECTED and row["reject_code"] == "ai_cannot_hire"
    assert row["reject_reason"] == ('AI check: The Greenhouse posting lists Remote - United States only. '
                                    f'"Location: Remote - United States" ({PAGE_URL})')
    assert json.loads(row["eligibility_reasons_json"])[1].startswith("Rules: Remote, but the posting does not say")
    assert run.checked == 1 and run.status_changes == {"needs_review -> rejected": 1}
    assert run.cost_usd == 0.1  # 20k in ($0.08) + 500 out ($0.01) on Opus + one search ($0.01)
    # reclassify rebuilds the job from the row: the stored check still applies.
    assert classify(row_to_job(row), filters, NOW).status == REJECTED


def test_a_quote_not_on_any_page_is_not_used(filters):
    store = JobStore(":memory:")
    job_id = stored_unclear_job(store, filters)
    client = FakeClient(response(fetched(), verdict(quote="Only candidates in the United States")))
    check_jobs(store, checker(client), [store.get(job_id)], filters, NOW)

    row = store.get(job_id)
    check = row_to_job(row).ai_check
    assert check.verdict == CANNOT_HIRE and not check.verified
    assert row["status"] == NEEDS_REVIEW
    assert "quote was not found on the page, so it is not used" in json.loads(row["eligibility_reasons_json"])[-1]


def test_a_quote_from_the_description_counts(filters):
    job = make_job(description="We build APIs with Python. Our payroll covers employees in Canada and Mexico only.")
    client = FakeClient(response(verdict(quote="payroll covers employees in Canada and Mexico only",
                                         url="job description")))
    check = checker(client).check(job, NOW)
    assert check.verified and check.source_url == "job description"


def test_verified_can_hire_shortlists_as_likely(filters):
    job = make_job(ai_check=AiCheck("can_hire", "The careers page says it hires in any country.",
                                    "We hire in any country", "https://acme.com/careers", verified=True))
    cls = classify(job, filters, NOW)
    assert cls.status == SHORTLISTED and cls.eligibility.verdict == LIKELY
    assert cls.eligibility.code == "ai_can_hire"


def test_rules_that_quote_evidence_still_win(filters):
    check = AiCheck(CANNOT_HIRE, "US only.", "Remote - United States", PAGE_URL, verified=True)
    assert classify(make_job(allowed_locations=["Worldwide"], ai_check=check), filters, NOW).eligibility.verdict == ELIGIBLE
    assert classify(make_job(allowed_locations=["Remote - US"], ai_check=check), filters, NOW).eligibility.code == "location_restricted"
    unclear = classify(make_job(ai_check=AiCheck("unknown", "Nothing found.")), filters, NOW)
    assert unclear.eligibility.verdict == UNCLEAR and "AI check found nothing decisive" in unclear.eligibility.reasons[-1]


def test_pause_turn_is_continued_and_a_missing_verdict_is_asked_for(filters):
    search = {"type": "server_tool_use", "id": "srv_1", "name": "web_search", "input": {"query": "acme careers"}}
    client = FakeClient(
        response(search, stop_reason="pause_turn"),
        response(fetched(), {"type": "text", "text": "It is US only."}, stop_reason="end_turn"),
        response(verdict()),
    )
    check = checker(client).check(make_job(), NOW)
    assert check.verified and check.searches == 3
    assert len(client.calls) == 3
    assert client.calls[1]["messages"][-1] == {"role": "assistant", "content": [search]}  # sent back as-is
    assert client.calls[1]["tool_choice"] == {"type": "auto"}
    assert client.calls[2]["messages"][-1]["content"].startswith("Call record_verdict now")
    # Opus 5.5 answers a forced tool_choice with a 400, so the nudge is the prompt alone.
    assert client.calls[2]["tool_choice"] == {"type": "auto"}


def test_models_that_allow_it_get_a_forced_record_verdict(filters):
    client = FakeClient(response({"type": "text", "text": "Found nothing."}, stop_reason="end_turn"), response(verdict()))
    checker(client, model="claude-sonnet-5").check(make_job(), NOW)
    assert client.calls[1]["tool_choice"] == {"type": "tool", "name": "record_verdict"}


def test_a_bad_key_stops_the_rest_and_saves_nothing(filters):
    store = JobStore(":memory:")
    ids = [stored_unclear_job(store, filters, source_job_id=str(i), company=f"Co{i}") for i in range(3)]
    error = Exception("Error code: 401 - invalid x-api-key")
    error.status_code = 401
    run = check_jobs(store, checker(FakeClient(error)), [store.get(i) for i in ids], filters, NOW)
    assert run.checked == 0 and run.notes == ["stopped early: the same error would hit every job"]
    assert len(run.errors) == 1 and "invalid x-api-key" in run.errors[0]
    assert all(store.get(i)["ai_check_json"] is None for i in ids)


def test_build_checker_needs_config_and_key(tmp_path, monkeypatch):
    config = tmp_path / "ai_check.json"
    assert build_checker(config) == (None, None)  # no file: off, silently
    config.write_text('{"enabled": true}')
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    checker_, note = build_checker(config)
    assert checker_ is None and "ANTHROPIC_API_KEY" in note


def test_daily_run_checks_new_needs_review_jobs_and_reports_them(tmp_path, filters):
    (tmp_path / "config").mkdir()
    http = FakeHttp({himalayas.SEARCH: lambda p: fixture_json("himalayas_search.json") if p["page"] == 1 else {"jobs": []}})
    client = FakeClient(response(fetched(), verdict()))
    summary, reports = pipeline.run(Paths(tmp_path), {"himalayas": {"queries": ["backend"]}}, filters, http=http,
                                    now=NOW, ai_checker=checker(client))
    assert len(client.calls) == 1  # only Miris needs review; the Node.js and Java roles are rejected by title
    assert "Company: Miris" in client.calls[0]["messages"][0]["content"]
    assert summary.ai_check["checked"] == 1 and summary.ai_check["verdicts"] == {CANNOT_HIRE: 1}
    text = reports[0].read_text()
    ai_group = text.split("### AI check: cannot hire from Lebanon (1)")[1]
    assert "Backend Engineer (Senior+)" in ai_group.split("###")[0]
    assert "**AI check** (claude-opus-5-5): 1 checked (1 cannot hire), about $0.10" in text

    # Already checked: a second run does not pay for it again.
    pipeline.run(Paths(tmp_path), {"himalayas": {"queries": ["backend"]}}, filters, http=http, now=NOW,
                 ai_checker=checker(client))
    assert len(client.calls) == 1


def test_no_ai_flag_skips_the_check(tmp_path, filters):
    (tmp_path / "config").mkdir()
    http = FakeHttp({himalayas.SEARCH: lambda p: fixture_json("himalayas_search.json") if p["page"] == 1 else {"jobs": []}})
    client = FakeClient(response(fetched(), verdict()))
    summary, _ = pipeline.run(Paths(tmp_path), {"himalayas": {"queries": ["backend"]}}, filters, http=http,
                              now=NOW, ai=False, ai_checker=checker(client))
    assert client.calls == [] and summary.ai_check is None


# --- DeepSeek over pages code fetched, then Claude Code with web search ----------------------

GH_URL = "https://job-boards.greenhouse.io/acme/jobs/42"
GH_API = "https://boards-api.greenhouse.io/v1/boards/acme/jobs/42"
GH_JSON = {"title": "Senior Backend Engineer", "location": {"name": "Remote - United States"},
           "content": "&lt;p&gt;We build APIs.&lt;/p&gt;"}


class FakeModel:
    """A JsonModel that returns canned answers and keeps what it was asked."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = []

    def ask(self, system, messages, schema, usage, example, max_tokens=4096):
        self.asked.append(messages[0]["content"])
        return self.answers.pop(0)


def answer(verdict=CANNOT_HIRE, quote="Location: Remote - United States", url=GH_URL):
    return {"verdict": verdict, "reason": "The posting lists Remote - United States.", "quote": quote, "source_url": url}


def deepseek(model, http, **config):
    return PagesChecker(AiCheckConfig(enabled=True, workers=1, model="deepseek-v4-pro", **config), model, http)


def web(model, http):
    return WebChecker(AiCheckConfig(enabled=True, workers=1, model="deepseek-v4-pro", web_model="claude-code"),
                      model, http)


def test_deepseek_reads_the_posting_through_the_board_api_and_its_quote_is_checked(filters):
    store = JobStore(":memory:")
    job_id = stored_unclear_job(store, filters, application_url=GH_URL)
    http = FakeHttp({GH_API: GH_JSON})
    model = FakeModel(answer())
    run = check_jobs(store, deepseek(model, http), [store.get(job_id)], filters, NOW)
    assert run.checked == 1 and run.model == "deepseek-v4-pro"
    assert f"--- Page: {GH_URL} ---" in model.asked[0] and "Location: Remote - United States" in model.asked[0]
    row = store.get(job_id)
    assert row["status"] == REJECTED and json.loads(row["ai_check_json"])["verified"] is True


def test_deepseek_never_fetches_boards_that_block_scripts():
    job = make_job(application_url="https://himalayas.app/companies/acme/jobs/backend",
                   source_url="https://www.linkedin.com/jobs/view/1",
                   description="Apply at https://acme.com/careers/backend. We build APIs.")
    assert job_links(job, 3) == ["https://acme.com/careers/backend"]


def test_a_deepseek_quote_on_no_page_is_not_used(filters):
    store = JobStore(":memory:")
    job_id = stored_unclear_job(store, filters, application_url=GH_URL)
    model = FakeModel(answer(quote="Applicants must live in the United States"))
    check_jobs(store, deepseek(model, FakeHttp({GH_API: GH_JSON})), [store.get(job_id)], filters, NOW)
    row = store.get(job_id)
    assert row["status"] == NEEDS_REVIEW and json.loads(row["ai_check_json"])["verified"] is False


def test_claude_code_runs_only_when_deepseek_could_not_settle_it(filters):
    first = FakeModel(answer(), {"verdict": "unknown", "reason": "Nothing says.", "quote": "", "source_url": ""})
    second = FakeModel(answer())
    http = FakeHttp({GH_API: GH_JSON})
    two = TwoStepChecker(deepseek(first, http), web(second, http))
    settled = two.check(make_job(application_url=GH_URL), NOW)
    assert settled.verified and settled.model == "deepseek-v4-pro" and second.asked == []

    unsettled = two.check(make_job(application_url=GH_URL), NOW)
    assert len(second.asked) == 1 and "Company: Acme" in second.asked[0]
    # Code fetched the page Claude Code named and found the quote there itself.
    assert unsettled.verified and unsettled.model == "claude-code" and unsettled.source_url == GH_URL


def test_a_claude_code_quote_counts_only_when_code_finds_it_on_the_page(filters):
    http = FakeHttp({GH_API: GH_JSON, "https://acme.com/careers": RuntimeError("403")})
    said = WebChecker.check(web(FakeModel(answer(quote="We only hire in the United States",
                                                 url="https://acme.com/careers")), http), make_job(), NOW)
    assert said.verdict == CANNOT_HIRE and not said.verified  # the page could not be read: nothing to check against

    from_description = web(FakeModel(answer(quote="We build APIs with Python", url=JOB_DESCRIPTION)), http)
    assert from_description.check(make_job(), NOW).verified

    # Text a page keeps in embedded data (Recruitee's application questions) still counts: code fetched it.
    page = ('<html><body><h1>Backend Engineer</h1><p>Remote</p><script type="application/json">'
            '{"question": "Do you have a Polish business entity that can invoice B2B?"}</script></body></html>')
    embedded = web(FakeModel(answer(quote="a Polish business entity that can invoice B2B", url="https://acme.com/o/1")),
                   FakeHttp({"https://acme.com/o/1": page}))
    assert embedded.check(make_job(), NOW).verified


def test_build_checker_with_deepseek(tmp_path, monkeypatch):
    config = tmp_path / "ai_check.json"
    config.write_text('{"enabled": true, "model": "deepseek-v4-pro", "web_model": "claude-code"}')
    checker_, note = build_checker(config)
    assert checker_ is None and "DEEPSEEK_API_KEY" in note
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    checker_, note = build_checker(config)  # tests never find the claude program
    assert isinstance(checker_, PagesChecker) and "no web step" in note
    monkeypatch.setattr("jobhunter.llm.claude_code_bin", lambda: "/usr/local/bin/claude")
    checker_, note = build_checker(config)
    assert isinstance(checker_, TwoStepChecker) and note is None
    assert checker_.label == "deepseek-v4-pro, then claude-code" and checker_.second.model.tools == "WebSearch,WebFetch"
