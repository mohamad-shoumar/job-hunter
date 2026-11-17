"""The daily digest: code picks the day's top jobs (one per company, by fit score), the model writes one idea
each, code drops an idea it cannot check, and a re-run adds nothing. A fake model; no real model calls."""

import json

import pytest

from jobhunter import cli, pipeline
from jobhunter.config import Paths
from jobhunter.digest import DigestConfig, IdeaWriter, check_idea, pick_jobs, run_digest, skills_text
from jobhunter.models import REACHED_OUT, REJECTED, SAVED, SHORTLISTED, VISA_LIST
from jobhunter.store import JobStore
from jobhunter.store.applications import insert_application
from jobhunter.store.lists import digest_candidates

from .conftest import FIXTURES, NOW, copy_config, store_job

PROFILE = FIXTURES / "profile" / "master_profile.md"
DAY = "2026-09-25"
POSTING = ("We are a payments team. Our merchants need to reconcile payment events from several providers every "
           "night. You will build services in Python with FastAPI and PostgreSQL, and work with Kafka.")


def idea(**changes) -> dict:
    base = {"problem": "Payment events from several providers disagree.",
            "quote": "reconcile payment events from several providers",
            "title": "Payment event reconciler",
            "does": ["Reads sample events from two made-up providers.", "Flags the ones that disagree.",
                     "Serves the result as a small JSON API."],
            "stack": ["Python", "FastAPI", "Kafka", "Rust"],
            "shows": "That the payments matching problem can be turned into a tested service in their stack.",
            "hours": 6, "limits": "Made-up sample data only."}
    return {**base, **changes}


class FakeModel:
    """Answers each call from a function of the message, and keeps the messages."""

    def __init__(self, reply=lambda message: idea()):
        self.reply = reply
        self.messages: list[str] = []

    def ask(self, system, messages, schema, usage, example, max_tokens=4096):
        message = messages[0]["content"]
        self.messages.append(message)
        usage.add({"input_tokens": 2000, "output_tokens": 300})
        answer = self.reply(message)
        if isinstance(answer, Exception):
            raise answer
        return answer


def writer(model) -> IdeaWriter:
    return IdeaWriter(DigestConfig(model="deepseek-v4-flash", workers=1), model)


def add(store, filters, n, company, score, status=SHORTLISTED, day=DAY, stage=None, title="Backend Engineer",
        description=POSTING, grade=None) -> int:
    job_id = store_job(store, filters, status=status, source_job_id=str(n), company=company, title=title,
                       description=description)
    store.set_report_date([job_id], day)
    if grade is not None or score is not None:
        store.save_fit_grade(job_id, grade if grade is not None else {"score": score, "parts": {}})
    if stage:
        insert_application(store, job_id, stage, NOW)
    return job_id


@pytest.fixture
def store(filters):
    store = JobStore(":memory:")
    add(store, filters, 1, "Acme", 80)                                   # picked first
    add(store, filters, 2, "acme ", 85, stage=REACHED_OUT)               # you acted on it: not New
    add(store, filters, 3, "Acme", 70, title="Platform Engineer")        # Acme's second job: one per company
    add(store, filters, 4, "Globex", 65)                                 # picked
    add(store, filters, 5, "Wayne", 62, status=VISA_LIST)                # visa list counts
    add(store, filters, 6, "Initech", 55)                                # below 60
    add(store, filters, 7, "Hooli", 95, status=REJECTED)                 # rejected
    add(store, filters, 8, "Stark", 90, day="2026-09-24")                # another day
    add(store, filters, 9, "Umbrella", 88, stage=SAVED)                  # saved is not New
    add(store, filters, 10, "Soylent", None)                             # no score yet
    add(store, filters, 11, "Tyrell", None, grade={"grade": 5})          # an old 1-5 grade reads as no score
    store.commit()
    return store


def test_picks_the_days_best_new_job_of_each_company_that_scores_well(store):
    rows = digest_candidates(store, DAY)
    assert {r["id"] for r in rows} == {1, 3, 4, 5, 6, 10, 11}
    picks = pick_jobs(rows, top=5, min_score=60)
    assert [(p.row["id"], p.score) for p in picks] == [(1, 80), (4, 65), (5, 62)]
    assert picks[0].others == 1  # Acme's Platform Engineer
    assert [p.row["id"] for p in pick_jobs(rows, top=2, min_score=60)] == [1, 4]
    assert len(pick_jobs(rows, top=50, min_score=0)) == 4  # at most 5, and one per company (Acme, Globex, Wayne, Initech)


def test_an_idea_with_a_made_up_quote_is_dropped_and_the_job_stays_listed(store, tmp_path):
    def reply(message):
        if "Company: Globex" in message:
            return idea(quote="we are drowning in unreconciled ledgers every single day")
        return idea()

    model = FakeModel(reply)
    run = run_digest(store, writer(model), DigestConfig(), PROFILE, tmp_path, DAY, NOW)
    assert [p.row["id"] for p in run.picks] == [1, 4, 5] and run.asked == 3 and run.added == 2
    globex = run.picks[1]
    assert globex.idea is None and globex.project_id is None and "quote is not in the posting" in globex.note
    rows = store.conn.execute("SELECT job_id, status, title, stack, idea_json FROM projects ORDER BY id").fetchall()
    assert [(r["job_id"], r["status"]) for r in rows] == [(1, "suggested"), (5, "suggested")]
    saved = json.loads(rows[0]["idea_json"])
    assert saved["digest_date"] == DAY and saved["rank"] == 1 and saved["score"] == 80
    # Rust is in neither the posting nor the skills: removed. Kafka is in the posting, not the skills: new to you.
    assert saved["stack"] == [{"name": "Python", "yours": True, "in_posting": True},
                              {"name": "FastAPI", "yours": True, "in_posting": True},
                              {"name": "Kafka", "yours": False, "in_posting": True}]
    assert saved["left_out"] == ["Rust"] and rows[0]["stack"] == "Python, FastAPI, Kafka"
    text = (tmp_path / f"digest_{DAY}.md").read_text()
    assert "Payment event reconciler" in text and "Kafka (new to you)" in text and "Rust" not in text
    assert "quote is not in the posting" in text and "2 of them have no fit score yet" in text


def test_running_a_day_again_asks_nothing_and_adds_no_rows(store, tmp_path):
    run_digest(store, writer(FakeModel()), DigestConfig(), PROFILE, tmp_path, DAY, NOW)
    count = store.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    again = FakeModel()
    run = run_digest(store, writer(again), DigestConfig(), PROFILE, tmp_path, DAY, NOW)
    assert again.messages == [] and run.added == 0 and run.asked == 0
    assert store.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == count == 3
    assert all(p.idea and "from an earlier run" in p.note for p in run.picks)


def test_a_second_digest_the_same_day_shows_at_most_five_best_first(store, filters, tmp_path):
    from jobhunter.store.projects import digest_projects

    run_digest(store, writer(FakeModel()), DigestConfig(), PROFILE, tmp_path, DAY, NOW)
    for n, company in enumerate(["Cyberdyne", "Oscorp", "Aperture"], 20):  # scored after the first digest
        add(store, filters, n, company, 90 - n)
    store.commit()
    run_digest(store, writer(FakeModel()), DigestConfig(), PROFILE, tmp_path, DAY, NOW)
    assert store.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 6
    shown = digest_projects(store, DAY)
    assert [r["company"] for r in shown] == ["Acme", "Cyberdyne", "Oscorp", "Aperture", "Globex"]


def test_the_model_sees_the_posting_and_only_the_skills(store, tmp_path):
    model = FakeModel()
    run_digest(store, writer(model), DigestConfig(), PROFILE, tmp_path, DAY, NOW, top=1)
    [message] = model.messages
    skills = skills_text(PROFILE)
    assert skills and skills in message and "reconcile payment events" in message
    profile = PROFILE.read_text()
    experience = profile.split("## Experience")[1].split("\n## ")[0]
    bullets = [line[2:].strip() for line in experience.splitlines() if line.startswith("- ")]
    assert bullets and not any(b[:40] in message for b in bullets)
    assert "## Experience" not in message and "Education" not in message


@pytest.mark.parametrize("change, why", [
    ({"shows": "Builds on your experience with payment systems."}, "claims experience"),
    ({"problem": "I built this kind of thing before."}, "claims experience"),
    ({"does": ["Uses 5 years of experience in Kafka."]}, "claims experience"),
    ({"hours": 30}, "not buildable in a day"),
    ({"stack": ["Rust", "Haskell"]}, "none of its stack"),
    ({"title": ""}, "left out part"),
])
def test_ideas_code_cannot_check_are_dropped(store, change, why):
    kept, reason = check_idea(idea(**change), store.get(1), skills_text(PROFILE))
    assert kept is None and why in reason


def test_a_posting_that_names_no_tools_gets_a_stack_from_your_skills(filters):
    """Augustus's posting (2026-11-17) named no tools at all: the stack then comes from the Skills lines."""
    store = JobStore(":memory:")
    job_id = add(store, filters, 1, "Augustus", 85, description="Own clearing products for banks across accounts, "
                 "payments and treasury. Design the experience and the API, and build across the stack.")
    answer = idea(quote="Design the experience and the API", stack=["Python", "FastAPI", "Elixir"])
    kept, reason = check_idea(answer, store.get(job_id), skills_text(PROFILE))
    assert not reason and [s["name"] for s in kept["stack"]] == ["Python", "FastAPI"]
    assert not any(s["in_posting"] for s in kept["stack"]) and kept["left_out"] == ["Elixir"]


def test_words_about_the_team_are_not_claims(store):
    kept, reason = check_idea(idea(problem="Their checkout user experience in mobile needs I/O-heavy work."),
                              store.get(1), skills_text(PROFILE))
    assert kept and not reason


def test_a_failed_model_call_costs_only_its_job(store, tmp_path):
    model = FakeModel(lambda m: RuntimeError("claude -p timed out") if "Company: Acme" in m else idea())
    run = run_digest(store, writer(model), DigestConfig(), PROFILE, tmp_path, DAY, NOW)
    assert run.added == 2 and run.errors and "Acme" in run.errors[0]
    assert run.picks[0].idea is None and "model call failed" in run.picks[0].note


def test_no_scored_jobs_still_writes_the_file(filters, tmp_path):
    store = JobStore(":memory:")
    add(store, filters, 1, "Acme", None)
    run = run_digest(store, writer(FakeModel()), DigestConfig(), PROFILE, tmp_path, DAY, NOW)
    assert run.picks == [] and run.unscored == 1
    assert "No job scored well enough" in (tmp_path / f"digest_{DAY}.md").read_text()


@pytest.fixture
def home(tmp_path, filters, monkeypatch):
    monkeypatch.setattr(cli, "utcnow", lambda: NOW)
    copy_config(tmp_path)
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "master_profile.md").write_text(PROFILE.read_text())
    store = JobStore(tmp_path / "data" / "jobs.sqlite")
    add(store, filters, 1, "Acme", 80)
    store.commit()
    store.close()
    return tmp_path


def test_the_command_lists_the_picks_without_a_model(home, capsys):
    # Tests have no Claude Code CLI: the picks are listed and the file written, with no ideas and no rows.
    assert cli.main(["--home", str(home), "digest", "--date", DAY]) == 0
    out = capsys.readouterr().out
    assert "1 of 1 open jobs picked" in out and "Acme" in out and "Claude Code CLI" in out
    assert (home / "reports" / f"digest_{DAY}.md").exists()
    store = JobStore(home / "data" / "jobs.sqlite")
    assert store.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0


def test_a_failing_digest_never_fails_the_run(home, monkeypatch, capsys):
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: (pipeline.RunSummary(run_id=1, started_at="x"), []))

    def broken(*args, **kwargs):
        raise RuntimeError("the digest broke")

    monkeypatch.setattr(cli, "_digest", broken)
    assert cli.main(["--home", str(home), "run", "--digest"]) == 0
    assert "Digest failed: the digest broke" in capsys.readouterr().out


def test_the_app_shows_the_latest_digest_and_never_writes(home):
    from fastapi.testclient import TestClient

    from jobhunter.config import OutreachConfig
    from jobhunter.web.app import create_app

    from .test_web import FakeServices

    paths = Paths(home)
    store = JobStore(paths.db_file)
    run_digest(store, writer(FakeModel()), DigestConfig(), paths.profile_file, paths.reports_dir, DAY, NOW)
    store.close()
    app = create_app(paths, "t", allowed_hosts=["testserver"],
                     services=FakeServices(OutreachConfig.load(paths.outreach_file)), now=lambda: NOW)
    data = TestClient(app).get("/api/digest").json()
    assert data["day"] == DAY == data["today"]
    [pick] = data["picks"]
    assert pick["job_id"] == 1 and pick["company"] == "Acme" and pick["stage"] == "new"
    assert pick["project_title"] == "Payment event reconciler" and pick["idea"]["quote"]
    store = JobStore(paths.db_file)
    assert store.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
