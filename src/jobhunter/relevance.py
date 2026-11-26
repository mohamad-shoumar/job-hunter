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

A title_include keyword listed in title_include_needs_role ("forward deployed")
counts only when the title also names an engineering role, so "Forward Deployed
Engineer" is a target and "Forward-Deployed Banker" is not.

AI and forward-deployed roles (junior_only) are wanted only at junior level: a
"senior"/"lead" title or a lower years ask rejects them, quoted.

Senior roles (`senior` in filters.json, the user's call 2026-11-20): every target role is
rejected, code `too_senior`, when its title says "senior" or its text asks for a senior
person ("We're looking for a Senior Backend Engineer", "Position level: Senior",
"senior-level expertise"), quoted. A text that only mentions senior people ("work with
senior engineers", "junior and senior developers welcome") is not an ask.

Another language's role (`other_stack` in filters.json, the user's call 2026-11-26, after 195
wrong-stack skips): the title rule above only sees "Backend Engineer (Java)". A posting that names
none of your languages anywhere ("Python", "TypeScript", "React"...) and requires one of `others`
in a sentence ("Strong hands-on experience in Java/J2EE, Spring Boot") is rejected, code
`other_stack`, quoting that sentence. A sentence that offers a choice or a bonus ("Java or a
comparable language", "C++ is a plus", "willingness to learn Go") never counts.
"""

from __future__ import annotations

import re

from functools import lru_cache

from .config import Filters, JuniorOnly, OtherStack
from .extract import find_required_yoe, quote_around, sentences
from .models import IRRELEVANT, MATCH, MAYBE, Assessment, Job
from .text import has_phrase, normalize_words

_PYTHON_FAMILY = {"python", "fastapi", "django", "flask"}
# "AI Harness Engineer", "AI-Native Engineer", "LLM Platform Developer": AI-building roles named
# too many ways to list. Checked after the exclusions, so "AI Sales Engineer" stays out.
_AI_ROLE = re.compile(r"\b(?:ai|llm|genai|agentic)\b(?:\s+[a-z0-9+#]+){0,3}?\s+(?:engineer|developer)\b")
_GENDER_MARKER = re.compile(r"\(\s*(?:[mfwdxh]\s*/\s*){1,3}[mfwdxh]\s*\)|\(\s*all genders\s*\)", re.I)
# Separators that join two ROLES ("Frontend / Backend Engineer"). Commas are
# left alone: "Software Engineer, Frontend" is one role and its team.
_ROLE_SPLIT = re.compile(r"\s+(?:/|&|\+|and|or)\s+|\s*/\s*|\s*;\s*|\s+\|\s+", re.I)
_ROLE_NOUN = re.compile(r"\b(?:engineer|developer|programmer|swe)\b")
# Wider than _ROLE_NOUN (which splits a title into roles): "Forward Deployed ML Engineering
# Expert" is an engineering role, "Forward-Deployed Banker" is not.
_ENGINEERING_ROLE = re.compile(r"\b(?:engineer|engineering|developer|programmer|swe)\b")
# The posting asking for a senior person, not naming senior colleagues: "looking for a Senior ...",
# "As a Senior Engineer, you will", "Position level: Senior", "senior-level expertise".
_ADJ = r"(?:(?:experienced|talented|skilled|highly[- ]skilled|motivated|passionate|strong|exceptional|hands-on)\s+)?"
_SENIOR_ASK = re.compile(
    r"\b(?:looking\s+for|seeking|hiring|searching\s+for|in\s+search\s+of|recruiting)\s+"
    r"(?:an?\s+|our\s+(?:next\s+|new\s+|first\s+)?)?" + _ADJ + r"senior\b"
    r"|\bas\s+(?:an?|our)\s+" + _ADJ + r"senior\b"
    r"|\b(?:position|role|job|career|experience|seniority)\s+level\s*[:\-–]\s*senior\b"
    r"|\bseniority\s*:\s*senior\b"
    r"|\bsenior[- ]level\s+(?:expertise|experience|skills)\b"
    r"|\bthis\s+(?:is\s+a\s+)?senior\s+(?:role|position)\b",
    re.I)
# A sentence naming a language as a bonus: only that sentence is left out ("C++ is a plus").
_BONUS = re.compile(
    r"\b(?:plus|bonus|nice[- ]to[- ]haves?|preferred|preferably|desirable|advantage|advantageous|ideally"
    r"|not (?:required|mandatory|essential)|beneficial|optional|familiarity|exposure)\b", re.I)
# A sentence naming a language as one choice, or one you can learn: the posting is open to other languages
# ("Java or a comparable language", "primarily Java/JVM, but we're more interested in ... the ability to learn").
_OPEN_CHOICE = re.compile(
    r"\b(?:comparable|equivalent|similar|or other|or another|any (?:modern|other|major|mainstream)|such as|e\.g\."
    r"|for example|like|etc|willing(?:ness)? to (?:learn|work|pick)|eager(?:ness)? to learn|happy to learn"
    r"|ability to learn|open to learning|learn it|ramp up|generalist)\b", re.I)
# Names that are also English words: matched only as written ("React to incidents", "Go further together").
_AS_WRITTEN = {"go", "react", "rust", "ruby", "rails", ".net"}
# A sentence that also names a lower level is open to both: "a senior or mid-level engineer".
_LOWER_LEVEL = re.compile(r"\b(?:junior|mid|medior|intermediate|graduate|entry[- ]level|early[- ]career)\b", re.I)


def _first(title: str, keywords: list[str]) -> str | None:
    return next((k for k in keywords if has_phrase(title, k)), None)


def _first_include(title: str, filters: Filters) -> str | None:
    """The first title_include keyword the title names.

    A keyword in title_include_needs_role only counts when the title also names
    an engineering role: "Forward Deployed Engineer" passes, "Forward-Deployed
    Banker" does not.
    """
    for keyword in filters.title_include:
        if not has_phrase(title, keyword):
            continue
        if keyword in filters.title_include_needs_role and not _ENGINEERING_ROLE.search(title):
            continue
        return keyword
    return None


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
        keyword = _first_include(candidate, filters)
        suffix = " (one of several roles in the title)" if i else ""
        if keyword:
            return True, f'Title matches "{keyword}"{suffix}', ""
        ai_role = _AI_ROLE.search(candidate)
        if ai_role:
            return True, f'Title is an AI engineering role ("{ai_role.group(0)}"){suffix}', ""
    if blocked:
        return False, f'Title contains "{blocked}"', "title_excluded"
    return False, "Title is not a target role", "title_not_target"


def junior_only_role(title: str, rules: JuniorOnly) -> str | None:
    """The AI or forward-deployed role a normalized title names, if it is one.

    None when the title also names a role from unless_title_names: "Senior
    Python / AI Backend Engineer" is a backend role and keeps the usual rules.
    """
    if _first(title, rules.unless_title_names):
        return None
    role = _first(title, rules.roles)
    if role:
        return role
    ai_role = _AI_ROLE.search(title)
    return ai_role.group(0) if ai_role else None


def senior_ask(text: str) -> str | None:
    """The sentence in which a posting asks for a senior person, if it does."""
    for segment in sentences(text):
        m = _SENIOR_ASK.search(segment)
        if m and not _LOWER_LEVEL.search(segment):
            return quote_around(segment, m.start(), m.end())
    return None


def _term(term: str, langs: str = "") -> re.Pattern:
    """One language name as a whole word: "Java" is not in "JavaScript", ".NET" is in "ASP.NET". "Go" counts
    only as a language: "in Go", "with Go as our primary language", "Kotlin / Go"."""
    left = "" if term[0] in ".#+" else r"(?<![A-Za-z0-9])"
    body = re.escape(term) + r"(?![A-Za-z0-9+#])" + (r"(?!\s*script)" if term.lower() == "java" else "")
    if term.lower() == "go":
        return re.compile(rf"\b(?:in|with|using)\s+Go(?=\s*(?:[,.;:/()]|and\b|or\b|as\b|$))"
                          rf"|(?<![A-Za-z0-9])Go\s*(?:[,/]|and\b|or\b)\s*(?:{langs})"
                          rf"|(?:{langs})\s*(?:[,/]|and\b|or\b)\s*Go(?![A-Za-z0-9])")
    return re.compile(left + body, 0 if term.lower() in _AS_WRITTEN else re.I)


@lru_cache(maxsize=4)
def _stack_patterns(yours: tuple[str, ...], others: tuple[str, ...]):
    langs = "|".join(re.escape(t) for t in (*yours, *others) if t.lower() != "go")
    mine = [_term(t) for t in yours]
    return mine, [(t, _term(t, langs)) for t in others]


def other_stack_ask(text: str, rules: OtherStack) -> tuple[str, str] | None:
    """(the language, the sentence requiring it) when the posting names none of `yours` anywhere, a sentence
    that is no bonus asks for one of `others`, and no sentence offers that language as a choice."""
    mine, others = _stack_patterns(tuple(rules.yours), tuple(rules.others))
    if not others or any(p.search(text or "") for p in mine):
        return None
    found = None
    for segment in sentences(text):
        hit = next(((name, m) for name, pattern in others for m in [pattern.search(segment)] if m), None)
        if not hit:
            continue
        if _OPEN_CHOICE.search(segment):
            return None
        if not found and not _BONUS.search(segment):
            found = hit[0], quote_around(segment, hit[1].start(), hit[1].end())
    return found


def fit_score(job: Job, filters: Filters) -> int:
    return sum(filters.fit_weights.get(skill, 0) for skill in job.skills)


def assess_relevance(job: Job, filters: Filters) -> tuple[Assessment, int]:
    ok, reason, code = check_title(job.title, filters)
    score = fit_score(job, filters)
    if not ok:
        return Assessment(IRRELEVANT, [reason], code), score

    reasons = [reason]
    yoe = job.required_yoe
    found = find_required_yoe(job.description) if yoe is not None else None
    said = f': "{found[1]}"' if found and found[0] == yoe else ""
    rules = filters.junior_only
    title = normalize_words(_GENDER_MARKER.sub(" ", job.title or ""))
    role = junior_only_role(title, rules) if rules else None
    if role:
        word = _first(title, rules.title_words)
        if word:
            return Assessment(IRRELEVANT, [f'"{role}" roles are junior-only, and the title says "{word}"'],
                              "junior_only"), score
        limit = rules.reject_if_required_yoe_at_least
        if yoe is not None and limit and yoe >= limit:
            return Assessment(IRRELEVANT, [f'"{role}" roles are junior-only, and it asks for {yoe}+ years{said}'],
                              "junior_only"), score
    if yoe is not None and filters.reject_if_required_yoe_at_least and yoe >= filters.reject_if_required_yoe_at_least:
        return Assessment(IRRELEVANT, [f"Asks for {yoe}+ years of experience{said}"], "too_senior"), score
    if filters.senior_title_words:
        word = _first(title, filters.senior_title_words)
        if word:
            return Assessment(IRRELEVANT, [f'Senior role: the title says "{word}"'], "too_senior"), score
        asked = senior_ask(job.description)
        if asked:
            return Assessment(IRRELEVANT, [f'Senior role: "{asked}"'], "too_senior"), score
    if filters.other_stack:
        asked = other_stack_ask(f"{job.title}\n{job.description or ''}", filters.other_stack)
        if asked:
            return Assessment(IRRELEVANT, [f'Built on {asked[0]}, and the posting names none of your languages: '
                                           f'"{asked[1]}"'], "other_stack"), score
    if yoe is not None and filters.stretch_yoe_at_least and yoe >= filters.stretch_yoe_at_least:
        reasons.append(f"Asks for {yoe}+ years (a stretch){said}")

    if has_phrase(normalize_words(job.title), "python") or _PYTHON_FAMILY & set(job.skills):
        reasons.append("Python stack")
        return Assessment(MATCH, reasons, "match"), score
    reasons.append("No Python mentioned")
    return Assessment(MAYBE, reasons, "maybe"), score
