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
    assert "**Earlier runs**" in new and "| 2026-11-24 17:00 | 1 | 0 | 10.0 | 10.0 | - |" in new


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
    assert "| 2026-11-24 17:00 | 1 | 0 | 5.0 | 5.0 | - |" in timing.report(records, at(190))


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


def test_a_form_mark_names_its_site_and_the_report_gives_minutes_per_form_by_site(tmp_path):
    assert timing.site_name("https://job-boards.eu.greenhouse.io/proton/jobs/5044422101") == "Greenhouse"
    assert timing.site_name("rbs.wd3.myworkdayjobs.com") == "Workday"
    assert timing.site_name("https://www.linkedin.com/jobs/view/4493030521") == "LinkedIn Easy Apply"
    assert timing.site_name("lever") == "Lever"
    assert timing.site_name("https://careers.example.org/apply/7") == "careers.example.org"
    assert timing.site_name("") is None
    log = tmp_path / "apply_timing.jsonl"
    timing.mark(log, 1, "form", at(0), site="https://jobs.lever.co/acme/1")
    timing.mark(log, 1, "linkedin", at(4))
    timing.mark(log, 2, "form", at(5), site="https://jobs.lever.co/globex/2")
    timing.mark(log, 2, "linkedin", at(7))
    timing.mark(log, 3, "form", at(8))  # no site given
    timing.mark(log, None, "report", at(9))
    out = timing.report(timing.read(log), at(10))
    assert "| Lever | 2 | 3.0 |" in out  # (4 + 2) / 2
    assert "| not recorded | 1 | 1.0 |" in out


def test_the_apps_skips_count_even_unmarked_and_say_why(tmp_path):
    log = tmp_path / "apply_timing.jsonl"
    timing.mark(log, 1, "posting", at(0))
    timing.mark(log, 1, "form", at(2))
    timing.mark(log, 2, "posting", at(4))  # skipped, marked
    timing.mark(log, 4, "posting", at(5))
    timing.mark(log, 4, "form", at(6))  # the form's own question ruled it out: skipped in the app
    timing.mark(log, None, "report", at(8))
    skips = {timing.runs(timing.read(log))[0]: {2: ("Wrong stack", "Globex"), 3: ("Wrong stack", "Initech"),
                                                4: ("Not open to me", "Umbrella")}}
    out = timing.report(timing.read(log), at(9), skips=skips)
    assert "for 4 jobs: 1 form filled, 3 skipped (2 timed)." in out
    assert "| 3 skipped jobs (2 timed) | 4.0 (2.0 each) | skipped |" in out
    assert "**Why jobs were skipped** (3 of 4 jobs looked at, 75%, from the app)" in out
    assert "| Wrong stack | 2 | Globex, Initech |" in out
    assert out.index("| Wrong stack") < out.index("| Not open to me")
    assert "**Per application ready** (1: forms filled or waiting on your sign-in): 9.0 min." in out  # the whole run, report included


def test_cost_counts_only_replies_inside_working_steps_and_a_mark_reply_starts_its_step(tmp_path):
    log = tmp_path / "apply_timing.jsonl"
    timing.mark(log, 1, "posting", at(0))
    timing.mark(log, 1, "form", at(5))
    timing.mark(log, None, "waiting", at(10))
    timing.mark(log, None, "report", at(20))
    timing.mark(log, None, "waiting", at(22))
    run = timing.runs(timing.read(log))[0]

    def turn(m, calls, marks=False):
        return timing.Turn(at(m), calls, 1000, 900, 10, marks)
    turns = [turn(-1, 9),  # before the run's first mark
             turn(1, 2), turn(4.9, 1, marks=True),  # carries the form mark: the form's first action
             turn(6, 3), turn(12, 50),  # while waiting on the user: not the run's work
             turn(21, 1), turn(30, 7)]  # after the run (the report rewritten later)
    out = timing.report(timing.read(log), at(23), turns={run: turns})
    assert "**Cost**: 7 tool calls in 4 replies, 4k tokens read (90% from the cache), 40 written." in out
    assert "| Filling the form | 5.0 | 42% | 4 |" in out
    assert "| Checking the posting | 5.0 | 42% | 2 |" in out
    assert "7 tool calls, 4k tokens read." in out  # per application ready (1)
    segs = timing.run_segments(timing.read(log), run, at(23))
    assert timing.cost(segs, turns).tool_calls == 7


def test_a_run_whose_session_log_is_gone_keeps_its_saved_cost(tmp_path):
    log = tmp_path / "apply_timing.jsonl"
    timing.mark(log, 1, "form", at(0))
    timing.mark(log, None, "report", at(10))
    run = timing.runs(timing.read(log))[0]
    costs_path = tmp_path / "costs.json"
    timing.save_costs(costs_path, {run: timing.Cost(tool_calls=30, turns=20, tokens_in=2_500_000)})
    out = timing.report(timing.read(log), at(11), costs=timing.load_costs(costs_path))
    assert "**Cost**: 30 tool calls in 20 replies, 2.5M tokens read" in out
    assert "| Tool calls |" not in out  # no per-step column without the log
    assert timing.load_costs(tmp_path / "none.json") == {}


def test_a_mirror_score_goes_into_the_open_run_and_never_opens_one(tmp_path):
    log = tmp_path / "apply_timing.jsonl"
    assert timing.mirror(log, 7, "before", ["Python"], [], ["Python"], at(0)) is None
    assert not log.exists()
    timing.mark(log, 7, "mirror", at(1))
    terms = ["Python", "PostgreSQL", "Rust"]
    timing.mirror(log, 7, "before", terms, ["Python"], ["Python", "PostgreSQL"], at(1))
    timing.mirror(log, 7, "after", terms, ["Python", "PostgreSQL"], ["Python", "PostgreSQL"], at(3))
    timing.mark(log, 7, "form", at(4))
    with pytest.raises(ValueError, match="before or after"):
        timing.mirror(log, 7, "during", terms, [], [], at(4))
    out = timing.report(timing.read(log), at(5), labels={7: "#7 Acme"})
    assert "| #7 Acme | 3 | 1 | 2 | Rust |" in out
    assert "| Mirroring the CV | 3.0 |" in out  # a mirror line is not a mark: the step still runs to the form


def test_a_runs_window_ends_when_its_work_ends_not_while_it_waits_on_you(tmp_path):
    log = tmp_path / "apply_timing.jsonl"
    run = timing.mark(log, 1, "posting", at(0))
    timing.mark(log, 1, "form", at(3))
    assert timing.window(timing.read(log), run, at(8)) == (at(0), at(8))  # still working: now
    timing.mark(log, None, "waiting", at(10))
    assert timing.window(timing.read(log), run, at(30)) == (at(0), at(10))  # a skip at 20 is not the run's


def test_a_name_with_a_pipe_does_not_break_the_tables(tmp_path):
    log = tmp_path / "apply_timing.jsonl"
    timing.mark(log, 1, "form", at(0))
    timing.mark(log, None, "report", at(5))
    run = timing.runs(timing.read(log))[0]
    out = timing.report(timing.read(log), at(5.02), labels={1: "#1 EMBL | EBI"},
                        skips={run: {2: ("Wrong stack", "Acme | Labs")}})
    assert "| #1 EMBL / EBI | 5.0 | form filled |" in out
    assert "| Wrong stack | 1 | Acme / Labs |" in out
    assert "Writing the report" not in out  # 1 second is not a row
