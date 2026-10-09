"""A cover letter for one job: your profile's facts, checked sentence by sentence.

The model writes the opening, one or two paragraphs and the closing. Code
writes the rest (your name and contact lines, the date, "Dear <Company>
Hiring Team,", the sign-off) and checks every sentence the model wrote
against profile/master_profile.md, the only source of facts about you (see
CLAUDE.md):

  - the facts it may use are the ones the tailored CV prints for this job:
    the summary, the Experience bullets for the job's tags (cv.job_tags, the
    same [core]/[lead]/... rules), skills, education and certifications.
    Never the logistics lines (where you live, time zone, notice, salary):
    the header already shows where you are, and the letter's few lines go
    to why you fit;
  - each paragraph names the facts it uses. In it, every number must be in
    one of those facts next to the same word ("800+ concurrent jobs"), every
    tool must be in them, and no seniority word ("senior", "lead") may be
    added;
  - the opening and closing may also repeat what the posting says about the
    company ("With 80,000 students ..."), but a sentence about you ("I",
    "my") still names only tools you have;
  - years of experience are never above the profile's;
  - what the posting asks for that the profile lacks is never claimed: the
    model may name up to MAX_GAPS of those (each word for word in the
    posting, central to it, and not in or close to your facts), and code
    writes one plain sentence saying you have not worked with them
    (cover_gap_text).

How the letter reads (length, shape, voice, the words that sound like AI) is
in config/cover_letter_guidelines.md, which the model gets as its
instructions. Code checks its "Never use" list like a fact rule, and dashes,
", -ing" add-ons, the "Use at most one" words and the length as style.

A letter that breaks a rule is sent back once with the reasons. A sentence
that still breaks a fact or "Never use" rule is left out, and the app says
what was removed and why; a style issue that is left is only noted (a dash
becomes a comma). The letter is plain text next to the CVs in cv_dir, named
like Doe_CoverLetter_Acme_Oct2026.md, to paste into a form or upload.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import tracking
from .config import OutreachConfig, my_details
from .contacts import clean_company_name
from .cv import TAG_RULES, Role, _camel, _sections, job_tags, parse_titles, printed_title, split_items
from .extract import _SKILL_RES, extract_skills
from .llm import JsonModel, Usage, json_model
from .pitch import (
    _SENIORITY, _capitalized_words, _fact_has, _number_context, _strip_notes, role_family, short_title, split_tags,
)
from .store import JobStore
from .text import iso

MAX_POSTING_CHARS = 6000
MAX_GAPS = 1
MAX_PARAGRAPHS = 3
# A letter outside this range still prints, with a note; a longer one is sent back once first.
MIN_WORDS, MAX_WORDS = 120, 300
GUIDELINES_FILE = Path(__file__).resolve().parents[2] / "config" / "cover_letter_guidelines.md"
# A gap is not named when your facts have work this close to it ("CI/CD" next to "quality gates").
_CLOSE_TO = {
    ("ci/cd", "ci", "cd", "continuous integration", "continuous delivery", "continuous deployment", "ci pipelines",
     "ci/cd pipelines"): ("quality gates", "deploy gates", "release qa"),
    ("observability", "monitoring"): ("datadog", "grafana"),
}
_FIRST_PERSON = re.compile(r"\b(?:I|I'm|I've|I'd|I'll|my|me|mine|myself)\b", re.I)
_YEARS = {"year", "years", "yr", "yrs"}
_OFFSET = re.compile(r"\b(?:UTC|GMT)\s?[+\-−]\s?\d{1,2}(?::\d\d)?", re.I)
_CALENDAR = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
             "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday"}
# Skills rows of the profile, and capitalized words in bullets that are not names of things.
_SKILL_ROWS = {"Languages", "Frameworks", "Databases", "Tools & Platforms", "Concepts & Methodologies"}
_GENERIC = {"software", "engineering", "engineer", "engineers", "developer", "factory", "applied", "workshop", "built",
            "academy", "builder", "path", "full", "stack", "star", "abu", "dhabi", "beirut", "lebanon", "sep", "mar",
            "lead", "team", "present"}
_MONTHS = {m[:3] for m in _CALENDAR}
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


class CoverError(tracking.TrackingError):
    """Shown to you as is."""


# --- the facts ---------------------------------------------------------------------------


@dataclass
class LetterFacts:
    facts: list[str]  # numbered from 1 for the model; the only things a letter may say about you
    skills: set[str]
    years: float | None
    name: str
    contact: list[str]  # email, phone, LinkedIn, GitHub: printed by code
    location: str | None

    @property
    def text(self) -> str:
        return "\n".join(self.facts)


def _skills_of(text: str) -> set[str]:
    found = set(extract_skills(text))
    if re.search(r"\bdistributed\b", text, re.I):  # stated as "distributed/backend systems"
        found.add("distributed systems")
    return found


def _bullets(body: str) -> list[str]:
    lines = [_strip_notes(raw.strip()[2:]) for raw in body.splitlines() if raw.strip().startswith("- ")]
    return [line for line in lines if line and "TODO" not in line]


def load_letter_facts(profile_path: Path, tags) -> LetterFacts:
    """The facts a letter for a job with these tags may use, in the profile's order."""
    text = profile_path.read_text()
    sections = _sections(text)
    wanted = set(tags) | {"core"}
    facts = _bullets(sections.get("Summary of experience", ""))
    roles: list[tuple[Role, str]] = []  # (role, employer)
    paragraphs: list[list[str]] = [[]]
    for raw in sections.get("Experience", "").splitlines():
        line = raw.strip()
        if line.startswith("### "):
            head, *rest = re.split(r"\s{2,}", line[4:].strip())
            title, _, employer = head.partition(" — ")
            roles.append((Role(f"R{len(roles) + 1}", title.strip(), rest[0] if rest else "", []), employer.strip()))
        elif not roles:
            continue  # the note above the first role
        elif not line:
            paragraphs.append([])
        elif line.lower().startswith("printed title:"):
            roles[-1][0].titles = parse_titles(line.split(":", 1)[1])
        elif line.startswith("- "):
            bullet_tags, bullet = split_tags(_strip_notes(line[2:]))
            if bullet and "TODO" not in bullet:
                roles[-1][0].bullets.append(bullet)
                roles[-1][0].tags.append(bullet_tags)
        else:
            paragraphs[-1].append(line)  # e.g. "All three CoinQuant roles: full time, working remotely ..."
    for role, employer in roles:
        title = printed_title(role, tags) or role.title
        where = f"{title} at {employer}" if employer else title
        facts += [f"{where} ({role.dates}): {b}" for b, t in zip(role.bullets, role.tags) if t & wanted]
    for lines in paragraphs:
        joined = _strip_notes(" ".join(lines))
        if joined and "TODO" not in joined and "answering" not in joined:
            facts.append(joined)
    for name in ("Skills (confirmed)", "Projects", "Education", "Certifications"):
        facts += _bullets(sections.get(name, ""))

    basics = my_details(text)
    joined = "\n".join(facts)
    years = re.search(r"\bAbout (\d+(?:\.\d+)?) years\b", joined)
    return LetterFacts(
        facts=facts, skills=_skills_of(joined), years=float(years.group(1)) if years else None,
        name=basics.get("Name", ""), location=basics.get("Location"),
        contact=[basics[k] for k in ("Email", "Phone", "LinkedIn", "GitHub") if basics.get(k)],
    )


def _named_in_facts(facts: LetterFacts) -> list[str]:
    """Names your facts use: each skills-row item ("Claude Code" from "AI coding agents (Claude Code)") and the
    capitalized names in your bullets and certifications ("Zapier", "Slack")."""
    names: list[str] = []
    for fact in facts.facts:
        label, colon, row = fact.partition(": ")
        if colon and label in _SKILL_ROWS:
            for item in split_items(row):
                names += [item] + [x.strip() for x in re.sub(r"[()]", ",", item).split(",")]
        else:
            # A role's bullet comes after "<title> at <employer> (<dates>): "; its first word is a verb.
            text = row if colon and label.endswith(")") else fact
            names += [w for w in _capitalized_words(text) if w.lower()[:3] not in _MONTHS and w.lower() not in _GENERIC]
    return [n for n in dict.fromkeys(n.strip() for n in names) if len(n) > 1]


def posting_matches(posting: str, facts: LetterFacts) -> list[str]:
    """What the posting asks for that your facts have, in the facts' words ("Python", "Zapier", "Claude Code")."""
    found = []
    for name in _named_in_facts(facts):
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", posting, 0 if name != name.lower() else re.I):
            found.append(name)
    # Keep the longest: "Claude Code" covers "Claude".
    return [n for n in found if not any(n != m and n.lower() in m.lower() for m in found)]


def posting_gaps(posting: str, skills: set[str]) -> list[str]:
    """Known skills the posting asks for that the facts do not have, spelled as the posting spells it.

    A hint for the model, which may name other tools too (see valid_gap)."""
    gaps = []
    for name in sorted(set(extract_skills(posting)) - skills):
        m = _SKILL_RES[name].search(posting)
        gaps.append(m.group(0).strip() if m else name)
    return gaps


# --- the checks ----------------------------------------------------------------------------


@dataclass
class JobText:
    posting: str  # the title and description
    names: list[str]  # the job title and company as written: naming them claims nothing
    skills: set[str] = field(default_factory=set)
    company: str = ""

    @classmethod
    def of(cls, title: str, description: str, company: str) -> JobText:
        posting = f"{title}\n{description}"
        names = sorted({title, short_title(title), role_family(title), company} - {""}, key=len, reverse=True)
        return cls(posting, names, set(extract_skills(posting)), company)

    def without_names(self, text: str) -> str:
        for name in self.names:
            text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", " ", text, flags=re.I)
        return text


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(" ".join(str(text or "").split())) if s.strip()]


def _known_offsets_out(text: str, known: str) -> str:
    """"UTC+3" is a time zone, not a number to check, when your facts or the posting have it."""
    squeeze = known.upper().replace(" ", "")
    return _OFFSET.sub(lambda m: " " if m.group(0).upper().replace(" ", "") in squeeze else m.group(0), text)


def check_sentence(text: str, sources: list[str], facts: LetterFacts, job: JobText,
                   framing: bool) -> tuple[list[str], list[str]]:
    """(why this sentence cannot print, things to check by eye).

    `sources` are the facts it may draw on. `framing` is the opening or closing, where a sentence may
    also repeat the posting's numbers about the company, and one that is not about you ("I", "my")
    may name the posting's tools.
    """
    bare = _known_offsets_out(job.without_names(text), f"{facts.text} {job.posting}")
    about_me = not framing or bool(_FIRST_PERSON.search(bare))
    cited = " ".join(sources)
    problems: list[str] = []
    warnings: list[str] = []
    # "one" is mostly not a number in prose ("one of", "no one").
    for number, suffix, word in _number_context(re.sub(r"\bone\b", "a", bare, flags=re.I)):
        shown = f'"{number}{suffix}{" " + word if word else ""}"'
        if word in _YEARS and about_me:
            if facts.years is None or float(number) > int(facts.years):
                problems.append(f"claims {number}{suffix} years; the profile has about "
                                f"{facts.years if facts.years is not None else 'no stated'} years")
            continue
        if any(_fact_has(number, word, s) for s in sources) or (framing and _fact_has(number, word, job.posting)):
            continue
        problems.append(f"{shown} is not in {'your facts or the posting' if framing else 'the facts it cites'}")
    have = _skills_of(cited)
    for skill in extract_skills(bare):
        if about_me and skill not in have:
            problems.append(f'names "{skill}" in a sentence about you, and '
                            f'{"your facts do" if framing else "the facts it cites do"} not')
        elif not about_me and skill not in facts.skills and skill not in job.skills:
            problems.append(f'names "{skill}", which is in neither your facts nor the posting')
    if about_me:
        for word in _SENIORITY:
            if re.search(rf"\b{word}\b", bare, re.I) and not re.search(rf"\b{word}\b", cited, re.I):
                problems.append(f'says "{word}", which {"your facts do" if framing else "the facts it cites do"} not')
    facts_text, posting_text = facts.text.lower(), job.posting.lower()
    for token in dict.fromkeys(_capitalized_words(text)):
        low = token.lower()
        if low in facts_text or low in _CALENDAR or any(low in n.lower() for n in job.names) or _OFFSET.fullmatch(token):
            continue
        if low in posting_text:
            if about_me:
                warnings.append(f'"{token}" is from the posting, not your profile: check the sentence does not claim it')
        elif about_me:
            problems.append(f'names "{token}", which is in neither your profile nor the posting')
        else:
            warnings.append(f'"{token}" is in neither your profile nor the posting: check it')
    return problems, warnings


# --- the style check ---------------------------------------------------------------------------

_WRITER_PART = re.compile(r"<!-- writer:start -->(.*?)<!-- writer:end -->", re.S)
_DASH = re.compile(r"\s*—\s*|\s+–\s+")  # an em dash, or a spaced en dash ("2023–2026" is fine)
DASH_ISSUE = "uses a dash (—); use a comma, a colon or a full stop"
# A paragraph that opens by restating the posting: "The role calls for...", "You need...".
_MIRROR = re.compile(
    r"^(?:the|this|your) (?:role|position|posting|job(?: description)?)\b[^.]{0,30}?\b(?:calls? for|asks? for"
    r"|requires?|emphasi[sz]es|mentions|needs|wants|is looking for|looks for|values)\b"
    r"|^your team (?:needs|wants|values|is looking for)\b"
    r"|^you(?:'re| are| will)? (?:need|want|ask for|are looking for|look for)\b", re.I)
# "I'm applying for the X role": the header and the form already say which job, so it wastes the first line.
_ANNOUNCES = re.compile(
    r"\b(?:I(?:'m| am)|I(?:'d| would) like to|I want to|I wish to|I'm writing to|I am writing to) "
    r"(?:apply|applying|be considered)\b|\bmy application (?:for|to)\b", re.I)
# Logistics: time zone, notice, start date, where you are. The header shows the location; the rest is for the form.
_LOGISTICS_TALK = re.compile(
    r"\btime ?zones?\b|\b(?:UTC|GMT|CET|EET|EST|PST)\b|\bnotice\b|\bstart date\b|\bavailable to start\b"
    r"|\bcan start\b|\bbased (?:in|out of)\b|\b(?:work|working|live|living) (?:remotely )?from\b|\bhours overlap\b"
    r"|\boverlap with\b", re.I)
ANNOUNCES_ISSUE = "announces the application; the reader knows the job. Open with why you fit it"
LOGISTICS_ISSUE = "talks logistics (time zone, notice, location); leave those to the CV header and the form"
_ING_TAIL = re.compile(r",\s+([a-z]+ing)\b[^,]*$", re.I)
# -ing words that are not an add-on clause after a comma.
_NOT_ADD_ON = {"including", "during", "according", "regarding", "following", "nothing", "something", "anything",
               "everything", "engineering", "testing", "backtesting", "trading", "pricing", "hiring", "onboarding",
               "tooling", "logging", "monitoring", "string", "thing", "spring", "morning", "bring"}


@dataclass
class Style:
    """How letters read: the writer's part of config/cover_letter_guidelines.md and its two word lists."""
    text: str = ""
    never: list[str] = field(default_factory=list)
    at_most_one: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path) -> Style:
        """An empty Style when the file is missing: letters are then written with the fact rules only."""
        try:
            whole = Path(path).read_text()
        except (OSError, TypeError):
            return cls()
        m = _WRITER_PART.search(whole)
        text = m.group(1).strip() if m else ""
        return cls(text, _items_under(text, "Never use"), _items_under(text, "Use at most one"))


def _items_under(text: str, heading: str) -> list[str]:
    """The "- item" lines under the ### heading that starts with `heading`; the dash has its own check."""
    m = re.search(rf"^### {re.escape(heading)}[^\n]*\n(.*?)(?=^#|\Z)", text, re.S | re.M)
    items = [line[2:].strip() for line in (m.group(1) if m else "").splitlines() if line.startswith("- ")]
    return [i for i in items if i and i not in {"—", "–"}]


def check_style(text: str, sources: list[str], job: JobText, style: Style,
                framing: bool) -> tuple[list[str], list[str], list[str]]:
    """(problems, style issues, "Use at most one" words) for one sentence.

    Problems are a "Never use" phrase, a sentence that announces the application ("I'm applying for"),
    logistics in the opening or closing (time zone, notice, location) and, in a paragraph, an opening that
    restates the posting: like a fact problem, sent back once and then the sentence is left out. Style issues are sent back once and
    then only noted. A phrase that is in the facts the sentence cites is allowed.
    """
    text = text.replace("’", "'")
    low = job.without_names(text).lower()
    cited = " ".join(sources).lower().replace("’", "'")

    def uses(phrase: str) -> bool:
        phrase = phrase.lower()
        return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", low)) and phrase not in cited

    problems = [f'uses "{p}", which is on the "Never use" list' for p in style.never if uses(p)]
    if _ANNOUNCES.search(text):
        problems.append(ANNOUNCES_ISSUE)
    if framing and _LOGISTICS_TALK.search(text):
        problems.append(LOGISTICS_ISSUE)
    company = re.escape(job.company) if job.company else None
    if not framing and (_MIRROR.search(text) or (company and re.match(
            rf"{company}(?:'s)? (?:values|needs|wants|is looking|asks|expects)\b", text, re.I))):
        problems.append("opens by restating the posting; start with what the engineer did")
    issues = [DASH_ISSUE] if _DASH.search(text) else []
    tail = _ING_TAIL.search(text.rstrip(".!? "))
    if tail and tail.group(1).lower() not in _NOT_ADD_ON and f", {tail.group(1).lower()}" not in cited:
        issues.append(f'ends with a ", {tail.group(1)} ..." add-on; make it its own sentence or cut it')
    if "!" in text or "?" in text:
        issues.append("has an exclamation mark or a question")
    return problems, issues, [w for w in style.at_most_one if uses(w)]


def undash(text: str) -> str:
    return re.sub(r",\s*,", ",", _DASH.sub(", ", text)).replace(", .", ".")


# --- what the model wrote, after the checks -------------------------------------------------


@dataclass
class Checked:
    text: str
    problems: list[str]  # facts or "Never use": sent back once, then the sentence is left out
    warnings: list[str]
    style: list[str] = field(default_factory=list)  # sent back once, then only noted
    at_most_one: list[str] = field(default_factory=list)  # the "Use at most one" words it uses


@dataclass
class Letter:
    opening: list[Checked]
    paragraphs: list[list[Checked]]
    closing: list[Checked]
    gaps: list[str]  # the posting's spelling, chosen by the model from posting_gaps
    notes: list[str] = field(default_factory=list)  # the model's own notes to you
    removed: list[str] = field(default_factory=list)  # sentences the checks took out, with why
    missing: list[str] = field(default_factory=list)  # what the answer lacks as a whole: sent back once
    words: int = 0  # what the model wrote, before the gap sentence

    def parts(self) -> list[list[Checked]]:
        return [self.opening, *self.paragraphs, self.closing]

    @property
    def problems(self) -> list[str]:
        return self.missing + [f'"{_short(c.text)}": {"; ".join(c.problems)}'
                               for part in self.parts() for c in part if c.problems]

    @property
    def style_issues(self) -> list[str]:
        """Sent back once with the problems; what is left after that is only noted."""
        whole = []
        once = list(dict.fromkeys(w for part in self.parts() for c in part if not c.problems for w in c.at_most_one))
        if len(once) > 1:
            listed = _join([f'"{w}"' for w in once], "and")
            whole.append(f'uses {listed}; use at most one word from the "Use at most one" list')
        return whole + [f'"{_short(c.text)}": {"; ".join(c.style)}'
                        for part in self.parts() for c in part if c.style and not c.problems]

    @property
    def to_fix(self) -> list[str]:
        """Everything the model is told when its answer is sent back."""
        long = [f"the letter is {self.words} words; keep it to 150-250, never over {MAX_WORDS}"] \
            if self.words > MAX_WORDS else []
        return self.problems + long + self.style_issues

    @property
    def warnings(self) -> list[str]:
        mine = (w for part in self.parts() for c in part if not c.problems for w in c.warnings)
        return list(dict.fromkeys([*mine, *self.style_issues]))

    def drop_failed(self) -> None:
        """After the last try: leave out what still breaks a rule, and turn a dash into a comma."""
        for part in self.parts():
            for c in [c for c in part if c.problems]:
                self.removed.append(f'"{c.text}" ({"; ".join(c.problems)})')
                part.remove(c)
            for c in part:
                if DASH_ISSUE in c.style:
                    c.text = undash(c.text)
                    c.style.remove(DASH_ISSUE)
        self.paragraphs = [p for p in self.paragraphs if p]


def _short(text: str) -> str:
    return f'{text[:90]}{"…" if len(text) > 90 else ""}'


def letter_from(answer: dict, facts: LetterFacts, job: JobText, gaps: list[str], style: Style | None = None) -> Letter:
    style = style or Style()

    def check(text: str, sources: list[str], framing: bool) -> list[Checked]:
        checked = []
        for s in sentences(text):
            problems, warnings = check_sentence(s, sources, facts, job, framing)
            more, issues, once = check_style(s, sources, job, style, framing)
            checked.append(Checked(s, problems + more, warnings, issues, once))
        return checked

    paragraphs = []
    for item in (answer.get("paragraphs") or [])[:MAX_PARAGRAPHS]:
        item = item if isinstance(item, dict) else {"text": item}  # DeepSeek may send plain strings
        ids = [i for i in dict.fromkeys(item.get("facts") or []) if isinstance(i, int) and 1 <= i <= len(facts.facts)]
        part = check(str(item.get("text") or ""), [facts.facts[i - 1] for i in ids], framing=False)
        if not ids:
            for c in part:
                c.problems.append("its paragraph cites none of the numbered facts")
        paragraphs.append(part)
    spelled = {g.lower(): g for g in gaps}
    chosen = []
    for item in answer.get("gaps") or []:
        item = " ".join(str(item).split()).strip(" .,;")
        if (item.lower() in spelled or valid_gap(item, facts, job)) and gap_matters(item, facts, job):
            chosen.append(spelled.get(item.lower(), item))
    letter = Letter(
        opening=check(str(answer.get("opening") or ""), facts.facts, framing=True),
        paragraphs=[p for p in paragraphs if p],
        closing=check(str(answer.get("closing") or ""), facts.facts, framing=True),
        gaps=list(dict.fromkeys(chosen))[:MAX_GAPS],  # anything else is dropped: never claimed, never denied
        notes=[" ".join(str(n).split()) for n in answer.get("notes") or [] if str(n).strip()][:3],
    )
    letter.words = _words_of(" ".join(c.text for part in letter.parts() for c in part))
    if not letter.paragraphs:
        letter.missing.append("the answer has no paragraphs")
    return letter


def valid_gap(item: str, facts: LetterFacts, job: JobText) -> bool:
    """A gap may be named when the posting says it word for word and shares no word with your facts.

    The second part keeps the letter from denying something you did: "event-driven systems" is not a
    gap when a fact says "event-driven"."""
    item = " ".join(item.split()).strip(" .,;")
    if not item or len(item.split()) > 4 or len(item) > 40:
        return False
    in_posting = re.search(rf"(?<![A-Za-z0-9]){re.escape(item)}(?![A-Za-z0-9])", job.posting, re.I)
    fact_words = set(re.findall(r"[a-z0-9]+", facts.text.lower()))
    shared = [w for w in re.findall(r"[a-z0-9]+", item.lower()) if len(w) >= 3 and w in fact_words]
    return bool(in_posting) and not shared and not set(extract_skills(item)) & facts.skills


def gap_matters(item: str, facts: LetterFacts, job: JobText) -> bool:
    """Worth saying you lack: it is in the job title or the posting names it twice, and your facts have no
    work close to it (see _CLOSE_TO). A one-off "nice to have" is never named."""
    pattern = rf"(?<![A-Za-z0-9]){re.escape(item)}(?![A-Za-z0-9])"
    title = job.posting.split("\n", 1)[0]
    central = bool(re.search(pattern, title, re.I)) or len(re.findall(pattern, job.posting, re.I)) >= 2
    facts_text = facts.text.lower()
    close = any(item.lower() in names and any(n in facts_text for n in near) for names, near in _CLOSE_TO.items())
    return central and not close


def _join(items: list[str], word: str) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} {word} {items[-1]}"


def gap_sentence(gaps: list[str], template: str) -> str:
    """"I have not worked with Kafka or Kubernetes yet, ..." ("or": the sentence says no)."""
    return template.format(gaps=_join(gaps, "or"), them="it" if len(gaps) == 1 else "them") if gaps else ""


# --- the model -----------------------------------------------------------------------------

SYSTEM = f"""\
You write the middle of a cover letter from a software engineer for one job \
posting. Code adds the contact lines, the date, the greeting and the sign-off, \
and checks every sentence you write against the engineer's numbered facts.

Return:
- opening: 1 or 2 sentences.
- paragraphs: 1 or 2 body paragraphs. facts: the numbers of the facts each \
paragraph uses. "Asked for and in the facts" helps you pick the main story; you \
do not need to name every item.
- gaps: 0 or {MAX_GAPS} tool or skill the posting requires that is not in the \
facts, written exactly as the posting writes it ("Asked for, not in the facts" \
lists some). Code adds one plain sentence saying the engineer has not worked \
with it, and drops a gap that the posting names only once outside the title, or \
that is close to work in the facts. Never mention a gap yourself.
- closing: 1 or 2 sentences.
- notes: 1 to 3 short lines for the engineer (see "Notes to the engineer").

Hard rules. Code removes a sentence that breaks one:
- About the engineer, use only the numbered facts. Never add a tool, language, \
number, team size, employer, title, result, years, responsibility, feeling or \
motive that is not in them. The posting's requirements describe the job, not the \
engineer.
- A number about the engineer appears exactly as in a fact, with the word that \
follows it in the fact ("800+ concurrent jobs"). A number about the company only \
in the opening or closing, exactly as the posting gives it.
- Never call the engineer senior, staff, principal or an architect unless a fact does.
- Never mention how many years of experience the posting asks for.
- No phrase from the "Never use" list below, and no body paragraph sentence that \
restates the posting ("The role calls for...", "You need...").

How the letter should read:

"""


def system_prompt(style: Style) -> str:
    """The rules code checks, then the guidelines file's part for the writer."""
    if not style.text:
        return SYSTEM + "Plain, specific, confident words. 150 to 250 words in all. No buzzwords, no dashes.\n"
    return SYSTEM + style.text + "\n"

SCHEMA = {
    "type": "object",
    "properties": {
        "opening": {"type": "string"},
        "paragraphs": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "facts": {"type": "array", "items": {"type": "integer"}}},
            "required": ["text", "facts"], "additionalProperties": False,
        }},
        "gaps": {"type": "array", "items": {"type": "string"}},
        "closing": {"type": "string"},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["opening", "paragraphs", "gaps", "closing", "notes"],
    "additionalProperties": False,
}

EXAMPLE = json.dumps({
    "opening": "...", "paragraphs": [{"text": "...", "facts": [4, 5]}, {"text": "...", "facts": [11]}],
    "gaps": ["Kafka"], "closing": "...", "notes": ["..."],
})


def _prompt(job, company: str, facts: LetterFacts, gaps: list[str]) -> str:
    posting = f"{job['title']}\n{job['description'] or ''}"
    return "\n".join([
        f"Job: {job['title']} at {company}", "",
        "The posting (use it to decide what matters; nothing in it is a fact about the engineer):",
        (job["description"] or "(no description)")[:MAX_POSTING_CHARS], "",
        "Asked for and in the facts: " + (", ".join(posting_matches(posting, facts)) or "(none found)"),
        "Asked for, not in the facts (found by code; there may be others): " + (", ".join(gaps) or "(none found)"), "",
        "Facts about the engineer (the only things you may say about them):",
        *[f"{n}. {fact}" for n, fact in enumerate(facts.facts, 1)],
    ])


class CoverWriter:
    def __init__(self, model: JsonModel, style: Style | None = None):
        self.model = model
        self.style = style if style is not None else Style.load(GUIDELINES_FILE)

    def write(self, job, company: str, facts: LetterFacts, gaps: list[str]) -> tuple[Letter, Usage, int]:
        job_text = JobText.of(job["title"] or "", job["description"] or "", company)
        messages: list[dict] = [{"role": "user", "content": _prompt(job, company, facts, gaps)}]
        usage = Usage()
        letter, attempt = None, 0
        for attempt in (1, 2):
            answer = self.model.ask(system_prompt(self.style), messages, SCHEMA, usage, EXAMPLE)
            letter = letter_from(answer, facts, job_text, gaps, self.style)
            if not letter.to_fix:
                break
            messages += [
                {"role": "assistant", "content": json.dumps(answer)},
                {"role": "user", "content": "Fix these and answer again with the whole JSON. Code removes a "
                    "sentence that still breaks a fact or \"Never use\" rule: " + "; ".join(letter.to_fix) + "."},
            ]
        letter.drop_failed()
        return letter, usage, attempt


def cover_model(config: OutreachConfig) -> str:
    return config.cover_model or config.cv_model


def build_cover_writer(config: OutreachConfig, claude=None) -> tuple[CoverWriter | None, str | None]:
    model, note = json_model(cover_model(config), "Cover letters", claude=claude)
    return (CoverWriter(model, Style.load(config.cover_guidelines)), None) if model else (None, note)


# --- the file ------------------------------------------------------------------------------

_TITLE_NOISE = re.compile(r"\s*[(\[][^)\]]*(?:remote|m/f|f/m|w/m|/d\b)[^)\]]*[)\]]|\s+[-–—|]\s+remote\b.*$", re.I)


def letter_title(title: str) -> str:
    """'Backend Engineer (Remote, m/f/d)' -> 'Backend Engineer'. The rest of the title stays as posted."""
    return _TITLE_NOISE.sub("", title).strip() or title


def body_of(letter: Letter, gap_text: str) -> list[str]:
    """The letter's paragraphs: what survived the check, the gap sentence, and a plain closing when it is empty.

    No opening survived: the first body paragraph opens the letter. A stock "I'm applying for ..." line
    would only repeat the header."""
    opening = " ".join(c.text for c in letter.opening)
    body = [" ".join(c.text for c in part) for part in letter.paragraphs]
    gap = gap_sentence(letter.gaps, gap_text)
    if gap:
        body = body[:-1] + [f"{body[-1]} {gap}"] if body else [gap]
    closing = " ".join(c.text for c in letter.closing) or "Thanks for reading."
    return [p for p in (opening, *body, closing) if p]


def render_letter(body: list[str], facts: LetterFacts, company: str, title: str, now: datetime) -> str:
    day = now.astimezone()
    head = [facts.name, " | ".join(facts.contact), f"{facts.location} (Remote)" if facts.location else ""]
    return "\n".join([
        *[h for h in head if h], "",
        f"{day:%B} {day.day}, {day:%Y}", "",
        f"{company} Hiring Team", letter_title(title), "",
        f"Dear {company} Hiring Team,", "",
        "\n\n".join(body), "",
        "Best regards,", facts.name,
    ]) + "\n"


def _words_of(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9][\w'+.-]*", text))


def _new_name(folder: Path, last_name: str, company: str, now: datetime) -> str:
    """Doe_CoverLetter_Acme_Oct2026.md, with _2, _3... when that name is taken (never overwrite one by hand)."""
    base = f"{last_name or 'Me'}_CoverLetter_{_camel(company)[:30] or 'Company'}_{now:%b%Y}"
    name, n = f"{base}.md", 1
    while (folder / name).exists():
        n += 1
        name = f"{base}_{n}.md"
    return name


def cover_of(app) -> dict | None:
    return json.loads(app["cover_letter_json"]) if app is not None and app["cover_letter_json"] else None


def letter_text(config: OutreachConfig, meta: dict | None) -> str | None:
    """The letter as it is on disk now (you may have edited it), else as it was written."""
    if not meta:
        return None
    path = Path(config.cv_dir).expanduser() / Path(meta["file"]).name
    try:
        return path.read_text()
    except OSError:
        return meta.get("text")


def cover_for_job(store: JobStore, job_id: int, writer: CoverWriter, profile_path: Path, config: OutreachConfig,
                  now: datetime) -> dict:
    """Write cv_dir/<name>.md and store it with the job. Writing the same job again rewrites its own file."""
    job = store.get(job_id)
    if job is None:
        raise CoverError(f"no job #{job_id}")
    company, _ = clean_company_name(job["company"])
    tags = job_tags(job["title"], job["description"] or "", {**TAG_RULES, **(config.cv_tags or {})})
    facts = load_letter_facts(profile_path, tags)
    if not facts.facts or not facts.name:
        raise CoverError("profile/master_profile.md has no name or no facts to write from")
    gaps = posting_gaps(f"{job['title']}\n{job['description'] or ''}", facts.skills)
    app = tracking.ensure_application(store, job_id, now)
    old = cover_of(app)
    store.commit()  # no write lock held during the model call

    letter, usage, attempts = writer.write(job, company, facts, gaps)
    if not letter.paragraphs:  # nothing worth sending: write no file, so the daily run tries again tomorrow
        why = "; ".join(letter.missing + letter.removed[:3]) or "the answer was empty"
        raise CoverError(f"No cover letter written: nothing in the answer passed the checks ({why[:400]})")
    body = body_of(letter, config.cover_gap_text)
    text = render_letter(body, facts, company, job["title"] or "", now)
    folder = Path(config.cv_dir).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    name = old["file"] if old else _new_name(folder, facts.name.split()[-1], company, now)
    path = folder / name
    path.write_text(text)

    words = _words_of(" ".join(body))
    notes = list(letter.notes)
    if not MIN_WORDS <= words <= MAX_WORDS:
        notes.append(f"It is {words} words; 150-250 reads best")
    if not writer.style.text:
        notes.append("Written without config/cover_letter_guidelines.md (not found), so only the fact rules applied")
    meta = {
        "file": name, "path": str(path), "words": words, "tags": tags,
        "gaps": gaps, "gaps_named": letter.gaps, "notes": notes, "removed": letter.removed,
        "warnings": letter.warnings, "model": writer.model.model, "cost_usd": usage.cost(writer.model.model) or 0.0,
        "attempts": attempts, "written_at": iso(now), "text": text,
    }
    store.conn.execute("UPDATE applications SET cover_letter_json = ?, updated_at = ? WHERE job_id = ?",
                       (json.dumps(meta), iso(now), job_id))
    tracking.add_event(store, job_id, "cover", f"Cover letter written: {name}" + (" (again)" if old else ""), now)
    store.commit()
    return meta
