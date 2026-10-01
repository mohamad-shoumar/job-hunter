from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from jobhunter.config import Filters
from jobhunter.models import REMOTE, Job

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text()


def fixture_json(name: str):
    return json.loads(fixture_text(name))


class FakeHttp:
    """Serves canned responses by URL. A route value may be a callable(params)."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, dict | None]] = []

    def _get(self, url, params=None):
        self.calls.append((url, params))
        if url not in self.routes:
            raise RuntimeError(f"unexpected URL {url}")
        value = self.routes[url]
        if callable(value):
            value = value(params or {})
        if isinstance(value, Exception):
            raise value
        return value

    def get_json(self, url, params=None):
        return self._get(url, params)

    def get_text(self, url, params=None):
        return self._get(url, params)


@pytest.fixture(autouse=True)
def no_real_keys(monkeypatch):
    """Tests never reach Hunter, Claude or Gmail, even when the shell has the keys set, and never run the
    Claude Code CLI, even where it is installed."""
    for name in ("HUNTER_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD",
                 "SERPAPI_API_KEY", "CLAUDE_CODE_BIN"):
        monkeypatch.delenv(name, raising=False)

    def no_claude_code(*args, **kwargs):
        raise RuntimeError("tests never run Claude Code")

    monkeypatch.setattr("jobhunter.llm.run_claude_code", no_claude_code)
    monkeypatch.setattr("jobhunter.llm.claude_code_bin", lambda: None)


@pytest.fixture
def filters() -> Filters:
    """The real config/filters.json, so tests fail if the shipped config breaks."""
    return Filters.load(ROOT / "config" / "filters.json")


def make_job(**overrides) -> Job:
    values = dict(
        source="test",
        source_job_id="1",
        source_url="https://example.com/jobs/1",
        company="Acme",
        title="Senior Backend Engineer (Python)",
        description="We build APIs with Python, FastAPI and PostgreSQL on AWS.",
        remote_status=REMOTE,
        posted_at=NOW,
    )
    values.update(overrides)
    return Job(**values)


def store_job(store, filters, **overrides) -> int:
    """Classify and insert a job; returns its id. Defaults to one that is shortlisted (open worldwide)."""
    from jobhunter.classify import classify

    overrides.setdefault("allowed_locations", ["Worldwide"])
    job = make_job(**overrides)
    job.first_seen = NOW
    return store.insert(job, classify(job, filters, NOW), None, NOW)
