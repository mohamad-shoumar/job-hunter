"""Cover letters: the facts, the company's pages, the sentence check, the retry, the file, the daily run and the app."""

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from jobhunter.config import OutreachConfig, Paths
from jobhunter.contacts import ensure_company, set_job_board
from jobhunter.cover import (
    ANNOUNCES_ISSUE, DASH_ISSUE, GUIDELINES_FILE, LOGISTICS_ISSUE, CoverError, CoverWriter, JobText, Style, check_sentence,
    check_style, company_site, cover_for_job, load_letter_facts, research, system_prompt,
)
from jobhunter.llm import JsonModel
from jobhunter.models import NEW
from jobhunter.report import _prepared_line
from jobhunter.store import JobStore
from jobhunter.store.applications import events_for, get_application
from jobhunter.web.app import create_app

from .conftest import FIXTURES, NOW, ROOT, YOUR_PROFILES, FakeHttp, store_job
from .test_pitch import FakeClient
from .test_web import AUTH, TOKEN, FakeServices

# The frozen copy of the profile.
PROFILE_FILE = FIXTURES / "profile" / "master_profile.md"
FACTS = load_letter_facts(PROFILE_FILE, set())
POSTING = ("Acme runs payments for 2,000 merchants. You will build Python services on AWS. "
           "We use Kafka and Workato. Kafka experience is required. 5+ years required.")
PAGES = [("https://acme.com", "Acme. Payouts in 40 countries. Our engineers run the Ledger team.")]
JOB = JobText.of("Senior Backend Engineer (Python)", POSTING, "Acme", PAGES)
SECOND = "At CoinQuant, I've helped build and ship production systems. I'd bring that to your team."

GOOD = {
    "reason": "Payments have to land in the right place every time.",
    "paragraph": "Acme runs payments for merchants, and getting money to the right place every time is a "
                 "backend problem I'd like to work on. I like work where being correct matters more than being "
                 "clever.",
    "quote": "Acme runs payments for 2,000 merchants",
    "notes": ["Picked the payments work from the posting."],
}
BAD = {**GOOD, "paragraph": "I've used Acme Wallet for years and ran Kubernetes for 1000+ services. " + GOOD["paragraph"]}


# --- the facts ------------------------------------------------------------------------------


def test_the_letter_uses_the_facts_the_cv_prints():
    text = FACTS.text
    assert "800+ concurrent Python jobs" in text and "Zapier Academy" in text
    assert "UTC+3" not in text and "Notice period" not in text and "Lives in" not in text  # logistics: the form's job
    assert "Lead a team of 5" not in text  # the [lead] bullet: only for lead jobs, like on the CV
    assert "Lead a team of 5" in load_letter_facts(PROFILE_FILE, {"lead"}).text
    assert "4200" not in text and "TODO" not in text and "7788" not in text  # never salary, notes or contact
    assert FACTS.years == 3.3 and FACTS.name == "Mohamad Shoumar"
    assert "kafka" not in FACTS.skills


@pytest.mark.parametrize("path", YOUR_PROFILES)
def test_your_profile_gives_a_letter_something_to_say(path, monkeypatch):
    """The real profile, by shape only, so editing it never breaks the tests. Name and contact come from .env."""
    monkeypatch.setenv("MY_NAME", "Jane Doe")
    monkeypatch.setenv("MY_EMAIL", "jane@example.com")
    facts = load_letter_facts(path, set())
    assert facts.name == "Jane Doe" and len(facts.facts) >= 5
    assert not any("TODO" in f or "Compensation" in f or "(Confirmed" in f for f in facts.facts)


# --- the company's pages ---------------------------------------------------------------------


HOME = "<html><body><h1>Acme</h1><p>Payouts in 40 countries.</p></body></html>"


def test_the_company_s_home_about_and_blog_pages_are_read():
    http = FakeHttp({"https://acme.com": HOME, "https://acme.com/about": "<p>We started in 2019.</p>",
                     "https://acme.com/blog": RuntimeError("404")})
    pages = company_site("acme.com", "Acme", http)
    assert [url for url, _ in pages] == ["https://acme.com", "https://acme.com/about"]
    assert "Payouts in 40 countries." in pages[0][1]


def test_a_guessed_domain_counts_only_when_it_names_the_company():
    http = FakeHttp({"https://acme.com": "<p>Domain for sale</p>"})
    assert company_site("acme.com", "Acme", http, guessed=True) == []
    assert company_site("acme.com", "Acme", FakeHttp({}), guessed=False) == []  # no home page: nothing else is tried


def test_research_uses_the_known_domain_and_skips_job_boards(filters):
    store = JobStore(":memory:")

    def company(**overrides):
        job = store.get(store_job(store, filters, description=POSTING, **overrides))
        return ensure_company(store, job), job

    row, job = company()
    store.conn.execute("UPDATE companies SET domain = 'acme.io' WHERE key = ?", (row["key"],))
    row, _ = company(source_job_id="9")
    found = research(row, job, OutreachConfig(), FakeHttp({"https://acme.io": HOME}))
    assert [url for url, _ in found.pages] == ["https://acme.io"] and found.note == ""
    guessed = research(*company(source_job_id="2", company="Globex"), OutreachConfig(), FakeHttp({}))
    assert guessed.pages == [] and "Could not read Globex's website (globex.com)" in guessed.note
    valsoft = research(*company(source_job_id="3", company="Valsoft Corporation"), OutreachConfig(),
                       FakeHttp({"https://valsoft.com": "<p>Valsoft buys software</p>"}))
    assert [url for url, _ in valsoft.pages] == ["https://valsoft.com"]
    set_job_board(store, row["key"], True)
    row, _ = company(source_job_id="10")
    assert "job board or agency" in research(row, job, OutreachConfig(), FakeHttp({})).note


# --- the sentence check ------------------------------------------------------------------------


def test_what_the_posting_or_pages_say_about_the_company_passes():
    assert check_sentence("Acme runs payments for 2,000 merchants, which is a lot of money to keep right.",
                          FACTS, JOB) == []
    assert check_sentence("Payouts in 40 countries means a lot of edge cases in the Ledger.", FACTS, JOB) == []
    assert check_sentence("Most of my work at CoinQuant runs on AWS Lambda and SQS.", FACTS, JOB) == []
    startup = JobText.of("Backend Engineer", "We are a seed-stage start-up building payroll SaaS.", "Acme")
    assert check_sentence("A startup doing payroll SaaS has a lot of backend work.", FACTS, startup) == []


@pytest.mark.parametrize("text, problem", [
    ("Acme Wallet looks like a hard product to build.", '"Wallet"'),  # a product nobody wrote down
    ("You serve 9,000 banks.", '"9000 banks"'),
    ("I have built Kafka pipelines for years.", '"kafka" in a sentence about you'),
    ("With my 6 years of backend work, this fits.", "claims 6 years"),
    ("As a senior engineer I want this.", '"senior"'),
    ("Doing that at a fintech consultancy like Acme is a good next step.", '"consultancy"'),
])
def test_a_made_up_detail_is_a_problem(text, problem):
    assert any(problem.lower() in p.lower() for p in check_sentence(text, FACTS, JOB))


def test_the_job_title_and_company_claim_nothing():
    assert check_sentence("Senior Backend Engineer (Python) at Acme sounds right.", FACTS, JOB) == []


def test_the_guidelines_file_gives_the_writer_its_part_and_the_lists():
    style = Style.load(GUIDELINES_FILE)
    assert "ONE specific reason" in style.text and "Background research" not in style.text
    assert {"passionate about", "I've used", "cutting-edge", "industry-leading"} <= set(style.never)
    assert "robust" in style.at_most_one and "—" not in style.never
    assert system_prompt(style).startswith("You write the first paragraph") and "ONE specific reason" in \
        system_prompt(style)
    assert Style.load("/nowhere") == Style()


def test_a_never_use_phrase_an_announcement_or_logistics_is_a_problem():
    style = Style.load(GUIDELINES_FILE)
    assert check_style("I've used your app every day.", JOB, style)[0] == \
        ['uses "I\'ve used", which is on the "Never use" list']
    assert ANNOUNCES_ISSUE in check_style("I'm applying for this role because of the payments work.", JOB, style)[0]
    assert LOGISTICS_ISSUE in check_style("I'm based in Beirut, close to your time zone.", JOB, style)[0]
    _, issues, once = check_style("It's a robust system — and a crucial one, enabling payouts.", JOB, style)
    assert len(issues) == 2 and once == ["robust", "crucial"]
    assert check_style("End-to-end flows - that caught my eye.", JOB, style)[1] == [DASH_ISSUE]


# --- the writer --------------------------------------------------------------------------------


def writer(*answers, http=None):
    return CoverWriter(JsonModel("claude-sonnet-5", claude=FakeClient(*answers)), Style.load(GUIDELINES_FILE), http)


def job_row(store, filters, **overrides):
    overrides.setdefault("description", POSTING)
    return store.get(store_job(store, filters, **overrides))


def test_a_bad_paragraph_is_sent_back_once_with_the_reasons(filters):
    store = JobStore(":memory:")
    w = writer(BAD, GOOD)
    opening, _, attempts = w.write(job_row(store, filters), "Acme", FACTS, PAGES, SECOND)
    assert attempts == 2 and opening.removed == [] and opening.text == GOOD["paragraph"]
    assert opening.found_at == "the posting"
    asked = w.model.claude.calls[0]["messages"][0]["content"]
    assert "--- https://acme.com ---\nAcme. Payouts in 40 countries." in asked and SECOND in asked
    assert "About 3.3 years" not in asked and "4200" not in asked  # your facts are for the checks, not the writer
    sent_back = w.model.claude.calls[1]["messages"][-1]["content"]
    assert "Wallet" in sent_back and "kubernetes" in sent_back and "I've used" in sent_back


def test_a_sentence_that_stays_bad_is_left_out_and_said_why(filters):
    store = JobStore(":memory:")
    opening, _, attempts = writer(BAD, BAD).write(job_row(store, filters), "Acme", FACTS, PAGES, SECOND)
    assert attempts == 2 and len(opening.removed) == 1 and "Acme Wallet" in opening.removed[0]  # 2 good ones left
    assert opening.text == GOOD["paragraph"]  # the good sentences stay


def test_length_and_an_unfound_quote_are_sent_back_then_only_noted(filters):
    store = JobStore(":memory:")
    long = {**GOOD, "paragraph": GOOD["paragraph"] + " Acme runs payments for 2,000 merchants, and I like "
            "backend work a lot because the services have to be right every single time for every "
            "merchant, every day, in every country they run in. That is the reason.",
            "quote": "we love our users"}
    opening, _, attempts = writer(long, long).write(job_row(store, filters), "Acme", FACTS, PAGES)
    assert attempts == 2 and opening.removed == []
    issues = " ".join(opening.style_issues)
    assert "4 sentences" in issues and "words; keep it to 65" in issues and "quote is not word for word" in issues
    assert "headline numbers" in issues  # "2,000 merchants": their numbers, not why the work interests you


@pytest.mark.parametrize("text", [
    "At CoinQuant I architected scalable systems and led a team.",
    "I've built event-driven platforms on AWS, so this fits.",
    "My experience with queues would help here.",
    "That is close to similar transitions I went through.",
])
def test_paragraph_1_never_describes_your_past_work(text, filters):
    """Paragraph 2 does that; a claim here is easy to make up ("led a team through similar transitions")."""
    store = JobStore(":memory:")
    answer = {**GOOD, "paragraph": f"{GOOD['paragraph']} {text}"}
    opening, _, attempts = writer(answer, answer).write(job_row(store, filters), "Acme", FACTS, PAGES)
    assert attempts == 2 and "describes your past work" in opening.removed[0] and opening.text == GOOD["paragraph"]


def test_a_third_try_when_too_little_would_be_left(filters):
    store = JobStore(":memory:")
    bad = {**GOOD, "paragraph": "At CoinQuant I built a ledger. I've led a team of 5."}
    opening, _, attempts = writer(bad, bad, GOOD).write(job_row(store, filters), "Acme", FACTS, PAGES)
    assert attempts == 3 and opening.text == GOOD["paragraph"]


# --- the file ------------------------------------------------------------------------------------


def config_for(folder, **overrides):
    overrides.setdefault("cover_paragraph", SECOND)
    return OutreachConfig(resume_dir=str(folder), cv_dir=str(folder / "output"), **overrides)


def test_the_letter_is_why_this_company_then_your_paragraph(tmp_path, filters):
    store = JobStore(":memory:")
    job_id = store_job(store, filters, description=POSTING)
    http = FakeHttp({"https://acme.com": "<h1>Acme</h1><p>Payouts in 40 countries. The Ledger team.</p>"})
    meta = cover_for_job(store, job_id, writer(GOOD, http=http), PROFILE_FILE, config_for(tmp_path), NOW)
    path = tmp_path / "output" / "Shoumar_CoverLetter_Acme_Sep2026.md"
    assert meta["file"] == path.name and meta["pages"] == ["https://acme.com"] and meta["quote_found_at"]
    text = path.read_text()
    assert text == f"{GOOD['paragraph']}\n\n{SECOND}\n"  # only the two paragraphs: no header, greeting or sign-off
    app = get_application(store, job_id)
    assert json.loads(app["cover_letter_json"])["text"] == text and app["stage"] == NEW
    assert [e["detail"] for e in events_for(store, job_id)][-1] == f"Cover letter written: {path.name}"

    again = cover_for_job(store, job_id, writer(GOOD), PROFILE_FILE, config_for(tmp_path), NOW)
    assert again["file"] == meta["file"] and len(list((tmp_path / "output").glob("*.md"))) == 1
    assert "No pages fetched" in " ".join(again["notes"]) and again["pages"] == []


def test_your_paragraph_prints_word_for_word_unchecked(tmp_path, filters):
    """It may use words the model may not ("fast-paced", "leverage"): you wrote it."""
    store = JobStore(":memory:")
    job_id = store_job(store, filters, description=POSTING)
    mine = "In a fast-paced  startup I leverage   multi-agent workflows."
    meta = cover_for_job(store, job_id, writer(GOOD), PROFILE_FILE, config_for(tmp_path, cover_paragraph=mine), NOW)
    assert meta["text"].endswith("\n\nIn a fast-paced startup I leverage multi-agent workflows.\n")  # spaces tidied
    alone = cover_for_job(store, job_id, writer(GOOD), PROFILE_FILE, config_for(tmp_path, cover_paragraph=""), NOW)
    assert "paragraph 1 only" in " ".join(alone["notes"])


def test_an_answer_with_nothing_usable_writes_nothing(tmp_path, filters):
    store = JobStore(":memory:")
    job_id = store_job(store, filters, description=POSTING)
    with pytest.raises(CoverError, match="No cover letter written"):
        cover_for_job(store, job_id, writer({}, {}, {}), PROFILE_FILE, config_for(tmp_path), NOW)
    assert not list((tmp_path / "output").glob("*.md"))
    assert get_application(store, job_id)["cover_letter_json"] is None


def test_a_letter_made_by_hand_is_never_overwritten(tmp_path, filters):
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "Shoumar_CoverLetter_Acme_Sep2026.md").write_text("by hand")
    store = JobStore(":memory:")
    job_id = store_job(store, filters, description=POSTING)
    meta = cover_for_job(store, job_id, writer(GOOD), PROFILE_FILE, config_for(tmp_path), NOW)
    assert meta["file"] == "Shoumar_CoverLetter_Acme_Sep2026_2.md"
    assert (tmp_path / "output" / "Shoumar_CoverLetter_Acme_Sep2026.md").read_text() == "by hand"


def test_relative_folders_are_inside_the_project_and_letters_are_not_automatic(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "outreach.json").write_text(json.dumps({"resume_dir": "resume", "cv_dir": "resume/output"}))
    config = OutreachConfig.load(tmp_path / "config" / "outreach.json")
    assert config.resume_dir == str(tmp_path.resolve() / "resume")
    assert config.cv_dir == str(tmp_path.resolve() / "resume" / "output")
    assert config.cover_model == "" and config.auto_cover is False and config.cover_paragraph == ""
    assert config.cover_guidelines == str(tmp_path.resolve() / "config" / "cover_letter_guidelines.md")
    # The shipped file on purpose: letters only on request, by Claude Code, are your settled choices (2026-10-20).
    shipped = OutreachConfig.load(ROOT / "config" / "outreach.json")
    assert shipped.auto_cover is False and shipped.cover_model == "claude-code" and shipped.cover_paragraph


# --- the daily run and the report ---------------------------------------------------------------


@pytest.fixture
def home(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "outreach.json").write_text(json.dumps(
        {"cv_dir": "resume/output", "auto_lookup": False, "auto_tailor": False}))
    shutil.copytree(FIXTURES / "profile", tmp_path / "profile")
    return tmp_path


def test_the_daily_run_writes_no_letters_unless_auto_cover_is_on(home, filters, monkeypatch):
    from jobhunter import outreach

    monkeypatch.setattr(outreach, "build_cover_writer", lambda config: (writer(GOOD, GOOD), None))
    store = JobStore(":memory:")
    job_id = store_job(store, filters, description=POSTING)
    assert outreach.run_outreach(store, Paths(home), [job_id], NOW)["covers"] == []
    (home / "config" / "outreach.json").write_text(json.dumps(
        {"cv_dir": "resume/output", "auto_lookup": False, "auto_tailor": False, "auto_cover": True}))
    summary = outreach.run_outreach(store, Paths(home), [job_id], NOW)
    assert summary["covers"] == [f"#{job_id}: Shoumar_CoverLetter_Acme_Sep2026.md"] and summary["errors"] == []


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
    # The shipped config/ on purpose: the app needs a whole project folder (outreach, sources, cover guidelines).
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
    assert cover["file"] == "Shoumar_CoverLetter_Acme_Sep2026.md" and cover["text"].startswith(GOOD["paragraph"])
    assert GOOD["paragraph"] in cover["text"] and "At CoinQuant, I've helped build" in cover["text"]
    path = home / "resume" / "output" / cover["file"]  # cv_dir is relative: inside the project
    path.write_text(path.read_text() + "\nKind regards\n")
    assert "Kind regards" in client.get("/api/jobs/1").json()["cover"]["text"]  # your edits show
    assert client.get("/api/jobs").json()["jobs"][0]["has_cover"] is True
