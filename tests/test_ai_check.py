"""AI web check, through a fake Anthropic client that returns canned response blocks."""

import json
from types import SimpleNamespace

from jobhunter import pipeline
from jobhunter.ai_check import AiCheckConfig, AiChecker, build_checker, check_jobs, find_quote
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
    assert client.calls[2]["tool_choice"] == {"type": "tool", "name": "record_verdict"}


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
