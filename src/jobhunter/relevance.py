"""Is this a role worth applying to? Title rules plus a skills fit score.

All keyword lists live in config/filters.json. Matching is whole-word on the
normalized title, so "Back-End Engineer" matches the keyword "backend".

Three kinds of exclusion:
  title_exclude               seniority/function words ("staff", "head of",
                              "sales"). Checked against the WHOLE title; there
                              is no way around them.
  title_exclude_unless_python another language's role ("Backend Engineer
                              (Java)"). Whole title, unless it also says Python.
  title_exclude_single_role   specialties ("frontend", "ios", "qa"). Skipped
                              when the title names a second role that is a
                              target: "Frontend / Backend Engineer" passes.
"""

from __future__ import annotations

import re

from .config import Filters
from .models import IRRELEVANT, MATCH, MAYBE, Assessment, Job
from .text import has_phrase, normalize_words

_PYTHON_FAMILY = {"python", "fastapi", "django", "flask"}
_GENDER_MARKER = re.compile(r"\(\s*(?:[mfwdxh]\s*/\s*){1,3}[mfwdxh]\s*\)|\(\s*all genders\s*\)", re.I)
# Separators that join two ROLES ("Frontend / Backend Engineer"). Commas are
# left alone: "Software Engineer, Frontend" is one role and its team.
_ROLE_SPLIT = re.compile(r"\s+(?:/|&|\+|and|or)\s+|\s*/\s*|\s*;\s*|\s+\|\s+", re.I)
_ROLE_NOUN = re.compile(r"\b(?:engineer|developer|programmer|swe)\b")


def _first(title: str, keywords: list[str]) -> str | None:
    return next((k for k in keywords if has_phrase(title, k)), None)


def _role_parts(raw_title: str) -> list[str]:
    """'Backend & Frontend Engineer' -> ['backend engineer', 'frontend engineer'].

    A part without its own role noun borrows the last part's ("Backend" gets
    "engineer"); a part that still has none is not a role and is dropped, so
    'Head of Applied AI & Trading Systems' does not yield a 'trading systems' role.
    """
    parts = [normalize_words(p) for p in _ROLE_SPLIT.split(raw_title) if p.strip()]
    if len(parts) < 2:
        return []
    last_noun = _ROLE_NOUN.findall(parts[-1])
    noun = last_noun[-1] if last_noun and parts[-1].endswith(last_noun[-1]) else None
    out = []
    for part in parts:
        if not _ROLE_NOUN.search(part) and noun:
            part = f"{part} {noun}"
        if _ROLE_NOUN.search(part):
            out.append(part)
    return out


def check_title(raw_title: str, filters: Filters) -> tuple[bool, str, str]:
    cleaned = _GENDER_MARKER.sub(" ", raw_title or "")
    title = normalize_words(cleaned)
    keyword = _first(title, filters.title_exclude)
    if keyword:
        return False, f'Title contains "{keyword}"', "title_excluded"
    if not has_phrase(title, "python"):
        keyword = _first(title, filters.title_exclude_unless_python)
        if keyword:
            return False, f'Title is a "{keyword}" role', "other_stack"

    blocked = None
    for i, candidate in enumerate([title] + _role_parts(cleaned)):
        specialty = _first(candidate, filters.title_exclude_single_role)
        if specialty:
            blocked = blocked or specialty
            continue
        keyword = _first(candidate, filters.title_include)
        if keyword:
            suffix = " (one of several roles in the title)" if i else ""
            return True, f'Title matches "{keyword}"{suffix}', ""
    if blocked:
        return False, f'Title contains "{blocked}"', "title_excluded"
    return False, "Title is not a target role", "title_not_target"


def fit_score(job: Job, filters: Filters) -> int:
    return sum(filters.fit_weights.get(skill, 0) for skill in job.skills)


def assess_relevance(job: Job, filters: Filters) -> tuple[Assessment, int]:
    ok, reason, code = check_title(job.title, filters)
    score = fit_score(job, filters)
    if not ok:
        return Assessment(IRRELEVANT, [reason], code), score

    reasons = [reason]
    yoe = job.required_yoe
    if yoe is not None and filters.reject_if_required_yoe_at_least and yoe >= filters.reject_if_required_yoe_at_least:
        return Assessment(IRRELEVANT, [f"Asks for {yoe}+ years of experience"], "too_senior"), score
    if yoe is not None and filters.stretch_yoe_at_least and yoe >= filters.stretch_yoe_at_least:
        reasons.append(f"Asks for {yoe}+ years (a stretch)")

    if has_phrase(normalize_words(job.title), "python") or _PYTHON_FAMILY & set(job.skills):
        reasons.append("Python stack")
        return Assessment(MATCH, reasons, "match"), score
    reasons.append("No Python mentioned")
    return Assessment(MAYBE, reasons, "maybe"), score
