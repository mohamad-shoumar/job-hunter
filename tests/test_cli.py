"""`jobhunter <command>` on a project folder in tmp_path: what it reads, prints and writes.
(`run` is tested through pipeline.py, `serve` through the web app.)"""

import json
import shutil
from datetime import timedelta

import pytest

from jobhunter import cli
from jobhunter.store import JobStore

from .conftest import FIXTURES, NOW, copy_config, store_job

DAY = "2026-09-25"  # NOW's day, the report the jobs are filed under


@pytest.fixture
def home(tmp_path, filters, monkeypatch):
    """A project folder with no .env: a shortlisted job, one cleared from the old review list (2026-10-29) and a
    rejected one, filed under DAY."""
    monkeypatch.setattr(cli, "utcnow", lambda: NOW)  # ages are judged on NOW, not on the day the tests run
    copy_config(tmp_path)
    shutil.copytree(FIXTURES / "profile", tmp_path / "profile")
    store = JobStore(tmp_path / "data" / "jobs.sqlite")
    ids = [
        store_job(store, filters),  # #1 Acme, open worldwide: shortlisted
        store_job(store, filters, status="rejected", reject_code="review_cleared", source_job_id="2",
                  company="Initech", title="Backend Engineer", allowed_locations=[]),  # #2 cleared, would be shortlisted
        store_job(store, filters, source_job_id="3", company="Globex", title="Sales Manager"),  # #3 rejected
    ]
    store.set_report_date(ids, DAY)
    store.commit()
    store.close()
    return tmp_path


def jobhunter(home, *argv) -> int:
    return cli.main(["--home", str(home), *argv])


def stored(home, job_id):
    store = JobStore(home / "data" / "jobs.sqlite")
    try:
        return store.get(job_id)
    finally:
        store.close()


def test_stats_counts_jobs_by_status_and_source(home, capsys):
    assert jobhunter(home, "stats") == 0
    out, err = capsys.readouterr()
    assert json.loads(out) == {"jobs_by_status": {"shortlisted": 1, "rejected": 2},
                               "sightings_by_source": {"test": 3}, "runs": 0}
    assert err == ""


def test_show_says_why_a_job_got_its_status(home, capsys):
    assert jobhunter(home, "show", "3") == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[:2] == ["#3  Sales Manager — Globex", 'status: rejected  (Title contains "manager")']
    assert '  - Title contains "manager"' in lines
    assert "We build APIs with Python, FastAPI and PostgreSQL on AWS." not in lines
    assert jobhunter(home, "show", "3", "--description") == 0
    assert capsys.readouterr().out.endswith("\nWe build APIs with Python, FastAPI and PostgreSQL on AWS.\n")


def test_show_an_unknown_job(home, capsys):
    assert jobhunter(home, "show", "99") == 1
    assert capsys.readouterr().err == "no job #99\n"


def test_linkedin_sets_the_person_and_the_note_for_a_job(home, capsys):
    """What the apply-job skill fills in after it finds the one person (the user's call, 2026-11-05)."""
    note = "Hi Ana, I just applied for the Backend Engineer role. I lead a backend team of 3 engineers."
    assert jobhunter(home, "linkedin", "1", "--url", "www.linkedin.com/in/ana-ruiz", "--note", note) == 0
    out = capsys.readouterr().out
    assert "LinkedIn: https://www.linkedin.com/in/ana-ruiz" in out and f"Note ({len(note)} characters): {note}" in out
    # With nothing to set it only shows what the job has.
    assert jobhunter(home, "linkedin", "1") == 0
    assert "https://www.linkedin.com/in/ana-ruiz" in capsys.readouterr().out
    # A note over LinkedIn's limit is stored, and says so.
    assert jobhunter(home, "linkedin", "1", "--note", "x" * 301) == 0
    assert "Note (301 characters, over the 300 LinkedIn allows)" in capsys.readouterr().out


def test_linkedin_records_the_followup_and_backfills_the_dates(home, capsys):
    """The step that was missing (the user's call, 2026-11-07): apply-job writes the follow-up with
    --followup, and --accepted-at backfills an invite that was accepted days ago."""
    assert jobhunter(home, "linkedin", "1", "--followup", "  Hi Ana, is the role still open?  ",
                     "--sent-at", "2026-11-01", "--accepted-at", "2026-11-02") == 0
    out = capsys.readouterr().out
    assert "Follow-up: Hi Ana, is the role still open?" in out
    assert "sent=2026-11-01" in out and "accepted=2026-11-02" in out and "replied=-" in out
    # An empty string clears one step; the follow-up and the other steps stay.
    assert jobhunter(home, "linkedin", "1", "--accepted-at", "") == 0
    out = capsys.readouterr().out
    assert "accepted=-" in out and "sent=2026-11-01" in out and "Hi Ana, is the role still open?" in out
    assert jobhunter(home, "linkedin", "1", "--replied-at", "whenever") == 1
    assert "--replied-at: not a date: whenever" in capsys.readouterr().err


def test_linkedin_refuses_a_link_that_is_not_linkedin(home, capsys):
    assert jobhunter(home, "linkedin", "1", "--url", "https://example.com/in/ana") == 1
    assert "not a LinkedIn link" in capsys.readouterr().err
    assert jobhunter(home, "linkedin", "99", "--url", "linkedin.com/in/ana") == 1
    assert capsys.readouterr().err == "no job #99\n"


def test_report_rebuilds_one_day_s_file(home, capsys):
    assert jobhunter(home, "report", "--date", DAY) == 0
    path = home / "reports" / f"{DAY}.md"
    assert capsys.readouterr().out == f"{path}   1 shortlisted, 0 on the visa list, 2 rejected\n"
    text = path.read_text()
    assert "## Shortlisted (1)" in text and "### 1. Senior Backend Engineer (Python) — Acme" in text
    assert "Needs review" not in text and "### Cleared from the old review list (1)" in text
    assert "| 3 | [Sales Manager](https://example.com/jobs/1) | Globex | Title contains \"manager\" |" in text


def test_reclassify_applies_an_edited_filter_and_rebuilds_that_day_s_report(home, capsys):
    assert jobhunter(home, "reclassify") == 0
    assert capsys.readouterr().out.startswith("no changes\n")
    assert not (home / "reports").exists()  # nothing changed, so no report was touched

    filters_file = home / "config" / "filters.json"
    settings = json.loads(filters_file.read_text())
    settings["blocked_companies"].append({"name": "Acme", "why": "never again"})
    settings["blocked_companies"].append({"name": "Initech", "why": "left for review"})
    filters_file.write_text(json.dumps(settings))
    assert jobhunter(home, "reclassify") == 0
    path = home / "reports" / f"{DAY}.md"
    out = capsys.readouterr().out.splitlines()
    assert out[:2] == ["    1  shortlisted -> rejected", f"rebuilt {path}"]
    job = stored(home, 1)
    assert (job["status"], job["reject_code"]) == ("rejected", "blocked_company")
    job = stored(home, 2)  # cleared from the old review list (2026-10-29): never judged again
    assert (job["status"], job["reject_code"]) == ("rejected", "review_cleared")
    text = path.read_text()
    assert "## Shortlisted (0)" in text and "never again" in text


def test_reclassify_folds_a_second_copy_of_a_role_and_then_leaves_it_alone(home, capsys, filters):
    """The rules give a copy rejected `duplicate_role` its own status back, and the fold pass takes
    it away again: the second run must report nothing and rebuild nothing (duplicates.py)."""
    store = JobStore(home / "data" / "jobs.sqlite")
    # Same company and title as #1, and the same place (neither names one), but its own posting.
    copy = store_job(store, filters, source_job_id="4", posted_at=NOW - timedelta(days=4),
                     application_url="https://job-boards.greenhouse.io/acme/jobs/4")
    store.set_report_date([copy], DAY)
    store.commit()
    store.close()

    assert jobhunter(home, "reclassify") == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "    1  duplicate copies rejected"
    assert out[1].endswith('at Acme, no location given, posted 2026-09-25 (the newest posting of this role)')
    assert stored(home, copy)["reject_code"] == "duplicate_role"  # #1 is the newer posting
    assert stored(home, 1)["status"] == "shortlisted"

    assert jobhunter(home, "reclassify") == 0
    assert capsys.readouterr().out.startswith("no changes\n")
    assert stored(home, copy)["reject_code"] == "duplicate_role"


def test_sources_lists_what_is_on_and_why_the_rest_is_not(home, capsys):
    (home / "config" / "sources.json").write_text(json.dumps({
        "_about": "a note, not a source",
        "remoteok": {"enabled": True},
        "nodesk": {"enabled": False},
        "hiringcafe": {"enabled": True},
        "remotok": {"enabled": True},
    }))
    assert jobhunter(home, "sources") == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "enabled   remoteok" and len(lines) == 3
    assert lines[1].startswith("skipped   hiringcafe: not implemented")
    assert lines[2].startswith("skipped   remotok: unknown")


def test_a_folder_with_no_config_is_refused(tmp_path):
    with pytest.raises(SystemExit) as stop:
        cli.main(["--home", str(tmp_path), "stats"])
    assert str(stop.value).startswith(f"no config at {tmp_path.resolve() / 'config' / 'sources.json'}")


def test_a_project_with_no_profile_yet_still_runs_and_says_how_to_start(home, capsys):
    shutil.rmtree(home / "profile")
    assert jobhunter(home, "stats") == 0
    assert "copy profile/master_profile.example.md there" in capsys.readouterr().err


def test_grade_rescore_updates_the_salary_part_with_no_model(home, capsys, monkeypatch):
    """After FIT_SALARY_FLOORS changes, `grade --rescore` scores again from the stored answer: no model call."""
    import json

    store = JobStore(home / "data" / "jobs.sqlite")
    store.conn.execute("UPDATE jobs SET salary_min = 3000, salary_max = 4000, salary_currency = 'USD', "
                       "salary_period = 'month', salary_raw = '$3,000 - $4,000 a month' WHERE id = 1")
    answer = {"seniority": "mid", "required_skills": [], "domain": "direct", "domain_why": "", "benefits_quote": "",
              "equity_quote": "", "interview": {"live_coding": "unknown", "rounds": None, "quote": ""}, "reason": "x"}
    store.save_fit_grade(1, {"score": 0, "parts": {}, "reason": "x", "answer": answer, "model": "m", "at": "x"})
    store.commit()
    store.close()
    monkeypatch.setenv("FIT_SALARY_FLOORS", "default=30000 USD")  # made up
    assert jobhunter(home, "grade", "--rescore", "1") == 0
    grade = json.loads(stored(home, 1)["fit_grade_json"])
    assert grade["parts"]["salary"][0] == 7 and grade["score"] == sum(p for p, _ in grade["parts"].values())
    assert "1 scored jobs looked at again" in capsys.readouterr().out


def test_timing_marks_steps_and_reports_minutes_with_company_names(home, capsys, monkeypatch):
    clock = iter(NOW + timedelta(minutes=m) for m in (0, 0, 3, 8, 12, 15))
    monkeypatch.setattr(cli, "utcnow", lambda: next(clock))
    assert jobhunter(home, "timing", "start") == 0
    assert jobhunter(home, "timing", "mark", "1", "posting") == 0
    assert jobhunter(home, "timing", "mark", "1", "form") == 0
    assert jobhunter(home, "timing", "snag", "1", "Upload button did nothing", "--fix", "use the stand-in box") == 0
    assert jobhunter(home, "timing", "mark", "-", "report") == 0
    capsys.readouterr()
    assert jobhunter(home, "timing", "report") == 0
    out = capsys.readouterr().out
    assert "15.0 min of work for 1 job: 1 form filled. Snags cost 4.0 min." in out
    assert "| #1 Acme | 12.0 | form filled |" in out
    assert "- #1 Acme, 4.0 min: Upload button did nothing. Fix: use the stand-in box" in out
    assert (home / "data" / "apply_timing.jsonl").exists()


def test_timing_mirror_scores_the_jobs_cv_and_the_report_counts_the_apps_skips(home, capsys, monkeypatch):
    from jobhunter.store.applications import save_tailored_cv
    from jobhunter.tracking import ensure_application, set_stage

    version = home / "resume" / "versions" / "Backend_Acme_Sep2026.md"
    version.parent.mkdir(parents=True)
    version.write_text("title: Backend Engineer\n\n## Professional Experience\n\n### Acme | 2025 - Present\n"
                       "- Built Python APIs.\n\n## Skills\nTools: Docker, Git, Datadog, Grafana, PostgreSQL\n")
    store = JobStore(home / "data" / "jobs.sqlite")
    ensure_application(store, 1, NOW)
    save_tailored_cv(store, 1, {"source": "versions/Backend_Acme_Sep2026.md"}, NOW)
    set_stage(store, 2, "closed", NOW + timedelta(minutes=3), reason="skipped", skip_reason="wrong_stack")
    store.commit()
    store.close()
    clock = iter(NOW + timedelta(minutes=m) for m in (0, 0, 1, 2, 2, 4, 5, 6))
    monkeypatch.setattr(cli, "utcnow", lambda: next(clock))
    assert jobhunter(home, "timing", "mirror", "1", "before", "--must", "Python; PostgreSQL; Rust") == 0
    assert "no apply-job run open: shown, not recorded" in capsys.readouterr().out
    assert jobhunter(home, "timing", "mark", "1", "mirror") == 0
    assert jobhunter(home, "timing", "mirror", "1", "before", "--must", "Python; PostgreSQL; Rust") == 0
    out = capsys.readouterr().out
    assert "#1 before: 1 of 3 must-haves in the top part, 2 on the CV" in out
    assert "  PostgreSQL: on the CV" in out and "  Rust: not on the CV" in out
    version.write_text(version.read_text().replace("Tools: Docker, Git, Datadog, Grafana, PostgreSQL",
                                                   "Tools: PostgreSQL, Docker, Git, Datadog, Grafana"))
    assert jobhunter(home, "timing", "mirror", "1", "after", "--must", "Python; PostgreSQL; Rust") == 0
    assert jobhunter(home, "timing", "mark", "1", "form", "--site", "https://jobs.lever.co/acme/1") == 0
    assert "#1 form (Lever)" in capsys.readouterr().out
    assert jobhunter(home, "timing", "mark", "-", "report") == 0
    capsys.readouterr()
    assert jobhunter(home, "timing", "report") == 0
    out = capsys.readouterr().out
    assert "for 2 jobs: 1 form filled, 1 skipped (0 timed)." in out
    assert "| Wrong stack | 1 | Initech |" in out
    assert "| #1 Acme | 3 | 1 | 2 | Rust |" in out
    assert "| Lever | 1 | 2.0 |" in out
    assert "**Cost**" not in out  # no session log in a test
    assert jobhunter(home, "timing", "mirror", "3", "after", "--must", "Python") == 1
    assert "no tailored CV" in capsys.readouterr().err


def test_timing_refuses_an_unknown_step(home, capsys):
    assert jobhunter(home, "timing", "mark", "1", "apply") == 1
    assert "unknown step" in capsys.readouterr().err
