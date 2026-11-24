"""timing.py: the apply-job skill's step marks add up into minutes per job and step, with snags and notes."""

from datetime import datetime, timedelta, UTC

import pytest

from jobhunter import timing

T0 = datetime(2026, 11, 24, 17, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def test_a_step_lasts_until_the_next_mark_and_snag_time_counts_as_lost(tmp_path):
    log = tmp_path / "data" / "apply_timing.jsonl"
    timing.start(log, at(0))
    timing.mark(log, None, "setup", at(0))
    timing.mark(log, 7, "posting", at(2))
    timing.mark(log, 7, "form", at(5))
    timing.snag(log, 7, "Location box needs its suggestion clicked", "add it to the skill", at(9))
    timing.mark(log, 7, "form", at(13))
    timing.note(log, 7, "Guessed 1 year for LLM apps in production", at(14))
    timing.mark(log, None, "waiting", at(16))
    out = timing.report(timing.read(log), at(30), labels={7: "#7 Acme"})

    assert out.startswith("**This run** (2026-11-24 17:00-17:30 UTC): 16.0 min of work for 1 job: "
                          "1 form filled. Snags cost 4.0 min. Waiting on you: 14.0 min (not counted).")
    assert "| Filling the form | 11.0 | 69% |" in out  # biggest step first
    assert "| Checking the posting | 3.0 | 19% |" in out
    assert "| Setup | 2.0 | 12% |" in out
    assert out.index("Filling the form") < out.index("Checking the posting") < out.index("| Setup")
    assert "| #7 Acme | 14.0 | form filled |" in out
    assert "- #7 Acme, 4.0 min: Location box needs its suggestion clicked. Fix: add it to the skill" in out
    assert "- #7 Acme: Guessed 1 year for LLM apps in production" in out
    assert "Earlier runs" not in out  # only one run so far


def test_each_job_gets_a_result_and_skipped_jobs_share_one_row(tmp_path):
    log = tmp_path / "apply_timing.jsonl"
    timing.mark(log, 1, "posting", at(0))  # skipped
    timing.mark(log, 2, "posting", at(1))  # skipped
    timing.mark(log, 3, "posting", at(2))
    timing.mark(log, 3, "tailor", at(3))
    timing.mark(log, 3, "linkedin", at(5))  # a sign-in page: CV and contact, no form
    timing.mark(log, None, "report", at(8))
    out = timing.report(timing.read(log), at(9))
    assert "for 3 jobs: 1 needs your sign-in, 2 skipped." in out
    assert "| #3 | 6.0 | needs your sign-in |" in out
    assert "| 2 skipped jobs | 2.0 (1.0 each) | skipped |" in out
    assert "| #1 |" not in out


def test_a_mark_with_no_open_run_starts_one_and_old_runs_stop_at_their_last_line(tmp_path):
    log = tmp_path / "apply_timing.jsonl"
    first = timing.mark(log, 1, "posting", at(0))  # no `start`: begins a run anyway
    timing.mark(log, 1, "cv", at(10))
    later = at(60 * 24)  # the next day: the old run is closed, not stretched to now
    second = timing.mark(log, 2, "posting", later)
    assert first != second
    records = timing.read(log)
    old = timing.report(records, later + timedelta(minutes=5), run=first)
    assert "10.0 min of work for 1 job" in old  # the cv mark was its last line: 0 minutes, not a day
    assert "Checking the CV" not in old  # a step with no time gets no row
    new = timing.report(records, later + timedelta(minutes=5))
    assert "| 1 skipped job | 5.0 (5.0 each) | skipped |" in new
    assert "**Earlier runs**" in new and "| 2026-11-24 17:00 | 1 | 10.0 | 10.0 |" in new


def test_a_run_replaced_by_a_newer_one_the_same_day_is_not_stretched_to_now(tmp_path):
    log = tmp_path / "apply_timing.jsonl"
    morning = timing.start(log, at(0))
    timing.mark(log, 1, "posting", at(0))
    timing.mark(log, 1, "form", at(5))  # cut off here: never marked waiting
    timing.start(log, at(180))
    timing.mark(log, 2, "posting", at(180))
    records = timing.read(log)
    old = timing.report(records, at(190), run=morning)
    assert "(2026-11-24 17:00-17:05 UTC): 5.0 min of work" in old
    assert "| 2026-11-24 17:00 | 1 | 5.0 | 5.0 |" in timing.report(records, at(190))


def test_unknown_steps_and_runs_are_refused(tmp_path):
    log = tmp_path / "apply_timing.jsonl"
    with pytest.raises(ValueError, match="unknown step 'apply'"):
        timing.mark(log, 1, "apply", at(0))
    assert not log.exists()
    timing.mark(log, 1, "posting", at(0))
    with pytest.raises(ValueError, match="no run 'x'"):
        timing.report(timing.read(log), at(1), run="x")


def test_a_broken_line_costs_only_itself(tmp_path):
    log = tmp_path / "apply_timing.jsonl"
    timing.mark(log, 1, "posting", at(0))
    with log.open("a") as f:
        f.write("not json\n")
    timing.mark(log, 1, "form", at(2))
    assert [r.get("step") for r in timing.read(log)] == [None, "posting", "form"]  # the run's start, 2 marks


def test_nothing_recorded_says_how_to_begin(tmp_path):
    assert "jobhunter timing start" in timing.report([], at(0))
