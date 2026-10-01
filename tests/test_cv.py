"""Tailored CVs: the profile facts, the fact check, the file, the PDF step (faked) and the web app."""

import csv
import json
import re
import shutil
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from jobhunter import tracking
from jobhunter.config import OutreachConfig, Paths
from jobhunter.cv import (
    MAX_BULLET_WORDS, TAG_RULES, CvWriter, TailorError, check_bullet, check_headline, check_version, job_tags,
    load_facts, plan_from, printed_title, render, role_label, save_version, scan, select, split_items,
    tailor_for_job, tailored_of, version_of,
)
from jobhunter.llm import JsonModel
from jobhunter.store import JobStore
from jobhunter.text import iso
from jobhunter.web.app import create_app

from .conftest import FIXTURES, NOW, ROOT, store_job
from .test_pitch import PROFILE, FakeClient
from .test_web import AUTH, TOKEN, FakeServices

# A frozen copy: these tests cite bullets by position. test_your_profile_is_well_formed checks the real one.
PROFILE_FILE = FIXTURES / "profile" / "master_profile.md"
ROLES, SKILLS, HEADLINES = load_facts(PROFILE_FILE)
R1 = {n: b for n, b in enumerate(ROLES[0].bullets, 1)}

GOOD = {
    "headline": "Backend Engineer - Python & AWS",
    "roles": [
        {"role": "R1", "bullets": [
            {"sources": ["R1.1"], "text": "Architected a serverless platform on AWS Lambda that runs 800+ concurrent "
                                          "Python jobs with zero production failures."},
            {"sources": ["R1.2"], "text": "Designed failure handling so no job is silently lost: SQS dead-letter "
                                          "queue, idempotent PostgreSQL writes and credit refunds."},
            {"sources": ["R1.4"], "text": "Designed a slippage model that improves backtest realism and trading "
                                          "cost accuracy."},
        ]},
        {"role": "R2", "bullets": [{"sources": ["R2.1"], "text": "Led the microservices packaging migration from "
                                                                 "Bazel to Poetry across internal Python services."}]},
        {"role": "R3", "bullets": [{"sources": ["R3.1"], "text": "Designed REST APIs in Python for the backtesting "
                                                                 "platform, delivering market and simulation data."}]},
    ],
    "skills": [{"label": "Languages", "items": ["Python", "SQL", "Rust"]},
               {"label": "Tools & Platforms", "items": ["AWS (Lambda, SQS)", "Docker"]}],
    "changes": ["Put the AWS Lambda platform first: the posting is about serverless Python."],
}
BAD = {**GOOD, "roles": [{"role": "R1", "bullets": [
    {"sources": ["R1.1"], "text": "Architected a Kubernetes platform that runs 1000+ concurrent Python jobs."},
]}] + GOOD["roles"][1:]}


# --- the facts and the file ------------------------------------------------------------


def test_facts_come_from_the_profile():
    assert [r.title for r in ROLES] == ["Team Lead - Algorithmic Trader", "Backend Developer", "Full Stack Developer"]
    assert "Slack gateway" in R1[9] and "Confirmed by me" not in R1[9]  # the note is not part of the fact
    assert not any(b.startswith("[") or "TODO" in b for r in ROLES for b in r.bullets)  # tags are not part of it
    assert ROLES[0].tags[0] == {"core"} and ROLES[0].tags[5] == {"lead"} and ROLES[0].tags[8] == {"automation"}
    assert ROLES[0].titles == [("Algorithmic Trader", {"default"}), ("Team Lead", {"lead"})] and not ROLES[1].titles
    assert HEADLINES[0] == "Backend Engineer" and "Forward Deployed Engineer" in HEADLINES
    assert SKILLS["Tools & Platforms"][0] == "AWS (Lambda, SQS)"  # the comma in brackets does not split it
    assert SKILLS["Tools & Platforms"][-1] == "AI coding agents (Claude Code)"


def test_your_profile_is_well_formed():
    """The real profile, by shape only, so editing it never breaks the tests - but a typo still shows up here."""
    roles, skills, headlines = load_facts(ROOT / "profile" / "master_profile.md")
    known = set(TAG_RULES) | {"core"}
    assert roles and skills and headlines
    for role in roles:
        assert len(role.tags) == len(role.bullets) and any("core" in t for t in role.tags), role.title
        assert all(t <= known for t in role.tags), f"{role.title}: unknown tag in {[sorted(t) for t in role.tags]}"
        for bullet in role.bullets:  # a note that is not "(Confirmed by me ...)" would print on the CV
            assert not re.search(r"\((?:stated|confirmed|note|todo)\b", bullet, re.I), bullet
            assert not bullet.startswith("[") and len(bullet.split()) <= MAX_BULLET_WORDS + 10, bullet
        for title, want in role.titles:
            assert title and want <= known | {"default"}, role.title
    assert all(item.count("(") == item.count(")") for row in skills.values() for item in row)


def test_skills_rows_split_on_commas_outside_brackets():
    assert split_items("AWS (Lambda, SQS), Docker,  Git") == ["AWS (Lambda, SQS)", "Docker", "Git"]


@pytest.mark.parametrize("title, posting, tags", [
    ("Backend Engineer", "Shape engineering practices through hands-on leadership.", {}),  # not a lead signal
    ("Tech Lead, Payments", "", {"lead": 'the title says "lead"'}),
    ("Backend Engineer", "You will be mentoring two engineers.", {"lead": 'the posting says "mentoring"'}),
    ("Senior Full-Stack Engineer", "", {"fullstack": 'the title says "full-stack"'}),
    ("Software Engineer", "Our stack: Python, React and Postgres.", {"fullstack": 'the posting says "React"'}),
    ("Backend Engineer", "On call, you react to incidents fast.", {}),  # the verb, not the library
    ("AI Automation Engineer", "", {"automation": 'the title says "automation"'}),
    ("Backend Engineer", "We talk on Slack and ship AI-powered tools.", {}),  # a tool we use, not a requirement
    ("Backend Engineer", "Build LLM workflows and a Slack bot.", {"automation": 'the posting says "llm"'}),
])
def test_job_tags_say_why(title, posting, tags):
    assert job_tags(title, posting) == tags


def test_tags_choose_the_bullets_and_the_title():
    kept, skipped = select(ROLES, {"lead"})
    assert kept[0].bullets == [R1[n] for n in (1, 2, 3, 4, 5, 6, 7)]  # core, then lead and fullstack-or-lead
    assert skipped["R1"] == [f"[automation] - {R1[8]}", f"[automation] - {R1[9]}"]
    assert skipped["R3"] == [f"[fullstack, mobile] - {ROLES[2].bullets[2]}"] and skipped["R2"] == []
    core, _ = select(ROLES, [])
    assert core[0].bullets == [R1[n] for n in (1, 2, 3, 4, 5)]
    assert printed_title(ROLES[0], {"lead"}) == "Team Lead" and printed_title(ROLES[0], set()) == "Algorithmic Trader"
    assert printed_title(ROLES[1], {"lead"}) is None


def test_resume_md_roles_are_matched_by_title_and_dates():
    lines = (FIXTURES / "resume.md").read_text().splitlines()
    matched, rows = scan(lines, ROLES, SKILLS)
    assert [r.key for r in matched.values()] == ["R1", "R2", "R3"]
    assert sorted(rows.values()) == ["Frameworks", "Languages", "Tools & Platforms"]  # not "Spoken": not in the profile
    printed = [line.replace("Team Lead - Algorithmic Trader", "Algorithmic Trader") for line in lines]
    assert [r.key for r in scan(printed, ROLES, SKILLS)[0].values()] == ["R1", "R2", "R3"]  # a printed title matches


def test_the_file_keeps_the_layout_and_prints_only_checked_lines():
    lines = (FIXTURES / "resume.md").read_text().splitlines()
    matched, rows = scan(lines, ROLES, SKILLS)
    roles, skipped = select(list(matched.values()), [])
    plan = plan_from(GOOD, roles, {k: SKILLS[k] for k in rows.values()}, HEADLINES, PROFILE)
    assert plan.problems == [] and plan.notes == [
        "Team Lead - Algorithmic Trader: added 2 bullet(s) the answer left out (R1.3, R1.5)",
        "Backend Developer: added 1 bullet(s) the answer left out (R2.2)",
        "Full Stack Developer: added 1 bullet(s) the answer left out (R3.2)",
        'Languages: left out "Rust", which is not in your profile',
    ]
    plan.skipped, plan.titles = skipped, {"R1": "Algorithmic Trader"}
    text = render(lines, matched, rows, plan, "TAILORED for Acme", compact=True)
    assert text.startswith("// TAILORED for Acme\n# Mohamad Shoumar\ntitle: Backend Engineer - Python & AWS\n")
    assert "location: Beirut, Lebanon\ncompact: yes\n\n## Professional Experience" in text
    assert "Present\nAlgorithmic Trader\n- Architected a serverless platform" in text  # the printed title
    assert f"- {R1[3]}\n- {R1[5]}\n// [lead] - {R1[6]}" in text  # core bullets always print; lead ones not here
    assert f"// [automation] - {R1[9]}" in text and "[core]" not in text
    assert "spare bullet" not in text and "Summary" not in text
    assert "Languages: Python, SQL\n" in text and "Spoken: English, Arabic" in text
    assert "Tools & Platforms: AWS (Lambda, SQS), Docker\n" in text
    assert "Frameworks: Django, FastAPI, Node.js, React, Next.js, React Native" in text  # not asked for: the profile row
    assert text.rstrip().endswith("Completed the boot camp as a Star Developer with a Full stack web app.")


@pytest.mark.parametrize("text, problem", [
    ("Architected a serverless platform on AWS Lambda running 900+ concurrent Python jobs.", '"900+ concurrent"'),
    ("Architected a serverless platform on AWS Lambda for 800+ concurrent jobs using Kafka.", 'names "kafka"'),
    ("As a senior engineer, architected a serverless platform on AWS Lambda.", 'says "senior"'),
    ("Architected a serverless platform on AWS Lambda for Goldman Sachs.", 'names "Goldman"'),
    ("Architected a robust, scalable, secure, resilient, observable serverless platform on AWS Lambda.",
     "adds 5 words"),
])
def test_a_rewrite_may_not_add_facts(text, problem):
    assert any(problem in p for p in check_bullet(text, [R1[1]]))


def test_a_faithful_rewrite_passes():
    assert check_bullet("Architected a serverless platform on AWS Lambda that runs 800+ concurrent Python jobs "
                        "with zero production failures.", [R1[1]]) == []
    assert check_bullet("Built REST APIs in Python for the backtesting platform.", [ROLES[2].bullets[0]]) == []


def test_the_headline_is_a_target_role():
    assert check_headline("Backend Engineer - Python & AWS", HEADLINES, PROFILE) == ("Backend Engineer - Python & AWS", None)
    assert check_headline("Staff Backend Engineer", HEADLINES, PROFILE)[0] == "Backend Engineer"
    headline, why = check_headline("Python Engineer - Kubernetes & Go", HEADLINES, PROFILE)
    assert headline == "Python Engineer" and "kubernetes" in why


def test_role_label_names_the_file_like_build_py():
    assert role_label("Senior Backend Engineer (Python)") == "Backend"
    assert role_label("Forward Deployed Engineer - Remote") == "ForwardDeployed"
    assert role_label("Engineer") == "Engineer"


# --- the writer ---------------------------------------------------------------------------


def job_row(store, filters, **overrides):
    return store.get(store_job(store, filters, **overrides))


def test_a_bad_rewrite_is_sent_back_once(filters):
    store = JobStore(":memory:")
    client = FakeClient(BAD, GOOD)
    plan, usage, attempts = CvWriter(JsonModel("claude-sonnet-5", claude=client)).plan(
        job_row(store, filters), "Acme", ROLES, SKILLS, HEADLINES, PROFILE)
    assert attempts == 2 and plan.problems == [] and plan.bullets["R1"][0].startswith("Architected a serverless")
    first = client.calls[0]
    assert first["output_config"]["format"]["type"] == "json_schema" and first["thinking"] == {"type": "disabled"}
    assert "R1.1: Architected" in first["messages"][0]["content"] and "961" not in first["messages"][0]["content"]
    assert "1000+" in client.calls[1]["messages"][-1]["content"]


def test_a_rewrite_that_stays_bad_prints_the_profile_s_words(filters):
    store = JobStore(":memory:")
    plan, _, _ = CvWriter(JsonModel("claude-sonnet-5", claude=FakeClient(BAD, BAD))).plan(
        job_row(store, filters), "Acme", ROLES, SKILLS, HEADLINES, PROFILE)
    assert plan.bullets["R1"] == list(R1.values())  # R1.1 in its own words, then the ones the answer left out
    assert any("Overruled" in n and "kubernetes" in n for n in plan.notes)


def test_deepseek_answers_through_the_same_check(filters):
    import httpx

    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(GOOD)}}],
                                         "usage": {"prompt_tokens": 3000, "completion_tokens": 600}})

    store = JobStore(":memory:")
    model = JsonModel("deepseek-v4-pro", deepseek_key="ds", http=httpx.Client(transport=httpx.MockTransport(handler)))
    plan, usage, _ = CvWriter(model).plan(job_row(store, filters), "Acme", ROLES, SKILLS, HEADLINES, PROFILE)
    assert plan.headline == "Backend Engineer - Python & AWS" and usage.cost("deepseek-v4-pro") > 0
    assert seen[0]["response_format"] == {"type": "json_object"} and '"headline"' in seen[0]["messages"][0]["content"]


# --- the whole step, with build.py faked ----------------------------------------------------


@pytest.fixture
def resume(tmp_path):
    folder = tmp_path / "resume"
    (folder / "output").mkdir(parents=True)
    shutil.copy(FIXTURES / "resume.md", folder / "resume.md")
    (folder / "build.py").write_text("# stands in for the real one\n")
    (folder / "output" / "Shoumar_Resume_General.pdf").write_bytes(b"%PDF")
    (folder / "applications.csv").write_text("Company,Role,Resume file,Created,Applied,Status,Notes\n")
    return folder


class FakeBuild:
    """Writes output/Shoumar_<name>.pdf like build.py; `pages` are the page counts it reports, in order."""

    def __init__(self, *pages):
        self.pages = list(pages)
        self.sources = []

    def __call__(self, folder, source):
        self.sources.append(source.read_text())
        pdf = folder / "output" / f"Shoumar_{source.stem}.pdf"
        pdf.write_bytes(b"%PDF")
        return pdf, self.pages.pop(0) if self.pages else 1


def config_for(folder, **overrides):
    return OutreachConfig(resume_dir=str(folder), cv_dir=str(folder / "output"), **overrides)


def writer(*answers):
    return CvWriter(JsonModel("claude-sonnet-5", claude=FakeClient(*answers)))


def test_tailoring_writes_the_version_builds_it_and_attaches_it(resume, filters):
    store = JobStore(":memory:")
    job_id = store_job(store, filters, description="We build serverless Python on AWS. Kafka is a plus.")
    build = FakeBuild(2, 1)
    meta = tailor_for_job(store, job_id, writer(GOOD), PROFILE_FILE, config_for(resume), NOW, builder=build)
    assert meta["file"] == "Shoumar_Backend_Acme_Sep2026.pdf" and meta["source"] == "versions/Backend_Acme_Sep2026.md"
    assert meta["pages"] == 1 and "compact: yes" in build.sources[1] and "compact: yes" not in build.sources[0]
    assert meta["gaps"] == ["kafka"] and meta["headline"] == "Backend Engineer - Python & AWS"
    assert meta["tags"] == {} and meta["titles"] == {"R1": "Algorithmic Trader"}
    assert meta["changes"][0].startswith("Core bullets only") and meta["changes"][1:] == GOOD["changes"]
    assert "Present\nAlgorithmic Trader\n- " in build.sources[1] and f"// [lead] - {R1[6]}" in build.sources[1]
    app = tracking.get_application(store, job_id)
    assert app["cv_file"] == meta["file"] and app["stage"] == tracking.NEW
    assert (resume / "versions" / "Backend_Acme_Sep2026.md").read_text() == build.sources[1]
    rows = list(csv.reader((resume / "applications.csv").open()))
    assert rows[1][:3] == ["Acme", "Senior Backend Engineer (Python)", "output/Shoumar_Backend_Acme_Sep2026.pdf"]

    again = tailor_for_job(store, job_id, writer(GOOD), PROFILE_FILE, config_for(resume), NOW, builder=FakeBuild())
    assert again["file"] == meta["file"] and len(list(csv.reader((resume / "applications.csv").open()))) == 2
    assert [e["detail"] for e in tracking.events_for(store, job_id)][-1].endswith("(again)")


def test_a_cv_that_spills_loses_optional_bullets_never_core_ones(resume, filters):
    store = JobStore(":memory:")
    job_id = store_job(store, filters, title="Engineering Manager")  # a lead job: two optional bullets print
    build = FakeBuild(2, 2, 1)  # two pages, still two in compact, then one
    meta = tailor_for_job(store, job_id, writer(GOOD), PROFILE_FILE, config_for(resume), NOW, builder=build)
    assert meta["tags"] == {"lead": 'the title says "manager"'} and meta["titles"] == {"R1": "Team Lead"}
    assert meta["pages"] == 1 and len(build.sources) == 3
    final = build.sources[-1]
    assert f"- {R1[6]}\n// - {R1[7]}" in final  # the last optional bullet went, the other stayed
    assert all(f"- {R1[n]}" in final for n in (3, 5)) and "Present\nTeam Lead\n" in final
    assert any(n.startswith("Cut to fit one page") for n in meta["notes"])


def test_a_cv_made_by_hand_is_never_overwritten(resume, filters):
    (resume / "versions").mkdir()
    (resume / "versions" / "Backend_Acme_Sep2026.md").write_text("by hand")
    store = JobStore(":memory:")
    meta = tailor_for_job(store, store_job(store, filters), writer(GOOD), PROFILE_FILE, config_for(resume), NOW,
                          builder=FakeBuild())
    assert meta["file"] == "Shoumar_Backend_Acme_Sep2026_2.pdf"
    assert (resume / "versions" / "Backend_Acme_Sep2026.md").read_text() == "by hand"


def test_the_daily_run_keeps_a_cv_you_picked(resume, filters):
    store = JobStore(":memory:")
    job_id = store_job(store, filters)
    tracking.ensure_application(store, job_id, NOW)
    store.conn.execute("UPDATE applications SET cv_file = 'Shoumar_Resume_General.pdf' WHERE job_id = ?", (job_id,))
    tailor_for_job(store, job_id, writer(GOOD), PROFILE_FILE, config_for(resume), NOW, builder=FakeBuild(), pick=False)
    assert tracking.get_application(store, job_id)["cv_file"] == "Shoumar_Resume_General.pdf"


def test_the_daily_run_tailors_new_shortlisted_jobs(resume, filters, tmp_path, monkeypatch):
    from jobhunter import cv, outreach

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "outreach.json").write_text(json.dumps(
        {"resume_dir": str(resume), "cv_dir": str(resume / "output"), "auto_lookup": False}))
    shutil.copytree(FIXTURES / "profile", tmp_path / "profile")
    monkeypatch.setattr(outreach, "build_cv_writer", lambda config: (writer(GOOD), None))
    monkeypatch.setattr(cv, "build_pdf", FakeBuild())
    store = JobStore(":memory:")
    job_id = store_job(store, filters)
    summary = outreach.run_outreach(store, Paths(tmp_path), [job_id], NOW)
    assert summary["cvs"] == [f"#{job_id}: Shoumar_Backend_Acme_Sep2026.pdf"] and summary["errors"] == []
    assert outreach.run_outreach(store, Paths(tmp_path), [job_id], NOW)["cvs"] == []  # once per job
    other = store_job(store, filters, source_job_id="2", company="Globex")
    assert outreach.run_outreach(store, Paths(tmp_path), [other], NOW, lookups=False)["cvs"] == []  # a date range


# --- the web app -----------------------------------------------------------------------------


class CvServices(FakeServices):
    def __init__(self, config):
        super().__init__(config)
        self.build = FakeBuild()

    def cv_writer(self):
        return writer(GOOD), None

    def build_pdf(self, folder, source):
        return self.build(folder, source)


@pytest.fixture
def cv_client(tmp_path, resume, filters):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    shutil.copytree(FIXTURES / "profile", tmp_path / "profile")
    settings = json.loads((tmp_path / "config" / "outreach.json").read_text())
    settings.update(resume_dir=str(resume), cv_dir=str(resume / "output"), default_cv="Shoumar_Resume_General.pdf")
    (tmp_path / "config" / "outreach.json").write_text(json.dumps(settings))
    store = JobStore(tmp_path / "data" / "jobs.sqlite")
    store_job(store, filters)
    store.close()
    paths = Paths(tmp_path)
    app = create_app(paths, TOKEN, allowed_hosts=["testserver"],
                     services=CvServices(OutreachConfig.load(paths.outreach_file)), now=lambda: NOW)
    return TestClient(app)


def test_tailor_attaches_the_cv_and_the_page_can_show_it(cv_client):
    assert cv_client.get("/api/jobs/1").json()["cv"]["file"] == "Shoumar_Resume_General.pdf"
    assert cv_client.post("/api/jobs/1/tailor", json={}).status_code == 403  # needs the token
    detail = cv_client.post("/api/jobs/1/tailor", json={}, headers=AUTH).json()
    assert detail["cv"]["file"] == "Shoumar_Backend_Acme_Sep2026.pdf" == detail["tailored"]["file"]
    assert detail["cv"]["tailored"]["changes"][1:] == GOOD["changes"]
    pdf = cv_client.get("/api/cv/Shoumar_Backend_Acme_Sep2026.pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-disposition"].startswith("inline")


def test_only_cvs_in_the_folder_can_be_read(cv_client):
    assert cv_client.get("/api/cv/resume.md").status_code == 404
    assert cv_client.get("/api/cv/..%2Fresume.md").status_code == 404


# --- your edits ------------------------------------------------------------------------------


def test_check_version_points_at_lines_that_say_more_than_the_profile():
    text = "\n".join([
        "## Professional Experience", "### CoinQuant, Abu Dhabi | Sept 2025 - Present", "Algorithmic Trader",
        f"- {R1[1]}",
        "- Architected a serverless platform on AWS Lambda and Kubernetes that runs 1000+ concurrent Python jobs.",
        "- Mentored interns on quantum computing research.",
        "// - Wrote the Rust matching engine.",  # hidden: never prints, so never checked
        "## Skills", "Languages: Python, SQL, Rust",
    ])
    checks = check_version(text, PROFILE_FILE)
    assert len(checks) == 3, checks
    assert '"1000+ concurrent" is not in your profile' in checks[0] and '"kubernetes"' in checks[0]
    assert checks[1].endswith("matches no bullet in your profile")
    assert checks[2] == "Languages: Rust not in your profile's skills"


def test_you_can_edit_a_tailored_cv_and_rebuild_it_without_the_model(resume, filters):
    store = JobStore(":memory:")
    job_id = store_job(store, filters)
    config = config_for(resume)
    meta = tailor_for_job(store, job_id, writer(GOOD), PROFILE_FILE, config, NOW, builder=FakeBuild())
    source = resume / meta["source"]
    original = source.read_text()
    edited = original.replace("- Designed a slippage model", "// - Designed a slippage model")
    assert edited != original
    build, later = FakeBuild(), NOW + timedelta(hours=1)
    result = save_version(store, job_id, config, PROFILE_FILE, later, edited, builder=build)
    assert result["source"] == meta["source"] and result["file"] == meta["file"] and result["pages"] == 1
    assert source.read_text() == edited == build.sources[0]  # what you saved is what was built
    assert source.with_suffix(".md.bak").read_text() == original  # one step back
    assert tailored_of(tracking.get_application(store, job_id))["edited_at"] == iso(later)
    assert [e["detail"] for e in tracking.events_for(store, job_id)][-1] == f"CV edited by you: {meta['file']}"

    with pytest.raises(TailorError, match="You edited this CV"):  # tailoring again asks first
        tailor_for_job(store, job_id, writer(GOOD), PROFILE_FILE, config, NOW, builder=FakeBuild())
    again = tailor_for_job(store, job_id, writer(GOOD), PROFILE_FILE, config, NOW, builder=FakeBuild(),
                           replace_edits=True)
    assert again["file"] == meta["file"] and "edited_at" not in again


def test_a_cv_made_by_hand_can_be_edited_but_not_the_general_one(resume, filters):
    store = JobStore(":memory:")
    job_id = store_job(store, filters, company="Clera")
    config = config_for(resume)
    with pytest.raises(TailorError, match="general CV"):
        save_version(store, job_id, config, PROFILE_FILE, NOW, "# Me\n", builder=FakeBuild())
    (resume / "versions").mkdir()
    (resume / "versions" / "Backend_Clera_Sep2026.md").write_text("# Me\n- a line you want gone\n")
    (resume / "output" / "Shoumar_Backend_Clera_Sep2026.pdf").write_bytes(b"%PDF")  # build.py made it from that file
    result = save_version(store, job_id, config, PROFILE_FILE, NOW, "# Me\n", builder=FakeBuild())
    assert result["source"] == "versions/Backend_Clera_Sep2026.md" and result["file"] == "Shoumar_Backend_Clera_Sep2026.pdf"
    assert (resume / "versions" / "Backend_Clera_Sep2026.md").read_text() == "# Me\n"
    with pytest.raises(TailorError, match="empty"):
        save_version(store, job_id, config, PROFILE_FILE, NOW, "  \n", builder=FakeBuild())


def test_only_files_in_versions_can_be_edited(resume, filters):
    store = JobStore(":memory:")
    job_id = store_job(store, filters, company="Nobody")
    tracking.ensure_application(store, job_id, NOW)
    for source in ("../resume.md", "versions/../resume.md", "resume.md"):
        store.conn.execute("UPDATE applications SET cv_tailored_json = ? WHERE job_id = ?",
                           (json.dumps({"source": source}), job_id))
        assert version_of(config_for(resume), "Nobody", tracking.get_application(store, job_id)) is None


def test_the_cv_text_can_be_edited_in_the_app(cv_client):
    assert cv_client.get("/api/jobs/1/cv-text").status_code == 404  # the general CV
    cv_client.post("/api/jobs/1/tailor", json={}, headers=AUTH)
    assert cv_client.get("/api/jobs/1").json()["cv"]["source"] == "Backend_Acme_Sep2026.md"
    opened = cv_client.get("/api/jobs/1/cv-text").json()
    assert opened["source"] == "versions/Backend_Acme_Sep2026.md" and isinstance(opened["checks"], list)
    text = opened["text"].replace("- Designed a slippage model", "// - Designed a slippage model")
    assert cv_client.put("/api/jobs/1/cv-text", json={"text": text}).status_code == 403  # needs the token
    assert cv_client.put("/api/jobs/1/cv-text", json={}, headers=AUTH).status_code == 400
    saved = cv_client.put("/api/jobs/1/cv-text", json={"text": text}, headers=AUTH).json()
    assert saved["cv_saved"]["file"] == "Shoumar_Backend_Acme_Sep2026.pdf" and saved["cv"]["tailored"]["edited_at"]
    assert cv_client.get("/api/jobs/1/cv-text").json()["text"] == text
    assert cv_client.post("/api/jobs/1/tailor", json={}, headers=AUTH).status_code == 400  # asks before replacing
    assert cv_client.post("/api/jobs/1/tailor", json={"replace_edits": True}, headers=AUTH).status_code == 200
