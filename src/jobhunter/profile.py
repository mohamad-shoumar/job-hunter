"""Reading profile/master_profile.md, the only source of facts about you (see CLAUDE.md).

`load_profile` gives the facts the email and the fit grade use: experience, skills and
education, never the Basics (phone, email) or logistics (salary). The CV (cv.load_facts)
and the cover letter (cover.load_letter_facts) read the same file in their own shapes,
with `sections`, `split_tags` and `strip_notes` from here. What a generated line may say
about those facts is grounding.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import my_details
from .extract import extract_skills

# Profile sections the facts come from. Basics (phone), logistics (salary) never.
_FACT_SECTIONS = ("Summary of experience", "Experience", "Skills (confirmed)", "Education")
_TAGS = re.compile(r"^\[([a-z][a-z, ]*)\]\s*")


@dataclass
class Profile:
    name: str
    first_name: str
    linkedin: str | None
    github: str | None
    facts: list[str]
    skills: set[str] = field(default_factory=set)
    phone: str | None = None
    city: str | None = None
    # "About 3.3 years of software engineering" -> 3.3; the pitch may claim at most the whole part.
    years: float | None = None

    @property
    def facts_text(self) -> str:
        return "\n".join(self.facts)


def sections(text: str) -> dict[str, str]:
    """{"Experience": its text, ...}: each "## " section by its title. Text before the first one is left out."""
    found = {}
    for part in re.split(r"^## ", text, flags=re.M)[1:]:
        title, _, body = part.partition("\n")
        found[title.strip()] = body
    return found


def strip_notes(line: str) -> str:
    """The line without your notes ("(Confirmed by me ...)"), which never reach a model or a CV."""
    return re.sub(r"\s*\((?:Confirmed by me|mohamad answering)[^)]*\)\.?", "", line).strip()


def split_tags(text: str) -> tuple[frozenset[str], str]:
    """'[fullstack, lead] Built ...' -> ({'fullstack', 'lead'}, 'Built ...'). A bullet with no tag is core."""
    m = _TAGS.match(text)
    if not m:
        return frozenset({"core"}), text
    return frozenset(t.strip() for t in m.group(1).split(",") if t.strip()), text[m.end():].strip()


def skills_in(text: str) -> set[str]:
    """The skills the facts name; "distributed/backend systems" also counts as distributed systems."""
    found = set(extract_skills(text))
    if re.search(r"\bdistributed\b", text, re.I):  # stated as "distributed/backend systems"
        found.add("distributed systems")
    return found


def years_in(text: str) -> float | None:
    """The years of experience the facts state ("About 3.3 years of software engineering" -> 3.3), or None."""
    m = re.search(r"\bAbout (\d+(?:\.\d+)?) years\b", text)
    return float(m.group(1)) if m else None


def load_profile(path: Path) -> Profile:
    text = path.read_text()
    basics = my_details(text)
    parts = re.split(r"^## ", text, flags=re.M)
    facts: list[str] = []
    for part in parts:
        title, _, body = part.partition("\n")
        if title.strip() not in _FACT_SECTIONS:
            continue
        role = ""
        for raw in body.splitlines():
            line = strip_notes(raw.strip())
            if not line or "TODO" in line:
                continue
            if line.startswith("### "):
                header = " ".join(line[4:].split())
                role = header.split("        ")[0]
                facts.append(f"Role: {header}")
            elif line.startswith("- "):
                text = split_tags(line[2:])[1]
                facts.append(f"{role}: {text}" if role and title.strip() == "Experience" else text)
    name = basics.get("Name", "").strip()
    profile = Profile(
        name=name, first_name=name.split()[0] if name else "", linkedin=_link(basics.get("LinkedIn")),
        github=_link(basics.get("GitHub")), facts=facts,
    )
    profile.phone = _link(basics.get("Phone"))
    profile.city = (_link(basics.get("Location")) or "").split(",")[0].strip() or None
    profile.skills = skills_in(profile.facts_text)
    profile.years = years_in(profile.facts_text)
    return profile


def _link(value: str | None) -> str | None:
    value = (value or "").strip()
    return None if not value or "TODO" in value else value
