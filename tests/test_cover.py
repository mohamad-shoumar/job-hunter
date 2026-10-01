"""Cover letters: the facts, the sentence check, the retry, the file, the daily run, the report and the web app."""

import json
import shutil
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from jobhunter import tracking
from jobhunter.config import OutreachConfig, Paths
from jobhunter.cover import (
    CoverWriter, JobText, check_sentence, cover_for_job, gap_sentence, letter_from, load_letter_facts,
    posting_gaps, posting_matches, valid_gap,
)
from jobhunter.llm import JsonModel
from jobhunter.report import _prepared_line
from jobhunter.store import JobStore
from jobhunter.web.app import create_app

from .conftest import FIXTURES, NOW, ROOT, store_job
from .test_pitch import FakeClient
from .test_web import AUTH, TOKEN, FakeServices

# The frozen copy: these tests cite facts by number.
PROFILE_FILE = FIXTURES / "profile" / "master_profile.md"
FACTS = load_letter_facts(PROFILE_FILE, set())
POSTING = ("Acme runs payments for 2,000 merchants. You will build Python services on AWS. "
           "We use Kafka and Workato. 5+ years required.")
JOB = JobText.of("Senior Backend Engineer (Python)", POSTING, "Acme")

GOOD = {
    "opening": "Acme runs payments for 2,000 merchants, and every one of them depends on services that do not "
               "fail quietly. That is the work I want to do in this Senior Backend Engineer (Python) role.",
    "paragraphs": [
        {"text": "At CoinQuant I architected a serverless, event-driven backtesting platform on AWS Lambda and SQS "
                 "that runs 800+ concurrent Python jobs with zero production failures. I designed its failure "
                 "handling so no job is silently lost.", "facts": [4, 5]},
        {"text": "I built a comprehensive test suite covering the full testing pyramid. I lead a team of 5 "
                 "engineers through code reviews.", "facts": [6, 3]},
    ],
    "gaps": ["Kafka", "Workato"],
    "closing": "I would bring that same care for reliability to your payments platform. I would be glad to talk.",
    "notes": ["Led with reliability: the posting is about payments."],
}
BAD = {**GOOD, "paragraphs": [
    {"text": "I ran Kubernetes clusters for 1000+ services. I designed its failure handling so no job is silently "
             "lost.", "facts": [5]},
] + GOOD["paragraphs"][1:]}


# --- the facts ------------------------------------------------------------------------------


def test_the_letter_uses_the_facts_the_cv_prints():
    text = FACTS.text
    assert "800+ concurrent Python jobs" in text and "Zapier Academy" in text and "UTC+3" in text
    assert "Lead a team of 5" not in text  # the [lead] bullet: only for lead jobs, like on the CV
    assert "Lead a team of 5" in load_letter_facts(PROFILE_FILE, {"lead"}).text
    assert "working remotely from Beirut, Lebanon" in text and "Confirmed by me" not in text
    assert "3500" not in text and "TODO" not in text and "961" not in text  # never salary, notes or contact
    assert not any(f.startswith("[") or "[core]" in f for f in FACTS.facts)
    assert FACTS.years == 3.3 and FACTS.name == "Mohamad Shoumar" and FACTS.location == "Beirut, Lebanon"
    assert FACTS.contact[0] == "me@example.com" and "kafka" not in FACTS.skills


def test_your_profile_gives_a_letter_something_to_say():
    """The real profile, by shape only, so editing it never breaks the tests."""
    facts = load_letter_facts(ROOT / "profile" / "master_profile.md", set())
    assert facts.name and facts.contact and len(facts.facts) >= 5
    assert not any("TODO" in f or "Compensation" in f or "(Confirmed" in f for f in facts.facts)


def test_what_the_posting_asks_for_is_split_into_matches_and_gaps():
    assert posting_gaps(POSTING, FACTS.skills) == ["Kafka"]
    assert {"Python", "AWS"} <= set(posting_matches(POSTING, FACTS))
    assert "Zapier" in posting_matches("Tools: Zapier, n8n and Claude Code.", FACTS)
    assert "Claude Code" in posting_matches("Tools: Zapier, n8n and Claude Code.", FACTS)


# --- the sentence check ------------------------------------------------------------------------


def body(text, *ids):
    return check_sentence(text, [FACTS.facts[i - 1] for i in ids], FACTS, JOB, framing=False)


def framing(text):
    return check_sentence(text, FACTS.facts, FACTS, JOB, framing=True)


def test_a_sentence_from_the_facts_it_cites_passes():
    assert body("I architected a serverless platform on AWS Lambda that runs 800+ concurrent Python jobs.", 4) \
        == ([], [])
    assert body("I lead a team of five engineers.", 3) == ([], [])
    assert body("Over three years I moved from full-stack work to the backend.", 1, 2) == ([], [])


@pytest.mark.parametrize("text, ids, problem", [
    ("It runs 900+ concurrent Python jobs.", [4], '"900+ concurrent" is not in the facts it cites'),
    ("It runs 800+ concurrent Python jobs.", [5], '"800+ concurrent" is not in the facts it cites'),  # wrong fact
    ("I have 5 years of backend experience.", [1], "claims 5 years"),
    ("I built it on Kubernetes.", [4], 'names "kubernetes"'),
    ("I built the slippage model in Python.", [7], 'names "python"'),  # Python is not in that fact
    ("As a senior engineer I built the slippage model.", [7], 'says "senior"'),
    ("I wired it into Workato and Snowflake.", [4], 'names "Snowflake"'),  # after "I", a name still counts
])
def test_a_paragraph_sentence_may_not_add_facts(text, ids, problem):
    problems, _ = body(text, *ids)
    assert any(problem in p for p in problems), problems


def test_a_tool_from_the_posting_in_a_sentence_about_you_is_flagged_for_your_eyes():
    problems, warnings = body("I connected the gateway to Workato.", 4)
    assert problems == [] and any('"Workato" is from the posting' in w for w in warnings)


def test_the_opening_may_repeat_the_posting_about_the_company():
    assert framing("Acme runs payments for 2,000 merchants, which I find exciting.") == ([], [])
    assert framing("Your team builds on Kafka and Python.") == ([], [])  # about them, from the posting
    assert framing("You ask for 5+ years.")[0] == []
    assert any('names "kafka" in a sentence about you' in p for p in framing("I have built on Kafka.")[0])
    assert any("claims 5 years" in p for p in framing("I bring 5 years of experience.")[0])
    assert any('"3,000 merchants"' in p or '"3000 merchants"' in p
               for p in framing("Acme runs payments for 3,000 merchants.")[0])


def test_the_job_title_and_company_claim_nothing():
    """'Senior' and 'Python' in the posted title are not you saying so."""
    assert framing("I am applying for the Senior Backend Engineer (Python) role at Acme.") == ([], [])


def test_a_known_time_zone_is_not_a_number_to_check():
    assert framing("Working from Beirut, I am on UTC+3 in summer.") == ([], [])


# --- gaps ------------------------------------------------------------------------------------------


def test_a_gap_must_be_in_the_posting_and_share_nothing_with_your_facts():
    assert valid_gap("Workato", FACTS, JOB) and valid_gap("kafka", FACTS, JOB)
    assert not valid_gap("Snowflake", FACTS, JOB)  # not in the posting
    assert not valid_gap("Python services", FACTS, JOB)  # you have Python: never deny it
    assert not valid_gap("a very long list of five words", FACTS, JOB)


def test_the_gap_sentence_is_code_s():
    template = OutreachConfig().cover_gap_text
    assert gap_sentence(["Kafka"], template) == ("I have not worked with Kafka yet, and I would make learning it an "
                                                 "early priority.")
    assert gap_sentence(["Kafka", "Go", "Rust"], template).startswith("I have not worked with Kafka, Go or Rust yet")
    assert gap_sentence([], template) == ""


def test_gaps_the_model_names_wrongly_are_dropped():
    letter = letter_from({**GOOD, "gaps": ["Kafka", "Python", "Snowflake"]}, FACTS, JOB, ["Kafka"])
    assert letter.gaps == ["Kafka"]


# --- the writer --------------------------------------------------------------------------------


def writer(*answers):
    return CoverWriter(JsonModel("claude-sonnet-5", claude=FakeClient(*answers)))


def job_row(store, filters, **overrides):
    overrides.setdefault("description", POSTING)
    return store.get(store_job(store, filters, **overrides))


def test_a_bad_letter_is_sent_back_once_with_the_reasons(filters):
    store = JobStore(":memory:")
    w = writer(BAD, GOOD)
    letter, usage, attempts = w.write(job_row(store, filters), "Acme", FACTS, ["Kafka"])
    assert attempts == 2 and letter.removed == [] and letter.problems == []
    sent = w.model.claude.calls
    assert "1. About 3.3 years" in sent[0]["messages"][0]["content"] and "3500" not in sent[0]["messages"][0]["content"]
    assert "Asked for, not in the facts (found by code; there may be others): Kafka" in sent[0]["messages"][0]["content"]
    assert "kubernetes" in sent[1]["messages"][-1]["content"] and "1000+" in sent[1]["messages"][-1]["content"]


def test_a_sentence_that_stays_bad_is_left_out_and_said_why(filters):
    store = JobStore(":memory:")
    letter, _, attempts = writer(BAD, BAD).write(job_row(store, filters), "Acme", FACTS, ["Kafka"])
    assert attempts == 2 and len(letter.removed) == 1 and "Kubernetes clusters" in letter.removed[0]
    kept = [c.text for part in letter.paragraphs for c in part]
    assert kept[0] == "I designed its failure handling so no job is silently lost."  # the good sentence stays
    assert not any("Kubernetes" in t for t in kept)


def test_an_answer_with_no_paragraphs_is_sent_back(filters):
    store = JobStore(":memory:")
    letter, _, attempts = writer({**GOOD, "paragraphs": []}, GOOD).write(job_row(store, filters), "Acme", FACTS, [])
    assert attempts == 2 and len(letter.paragraphs) == 2


# --- the file ------------------------------------------------------------------------------------


def config_for(folder, **overrides):
    return OutreachConfig(resume_dir=str(folder), cv_dir=str(folder / "output"), **overrides)


def test_the_letter_file_is_written_and_stored_with_the_job(tmp_path, filters):
    store = JobStore(":memory:")
    job_id = store_job(store, filters, description=POSTING)
    meta = cover_for_job(store, job_id, writer(GOOD), PROFILE_FILE, config_for(tmp_path), NOW)
    path = tmp_path / "output" / "Shoumar_CoverLetter_Acme_Sep2026.md"
    assert meta["file"] == path.name and meta["path"] == str(path) and meta["gaps_named"] == ["Kafka", "Workato"]
    text = path.read_text()
    assert text.startswith("Mohamad Shoumar\nme@example.com | +1 555 010 7788 | ")
    assert "\nSeptember 25, 2026\n" in text and "\nAcme Hiring Team\nSenior Backend Engineer (Python)\n" in text
    assert "\nDear Acme Hiring Team,\n\nAcme runs payments for 2,000 merchants" in text
    assert "I have not worked with Kafka or Workato yet" in text and text.endswith("Best regards,\nMohamad Shoumar\n")
    app = tracking.get_application(store, job_id)
    assert json.loads(app["cover_letter_json"])["text"] == text and app["stage"] == tracking.NEW
    assert [e["detail"] for e in tracking.events_for(store, job_id)][-1] == f"Cover letter written: {path.name}"

    again = cover_for_job(store, job_id, writer(GOOD), PROFILE_FILE, config_for(tmp_path), NOW)
    assert again["file"] == meta["file"] and len(list((tmp_path / "output").glob("*.md"))) == 1


def test_a_letter_made_by_hand_is_never_overwritten(tmp_path, filters):
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "Shoumar_CoverLetter_Acme_Sep2026.md").write_text("by hand")
    store = JobStore(":memory:")
    job_id = store_job(store, filters, description=POSTING)
    meta = cover_for_job(store, job_id, writer(GOOD), PROFILE_FILE, config_for(tmp_path), NOW)
    assert meta["file"] == "Shoumar_CoverLetter_Acme_Sep2026_2.md"
    assert (tmp_path / "output" / "Shoumar_CoverLetter_Acme_Sep2026.md").read_text() == "by hand"


def test_relative_folders_are_inside_the_project(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "outreach.json").write_text(json.dumps({"resume_dir": "resume", "cv_dir": "resume/output"}))
    config = OutreachConfig.load(tmp_path / "config" / "outreach.json")
    assert config.resume_dir == str(tmp_path.resolve() / "resume")
    assert config.cv_dir == str(tmp_path.resolve() / "resume" / "output")
    assert OutreachConfig.load(tmp_path / "config" / "outreach.json").cover_model == ""


# --- the daily run and the report ---------------------------------------------------------------


@pytest.fixture
def home(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "outreach.json").write_text(json.dumps(
        {"cv_dir": "resume/output", "auto_lookup": False, "auto_tailor": False}))
    shutil.copytree(FIXTURES / "profile", tmp_path / "profile")
    return tmp_path


def test_the_daily_run_writes_letters_for_new_shortlisted_jobs(home, filters, monkeypatch):
    from jobhunter import outreach

    monkeypatch.setattr(outreach, "build_cover_writer", lambda config: (writer(GOOD, GOOD), None))
    store = JobStore(":memory:")
    job_id = store_job(store, filters, description=POSTING)
    summary = outreach.run_outreach(store, Paths(home), [job_id], NOW)
    assert summary["covers"] == [f"#{job_id}: Shoumar_CoverLetter_Acme_Sep2026.md"] and summary["errors"] == []
    assert outreach.run_outreach(store, Paths(home), [job_id], NOW)["covers"] == []  # once per job
    assert outreach.run_outreach(store, Paths(home), [], NOW, ai=False)["covers"] == []


def test_the_daily_run_catches_up_on_recent_jobs_that_have_none(home, filters, monkeypatch):
    from jobhunter import outreach

    monkeypatch.setattr(outreach, "build_cover_writer", lambda config: (writer(GOOD, GOOD, GOOD), None))
    store = JobStore(":memory:")
    recent = store_job(store, filters, company="Recent")
    old = store_job(store, filters, source_job_id="2", company="Old")
    skipped = store_job(store, filters, source_job_id="3", company="Skipped")
    day = NOW.astimezone().date()
    store.set_report_date([recent, skipped], (day - timedelta(days=2)).isoformat())
    store.set_report_date([old], (day - timedelta(days=30)).isoformat())
    tracking.set_stage(store, skipped, tracking.CLOSED, NOW, reason="skipped")
    summary = outreach.run_outreach(store, Paths(home), [], NOW)  # nothing new today
    assert summary["covers"] == [f"#{recent}: Shoumar_CoverLetter_Recent_Sep2026.md"]


def test_the_report_links_the_job_s_cv_and_letter(tmp_path, filters):
    store = JobStore(":memory:")
    job_id = store_job(store, filters, description=POSTING)
    cover_for_job(store, job_id, writer(GOOD), PROFILE_FILE, config_for(tmp_path / "resume"), NOW)
    store.conn.execute("UPDATE applications SET cv_tailored_json = ? WHERE job_id = ?",
                       (json.dumps({"path": str(tmp_path / "resume" / "output" / "Shoumar_Backend_Acme.pdf")}), job_id))
    line = _prepared_line(store.applications_for([job_id])[job_id], tmp_path / "reports")
    assert line == ("- **Tailored for this job:** [CV](../resume/output/Shoumar_Backend_Acme.pdf) · "
                    "[cover letter](../resume/output/Shoumar_CoverLetter_Acme_Sep2026.md)")
    assert _prepared_line(None, tmp_path / "reports") is None


# --- the web app -------------------------------------------------------------------------------


class CoverServices(FakeServices):
    def cover_writer(self):
        return writer(GOOD), None


@pytest.fixture
def cover_client(tmp_path, filters):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    shutil.copytree(FIXTURES / "profile", tmp_path / "profile")
    store = JobStore(tmp_path / "data" / "jobs.sqlite")
    store_job(store, filters, description=POSTING)
    store.close()
    paths = Paths(tmp_path)
    app = create_app(paths, TOKEN, allowed_hosts=["testserver"],
                     services=CoverServices(OutreachConfig.load(paths.outreach_file)), now=lambda: NOW)
    return TestClient(app), tmp_path


def test_write_cover_letter_from_the_page(cover_client):
    client, home = cover_client
    assert client.get("/api/jobs/1").json()["cover"] is None
    assert client.post("/api/jobs/1/cover", json={}).status_code == 403  # needs the token
    detail = client.post("/api/jobs/1/cover", json={}, headers=AUTH).json()
    cover = detail["cover"]
    assert cover["file"] == "Shoumar_CoverLetter_Acme_Sep2026.md" and "Dear Acme Hiring Team," in cover["text"]
    assert cover["gaps_named"] == ["Kafka", "Workato"]
    path = home / "resume" / "output" / cover["file"]  # cv_dir is relative: inside the project
    path.write_text(path.read_text().replace("Best regards", "Kind regards"))
    assert "Kind regards" in client.get("/api/jobs/1").json()["cover"]["text"]  # your edits show
    assert client.get("/api/jobs").json()["jobs"][0]["has_cover"] is True
