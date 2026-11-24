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

    assert out.startswith("**Run 2026-11-24 17:00-17:30 UTC:** 16m working, 14m waiting on you, "
                          "4m lost to snags; 1 job, 14m a job.")
    assert "| Job | Setup | Posting | Form | Lost | Total |" in out
    assert "| #7 Acme |  | 3 | 11 | 4 | 14 |" in out
    assert "| Run (no job) | 2 |  |  |  | 2 |" in out
    assert "| **Total** | 2 | 3 | 11 | 4 | 16 |" in out
    assert "- #7 Acme, Form, 4 min: Location box needs its suggestion clicked → fix: add it to the skill" in out
    assert "- #7 Acme, Form: Guessed 1 year for LLM apps in production" in out
    assert "Last runs" not in out  # only one run so far


def test_a_mark_with_no_open_run_starts_one_and_old_runs_stop_at_their_last_line(tmp_path):
    log = tmp_path / "apply_timing.jsonl"
    first = timing.mark(log, 1, "posting", at(0))  # no `start`: begins a run anyway
    timing.mark(log, 1, "cv", at(10))
    later = at(60 * 24)  # the next day: the old run is closed, not stretched to now
    second = timing.mark(log, 2, "posting", later)
    assert first != second
    records = timing.read(log)
    old = timing.report(records, later + timedelta(minutes=5), run=first)
    assert "| #1 | 10 |  | 10 |" in old  # the cv mark was its last line: 0 minutes, not a day
    assert "CV check" not in old  # a step with no time gets no column
    new = timing.report(records, later + timedelta(minutes=5))
    assert "| #2 | 5 |  | 5 |" in new
    assert "Last runs:" in new and "| 2026-11-24 17:00 | 1 | 10m | 10m | 0m |" in new


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
