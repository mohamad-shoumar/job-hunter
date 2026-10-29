"""`jobhunter <command>` on a project folder in tmp_path: what it reads, prints and writes.
(`run` is tested through pipeline.py, `serve` through the web app.)"""

import json
import shutil

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
