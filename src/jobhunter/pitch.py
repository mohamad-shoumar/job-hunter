"""The cold email. By default fixed text from config/outreach.json (pitch_mode "fixed"):

    Subject: <title> - <your name>

    Hi <first name>,

    Saw you are looking for a <title>. In three years at a trading firm I went from full-stack developer to leading a team of 5, building the platforms the firm runs on: 800+ concurrent jobs and 115+ AI workflows in production.

    What's the best next step — a screening call or a technical task? I can turn either around this week.

    <your name>
    <city> · <phone> · LinkedIn (a link)     (MY_* in .env)

With pitch_mode "ai", the model writes the sentence after "Saw you are looking
for a <title>." instead, and the checks below apply to it.

The model gets the profile's experience, skills and education as numbered
facts (never the phone or salary lines) and says which facts it used. Then
plain code checks the line against profile/master_profile.md, the only
source of facts about you (see CLAUDE.md):

  - every number is in a cited fact, next to the same word
    ("800+ concurrent jobs" passes; "5 engineers" passes, "5 years" does not);
  - years of experience never above the profile's ("About 3.3 years" -> 3);
  - skills named are skills in the profile;
  - seniority words (senior, staff, principal, ...) are in the profile.

A draft that fails is retried once with the reasons. If it still fails it is
saved with the problems shown and cannot be sent until you edit it. The
daily run never overwrites a draft you edited.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import tracking
from .config import OutreachConfig, my_details
from .contacts import ROLE_LABELS, chosen_contact, clean_company_name
from .extract import extract_skills
from .llm import Usage, model_params
from .store import JobStore
from .text import iso

log = logging.getLogger(__name__)

# Profile sections the email may draw on. Basics (phone), logistics (salary) never.
_FACT_SECTIONS = ("Summary of experience", "Experience", "Skills (confirmed)", "Education")
_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
    "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "twenty": "20", "fifty": "50", "hundred": "100",
}
_NUMBER_RE = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*(\+|%|k\b|x\b)?", re.I)
_SENIORITY = ("senior", "staff", "principal", "architect", "head", "manager", "cto", "director", "vp", "chief", "lead")
MAX_AI_WORDS = 25
# Words a subject may use besides the job title, the company and profile words.
_PLAIN_WORDS = {"role", "with", "from", "years", "year", "your", "about", "remote"}


# --- the profile ----------------------------------------------------------------


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


def _strip_notes(line: str) -> str:
    return re.sub(r"\s*\((?:Confirmed by me|mohamad answering)[^)]*\)\.?", "", line).strip()


_TAGS = re.compile(r"^\[([a-z][a-z, ]*)\]\s*")


def split_tags(text: str) -> tuple[frozenset[str], str]:
    """'[fullstack, lead] Built ...' -> ({'fullstack', 'lead'}, 'Built ...'). A bullet with no tag is core."""
    m = _TAGS.match(text)
    if not m:
        return frozenset({"core"}), text
    return frozenset(t.strip() for t in m.group(1).split(",") if t.strip()), text[m.end():].strip()


def load_profile(path: Path) -> Profile:
    text = path.read_text()
    basics = my_details(text)
    sections = re.split(r"^## ", text, flags=re.M)
    facts: list[str] = []
    for section in sections:
        title, _, body = section.partition("\n")
        if title.strip() not in _FACT_SECTIONS:
            continue
        role = ""
        for raw in body.splitlines():
            line = _strip_notes(raw.strip())
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
    profile.skills = set(extract_skills(profile.facts_text))
    m = re.search(r"\bAbout (\d+(?:\.\d+)?) years\b", profile.facts_text)
    profile.years = float(m.group(1)) if m else None
    if re.search(r"\bdistributed\b", profile.facts_text, re.I):  # stated as "distributed/backend systems"
        profile.skills.add("distributed systems")
    return profile


def _link(value: str | None) -> str | None:
    value = (value or "").strip()
    return None if not value or "TODO" in value else value


# --- the fact guard ---------------------------------------------------------------


def _digits(text: str) -> str:
    return re.sub(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b", lambda m: _NUMBER_WORDS[m.group(1).lower()], text,
                  flags=re.I)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _stem(word: str) -> str:
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


def _number_context(text: str) -> list[tuple[str, str, str | None]]:
    """(number, its suffix, the word right after it): "800+ concurrent" -> ("800", "+", "concurrent")."""
    digits = _digits(text)
    found = []
    for m in _NUMBER_RE.finditer(digits):
        after = _words(digits[m.end():])
        found.append((m.group(1).replace(",", ""), m.group(2) or "", after[0] if after else None))
    return found


def _fact_has(number: str, word: str | None, fact: str) -> bool:
    """The fact has this number with `word` among the next four words ("800+ concurrent Python jobs")."""
    for m in _NUMBER_RE.finditer(_digits(fact)):
        if m.group(1).replace(",", "") != number:
            continue
        after = {_stem(w) for w in _words(_digits(fact)[m.end():])[:4]}
        if word is None or _stem(word) in after:
            return True
    return False


def _capitalized_words(text: str) -> list[str]:
    """Capitalized words that do not start a sentence: likely names of tools or companies.

    Only the sentence's first word is skipped, so in "I used Workato" the name still counts.
    """
    words = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        sentence = sentence.lstrip("\"'“‘(")
        words += [m.group(0) for m in re.finditer(r"\b[A-Z][\w.#+-]*[\w#+]", sentence) if m.start() > 0]
    return words


def check_draft(subject: str, hook: str, pitch: str, evidence_ids: list[int], profile: Profile, posting: str,
                job_skills: set[str], names: list[str], one_fact: bool = False) -> tuple[list[str], list[str]]:
    """one_fact (AI lines): a line with a number cites one fact, and names only that fact's skills."""
    """(problems that block sending, soft warnings)."""
    problems: list[str] = []
    warnings: list[str] = []
    cited = [profile.facts[i - 1] for i in evidence_ids if 1 <= i <= len(profile.facts)] or profile.facts
    for number, suffix, word in _number_context(f"{pitch} {subject}"):
        if word in ("year", "years", "yr", "yrs"):
            if profile.years is None or float(number) > int(profile.years):
                problems.append(f'claims {number}{suffix} years; the profile has about '
                                f'{profile.years if profile.years is not None else "no stated"} years')
            continue
        if not any(_fact_has(number, word, fact) for fact in cited):
            problems.append(f'"{number}{suffix}{" " + word if word else ""}" is not in the profile facts it cites')
    for skill in extract_skills(pitch):
        if skill not in profile.skills:
            problems.append(f'names "{skill}", which is not in your profile')
    if one_fact and _number_context(pitch):
        real = [i for i in evidence_ids if 1 <= i <= len(profile.facts)]
        if len(real) != 1:
            problems.append("the line must come from exactly one fact, so its number belongs to what it describes")
        else:
            fact_skills = set(extract_skills(profile.facts[real[0] - 1]))
            for skill in extract_skills(pitch):
                if skill in profile.skills and skill not in fact_skills:
                    problems.append(f'names "{skill}", which is not in the fact it cites (#{real[0]})')
    for skill in extract_skills(f"{subject} {hook}"):
        if skill not in profile.skills and skill not in job_skills:
            problems.append(f'names "{skill}", which is in neither your profile nor the posting')
    facts_words = set(_words(profile.facts_text))
    facts_stems = {_stem(w) for w in facts_words}
    title_words = {_stem(w) for w in _words(" ".join([posting.split("\n", 1)[0], profile.name, *names]))}
    for word in _words(subject):
        if len(word) > 3 and not word.isdigit() and _stem(word) not in facts_stems | title_words | _PLAIN_WORDS:
            problems.append(f'the subject says "{word}", which is not in your profile')
    for word in _SENIORITY:
        if re.search(rf"\b{word}\b", pitch, re.I) and word not in facts_words:
            problems.append(f'says "{word}", which is not in your profile')
    posting_words = set(_words(_digits(posting)))
    for number, _, _ in _number_context(hook):
        if number.replace(".", "") not in posting_words:
            problems.append(f'the number "{number}" in the hook is not in the posting')
    known = " ".join([profile.facts_text, posting, profile.name, *names]).lower()
    for token in _capitalized_words(pitch):
        if token.lower() not in known and token not in ("I", "I'm", "I've"):
            warnings.append(f'"{token}" is not in your profile or the posting; check it')
    words = len(_words(pitch))
    if words > MAX_AI_WORDS:
        warnings.append(f"the proof line is {words} words; keep it under {MAX_AI_WORDS}")
    return problems, warnings


# --- writing ----------------------------------------------------------------------

SYSTEM = """\
You write ONE line for a very short cold email from a software engineer to a \
person at a company that posted a job. Code writes everything else (greeting, \
"Saw you are looking for a <role>.", the ask, the signature, and a separate \
line about leading a team). So write only the proof line.

The line: one sentence, at most 18 words, the single most relevant thing the \
engineer built for this role, taken from ONE fact, with that fact's own \
number, in the form \
"I built <what, in plain words>: <number and what it counts>." Examples:
- "I built and run an AI automation platform: 115+ workflows."
- "I built a serverless AWS platform: 800+ concurrent Python jobs, zero production failures."
{angle}

Hard rules:
- Use only the numbered facts. Never add a skill, tool, employer, title, \
number or claim that is not in them. Never say "senior".
- Do not mention leading a team or years of experience (code adds those).
- Plain words, no buzzwords, no exclamation marks, no questions.
Also return evidence_ids: the numbers of the facts you used.
"""

_PLAIN_MATCH = (
    "The reader is in HR or recruiting and is not an engineer. They check three things: does the job title match, "
    "how many years, and does the engineer have the technologies the posting asks for. Say exactly that in everyday "
    "words: a job title from the facts, the years, two to four of the posting's required technologies that are also "
    "in the facts, and one simple sign of scope such as leading a team. No internal project names or jargon "
    "(no \"backtesting\", \"slippage\", \"validation gates\", \"pipelines\")."
)
_OWNER = (
    "The reader is the founder or CEO. They want someone who owns work end to end. Give one or two things the "
    "engineer built and owned, with a number if the facts have one, in plain words, picking what is closest to what "
    "this company does. Describe work by what it does, not by internal names or jargon: not 'backtesting platform' "
    "or 'LLM automation flow', but e.g. 'a platform that tests trading strategies on market data'."
)
_TECHNICAL = (
    "The reader leads engineering. Give one concrete technical proof that matches the posting's stack or problems: "
    "what was built, with what, at what scale. One sharp detail beats a list."
)
_ANGLES = {
    "ceo": _OWNER, "founder": _OWNER,
    "cto": _TECHNICAL, "eng_lead": _TECHNICAL, "eng_manager": _TECHNICAL,
    "recruiter": _PLAIN_MATCH, "hr": _PLAIN_MATCH,
}
_DEFAULT_ANGLE = ("The reader may not be an engineer. Say plainly which job title, years and required technologies "
                  "from the posting the engineer has, plus one proof with a number.")

SCHEMA = {
    "type": "object",
    "properties": {
        "pitch": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["pitch", "evidence_ids"],
    "additionalProperties": False,
}


@dataclass
class Draft:
    subject: str
    hook: str
    pitch: str
    evidence_ids: list[int]
    problems: list[str]
    warnings: list[str]
    model: str
    cost_usd: float
    attempts: int


class PitchWriter:
    subject_template = "{title} - {name}"

    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def _ask(self, system: str, messages: list[dict], usage: Usage) -> dict:
        params = model_params(self.model)
        output_config = {**params.pop("output_config", {}), "format": {"type": "json_schema", "schema": SCHEMA}}
        response = self.client.messages.create(model=self.model, max_tokens=1024, system=system, messages=messages,
                                               output_config=output_config, **params)
        usage.add(response.usage)
        text = next((b.text if not isinstance(b, dict) else b["text"] for b in response.content
                     if (b.get("type") if isinstance(b, dict) else b.type) == "text"), "{}")
        try:
            data = json.loads(text)
        except ValueError:
            data = {}
        return data

    def write(self, profile: Profile, job: sqlite3.Row, contact: sqlite3.Row | None) -> Draft:
        role = _field(contact, "role")
        system = SYSTEM.format(angle="Pick for this reader: " + _ANGLES.get(role, _DEFAULT_ANGLE))
        facts = "\n".join(f"{n}. {fact}" for n, fact in enumerate(profile.facts, 1))
        company, _ = clean_company_name(job["company"])
        reader = (f"{contact['full_name']}, {contact['position'] or ROLE_LABELS.get(contact['role'], '')}"
                  if contact else "someone at the company")
        posting = f"{job['title']}\n{job['description'] or ''}"
        messages: list[dict] = [{"role": "user", "content": "\n".join([
            f"Role: {job['title']}", f"Company: {company}", f"Reader: {reader}", "",
            "The posting (use it to pick what matters; its words are not facts about the engineer):",
            (job["description"] or "(no description)")[:4000], "",
            "Facts about the engineer (the only ones you may use):", facts,
        ])}]
        usage = Usage()
        job_skills = set(extract_skills(posting))
        names = [company] + ([contact["full_name"]] if contact else [])
        hook = opening(job["title"])
        subject = subject_for(job["title"], profile, self.subject_template)
        data: dict = {}
        problems: list[str] = []
        warnings: list[str] = []
        attempts = 0
        for attempts in (1, 2):
            data = self._ask(system, messages, usage)
            problems, warnings = check_draft(
                subject, hook, str(data.get("pitch") or ""),
                [int(i) for i in data.get("evidence_ids") or [] if isinstance(i, int)], profile, posting,
                job_skills, names, one_fact=True,
            )
            if not data.get("pitch"):
                problems = problems or ["the model returned no pitch"]
            if not problems:
                break
            messages += [
                {"role": "assistant", "content": json.dumps(data)},
                {"role": "user", "content": "These break the rules: " + "; ".join(problems)
                    + ". Write it again using only the numbered facts."},
            ]
        return Draft(
            subject=subject,
            hook=hook,
            pitch=" ".join(str(data.get("pitch") or "").split()),
            evidence_ids=[i for i in data.get("evidence_ids") or [] if isinstance(i, int)],
            problems=problems, warnings=warnings, model=self.model, cost_usd=usage.cost(self.model) or 0.0,
            attempts=attempts,
        )


# --- the email ----------------------------------------------------------------------


def linkedin_url(profile: Profile) -> str | None:
    if not profile.linkedin:
        return None
    url = profile.linkedin if profile.linkedin.startswith("http") else "https://www." + profile.linkedin.removeprefix("www.")
    return url.rstrip("/") + "/"


def signature(profile: Profile) -> str:
    """Name, then "Lisbon · +15550107788 · LinkedIn <url>". The HTML copy turns LinkedIn into a link."""
    url = linkedin_url(profile)
    phone = profile.phone.replace(" ", "") if profile.phone else None
    details = " · ".join(x for x in (profile.city, phone, f"LinkedIn <{url}>" if url else None) if x)
    return profile.name + (f"\n{details}" if details else "")


def _field(contact, name: str):
    return contact[name] if contact is not None and name in contact.keys() else None


def greeting(contact: sqlite3.Row | None, company: str) -> str:
    first = (_field(contact, "first_name") or "").strip()
    return f"Hi {first}," if first else f"Hi {company} team,"


_TITLE_TAIL = re.compile(r"\s*[(\[][^)\]]*[)\]]|\s+[-–—|:/]\s+.*$")
_SENIORITY_PREFIX = re.compile(r"\b(?:senior|sr\.?|junior|jr\.?|mid[- ]level|lead|staff|principal)\s+", re.I)


def short_title(title: str) -> str:
    """'Backend Engineer - Python [Remote / Global]' -> 'Backend Engineer'."""
    short = _TITLE_TAIL.sub("", title or "").strip()
    short = re.sub(r"^(?:remote|fully remote)\s+", "", short, flags=re.I)
    return short or (title or "").strip()


def role_family(title: str) -> str:
    """'Senior Backend Engineer' -> 'Backend Engineer'."""
    return _SENIORITY_PREFIX.sub("", short_title(title)).strip() or short_title(title)


def subject_for(title: str, profile: Profile, template: str = "{title} - {name}") -> str:
    return template.format(title=short_title(title), name=profile.name)


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def opening(title: str) -> str:
    role = short_title(title)
    return f"Saw you are looking for {_article(role)} {role}."


_DEFAULT_ASK = "What's the best next step — a screening call or a technical task? I can turn either around this week."


def assemble(pitch: str, contact, company: str, title: str, profile: Profile, ask_text: str = "") -> str:
    ask = (ask_text or _DEFAULT_ASK).format(company=company, title=short_title(title))
    return "\n\n".join(x for x in [
        greeting(contact, company), f"{opening(title)} {pitch}".strip(), ask, signature(profile),
    ] if x)


def to_plain(body: str) -> str:
    """The plain-text copy: "LinkedIn <url>" reads as "LinkedIn: url"."""
    return re.sub(r"LinkedIn <(https?://[^>\s]+)>", r"LinkedIn: \1", body)


def to_html(body: str) -> str:
    """The HTML twin of a plain-text body: same words, "LinkedIn <url>" becomes a link."""
    import html

    text = html.escape(body)
    text = re.sub(r"LinkedIn &lt;(https?://[^&\s]+)&gt;", r'<a href="\1">LinkedIn</a>', text)
    paragraphs = text.split("\n\n")
    return "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs)


# --- the CV ----------------------------------------------------------------------------


def cv_options(config: OutreachConfig) -> list[str]:
    folder = Path(config.cv_dir).expanduser()
    return sorted(p.name for p in folder.glob("*.pdf")) if folder.is_dir() else []


def cv_for(config: OutreachConfig, company: str, chosen: str | None) -> Path | None:
    """The PDF to attach: the one picked in the app, else one named after the company, else the default."""
    options = cv_options(config)
    folder = Path(config.cv_dir).expanduser()
    if chosen == "none":
        return None
    if chosen in options:
        return folder / chosen
    key = re.sub(r"[^a-z0-9]", "", company.lower())
    named = [o for o in options if key and key in re.sub(r"[^a-z0-9]", "", o.lower())]
    if named:
        return folder / named[0]
    name = default_cv(config, options)
    return folder / name if name else None


def default_cv(config: OutreachConfig, options: list[str] | None = None) -> str | None:
    """default_cv from outreach.json, else the master CV build.py makes (<Last name>_Resume_General.pdf)."""
    options = cv_options(config) if options is None else options
    if config.default_cv:
        return config.default_cv if config.default_cv in options else None
    return next((o for o in options if o.endswith("_Resume_General.pdf")), None)


def follow_up(seq: int, subject: str, contact: sqlite3.Row | None, company: str, title: str,
              profile: Profile) -> tuple[str, str]:
    """(subject, body) of follow-up 1 or 2. Fixed text: nothing new is claimed."""
    subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    if seq == 1:
        line = (f"Bumping this in case it got buried. I'm still keen on the {title} role "
                "and happy to share more about my work.")
    else:
        line = (f"Last note from me on this one: if the {title} role is still open, I'd be glad to talk. "
                "If the timing is wrong, no worries.")
    return subject, "\n\n".join([greeting(contact, company), line, signature(profile)])


def word_count(text: str) -> int:
    return len(_words(text))


# --- storing drafts -------------------------------------------------------------------


def save_draft(store: JobStore, job_id: int, draft: Draft, contact: sqlite3.Row | None, profile: Profile,
               now: datetime, config: OutreachConfig | None = None) -> sqlite3.Row:
    job = store.get(job_id)
    app = tracking.ensure_application(store, job_id, now)
    company, _ = clean_company_name(job["company"])
    body = assemble(draft.pitch, contact, company, job["title"], profile, config.ask_text if config else "")
    meta = {"model": draft.model, "cost_usd": draft.cost_usd, "evidence_ids": draft.evidence_ids,
            "attempts": draft.attempts, "written_at": iso(now), "contact_id": contact["id"] if contact else None}
    store.conn.execute(
        """
        UPDATE applications SET subject = ?, hook = ?, pitch = ?, body = ?, draft_version = draft_version + 1,
            draft_edited = 0, draft_blocked = ?, draft_warnings_json = ?, draft_meta_json = ?,
            contact_id = COALESCE(?, contact_id), updated_at = ?
        WHERE job_id = ?
        """,
        (draft.subject, draft.hook, draft.pitch, body, 1 if draft.problems else 0,
         json.dumps(draft.problems + draft.warnings), json.dumps(meta), contact["id"] if contact else None,
         iso(now), job_id),
    )
    what = "Email drafted" + (" with problems: " + "; ".join(draft.problems) if draft.problems else "")
    tracking.add_event(store, job_id, "draft", what, now)
    return tracking.get_application(store, job_id)


def reassemble(store: JobStore, job_id: int, profile: Profile, now: datetime,
               config: OutreachConfig | None = None) -> None:
    """Rebuild an unedited draft's body after the contact or the CV changed. No AI call."""
    app = tracking.get_application(store, job_id)
    if not app or app["draft_edited"] or not app["pitch"]:
        return
    job = store.get(job_id)
    contact = (store.conn.execute("SELECT * FROM contacts WHERE id = ?", (app["contact_id"],)).fetchone()
               if app["contact_id"] else None)
    company, _ = clean_company_name(job["company"])
    body = assemble(app["pitch"], contact, company, job["title"], profile, config.ask_text if config else "")
    if body != app["body"]:
        store.conn.execute("UPDATE applications SET body = ?, draft_version = draft_version + 1, updated_at = ? "
                           "WHERE job_id = ?", (body, iso(now), job_id))


def edit_draft(store: JobStore, job_id: int, subject: str, body: str, profile: Profile, now: datetime) -> sqlite3.Row:
    """Your own edit. It unblocks sending (you wrote it), keeps soft warnings, and the daily run never overwrites it."""
    job = store.get(job_id)
    app = tracking.ensure_application(store, job_id, now)
    posting = f"{job['title']}\n{job['description'] or ''}"
    company, _ = clean_company_name(job["company"])
    # Sentences about them ("I saw you're hiring a senior...") are checked like the hook, the rest like the pitch.
    sentences = re.split(r"(?<=[.!?])\s+", _personal_part(body, profile, job["title"]).strip())
    about_them = " ".join(x for x in sentences if re.search(r"\byou(?:r|'re|'ve)?\b", x, re.I))
    about_you = " ".join(x for x in sentences if not re.search(r"\byou(?:r|'re|'ve)?\b", x, re.I))
    problems, warnings = check_draft(subject, about_them, about_you, [], profile, posting,
                                     set(extract_skills(posting)), [company])
    store.conn.execute(
        "UPDATE applications SET subject = ?, body = ?, draft_version = draft_version + 1, draft_edited = 1, "
        "draft_blocked = 0, draft_warnings_json = ?, updated_at = ? WHERE job_id = ?",
        (subject.strip(), body.strip(), json.dumps(problems + warnings), iso(now), job_id),
    )
    if not app["draft_edited"]:
        tracking.add_event(store, job_id, "draft", "Email edited by you", now)
    return tracking.get_application(store, job_id)


def _personal_part(body: str, profile: Profile, title: str) -> str:
    """The body minus the greeting, opening, ask and signature, for the soft check on your edits."""
    text = body.split(f"\n{profile.name}\n")[0] if f"\n{profile.name}\n" in body else body
    text = text.replace(opening(title), " ")
    text = re.sub(r"(?:Saw you are looking for [^.\n]*\.|15 minutes to talk through[^?\n]*\?|"
                  r"Happy to take a short trial task instead\.|Could (?:I|you) [^?\n]*\?|"
                  r"Would you be open to [^?\n]*\?)", " ", text)
    return re.sub(r"^\s*Hi [^,\n]*,?", " ", text)


def fixed_draft(job: sqlite3.Row, profile: Profile, config: OutreachConfig) -> Draft:
    """Your own text from config/outreach.json: no AI, no cost."""
    return Draft(subject=subject_for(job["title"], profile, config.subject_template), hook=opening(job["title"]),
                 pitch=config.pitch_text.strip(), evidence_ids=[], problems=[], warnings=[], model="fixed text",
                 cost_usd=0.0, attempts=0)


def draft_for_job(store: JobStore, job_id: int, writer: PitchWriter | None, profile: Profile, config: OutreachConfig,
                  now: datetime, force: bool = False) -> str:
    """Write (or rewrite) the draft for one job. Returns a short status line. `writer` is only used in "ai" mode."""
    app = tracking.get_application(store, job_id)
    if app and app["draft_edited"] and not force:
        return "kept your edited draft"
    if app and app["emailed_at"] and not force:
        return "already emailed"
    job = store.get(job_id)
    contact = chosen_contact(store, job, config)
    if config.pitch_mode != "ai":
        draft = fixed_draft(job, profile, config)
    else:
        if writer is None:
            raise tracking.TrackingError("pitch_mode is \"ai\" but no AI key is set")
        store.commit()  # no write lock held during the API call
        writer.subject_template = config.subject_template
        draft = writer.write(profile, job, contact)
    save_draft(store, job_id, draft, contact, profile, now, config)
    store.commit()
    return "drafted with problems" if draft.problems else "drafted"


DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
_JSON_NOTE = """

Answer with one JSON object only, exactly these keys:
{"pitch": "...", "evidence_ids": [1, 2]}"""


class DeepSeekPitchWriter(PitchWriter):
    """The same writer and fact guard, on DeepSeek's OpenAI-format API (JSON mode, thinking off)."""

    def __init__(self, api_key: str, model: str, http=None):
        import httpx

        super().__init__(None, model)
        self._key = api_key
        self._http = http or httpx.Client(timeout=90)

    def _ask(self, system: str, messages: list[dict], usage: Usage) -> dict:
        body = {
            "model": self.model, "max_tokens": 1024,
            "messages": [{"role": "system", "content": system + _JSON_NOTE}, *messages],
            "response_format": {"type": "json_object"}, "thinking": {"type": "disabled"},
        }
        response = self._http.post(DEEPSEEK_URL, json=body, headers={"Authorization": f"Bearer {self._key}"})
        response.raise_for_status()  # the key is in a header, never in the error text
        data = response.json()
        tokens = data.get("usage") or {}
        usage.add({"input_tokens": tokens.get("prompt_tokens"), "output_tokens": tokens.get("completion_tokens")})
        try:
            return json.loads(data["choices"][0]["message"]["content"] or "{}")
        except (KeyError, IndexError, ValueError):
            return {}


def build_writer(config: OutreachConfig, claude=None) -> tuple[PitchWriter | None, str | None]:
    """DeepSeek when pitch_model is a deepseek model, else Claude."""
    import os

    if config.pitch_model.startswith("deepseek"):
        key = os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            return None, "email drafts skipped: set DEEPSEEK_API_KEY in .env (pitch_model is DeepSeek)"
        return DeepSeekPitchWriter(key, config.pitch_model), None
    from .llm import anthropic_client

    client = claude or anthropic_client()
    if client is None:
        return None, "email drafts skipped: set ANTHROPIC_API_KEY in .env"
    return PitchWriter(client, config.pitch_model), None
