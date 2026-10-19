"""A cover letter for one job: two paragraphs, only when you ask for one.

  1. Why you want to join this company: written by the model (DeepSeek) from
     the posting and a few pages code fetches from the company's website
     (its home page, /about, /blog). Code checks every sentence:
       - about the company, every number and name must be in the posting or
         those pages, so a product or customer the model made up is caught;
       - about you ("I", "my"), only tools and numbers in your profile facts
         (the ones the tailored CV prints for this job), never more years
         than the profile has, never "senior" unless a fact says it;
       - the "Never use" list in config/cover_letter_guidelines.md, and no
         "I'm applying for" or logistics (time zone, notice, location);
       - the model quotes the words its reason rests on, and code looks for
         them in the posting and pages (`find_quote`).
     A sentence that still breaks a rule after one retry is left out, and the
     app says why. Length (2-3 sentences, at most 65 words) is sent back once,
     then only noted.
  2. Your own paragraph, `cover_paragraph` in config/outreach.json, printed
     word for word and never checked: you wrote it.

How paragraph 1 reads is the writer part of config/cover_letter_guidelines.md.
Code writes the rest (your name and contact lines, the date, "Dear <Company>
Hiring Team,", the sign-off). The letter is plain text next to the CVs in
cv_dir, named like Doe_CoverLetter_Acme_Oct2026.md, to paste or upload.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import tracking
from .config import OutreachConfig, my_details
from .contacts import clean_company_name, domain_from_links, job_company, skip_list_match
from .cv import TAG_RULES, Role, _camel, _sections, job_tags, parse_titles, printed_title
from .extract import extract_skills
from .llm import JsonModel, Usage, find_quote, json_model
from .pitch import (
    _SENIORITY, _capitalized_words, _fact_has, _number_context, _strip_notes, role_family, short_title, split_tags,
)
from .store import JobStore
from .text import iso

MAX_POSTING_CHARS = 6000
MAX_PAGE_CHARS = 3000
# The company's pages code reads, in order: the home page first (nothing else is tried when it fails).
SITE_PATHS = ("", "/about", "/blog")
MAX_WORDS = 65
MIN_SENTENCES, MAX_SENTENCES = 2, 3
GUIDELINES_FILE = Path(__file__).resolve().parents[2] / "config" / "cover_letter_guidelines.md"
_FIRST_PERSON = re.compile(r"\b(?:I|I'm|I've|I'd|I'll|my|me|mine|myself)\b", re.I)
_YEARS = {"year", "years", "yr", "yrs"}
_OFFSET = re.compile(r"\b(?:UTC|GMT)\s?[+\-−]\s?\d{1,2}(?::\d\d)?", re.I)
_CALENDAR = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
             "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday"}
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
# What kind of company it is: easy to make up in plain words ("a fintech consultancy"), so each must be in the
# posting or the pages (or, in a sentence about you, your facts).
_COMPANY_KIND = re.compile(
    r"\b(?:consultanc(?:y|ies)|consulting|agency|agencies|start-?ups?|scale-?ups?|fintech|healthtech|edtech|"
    r"insurtech|proptech|legaltech|regtech|non-?profit|bank|marketplace|unicorn|open[- ]source|B2B|B2C|SaaS|"
    r"family-owned|bootstrapped|venture-backed|VC-backed|Series [A-E]|public company|publicly traded)\b", re.I)


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


# --- the research ----------------------------------------------------------------------------


@dataclass
class Research:
    pages: list[tuple[str, str]]  # (url, readable text) code fetched from the company's site
    note: str = ""  # why there are none, for you


def _mentions(text: str, company: str) -> bool:
    """Names the company, with or without its legal words ("Valsoft" for Valsoft Corporation)."""
    names = {company, " ".join(_LEGAL.sub(" ", company).split())} - {""}
    return any(re.search(rf"(?<![A-Za-z0-9]){re.escape(n)}(?![A-Za-z0-9])", text, re.I) for n in names)


def company_site(domain: str, company: str, http, guessed: bool = False) -> list[tuple[str, str]]:
    """The site's home page, /about and /blog as code reads them; a page that repeats one already read is left out.

    A guessed domain (acme.com for Acme) counts only when its home page names the company."""
    from .ai_check import fetch_page

    pages: list[tuple[str, str]] = []
    for path in SITE_PATHS:
        url = f"https://{domain}{path}"
        page = fetch_page(url, http)
        if page is None:
            if not path:
                return []
            continue
        text = page[0][:MAX_PAGE_CHARS]
        if not path and guessed and not _mentions(text, company):
            return []
        if all(text != seen for _, seen in pages):
            pages.append((url, text))
    return pages


def research(store: JobStore, job, config: OutreachConfig, http, now: datetime) -> Research:
    """The company's own pages: from its known domain, the links in the job, else <name>.com."""
    row = job_company(store, job, now)
    name = row["name"]
    if row["is_job_board"] or skip_list_match(name, config):
        return Research([], f"{name} is a job board or agency, so paragraph 1 is from the posting only")
    if http is None:
        return Research([], "No pages fetched, so paragraph 1 is from the posting only")
    domain = row["domain"] or domain_from_links(job["company"], [job["application_url"] or "", job["source_url"] or "",
                                                                 job["description"] or ""])
    tries = [(domain, False)] if domain else [(f"{guess}.com", True) for guess in _guesses(name)]
    for domain, guessed in tries:
        if pages := company_site(domain, name, http, guessed):
            return Research(pages)
    tried = ", ".join(d for d, _ in tries)
    return Research([], f"Could not read {name}'s website{f' ({tried})' if tried else ''}, so paragraph 1 is "
                        "from the posting only")


_LEGAL = re.compile(r"\b(?:inc|corp|corporation|co|company|llc|ltd|limited|plc|gmbh|ag|bv|sa|sarl|wll|fz-?llc|"
                    r"group|holdings?)\b\.?", re.I)


def _guesses(name: str) -> list[str]:
    """acmecorporation, then acme: the name run together, then without its legal words."""
    names = [name, _LEGAL.sub(" ", name)]
    return [g for g in dict.fromkeys(re.sub(r"[^a-z0-9]", "", n.lower()) for n in names) if g]


# --- the checks ----------------------------------------------------------------------------


@dataclass
class JobText:
    posting: str  # the title and description, then the pages code fetched: what may be said about the company
    names: list[str]  # the job title and company as written: naming them claims nothing
    skills: set[str] = field(default_factory=set)
    company: str = ""

    @classmethod
    def of(cls, title: str, description: str, company: str, pages: list[tuple[str, str]] = ()) -> JobText:
        posting = "\n".join([title, description, *(text for _, text in pages)])
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


def _kind_pattern(kind: str) -> str:
    """"startups" also matches "start-up", "open source" "open-source"."""
    letters = re.sub(r"[- ]", "", kind)
    letters = letters[:-3] if letters.endswith("ies") else letters[:-1] if letters.endswith("ups") else letters
    return r"\b" + "[- ]?".join(map(re.escape, letters))


def check_sentence(text: str, facts: LetterFacts, job: JobText) -> list[str]:
    """Why this sentence cannot print (empty when it can).

    About the company it may repeat the posting and the pages; a sentence about you ("I", "my") names only
    tools your facts have. Every number and every name must be in your facts, the posting or the pages."""
    bare = _known_offsets_out(job.without_names(text), f"{facts.text} {job.posting}")
    about_me = bool(_FIRST_PERSON.search(bare))
    problems: list[str] = []
    # "one" is mostly not a number in prose ("one of", "no one").
    for number, suffix, word in _number_context(re.sub(r"\bone\b", "a", bare, flags=re.I)):
        if word in _YEARS and about_me:
            if facts.years is None or float(number) > int(facts.years):
                problems.append(f"claims {number}{suffix} years; the profile has about "
                                f"{facts.years if facts.years is not None else 'no stated'} years")
            continue
        if any(_fact_has(number, word, s) for s in facts.facts) or _fact_has(number, word, job.posting):
            continue
        problems.append(f'"{number}{suffix}{" " + word if word else ""}" is in neither your facts nor the posting '
                        "or the company's pages")
    for skill in extract_skills(bare):
        if about_me and skill not in facts.skills:
            problems.append(f'names "{skill}" in a sentence about you, and your facts do not')
        elif not about_me and skill not in facts.skills and skill not in job.skills:
            problems.append(f'names "{skill}", which is in neither your facts nor the posting')
    if about_me:
        for word in _SENIORITY:
            if re.search(rf"\b{word}\b", bare, re.I) and not re.search(rf"\b{word}\b", facts.text, re.I):
                problems.append(f'says "{word}", which your facts do not')
    said = job.posting.lower() + (f"\n{facts.text.lower()}" if about_me else "")
    for kind in dict.fromkeys(m.group(0).lower() for m in _COMPANY_KIND.finditer(bare)):
        if not re.search(_kind_pattern(kind), said):
            problems.append(f'says "{kind}", which the posting and the company\'s pages do not')
    known = f"{facts.text}\n{job.posting}".lower()
    for token in dict.fromkeys(_capitalized_words(text)):
        low = token.lower()
        if low in known or low in _CALENDAR or any(low in n.lower() for n in job.names) or _OFFSET.fullmatch(token):
            continue
        problems.append(f'names "{token}", which is in neither your profile nor the posting or the company\'s pages')
    return problems


# --- the style check ---------------------------------------------------------------------------

_WRITER_PART = re.compile(r"<!-- writer:start -->(.*?)<!-- writer:end -->", re.S)
_DASH = re.compile(r"\s*—\s*|\s+[–-]\s+")  # an em dash, or a spaced en dash or hyphen ("end-to-end" is fine)
DASH_ISSUE = "uses a dash (—); use a comma, a colon or a full stop"
# "I'm applying for the X role": the header and the form already say which job, so it wastes the first line.
_ANNOUNCES = re.compile(
    r"\b(?:I(?:'m| am)|I(?:'d| would) like to|I want to|I wish to|I'm writing to|I am writing to) "
    r"(?:apply|applying|be considered)\b|\bmy application (?:for|to)\b", re.I)
# Logistics: time zone, notice, start date, where you are. The header shows the location; the rest is for the form.
_LOGISTICS_TALK = re.compile(
    r"\btime ?zones?\b|\b(?:UTC|GMT|CET|EET|EST|PST)\b|\bnotice\b|\bstart date\b|\bavailable to start\b"
    r"|\bcan start\b|\bbased (?:in|out of)\b|\b(?:work|working|live|living) (?:remotely )?from\b|\bhours overlap\b"
    r"|\boverlap with\b", re.I)
ANNOUNCES_ISSUE = "announces the application; the reader knows the job. Say why this company"
LOGISTICS_ISSUE = "talks logistics (time zone, notice, location); leave those to the CV header and the form"
_ING_TAIL = re.compile(r",\s+([a-z]+ing)\b[^,]*$", re.I)
# -ing words that are not an add-on clause after a comma.
_NOT_ADD_ON = {"including", "during", "according", "regarding", "following", "nothing", "something", "anything",
               "everything", "engineering", "testing", "backtesting", "trading", "pricing", "hiring", "onboarding",
               "tooling", "logging", "monitoring", "string", "thing", "spring", "morning", "bring"}


@dataclass
class Style:
    """How paragraph 1 reads: the writer's part of config/cover_letter_guidelines.md and its two word lists."""
    text: str = ""
    never: list[str] = field(default_factory=list)
    at_most_one: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path) -> Style:
        """An empty Style when the file is missing: the paragraph is then written with the fact rules only."""
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


def check_style(text: str, job: JobText, style: Style) -> tuple[list[str], list[str], list[str]]:
    """(problems, style issues, "Use at most one" words) for one sentence.

    Problems are a "Never use" phrase, a sentence that announces the application ("I'm applying for") and
    logistics (time zone, notice, location): like a fact problem, sent back once and then the sentence is
    left out. Style issues are sent back once and then only noted.
    """
    text = text.replace("’", "'")
    low = job.without_names(text).lower()

    def uses(phrase: str) -> bool:
        return bool(re.search(rf"(?<!\w){re.escape(phrase.lower())}(?!\w)", low))

    problems = [f'uses "{p}", which is on the "Never use" list' for p in style.never if uses(p)]
    if _ANNOUNCES.search(text):
        problems.append(ANNOUNCES_ISSUE)
    if _LOGISTICS_TALK.search(text):
        problems.append(LOGISTICS_ISSUE)
    issues = [DASH_ISSUE] if _DASH.search(text) else []
    tail = _ING_TAIL.search(text.rstrip(".!? "))
    if tail and tail.group(1).lower() not in _NOT_ADD_ON:
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
    style: list[str] = field(default_factory=list)  # sent back once, then only noted
    at_most_one: list[str] = field(default_factory=list)  # the "Use at most one" words it uses


@dataclass
class Opening:
    """Paragraph 1, sentence by sentence, and the words from the posting or a page its reason rests on."""
    sentences: list[Checked]
    quote: str = ""
    found_at: str | None = None  # where code found the quote: "the posting" or a page's URL
    notes: list[str] = field(default_factory=list)  # the model's own notes to you
    removed: list[str] = field(default_factory=list)  # sentences the checks took out, with why

    @property
    def text(self) -> str:
        return " ".join(c.text for c in self.sentences)

    @property
    def words(self) -> int:
        return _words_of(self.text)

    @property
    def problems(self) -> list[str]:
        if not self.sentences:
            return ["the paragraph is empty"]
        return [f'"{_short(c.text)}": {"; ".join(c.problems)}' for c in self.sentences if c.problems]

    @property
    def style_issues(self) -> list[str]:
        """Sent back once with the problems; what is left after that is only noted."""
        whole = []
        ok = [c for c in self.sentences if not c.problems]
        if ok and not MIN_SENTENCES <= len(ok) <= MAX_SENTENCES:
            whole.append(f"it has {len(ok)} sentences; write {MIN_SENTENCES} or {MAX_SENTENCES}")
        if self.words > MAX_WORDS:
            whole.append(f"it is {self.words} words; keep it to {MAX_WORDS} at most")
        once = list(dict.fromkeys(w for c in ok for w in c.at_most_one))
        if len(once) > 1:
            whole.append(f'uses {_join([f"{w!r}" for w in once], "and")}; use at most one word from the '
                         '"Use at most one" list')
        if self.sentences and not self.found_at:
            whole.append("the quote is not word for word in the posting or the pages: copy the exact words your "
                         "reason rests on")
        return whole + [f'"{_short(c.text)}": {"; ".join(c.style)}' for c in ok if c.style]

    @property
    def to_fix(self) -> list[str]:
        return self.problems + self.style_issues

    def drop_failed(self) -> None:
        """After the last try: leave out what still breaks a rule, and turn a dash into a comma."""
        for c in [c for c in self.sentences if c.problems]:
            self.removed.append(f'"{c.text}" ({"; ".join(c.problems)})')
            self.sentences.remove(c)
        for c in self.sentences:
            if DASH_ISSUE in c.style:
                c.text = undash(c.text)
                c.style.remove(DASH_ISSUE)


def _short(text: str) -> str:
    return f'{text[:90]}{"…" if len(text) > 90 else ""}'


def _join(items: list[str], word: str) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} {word} {items[-1]}"


def opening_from(answer: dict, facts: LetterFacts, job: JobText, sources: list[tuple[str, str]],
                 style: Style | None = None) -> Opening:
    """sources: (where, text) the quote may come from: the posting, then each page code fetched."""
    style = style or Style()
    checked = []
    for s in sentences(answer.get("paragraph")):
        more, issues, once = check_style(s, job, style)
        checked.append(Checked(s, check_sentence(s, facts, job) + more, issues, once))
    quote = " ".join(str(answer.get("quote") or "").split())
    return Opening(
        sentences=checked, quote=quote, found_at=find_quote(quote, sources) if quote else None,
        notes=[" ".join(str(n).split()) for n in answer.get("notes") or [] if str(n).strip()][:2],
    )


# --- the model -----------------------------------------------------------------------------

SYSTEM = """\
You write the first paragraph of a software engineer's cover letter: why they \
want to join this company. Code adds the greeting, then a second paragraph the \
engineer wrote, then the sign-off, and checks every sentence you write.

Return:
- paragraph: the paragraph.
- quote: the exact words, copied from the posting or one of the company's pages, \
that your one reason rests on (at least 4 words). Code looks for them there.
- notes: 0 to 2 short lines for the engineer: the detail you picked and where it was.

Hard rules. Code removes a sentence that breaks one:
- About the company, say only what the posting or the company's pages say. Never \
name a product, customer, number, tool, person or blog post that is not in them, \
and never say what kind of company it is (a consultancy, a startup, fintech, \
SaaS) unless they do.
- About the engineer, use only the listed facts. Never add a tool, number, \
employer, title, years, feeling or habit that is not in them, and never merge \
two facts into one claim (a team the engineer leads and a system they built are \
separate facts).
- No phrase from the "Never use" list below. Never announce the application or \
talk about time zone, notice or location.

How the paragraph should read:

"""


def system_prompt(style: Style) -> str:
    """The rules code checks, then the guidelines file's part for the writer."""
    if not style.text:
        return SYSTEM + "2 or 3 plain sentences, at most 65 words, one specific reason. No buzzwords, no dashes.\n"
    return SYSTEM + style.text + "\n"


SCHEMA = {
    "type": "object",
    "properties": {
        "paragraph": {"type": "string"},
        "quote": {"type": "string"},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["paragraph", "quote", "notes"],
    "additionalProperties": False,
}

EXAMPLE = json.dumps({"paragraph": "...", "quote": "...", "notes": ["..."]})


def _prompt(job, company: str, facts: LetterFacts, pages: list[tuple[str, str]], second: str) -> str:
    lines = [
        f"Job: {job['title']} at {company}", "",
        "The posting:", (job["description"] or "(no description)")[:MAX_POSTING_CHARS], "",
        "The company's own pages, as code fetched them (your only research):",
    ]
    for url, text in pages:
        lines += [f"--- {url} ---", text]
    if not pages:
        lines.append("(none could be read: work from the posting only)")
    lines += ["", "Facts about the engineer (the only things you may say about them):",
              *[f"- {fact}" for fact in facts.facts]]
    if second:
        lines += ["", "The second paragraph, which the engineer wrote and which follows yours word for word "
                      "(do not repeat it):", second]
    return "\n".join(lines)


class CoverWriter:
    def __init__(self, model: JsonModel, style: Style | None = None, http=None):
        self.model = model
        self.style = style if style is not None else Style.load(GUIDELINES_FILE)
        self.http = http  # reads the company's pages; None reads none

    def write(self, job, company: str, facts: LetterFacts, pages: list[tuple[str, str]],
              second: str = "") -> tuple[Opening, Usage, int]:
        job_text = JobText.of(job["title"] or "", job["description"] or "", company, pages)
        sources = [("the posting", f"{job['title'] or ''}\n{job['description'] or ''}"), *pages]
        messages: list[dict] = [{"role": "user", "content": _prompt(job, company, facts, pages, second)}]
        usage = Usage()
        opening, attempt = None, 0
        for attempt in (1, 2):
            answer = self.model.ask(system_prompt(self.style), messages, SCHEMA, usage, EXAMPLE, max_tokens=1024)
            opening = opening_from(answer, facts, job_text, sources, self.style)
            if not opening.to_fix:
                break
            messages += [
                {"role": "assistant", "content": json.dumps(answer)},
                {"role": "user", "content": "Fix these and answer again with the whole JSON. Code removes a "
                    "sentence that still breaks a fact or \"Never use\" rule: " + "; ".join(opening.to_fix) + "."},
            ]
        opening.drop_failed()
        return opening, usage, attempt


def cover_model(config: OutreachConfig) -> str:
    return config.cover_model or config.cv_model


def build_cover_writer(config: OutreachConfig, claude=None) -> tuple[CoverWriter | None, str | None]:
    from .http import Http

    model, note = json_model(cover_model(config), "Cover letters", claude=claude)
    if model is None:
        return None, note
    return CoverWriter(model, Style.load(config.cover_guidelines), Http(timeout=10, retries=0)), None


# --- the file ------------------------------------------------------------------------------


_TITLE_NOISE = re.compile(r"\s*[(\[][^)\]]*(?:remote|m/f|f/m|w/m|/d\b)[^)\]]*[)\]]|\s+[-–—|]\s+remote\b.*$", re.I)


def letter_title(title: str) -> str:
    """'Backend Engineer (Remote, m/f/d)' -> 'Backend Engineer'. The rest of the title stays as posted."""
    return _TITLE_NOISE.sub("", title).strip() or title


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
    found = research(store, job, config, writer.http, now)
    app = tracking.ensure_application(store, job_id, now)
    old = cover_of(app)
    store.commit()  # no write lock held while pages load and the model writes

    second = " ".join(config.cover_paragraph.split())
    opening, usage, attempts = writer.write(job, company, facts, found.pages, second)
    if not opening.sentences:  # nothing worth sending: write no file
        why = "; ".join(opening.removed[:3]) or "the answer was empty"
        raise CoverError(f"No cover letter written: nothing in paragraph 1 passed the checks ({why[:400]})")
    text = render_letter([p for p in (opening.text, second) if p], facts, company, job["title"] or "", now)
    folder = Path(config.cv_dir).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    name = old["file"] if old else _new_name(folder, facts.name.split()[-1], company, now)
    path = folder / name
    path.write_text(text)

    notes = list(opening.notes) + ([found.note] if found.note else [])
    if not second:
        notes.append("cover_paragraph in config/outreach.json is empty, so the letter has paragraph 1 only")
    if not writer.style.text:
        notes.append("Written without config/cover_letter_guidelines.md (not found), so only the fact rules applied")
    meta = {
        "file": name, "path": str(path), "words": _words_of(opening.text), "tags": tags,
        "pages": [url for url, _ in found.pages], "quote": opening.quote, "quote_found_at": opening.found_at,
        "notes": notes, "removed": opening.removed, "warnings": opening.style_issues,
        "model": writer.model.model, "cost_usd": usage.cost(writer.model.model) or 0.0,
        "attempts": attempts, "written_at": iso(now), "text": text,
    }
    store.conn.execute("UPDATE applications SET cover_letter_json = ?, updated_at = ? WHERE job_id = ?",
                       (json.dumps(meta), iso(now), job_id))
    tracking.add_event(store, job_id, "cover", f"Cover letter written: {name}" + (" (again)" if old else ""), now)
    store.commit()
    return meta
