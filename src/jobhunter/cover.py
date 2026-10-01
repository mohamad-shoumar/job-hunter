"""A cover letter for one job: your profile's facts, checked sentence by sentence.

The model writes the opening, one or two paragraphs and the closing. Code
writes the rest (your name and contact lines, the date, "Dear <Company>
Hiring Team,", the sign-off) and checks every sentence the model wrote
against profile/master_profile.md, the only source of facts about you (see
CLAUDE.md):

  - the facts it may use are the ones the tailored CV prints for this job:
    the summary, the Experience bullets for the job's tags (cv.job_tags, the
    same [core]/[lead]/... rules), skills, education, certifications, and
    where you live and work from (never the salary line);
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
    posting, and not in your facts), and code writes one plain sentence
    saying you have not worked with them (cover_gap_text).

A letter that breaks a rule is sent back once with the reasons. A sentence
that still breaks one is left out, and the app says what was removed and
why. The letter is plain text next to the CVs in cv_dir, named like
Shoumar_CoverLetter_Acme_Oct2026.md, to paste into a form or upload.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import tracking
from .config import OutreachConfig
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
MAX_GAPS = 3
MAX_PARAGRAPHS = 3
# A letter outside this range still prints, with a note.
MIN_WORDS, MAX_WORDS = 180, 420
# Logistics lines a letter may use. Never "Compensation expectations".
_LOGISTICS = ("Lives in", "Time zone", "Notice period")
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
    for name in ("Skills (confirmed)", "Education", "Certifications"):
        facts += _bullets(sections.get(name, ""))
    facts += [b for b in _bullets(sections.get("Work authorization and logistics", "")) if b.startswith(_LOGISTICS)]

    basics = {k: v.strip() for k, v in re.findall(r"^- (Name|Email|Phone|LinkedIn|GitHub|Location): (.+)$", text, re.M)
              if "TODO" not in v}
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

    @classmethod
    def of(cls, title: str, description: str, company: str) -> JobText:
        posting = f"{title}\n{description}"
        names = sorted({title, short_title(title), role_family(title), company} - {""}, key=len, reverse=True)
        return cls(posting, names, set(extract_skills(posting)))

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


# --- what the model wrote, after the checks -------------------------------------------------


@dataclass
class Checked:
    text: str
    problems: list[str]
    warnings: list[str]


@dataclass
class Letter:
    opening: list[Checked]
    paragraphs: list[list[Checked]]
    closing: list[Checked]
    gaps: list[str]  # the posting's spelling, chosen by the model from posting_gaps
    notes: list[str] = field(default_factory=list)  # the model's own notes to you
    removed: list[str] = field(default_factory=list)  # sentences the fact check took out, with why
    missing: list[str] = field(default_factory=list)  # what the answer lacks as a whole: sent back once

    def parts(self) -> list[list[Checked]]:
        return [self.opening, *self.paragraphs, self.closing]

    @property
    def problems(self) -> list[str]:
        return self.missing + [f'"{c.text[:90]}{"…" if len(c.text) > 90 else ""}": {"; ".join(c.problems)}'
                               for part in self.parts() for c in part if c.problems]

    @property
    def warnings(self) -> list[str]:
        return list(dict.fromkeys(w for part in self.parts() for c in part if not c.problems for w in c.warnings))

    def drop_failed(self) -> None:
        for part in self.parts():
            for c in [c for c in part if c.problems]:
                self.removed.append(f'"{c.text}" ({"; ".join(c.problems)})')
                part.remove(c)
        self.paragraphs = [p for p in self.paragraphs if p]


def letter_from(answer: dict, facts: LetterFacts, job: JobText, gaps: list[str]) -> Letter:
    def check(text: str, sources: list[str], framing: bool) -> list[Checked]:
        return [Checked(s, *check_sentence(s, sources, facts, job, framing)) for s in sentences(text)]

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
        if item.lower() in spelled or valid_gap(item, facts, job):
            chosen.append(spelled.get(item.lower(), item))
    letter = Letter(
        opening=check(str(answer.get("opening") or ""), facts.facts, framing=True),
        paragraphs=[p for p in paragraphs if p],
        closing=check(str(answer.get("closing") or ""), facts.facts, framing=True),
        gaps=list(dict.fromkeys(chosen))[:MAX_GAPS],  # anything else is dropped: never claimed, never denied
        notes=[" ".join(str(n).split()) for n in answer.get("notes") or [] if str(n).strip()][:3],
    )
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


def _join(items: list[str], word: str) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} {word} {items[-1]}"


def gap_sentence(gaps: list[str], template: str) -> str:
    """"I have not worked with Kafka or Kubernetes yet, ..." ("or": the sentence says no)."""
    return template.format(gaps=_join(gaps, "or"), them="it" if len(gaps) == 1 else "them") if gaps else ""


# --- the model -----------------------------------------------------------------------------

SYSTEM = f"""\
You write the middle of a cover letter from a software engineer for one job \
posting. Code adds the contact lines, the date, "Dear <Company> Hiring Team," and \
the sign-off, and checks every sentence you write against the engineer's \
numbered facts.

Return:
- opening: 2 or 3 sentences. Start with something specific from the posting: \
what the company does, a problem this role solves, or a number the posting gives \
about the company. Name the role. Do not start with "I" or "I am writing".
- paragraphs: 2 paragraphs of 3 or 4 sentences. Each connects one or two of \
the posting's main requirements to what the engineer did, with the facts' own \
numbers. Name every item of "Asked for and in the facts" that matters for the \
role, with the posting's own word for it. facts: the numbers of the facts the \
paragraph uses.
- gaps: the 1 to {MAX_GAPS} most important tools or skills the posting asks for \
that are not in the facts, each written exactly as the posting writes it ("Asked \
for, not in the facts" lists some; read the requirements for others). Empty only \
when the facts cover every requirement. Code adds one honest sentence saying the \
engineer has not worked with them. Do not mention them yourself.
- closing: 2 sentences: what the engineer would bring to this team and an \
invitation to talk, then thanks. Nothing new about the engineer.
- notes: 1 to 3 short lines telling the engineer what you led with and why.

Hard rules. Code removes a sentence that breaks one:
- About the engineer, use only the numbered facts. Never add a tool, language, \
number, team size, employer, title, result, years or responsibility that is not \
in them. The posting's requirements describe the job, not the engineer.
- A number about the engineer appears exactly as in a fact, next to the same \
words ("800+ concurrent Python jobs"). A number about the company only in the \
opening or closing, exactly as the posting gives it.
- Never call the engineer senior, staff, principal or an architect unless a fact does.
- Never mention how many years of experience the posting asks for.
- At least 250 and at most 350 words in all. Plain, specific, confident words. No buzzwords \
("passionate", "leverage", "cutting-edge", "synergy"), no exclamation marks, no \
questions.
"""

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
    def __init__(self, model: JsonModel):
        self.model = model

    def write(self, job, company: str, facts: LetterFacts, gaps: list[str]) -> tuple[Letter, Usage, int]:
        job_text = JobText.of(job["title"] or "", job["description"] or "", company)
        messages: list[dict] = [{"role": "user", "content": _prompt(job, company, facts, gaps)}]
        usage = Usage()
        letter, attempt = None, 0
        for attempt in (1, 2):
            answer = self.model.ask(SYSTEM, messages, SCHEMA, usage, EXAMPLE)
            letter = letter_from(answer, facts, job_text, gaps)
            if not letter.problems:
                break
            messages += [
                {"role": "assistant", "content": json.dumps(answer)},
                {"role": "user", "content": "Code will remove these sentences, because they break the rules: "
                    + "; ".join(letter.problems) + ". Answer again with the whole JSON, fixing them."},
            ]
        letter.drop_failed()
        return letter, usage, attempt


def cover_model(config: OutreachConfig) -> str:
    return config.cover_model or config.cv_model


def build_cover_writer(config: OutreachConfig, claude=None) -> tuple[CoverWriter | None, str | None]:
    model, note = json_model(cover_model(config), "Cover letters", claude=claude)
    return (CoverWriter(model), None) if model else (None, note)


# --- the file ------------------------------------------------------------------------------

_TITLE_NOISE = re.compile(r"\s*[(\[][^)\]]*(?:remote|m/f|f/m|w/m|/d\b)[^)\]]*[)\]]|\s+[-–—|]\s+remote\b.*$", re.I)


def letter_title(title: str) -> str:
    """'Backend Engineer (Remote, m/f/d)' -> 'Backend Engineer'. The rest of the title stays as posted."""
    return _TITLE_NOISE.sub("", title).strip() or title


def body_of(letter: Letter, company: str, title: str, gap_text: str) -> list[str]:
    """The letter's paragraphs: what survived the check, the gap sentence, and a plain line where a part is empty."""
    opening = " ".join(c.text for c in letter.opening) or f"I am applying for the {letter_title(title)} role at {company}."
    body = [" ".join(c.text for c in part) for part in letter.paragraphs]
    gap = gap_sentence(letter.gaps, gap_text)
    if gap:
        body = body[:-1] + [f"{body[-1]} {gap}"] if body else [gap]
    closing = " ".join(c.text for c in letter.closing) or "Thank you for your time and consideration."
    return [opening, *body, closing]


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
    """Shoumar_CoverLetter_Acme_Oct2026.md, with _2, _3... when that name is taken (never overwrite one by hand)."""
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
        raise CoverError(f"No cover letter written: nothing in the answer passed the fact check ({why[:400]})")
    body = body_of(letter, company, job["title"] or "", config.cover_gap_text)
    text = render_letter(body, facts, company, job["title"] or "", now)
    folder = Path(config.cv_dir).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    name = old["file"] if old else _new_name(folder, facts.name.split()[-1], company, now)
    path = folder / name
    path.write_text(text)

    words = _words_of(" ".join(body))
    notes = list(letter.notes)
    if not MIN_WORDS <= words <= MAX_WORDS:
        notes.append(f"It is {words} words; {MIN_WORDS}-{MAX_WORDS} reads best")
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
