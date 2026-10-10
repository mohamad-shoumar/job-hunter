"""Project paths and config files. Everything lives under one project directory."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path

from .agency import AgencyRules
from .identity import company_key
from .relocation import Relocation
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
    def outreach_file(self) -> Path:
        return self.root / "config" / "outreach.json"

    @property
    def profile_file(self) -> Path:
        return self.root / "profile" / "master_profile.md"

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


# Your contact details live in .env, so no file in git holds them. Each one wins over the same
# "- Email: ..." line in the profile's Basics, which still works when .env leaves it empty.
MY_DETAILS = {"Name": "MY_NAME", "Email": "MY_EMAIL", "Phone": "MY_PHONE", "LinkedIn": "MY_LINKEDIN",
              "GitHub": "MY_GITHUB", "Location": "MY_LOCATION"}


def my_details(profile_text: str) -> dict[str, str]:
    """{"Name": ..., "Email": ...}: the MY_* values from .env, else the profile's Basics lines. TODO ones are left out."""
    found = {k: v.strip() for k, v in re.findall(r"^- (Name|Email|Phone|LinkedIn|GitHub|Location): (.+)$",
                                                 profile_text, re.M)}
    for key, env in MY_DETAILS.items():
        if os.environ.get(env, "").strip():
            found[key] = os.environ[env].strip()
    return {k: v for k, v in found.items() if v and "TODO" not in v}


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
    # company_key -> (name as written, why): these companies are rejected outright.
    blocked_companies: dict[str, tuple[str, str]] = field(default_factory=dict)
    # Staffing agencies and talent marketplaces (agency.py): rejected with what matched.
    agencies: AgencyRules = field(default_factory=AgencyRules)
    # A company's own careers page keeps a job listed while it is open, often for months.
    max_posting_age_days_company_boards: int | None = None
    # Countries you would move to (relocation.py): jobs there may be on-site. None: remote only.
    relocation: Relocation | None = None

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
            blocked_companies={company_key(b["name"]): (b["name"], b.get("why", ""))
                               for b in data.get("blocked_companies", []) if company_key(b["name"])},
            agencies=AgencyRules.from_dict(data.get("agencies")),
            relocation=Relocation.from_dict(data.get("relocation")),
            max_posting_age_days_company_boards=data.get("max_posting_age_days_company_boards"),
        )

    @classmethod
    def load(cls, path: Path) -> Filters:
        return cls.from_dict(load_json(path))


@dataclass
class OutreachConfig:
    """config/outreach.json: who to contact, the email, sending limits. See contacts.py, pitch.py, mailer.py."""

    # Companies with at most this many people: email the CEO/founder directly.
    small_company_max_employees: int = 50
    small_company_targets: list[str] = field(default_factory=lambda: ["ceo", "founder", "cto"])
    large_company_targets: list[str] = field(default_factory=lambda: ["eng_lead", "eng_manager", "recruiter", "hr"])
    # Job boards and staffing agencies: there is no one there to pitch.
    skip_companies: list[str] = field(default_factory=list)
    auto_lookup: bool = True
    max_companies_per_run: int = 10
    hunter_reserve_credits: float = 5.0
    claude_fallback_in_daily_run: bool = False
    fallback_model: str = "claude-haiku-4-5"
    fallback_max_searches: int = 2
    pitch_model: str = "claude-sonnet-5"
    # "fixed": the email is your own text below, no AI. "ai": the model writes the proof line instead of pitch_text.
    pitch_mode: str = "fixed"
    subject_template: str = "{title} - {name}"
    pitch_text: str = ""
    ask_text: str = ""
    # The closing question for HR and recruiters; empty means ask_text.
    hr_ask_text: str = ""
    auto_draft: bool = True
    follow_up_business_days: list[int] = field(default_factory=lambda: [4, 7])
    ghost_after_business_days: int = 7
    daily_send_cap: int = 15
    daily_guessed_cap: int = 3
    # CVs to attach: PDFs in this folder. A file whose name contains the company (e.g.
    # Doe_FullStack_LigaData_Sep2026.pdf) is picked for that company, else default_cv. Empty
    # default_cv means the master CV build.py makes: <Last name>_Resume_General.pdf.
    # A relative path is inside the project folder.
    cv_dir: str = "resume/output"
    default_cv: str = ""
    # Tailored CVs (cv.py): resume.md (the layout) and build.py live in resume_dir; build.py
    # writes the PDFs into its output/ folder, which is cv_dir.
    resume_dir: str = "resume"
    cv_model: str = "deepseek-v4-pro"
    auto_tailor: bool = True
    max_cvs_per_run: int = 5
    # Replaces cv.TAG_RULES for the tags it names: {"lead": {"title": [...], "posting": [...]}}.
    cv_tags: dict = field(default_factory=dict)
    # Cover letters (cover.py): written next to the CVs in cv_dir. Empty cover_model means cv_model;
    # "claude-code" (or "claude-code:<model>") runs the Claude Code CLI, signed in with your account.
    cover_model: str = ""
    # How letters read: its writer part is the model's instructions, its word lists are checked.
    cover_guidelines: str = "config/cover_letter_guidelines.md"
    auto_cover: bool = True
    max_covers_per_run: int = 5
    # The one sentence about what the posting asks for and the profile does not have. Code writes it.
    cover_gap_text: str = "I haven't worked with {gaps} yet, and I'd make learning {them} an early priority."
    # The daily run also catches up on shortlisted jobs filed this many days back that still have no
    # tailored CV or cover letter (one that failed, e.g. on a network error at wake-up).
    catch_up_days: int = 7

    @classmethod
    def load(cls, path: Path) -> OutreachConfig:
        data = load_json(path) if path.exists() else {}
        known = {f.name for f in fields(cls)}
        config = cls(**{k: v for k, v in data.items() if k in known})
        # config/outreach.json sits in <project>/config, so a relative folder is inside the project.
        root = path.resolve().parent.parent
        for name in ("cv_dir", "resume_dir", "cover_guidelines"):
            folder = Path(getattr(config, name)).expanduser()
            setattr(config, name, str(folder if folder.is_absolute() else root / folder))
        return config
