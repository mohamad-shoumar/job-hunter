"""sessionlog.py: a run's tool calls and tokens, from the Claude Code session that timed it."""

import json
import os
from datetime import datetime, timedelta, UTC

from jobhunter import sessionlog

T0 = datetime(2026, 11, 24, 17, 0, tzinfo=UTC)


def at(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def reply(minutes, msg_id, content, usage=None):
    return {"type": "assistant", "timestamp": at(minutes),
            "message": {"id": msg_id, "content": content,
                        "usage": usage or {"input_tokens": 2, "cache_creation_input_tokens": 98,
                                           "cache_read_input_tokens": 900, "output_tokens": 50}}}


def bash(cmd, tool_id):
    return {"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": cmd}}


def write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines))


def test_the_timed_session_is_read_once_per_reply_with_its_subagents_and_others_left_out(tmp_path):
    root = tmp_path / "projects"
    run = root / "-Users-me-job-hunter" / "s1.jsonl"
    write(run, [
        {"type": "user", "timestamp": at(0), "message": {"content": "apply to my jobs"}},
        reply(0, "m1", [bash("cd ~/job-hunter && .venv/bin/jobhunter timing mark - setup", "t1")]),
        reply(1, "m2", [{"type": "thinking", "thinking": "..."}]),
        reply(1, "m2", [bash("ls", "t2")]),  # the same reply on a second line: tokens counted once
        reply(1, "m2", [bash("pwd", "t3")]),
        reply(90, "m9", [bash("ls", "t9")]),  # outside the window
    ])
    write(root / "-Users-me-job-hunter" / "s1" / "subagents" / "agent-a.jsonl", [reply(2, "a1", [bash("cat x", "t4")])])
    write(root / "-Users-me-other" / "s2.jsonl", [reply(1, "o1", [bash("make test", "o1t")])])  # another workspace
    old = root / "-Users-me-job-hunter" / "s0.jsonl"
    write(old, [reply(-60 * 48, "x1", [bash("jobhunter timing mark - setup", "x")])])
    os.utime(old, (0, 0))  # untouched since long before the run: never opened
    turns = sessionlog.turns_for({"r1": (T0, T0 + timedelta(minutes=30)), "r0": (T0 - timedelta(days=2), T0 - timedelta(days=1))}, root)
    assert list(turns) == ["r1"]
    got = turns["r1"]
    assert [t.tool_calls for t in got] == [1, 2, 1]
    assert [t.marks for t in got] == [True, False, False]
    assert got[1].tokens_in == 1000 and got[1].tokens_cached == 900 and got[1].tokens_out == 50


def test_no_projects_folder_means_no_cost(tmp_path):
    assert sessionlog.turns_for({"r": (T0, T0)}, tmp_path / "missing") == {}
    assert sessionlog.turns_for({}, tmp_path) == {}


def test_the_folder_follows_claude_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert sessionlog.projects_dir() == tmp_path / "projects"
