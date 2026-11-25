"""What an apply-job run cost: tool calls and tokens, read from Claude Code's own session logs (the
user's ask, 2026-11-25: a run can get shorter while doing more work per job).

Claude Code writes one JSONL file per session under ~/.claude/projects/<folder>/ (or $CLAUDE_CONFIG_DIR),
with each subagent's file in <session id>/subagents/. A reply split over several lines repeats its
token counts on each, so a reply is counted once by its message id. The run's session is the one
that called `jobhunter timing` inside the run's window: other sessions open at the same time (other
workspaces) are left out. Only read, never written; `jobhunter timing report` is the only reader.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .timing import Turn

MARKER = b"jobhunter timing"  # a session that never called it ran no timed run


def projects_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser() / "projects"


def _when(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _session_files(root: Path, since: datetime) -> list[list[Path]]:
    """Each session that may hold a timed run: its main file (changed since `since`, calling `jobhunter
    timing`) and its subagents' files. The byte search runs before any JSON is read: the folder is GBs."""
    out = []
    if not root.is_dir():
        return out
    cutoff = since.timestamp()
    for main in root.glob("*/*.jsonl"):
        try:
            if main.stat().st_mtime < cutoff or MARKER not in main.read_bytes():
                continue
        except OSError:
            continue
        out.append([main, *sorted((main.parent / main.stem).glob("**/*.jsonl"))])
    return out


def _read(files: list[Path]) -> tuple[list[Turn], list[datetime]]:
    """The session's replies (one Turn per message id) and when it called `jobhunter timing`."""
    replies: dict[str, dict] = {}
    calls: list[datetime] = []
    for path in files:
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for n, line in enumerate(lines):
            if '"assistant"' not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            msg = rec.get("message") if rec.get("type") == "assistant" else None
            at = _when(rec.get("timestamp", ""))
            if not isinstance(msg, dict) or at is None:
                continue
            key = msg.get("id") or f"{path}:{n}"
            reply = replies.setdefault(key, {"at": at, "usage": {}, "tools": set(), "marks": False})
            reply["usage"] = msg.get("usage") or reply["usage"]
            for block in msg.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    reply["tools"].add(block.get("id") or f"{key}:{len(reply['tools'])}")
                    text = json.dumps(block.get("input"))
                    if MARKER.decode() in text:
                        calls.append(at)
                        reply["marks"] |= "timing mark" in text
    turns = []
    for r in replies.values():
        u = r["usage"]
        cached = u.get("cache_read_input_tokens") or 0
        fresh = (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
        turns.append(Turn(r["at"], len(r["tools"]), fresh + cached, cached, u.get("output_tokens") or 0, r["marks"]))
    return sorted(turns, key=lambda t: t.at), calls


def turns_for(windows: dict[str, tuple[datetime, datetime]], root: Path | None = None) -> dict[str, list[Turn]]:
    """{run: the replies inside its window} for each run whose session log is still on disk (Claude Code
    deletes old ones), from the sessions that called `jobhunter timing` inside that window."""
    if not windows:
        return {}
    root = root or projects_dir()
    sessions = [_read(files) for files in _session_files(root, min(start for start, _ in windows.values()))]
    out: dict[str, list[Turn]] = {}
    for run, (start, end) in windows.items():
        picked = [turns for turns, calls in sessions if any(start <= c <= end for c in calls)]
        if picked:
            out[run] = sorted((t for turns in picked for t in turns if start <= t.at <= end), key=lambda t: t.at)
    return out
