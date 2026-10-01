"""The Claude Code writer (`claude -p`): the command it runs, the answer it reads, and that tests never run it."""

import pytest

from jobhunter import llm
from jobhunter.llm import JsonModel, Usage, json_model, key_note
from jobhunter.llm import claude_code_bin as real_claude_code_bin  # before conftest swaps these out
from jobhunter.llm import run_claude_code as real_run_claude_code

from .conftest import fixture_text

SCHEMA = {"type": "object", "properties": {"opening": {"type": "string"}}, "required": ["opening"]}


class FakeRun:
    def __init__(self, out: str):
        self.out = out
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, args, prompt, timeout):
        self.calls.append((args, prompt))
        return self.out


def test_claude_code_runs_with_no_tools_and_none_of_your_settings(monkeypatch):
    run = FakeRun(fixture_text("claude_code_result.json"))  # a trimmed real `claude -p --output-format json`
    monkeypatch.setattr(llm, "run_claude_code", run)
    usage = Usage()
    answer = JsonModel("claude-code:sonnet").ask("Write one line.", [{"role": "user", "content": "Hi"}],
                                                 SCHEMA, usage, "{}")
    assert answer == {"opening": "Hi, good to see you."}
    assert usage.input == 2 and usage.output == 172 and usage.cache_write == 3000
    args, prompt = run.calls[0]
    assert args[1:4] == ["-p", "--output-format", "json"] and prompt == "Hi"
    assert args[args.index("--system-prompt") + 1] == "Write one line."
    assert args[args.index("--tools") + 1] == "" and args[args.index("--setting-sources") + 1] == ""
    assert args[args.index("--model") + 1] == "sonnet" and '"required": ["opening"]' in args[args.index("--json-schema") + 1]
    assert "--no-session-persistence" in args and "--strict-mcp-config" in args


def test_a_retry_sends_the_earlier_turns_as_one_prompt(monkeypatch):
    run = FakeRun(fixture_text("claude_code_result.json"))
    monkeypatch.setattr(llm, "run_claude_code", run)
    JsonModel("claude-code").ask("s", [{"role": "user", "content": "Write it."},
                                       {"role": "assistant", "content": '{"opening": "x"}'},
                                       {"role": "user", "content": "Fix these: a dash."}], SCHEMA, Usage(), "{}")
    args, prompt = run.calls[0]
    assert prompt == 'Write it.\n\nYour answer was:\n{"opening": "x"}\n\nFix these: a dash.'
    assert "--model" not in args  # plain "claude-code": the CLI's default model


def test_a_failed_run_is_an_error_not_an_empty_letter(monkeypatch):
    monkeypatch.setattr(llm, "run_claude_code", FakeRun('{"type": "result", "is_error": true, "result": "Not logged in"}'))
    with pytest.raises(RuntimeError, match="Not logged in"):
        JsonModel("claude-code").ask("s", [{"role": "user", "content": "x"}], SCHEMA, Usage(), "{}")


def test_claude_code_needs_the_program_not_an_api_key(monkeypatch, tmp_path):
    assert "Claude Code CLI" in key_note("claude-code", "Cover letters")  # conftest: no `claude` here
    assert json_model("claude-code", "Cover letters") == (None, key_note("claude-code", "Cover letters"))
    monkeypatch.setattr(llm, "claude_code_bin", lambda: "/usr/local/bin/claude")
    assert key_note("claude-code", "Cover letters") is None
    model, note = json_model("claude-code", "Cover letters")
    assert note is None and model.model == "claude-code" and model.claude is None


def test_the_program_is_found_from_the_env_setting(monkeypatch, tmp_path):
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("CLAUDE_CODE_BIN", str(fake))
    assert real_claude_code_bin() == str(fake)


def test_the_run_never_sees_an_api_key_and_has_a_time_limit(monkeypatch):
    """With ANTHROPIC_API_KEY set, `claude -p` would bill it instead of using your Claude login."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert real_run_claude_code(["/bin/sh", "-c", 'printf "%s" "${ANTHROPIC_API_KEY:-none}"'], "", 5) == "none"
    with pytest.raises(RuntimeError, match="took longer than 1 seconds"):
        real_run_claude_code(["/bin/sleep", "5"], "", 1)


def test_tests_never_run_claude_code():
    with pytest.raises(RuntimeError, match="tests never run Claude Code"):
        llm.run_claude_code(["claude", "-p"], "hi", 5)
