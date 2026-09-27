"""Project paths and config files. Everything lives under one project directory."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .text import normalize_words


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def sources_file(self) -> Path:
        return self.root / "config" / "sources.json"

    @property
    def filters_file(self) -> Path:
        return self.root / "config" / "filters.json"

    @property
    def ai_check_file(self) -> Path:
        return self.root / "config" / "ai_check.json"

    @property
    def db_file(self) -> Path:
        return self.root / "data" / "jobs.sqlite"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def env_file(self) -> Path:
        return self.root / ".env"


def resolve_root(explicit: str | None = None) -> Path:
    """--home, then $JOBHUNTER_HOME, then the nearest parent holding config/sources.json."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    if os.environ.get("JOBHUNTER_HOME"):
        return Path(os.environ["JOBHUNTER_HOME"]).expanduser().resolve()
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / "config" / "sources.json").exists():
            return candidate
    return here


def load_dotenv(path: Path) -> None:
    """Minimal KEY=VALUE reader. Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def load_json(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


@dataclass
class Filters:
    max_posting_age_days: int | None
    reject_if_required_yoe_at_least: int | None
    stretch_yoe_at_least: int | None
    dedupe_window_days: int
    title_include: list[str]
    title_exclude: list[str]
    title_exclude_unless_python: list[str]
    title_exclude_single_role: list[str]
    fit_weights: dict[str, int]

    @classmethod
    def from_dict(cls, data: dict) -> Filters:
        def words(key: str) -> list[str]:
            return [w for w in (normalize_words(x) for x in data.get(key, [])) if w]

        return cls(
            max_posting_age_days=data.get("max_posting_age_days", 30),
            reject_if_required_yoe_at_least=data.get("reject_if_required_yoe_at_least"),
            stretch_yoe_at_least=data.get("stretch_yoe_at_least"),
            dedupe_window_days=int(data.get("dedupe_window_days", 60)),
            title_include=words("title_include"),
            title_exclude=words("title_exclude"),
            title_exclude_unless_python=words("title_exclude_unless_python"),
            title_exclude_single_role=words("title_exclude_single_role"),
            fit_weights={k.lower(): int(v) for k, v in data.get("fit_weights", {}).items()},
        )

    @classmethod
    def load(cls, path: Path) -> Filters:
        return cls.from_dict(load_json(path))
