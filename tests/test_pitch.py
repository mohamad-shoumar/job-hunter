"""The email: profile facts, the fact guard, the writer (through a fake client), and stored drafts."""

import json
from types import SimpleNamespace

import pytest

from jobhunter import tracking
from jobhunter.config import OutreachConfig
from jobhunter.contacts import save_manual_contact
from jobhunter.pitch import (
    PitchWriter, assemble, check_draft, cv_for, draft_for_job, edit_draft, follow_up, load_profile, reassemble,
    subject_for, to_html, to_plain,
)
from jobhunter.store import JobStore

from .conftest import FIXTURES, NOW, ROOT, store_job

PROFILE = load_profile(FIXTURES / "profile" / "master_profile.md")
POSTING = "Backend Engineer\nWe use Django and Kafka. 5+ years required. A team of 12."
CONFIG = OutreachConfig(pitch_mode="ai")  # the AI-writer tests


def check(pitch, hook="I saw your Backend Engineer posting.", evidence=(), subject="Backend role at Acme"):
    return check_draft(subject, hook, pitch, list(evidence), PROFILE, POSTING, {"django", "kafka"},
                       ["Acme"])


def test_profile_facts_leave_out_contact_details_and_salary():
    text = PROFILE.facts_text
    assert "800+ concurrent Python jobs" in text and "team of 5 engineers" in text
    assert "7788" not in text and "4200" not in text and "me@example.com" not in text and "TODO" not in text
    assert PROFILE.years == 3.3
    assert PROFILE.linkedin == "linkedin.com/in/example" and "kafka" not in PROFILE.skills


def test_real_facts_pass():
    assert check("I architected a serverless AWS Lambda platform: over 800 concurrent Python jobs, "
                 "and I lead a team of five engineers.") == ([], [])


@pytest.mark.parametrize("pitch, problem", [
    ("I have 5 years of Python experience.", "claims 5 years"),
    ("I built Kafka pipelines in Python.", 'names "kafka"'),
    ("As a senior engineer I built 115+ version-controlled workflows.", 'says "senior"'),
    ("I cut deploy time by 40% on AWS.", '"40% on" is not in the profile'),
])
def test_invented_facts_are_caught(pitch, problem):
    problems, _ = check(pitch)
    assert any(problem in p for p in problems), problems


def test_years_are_allowed_up_to_the_profile_s():
    assert check("I'm a full stack developer with 3+ years in Python, FastAPI and React.") == ([], [])
    assert check("Python and React, team lead", subject="Full Stack Engineer: 3+ years, Python") == ([], [])
    assert any("claims 4" in p for p in check("I have 4 years in Python.")[0])
    assert any("claims 5" in p for p in check("Python work.", subject="Engineer with 5 years")[0])


def test_the_subject_may_not_claim_the_posting_s_stack():
    problems, _ = check("I built RESTful APIs in Python.", subject="Backend Engineer: Django and Kafka")
    assert problems == ['the subject says "kafka", which is not in your profile']


def test_unknown_tool_names_are_a_soft_warning():
    problems, warnings = check("I built RESTful APIs in Python and use Snowflake daily.")
    assert problems == [] and warnings == ['"Snowflake" is not in your profile or the posting; check it']


FIXED = OutreachConfig.load(ROOT / "config" / "outreach.json")


def test_the_email_is_your_template(filters):
    store = JobStore(":memory:")
    job_id = store_job(store, filters, company="LigaData", title="Full Stack Engineer - MENA")
    save_manual_contact(store, job_id, "Rima Haddad", "rima@ligadata.com", "HR Manager", NOW)
    assert draft_for_job(store, job_id, None, PROFILE, FIXED, NOW) == "drafted"  # no AI, no key needed
    app = tracking.get_application(store, job_id)
    assert app["subject"] == "Full Stack Engineer - Mohamad Shoumar"
    assert app["body"] == (
        "Hi Rima,\n\n"
        "Saw you are looking for a Full Stack Engineer. In three years at a trading firm I went from full-stack "
        "developer to leading a team of 5, building the platforms the firm runs on: 800+ concurrent jobs and 115+ AI "
        "workflows in production.\n\n"
        "What's the best next step — a screening call or a technical task? I can turn either around this week.\n\n"
        "Mohamad Shoumar\n"
        "Beirut · +15550107788 · LinkedIn <https://www.linkedin.com/in/example/>"
    )
    assert "looking for an AI Engineer." in assemble("x.", None, "Acme", "AI Engineer", PROFILE)


def test_the_plain_copy_spells_out_the_link():
    assert to_plain("Beirut · LinkedIn <https://www.linkedin.com/in/x/>") == "Beirut · LinkedIn: https://www.linkedin.com/in/x/"


def test_the_html_version_links_linkedin():
    html = to_html("Hi,\n\nMohamad Shoumar\nBeirut · LinkedIn <https://www.linkedin.com/in/example/> · CV attached")
    assert '<a href="https://www.linkedin.com/in/example/">LinkedIn</a>' in html and "<br>" in html


def test_the_cv_is_picked_by_company(tmp_path):
    for name in ("Shoumar_Resume_General.pdf", "Shoumar_FullStack_LigaData_Sep2026.pdf"):
        (tmp_path / name).write_bytes(b"%PDF")
    config = OutreachConfig(cv_dir=str(tmp_path))
    assert cv_for(config, "LigaData", None).name == "Shoumar_FullStack_LigaData_Sep2026.pdf"
    assert cv_for(config, "Acme", None).name == "Shoumar_Resume_General.pdf"
    assert cv_for(config, "Acme", "Shoumar_FullStack_LigaData_Sep2026.pdf").name.startswith("Shoumar_FullStack")
    assert cv_for(config, "Acme", "none") is None


def test_follow_ups_reply_in_the_thread_and_claim_nothing_new():
    subject, body = follow_up(1, "Python backend role at Acme", {"first_name": "Ana"}, "Acme", "Backend Engineer", PROFILE)
    assert subject == "Re: Python backend role at Acme" and body.startswith("Hi Ana,") and "Backend Engineer" in body
    assert follow_up(2, "Re: x", None, "Acme", "Backend Engineer", PROFILE)[0] == "Re: x"


# --- the writer, through a fake client -------------------------------------------------


class FakeClient:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        text = json.dumps(self.answers.pop(0))
        return SimpleNamespace(content=[{"type": "text", "text": text}],
                               usage={"input_tokens": 2500, "output_tokens": 120})


GOOD = {"subject": "Backend Engineer: Python APIs, team lead",
        "pitch": "I built and run an AI automation platform: 115+ version-controlled workflows.", "evidence_ids": [12]}
BAD = {**GOOD, "pitch": "I have 5 years of Python experience."}


def acme(store, filters):
    return store_job(store, filters, description="We build APIs with Python and Django.")


def test_a_bad_draft_is_retried_with_the_reasons(filters):
    store = JobStore(":memory:")
    job_id = acme(store, filters)
    client = FakeClient(BAD, GOOD)
    draft = PitchWriter(client, "claude-sonnet-5").write(PROFILE, store.get(job_id), None)
    assert draft.problems == [] and draft.attempts == 2 and draft.pitch == GOOD["pitch"]
    first = client.calls[0]
    assert first["thinking"] == {"type": "disabled"} and first["output_config"]["format"]["type"] == "json_schema"
    assert "claims 5 years" in client.calls[1]["messages"][-1]["content"]
    assert "ONE line" in first["system"] and draft.subject == "Senior Backend Engineer - Mohamad Shoumar"
    assert "7788" not in first["messages"][0]["content"]  # the phone number never reaches the model


def test_a_draft_that_stays_bad_is_blocked(filters):
    store = JobStore(":memory:")
    job_id = acme(store, filters)
    draft_for_job(store, job_id, PitchWriter(FakeClient(BAD, BAD), "claude-sonnet-5"), PROFILE, CONFIG, NOW)
    app = tracking.get_application(store, job_id)
    assert app["draft_blocked"] == 1 and any("claims 5 years" in w for w in tracking.warnings_of(app))
    assert app["stage"] == tracking.NEW  # a draft alone does not move the job


def test_opus_5_5_gets_low_effort_instead_of_disabled_thinking(filters):
    store = JobStore(":memory:")
    client = FakeClient(GOOD)
    PitchWriter(client, "claude-opus-5-5").write(PROFILE, store.get(acme(store, filters)), None)
    assert "thinking" not in client.calls[0] and client.calls[0]["output_config"]["effort"] == "low"


def test_your_edits_are_kept_and_unblock_sending(filters):
    store = JobStore(":memory:")
    job_id = acme(store, filters)
    draft_for_job(store, job_id, PitchWriter(FakeClient(BAD, BAD), "claude-sonnet-5"), PROFILE, CONFIG, NOW)
    edit_draft(store, job_id, "Backend role", "Hi,\n\nI saw you're hiring a senior backend engineer. "
               "I built RESTful APIs in Python.\n\nCould I send you my CV?\n\nMohamad Shoumar", PROFILE, NOW)
    app = tracking.get_application(store, job_id)
    assert app["draft_edited"] == 1 and app["draft_blocked"] == 0 and tracking.warnings_of(app) == []
    assert draft_for_job(store, job_id, PitchWriter(FakeClient(GOOD), "claude-sonnet-5"), PROFILE, CONFIG, NOW) \
        == "kept your edited draft"
    edit_draft(store, job_id, "Backend role", "Hi,\n\nAs a senior engineer I built APIs.", PROFILE, NOW)
    assert tracking.warnings_of(tracking.get_application(store, job_id)) == ['says "senior", which is not in your profile']


def test_a_new_contact_rebuilds_an_unedited_draft(filters):
    store = JobStore(":memory:")
    job_id = acme(store, filters)
    draft_for_job(store, job_id, None, PROFILE, FIXED, NOW)
    assert tracking.get_application(store, job_id)["body"].startswith("Hi Acme team,\n\nSaw you are looking for a Senior")
    save_manual_contact(store, job_id, "Ana Ruiz", "ana@acme.io", "CEO", NOW)
    reassemble(store, job_id, PROFILE, NOW, FIXED)
    assert tracking.get_application(store, job_id)["body"].startswith("Hi Ana,")


def test_deepseek_writes_drafts_through_the_same_guard(filters, monkeypatch):
    import httpx

    from jobhunter.pitch import DeepSeekPitchWriter, build_writer

    seen = []
    answers = [BAD, GOOD]

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answers.pop(0))}}],
                                         "usage": {"prompt_tokens": 2500, "completion_tokens": 120}})

    store = JobStore(":memory:")
    writer = DeepSeekPitchWriter("ds-key", "deepseek-flash", http=httpx.Client(transport=httpx.MockTransport(handler)))
    draft = writer.write(PROFILE, store.get(acme(store, filters)), None)
    assert draft.problems == [] and draft.attempts == 2 and draft.cost_usd > 0
    body = json.loads(seen[0].content)
    assert body["response_format"] == {"type": "json_object"} and body["thinking"] == {"type": "disabled"}
    assert seen[0].headers["Authorization"] == "Bearer ds-key" and "ds-key" not in str(seen[0].url)
    assert build_writer(OutreachConfig(pitch_model="deepseek-flash"))[0] is None  # no key: off, with a note
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    assert isinstance(build_writer(OutreachConfig(pitch_model="deepseek-flash"))[0], DeepSeekPitchWriter)


def test_the_subject_claims_nothing_new():
    assert check("I built RESTful APIs in Python.", subject="Backend Engineer: Python APIs, team lead") == ([], [])
    problems, _ = check("I built RESTful APIs in Python.", subject="Backend Engineer: serverless telemetry, AWS")
    assert problems == ['the subject says "telemetry", which is not in your profile']


def test_an_ai_line_cannot_mix_two_facts():
    mixed = "I built REST APIs in Python and React user interfaces: 800+ concurrent Python jobs."
    problems, _ = check_draft("", "", mixed, [15, 5], PROFILE, POSTING, set(), [], one_fact=True)
    assert "exactly one fact" in problems[0]
    problems, _ = check_draft("", "", mixed, [5], PROFILE, POSTING, set(), [], one_fact=True)
    assert any('"rest api", which is not in the fact' in p for p in problems)
    good = "I built a serverless AWS platform: 800+ concurrent Python jobs, zero production failures."
    assert check_draft("", "", good, [5], PROFILE, POSTING, set(), [], one_fact=True) == ([], [])
