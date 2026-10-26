from __future__ import annotations

import json
import shutil
from datetime import datetime, UTC
from pathlib import Path

import pytest

from jobhunter.config import MY_DETAILS, Filters
from jobhunter.models import REMOTE, Job

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
# Your profile (not in git, so a fresh copy has none) and the made-up example that is: tests check their shape only.
YOUR_PROFILES = [
    pytest.param(path, id=path.name, marks=pytest.mark.skipif(not path.exists(), reason=f"no {path.name} (not in git)"))
    for path in (ROOT / "profile" / "master_profile.md", ROOT / "profile" / "master_profile.example.md")
]


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

    def get_bytes(self, url, params=None):
        return self._get(url, params)

    def post_json(self, url, body, headers=None):
        """A route value that is callable gets the JSON body (a search request)."""
        return self._get(url, body)

    def post_form(self, url, data):
        return self._get(url, data)


@pytest.fixture(autouse=True)
def no_real_keys(monkeypatch):
    """Tests never reach Hunter, Claude or Gmail, even when the shell has the keys set, and never run the
    Claude Code CLI, even where it is installed. Your MY_* details are cleared too, so the fixtures' own apply."""
    for name in ("HUNTER_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD",
                 "SERPAPI_API_KEY", "CLAUDE_CODE_BIN", "RELOCATION_MIN_MONTHLY_USD", *MY_DETAILS.values()):
        monkeypatch.delenv(name, raising=False)

    def no_claude_code(*args, **kwargs):
        raise RuntimeError("tests never run Claude Code")

    monkeypatch.setattr("jobhunter.llm.run_claude_code", no_claude_code)
    monkeypatch.setattr("jobhunter.llm.claude_code_bin", lambda: None)


@pytest.fixture
def filters() -> Filters:
    """A frozen copy of config/filters.json, so editing a preference there (years cap, blocked companies,
    agencies...) never breaks a rule test. Add a key here when a rule needs one. test_config.py checks
    that the real file still loads."""
    return Filters.load(FIXTURES / "filters.json")


def copy_config(home: Path) -> None:
    """A project folder's config/: the shipped files, with the frozen filters the `filters` fixture uses,
    so the CLI and the web app judge jobs by the same rules as the tests that stored them."""
    shutil.copytree(ROOT / "config", home / "config")
    shutil.copy(FIXTURES / "filters.json", home / "config" / "filters.json")


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
