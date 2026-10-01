"""A CV tailored to one job: your profile's facts, in the layout of your resume.md.

The model only chooses, orders and rewords. Code writes the file and checks
every line against profile/master_profile.md, the only source of facts about
you (see CLAUDE.md):

  - the name, contact lines, employers, job titles, dates and education are
    copied from resume.md in resume_dir (resume/ in the project), never written
    by the model;
  - a role's bullets come from that role's bullets in the profile. Each
    bullet the model writes names the profile bullet(s) it rewords, from the
    same role, and is kept only when its numbers, tools, seniority words and
    names are in those bullets and it adds at most MAX_NEW_WORDS other words.
    Otherwise the profile's own wording is printed;
  - which bullets print is decided by code, from the profile's tags: "[core]"
    bullets always, an optional one ("[lead]", "[fullstack]", "[automation]"...)
    only when the job matches that tag (TAG_RULES, overridable as cv_tags in
    config/outreach.json; each match quotes what it matched). The model orders
    and rewords them; one it leaves out is printed anyway in the profile's words.
    A role's "Printed title:" line picks its title the same way. A CV still two
    pages long in the compact layout loses optional bullets, oldest role first,
    until it fits;
  - a skills row only holds skills from the profile row with the same label;
  - the headline is one of your target roles (or the profile's headline),
    optionally "<role> - <focus>" where the focus uses profile words only;
  - there is never a Summary section.

Rewrites that break a rule are sent back once with the reasons, like the
email. Profile bullets left out stay in the file as // comments, so you can
swap one in by hand. build.py in the resume folder turns the file into a PDF
(rebuilt with "compact: yes" if it spills onto a second page), and that PDF
becomes the job's attachment, which the app can show you.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import tracking
from .config import OutreachConfig
from .contacts import clean_company_name
from .extract import extract_skills
from .llm import JsonModel, Usage, json_model, key_note
from .pitch import (
    _SENIORITY, Profile, _capitalized_words, _fact_has, _number_context, _strip_notes, load_profile, role_family,
    split_tags,
)
from .store import JobStore
from .text import iso

MAX_NEW_WORDS = 4
MAX_BULLET_WORDS = 40
MAX_POSTING_CHARS = 6000
# When a job gets a profile tag's optional bullets: a phrase in its title, or in the posting.
# Matched as whole words, ignoring case, except that a phrase with a capital letter must match
# that case ("React" the library, not "react to incidents"). "leadership" alone is deliberately
# not a lead signal.
TAG_RULES: dict[str, dict[str, list[str]]] = {
    "lead": {
        "title": ["lead", "manager", "head of"],
        "posting": ["team lead", "tech lead", "technical lead", "lead a team", "leading a team", "lead the team",
                    "manage a team", "managing a team", "people management", "direct reports", "mentor",
                    "mentoring", "mentorship"],
    },
    "fullstack": {
        "title": ["full stack", "full-stack", "fullstack", "frontend", "front-end", "front end", "react", "next.js"],
        "posting": ["full stack", "full-stack", "fullstack", "React", "next.js", "nextjs", "frontend development",
                    "front-end development"],
    },
    "automation": {
        "title": ["automation", "ai", "llm", "agent", "agents", "agentic", "machine learning", "forward deployed",
                  "solutions engineer", "integration", "integrations"],
        "posting": ["llm", "llms", "large language model", "ai agent", "ai agents", "agentic", "genai",
                    "generative ai", "ai automation", "workflow automation", "process automation",
                    "business automation", "zapier", "n8n", "make.com", "slack api", "slack bot", "slack bots",
                    "slack app", "slack integration", "slack integrations", "rag", "prompt engineering"],
    },
    "mobile": {
        "title": ["mobile", "react native", "ios", "android"],
        "posting": ["react native", "mobile app", "mobile apps", "mobile application", "mobile development"],
    },
}
# Short words that say nothing new, so they never count as added words.
_STOP = {
    "with", "that", "from", "into", "across", "over", "their", "them", "this", "these", "those", "which", "while",
    "using", "used", "through", "within", "each", "every", "both", "also", "than", "then", "they", "were", "been",
    "being", "have", "more", "most", "such", "other", "like", "based", "around", "about", "after", "before",
    "under", "including", "where", "when", "what", "some", "only", "very",
}
_SUFFIXES = ("ations", "ation", "ating", "ated", "ates", "ings", "ing", "ers", "ed", "es", "er", "s")


class TailorError(tracking.TrackingError):
    """Shown to you as is."""


# --- the facts: profile roles and skills, matched to resume.md ------------------------


@dataclass(eq=False)
class Role:
    key: str  # "R1", as the model sees it
    title: str
    dates: str
    bullets: list[str]  # the profile's bullets: the only ones this role may print
    tags: list[frozenset[str]] = field(default_factory=list)  # each bullet's tags, same order
    # From "Printed title: Algorithmic Trader [default] · Team Lead [lead]": (title, its tags).
    titles: list[tuple[str, frozenset[str]]] = field(default_factory=list)


def parse_titles(text: str) -> list[tuple[str, frozenset[str]]]:
    out = []
    for part in text.split("·"):
        m = re.match(r"^(.*?)\s*\[([a-z][a-z, ]*)\]$", part.strip())
        if m:
            out.append((m.group(1).strip(), frozenset(t.strip() for t in m.group(2).split(","))))
        elif part.strip():
            out.append((part.strip(), frozenset({"default"})))
    return out


def split_items(row: str) -> list[str]:
    """'AWS (Lambda, SQS), Docker' -> ['AWS (Lambda, SQS)', 'Docker']: commas inside brackets stay."""
    items, depth, start = [], 0, 0
    for i, ch in enumerate(row):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            items.append(row[start:i])
            start = i + 1
    items.append(row[start:])
    return [x.strip() for x in items if x.strip()]


def _sections(text: str) -> dict[str, str]:
    sections = {}
    for part in re.split(r"^## ", text, flags=re.M)[1:]:
        title, _, body = part.partition("\n")
        sections[title.strip()] = body
    return sections


def load_facts(profile_path: Path) -> tuple[list[Role], dict[str, list[str]], list[str]]:
    """(roles newest first, skills rows by label, allowed headlines) from the profile."""
    text = profile_path.read_text()
    sections = _sections(text)
    roles: list[Role] = []
    for raw in sections.get("Experience", "").splitlines():
        line = _strip_notes(raw.strip())
        if line.startswith("### "):
            head, *rest = re.split(r"\s{2,}", line[4:].strip())
            roles.append(Role(f"R{len(roles) + 1}", head.split(" — ")[0].strip(), rest[0] if rest else "", []))
        elif line.lower().startswith("printed title:") and roles and "TODO" not in line:
            roles[-1].titles = parse_titles(line.split(":", 1)[1])
        elif line.startswith("- ") and roles and "TODO" not in line:
            tags, bullet = split_tags(line[2:].strip())
            roles[-1].bullets.append(bullet)
            roles[-1].tags.append(tags)
    skills = {}
    for raw in sections.get("Skills (confirmed)", "").splitlines():
        m = re.match(r"- ([^:]+): (.+)$", raw.strip())
        if m and "TODO" not in m.group(2):
            skills[m.group(1).strip()] = split_items(m.group(2))
    headlines = []
    m = re.search(r"^- Headline: (.+)$", text, re.M)
    for part in ([m.group(1)] if m else []) + re.split(r"[·\n]", sections.get("Target roles", "")):
        part = part.strip()
        if part and "TODO" not in part and part not in headlines:
            headlines.append(part)
    return [r for r in roles if r.bullets], skills, headlines


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", re.sub(r"\bsept\b", "sep", text.lower())))


def _match(roles: list[Role], title: str, dates: str) -> Role | None:
    """resume.md may print the real title or one of the role's printed titles."""
    same = [r for r in roles if _norm(title) in {_norm(r.title), *(_norm(t) for t, _ in r.titles)}]
    exact = [r for r in same if _norm(r.dates) == _norm(dates)]
    return exact[0] if exact else same[0] if len(same) == 1 else None


def scan(lines: list[str], roles: list[Role], skills: dict[str, list[str]]) -> tuple[dict[int, Role], dict[int, str]]:
    """Where resume.md holds each profile role (the index of its job-title line) and each skills row."""
    matched: dict[int, Role] = {}
    rows: dict[int, str] = {}
    section, header = "", None
    for i, raw in enumerate(lines):
        s = raw.strip()
        if not s or s.startswith("//"):
            continue
        if s.startswith("## "):
            section, header = s[3:].strip().lower(), None
        elif s.startswith("### "):
            header = s[4:]
        elif header is not None:
            # The line after "### CoinQuant, Abu Dhabi | Sept 2025 - Present" is the job title.
            if "experience" in section and not s.startswith("- "):
                role = _match(roles, s, header.partition("|")[2])
                if role and role not in matched.values():
                    matched[i] = role
            header = None
        elif "skill" in section and ":" in s and not s.startswith("- "):
            label = s.split(":", 1)[0].strip()
            if label in skills:
                rows[i] = label
    return matched, rows


# --- which bullets and titles this job gets ------------------------------------------------


def _phrase_in(phrase: str, text: str) -> bool:
    flags = 0 if phrase != phrase.lower() else re.I
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", text, flags) is not None


def job_tags(title: str, posting: str, rules: dict[str, dict[str, list[str]]] | None = None) -> dict[str, str]:
    """{tag: why} for the optional tags this job matches, e.g. {"lead": 'the title says "lead"'}."""
    title, posting = title or "", posting or ""
    found = {}
    for tag, rule in (rules or TAG_RULES).items():
        hit = next((p for p in rule.get("title", []) if _phrase_in(p, title)), None)
        if hit:
            found[tag] = f'the title says "{hit}"'
            continue
        hit = next((p for p in rule.get("posting", []) if _phrase_in(p, posting)), None)
        if hit:
            found[tag] = f'the posting says "{hit}"'
    return found


def select(roles: list[Role], tags) -> tuple[list[Role], dict[str, list[str]]]:
    """(each role with only the bullets it prints for these tags, {role key: "[tags] - bullet" left out})."""
    tags = set(tags) | {"core"}
    kept, skipped = [], {}
    for role in roles:
        marks = role.tags or [frozenset({"core"})] * len(role.bullets)
        keep = [i for i, t in enumerate(marks) if t & tags]
        kept.append(Role(role.key, role.title, role.dates, [role.bullets[i] for i in keep],
                         [marks[i] for i in keep], role.titles))
        skipped[role.key] = [f"[{', '.join(sorted(marks[i]))}] - {role.bullets[i]}"
                             for i in range(len(role.bullets)) if i not in keep]
    return kept, skipped


def printed_title(role: Role, tags) -> str | None:
    """The role's printed title for these tags: a tagged one that matches, else the default. None: no choices."""
    if not role.titles:
        return None
    for title, want in role.titles:
        if "default" not in want and want & set(tags):
            return title
    return next((t for t, want in role.titles if "default" in want), role.titles[0][0])


# --- the checks ---------------------------------------------------------------------------


def _root(word: str) -> str:
    w = word.lower()
    for suffix in _SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            w = w[: -len(suffix)]
            break
    return w[:-1] if w.endswith("e") and len(w) > 3 else w


def _content_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 4 and not w.isdigit() and w not in _STOP]


def _knows(token: str, words: set[str]) -> bool:
    """Each part of the name is there, or starts a word that is ("REST" in "RESTful", "API" in "APIs")."""
    return all(p in words or (len(p) >= 3 and any(w.startswith(p) for w in words))
               for p in re.findall(r"[a-z0-9#+]+", token.lower()))


def check_bullet(text: str, sources: list[str]) -> list[str]:
    """Why this rewrite of `sources` cannot be printed (empty: it can)."""
    if not text:
        return ["it is empty"]
    cited = " ".join(sources)
    problems = []
    for number, suffix, word in _number_context(text):
        if not any(_fact_has(number, word, s) for s in sources):
            problems.append(f'"{number}{suffix}{" " + word if word else ""}" is not in the bullet it rewords')
    cited_skills = set(extract_skills(cited))
    problems += [f'names "{s}", which the bullet it rewords does not' for s in extract_skills(text)
                 if s not in cited_skills]
    for word in _SENIORITY:
        if re.search(rf"\b{word}\b", text, re.I) and not re.search(rf"\b{word}\b", cited, re.I):
            problems.append(f'says "{word}", which the bullet it rewords does not')
    cited_words = set(re.findall(r"[a-z0-9#+]+", cited.lower()))
    for token in dict.fromkeys(_capitalized_words(text)):
        if not extract_skills(token) and not _knows(token, cited_words):  # skills were checked above
            problems.append(f'names "{token}", which the bullet it rewords does not')
    roots = {_root(w) for w in re.findall(r"[a-z0-9]+", cited.lower())}
    added = list(dict.fromkeys(w for w in _content_words(text) if _root(w) not in roots))
    if len(added) > MAX_NEW_WORDS:
        problems.append(f"adds {len(added)} words that are not in it ({', '.join(added)}); at most {MAX_NEW_WORDS}")
    words = len(text.split())
    if words > MAX_BULLET_WORDS:
        problems.append(f"is {words} words; at most {MAX_BULLET_WORDS}")
    return problems


def check_headline(text: str, headlines: list[str], profile: Profile) -> tuple[str, str | None]:
    """(the headline to print, why the asked one was changed or None)."""
    text = " ".join(text.split())
    role, _, focus = text.partition(" - ")
    allowed = {h.lower(): h for h in headlines}
    if role.strip().lower() not in allowed:
        return headlines[0], f'the headline "{text}" is not one of your target roles'
    role, focus = allowed[role.strip().lower()], focus.strip()
    if not focus:
        return role, None
    known = {_root(w) for w in re.findall(r"[a-z0-9]+", profile.facts_text.lower())}
    problems = [f'"{s}" is not in your profile' for s in extract_skills(focus) if s not in profile.skills]
    added = [w for w in re.findall(r"[a-z0-9]+", focus.lower()) if w not in ("and", "with") and _root(w) not in known]
    if added:
        problems.append(f"{', '.join(added)} not in your profile")
    for word in _SENIORITY:
        if re.search(rf"\b{word}\b", focus, re.I) and not re.search(rf"\b{word}\b", profile.facts_text, re.I):
            problems.append(f'"{word}" is not in your profile')
    if len(focus.split()) > 5:
        problems.append("longer than 5 words")
    if problems:
        return role, f'the headline focus "{focus}": ' + "; ".join(problems)
    return f"{role} - {focus}", None


# --- what the model asked for, after the checks ---------------------------------------


@dataclass
class Plan:
    headline: str
    bullets: dict[str, list[str]]  # role key -> the bullets to print
    unused: dict[str, list[str]]  # role key -> profile bullets left out (kept as // comments)
    skills: dict[str, list[str]]  # label -> items to print
    changes: list[str] = field(default_factory=list)  # the model's own notes to you
    problems: list[str] = field(default_factory=list)  # rewrites that broke a rule: sent back once
    notes: list[str] = field(default_factory=list)  # what code changed, shown to you
    titles: dict[str, str] = field(default_factory=dict)  # role key -> printed title, when the role has choices
    skipped: dict[str, list[str]] = field(default_factory=dict)  # role key -> "[tags] - bullet" not for this job
    optional: dict[str, list[bool]] = field(default_factory=dict)  # role key -> per printed bullet: not core


def plan_from(answer: dict, roles: list[Role], skills: dict[str, list[str]], headlines: list[str],
              profile: Profile) -> Plan:
    problems: list[str] = []
    notes: list[str] = []
    headline, why = check_headline(str(answer.get("headline") or ""), headlines, profile)
    if why:
        problems.append(why)
    asked = {}
    for item in answer.get("roles") or []:
        if isinstance(item, dict):
            asked.setdefault(str(item.get("role") or "").strip(), item.get("bullets") or [])
    if not asked:
        problems.append("the answer has no roles")
    bullets: dict[str, list[str]] = {}
    unused: dict[str, list[str]] = {}
    optional: dict[str, list[bool]] = {}
    for role in roles:
        ids = {f"{role.key}.{i}": b for i, b in enumerate(role.bullets, 1)}
        extra = {key: bool(role.tags) and "core" not in role.tags[i] for i, key in enumerate(ids)}
        chosen: list[str] = []
        flags: list[bool] = []
        used: set[str] = set()
        for item in asked.get(role.key) or []:
            if not isinstance(item, dict):
                continue
            sources = [s for s in dict.fromkeys(str(x).strip() for x in item.get("sources") or [])
                       if s in ids and s not in used][:2]
            if not sources:
                notes.append(f"{role.title}: left out a bullet that cites none of this role's bullets")
                continue
            used.update(sources)
            text = " ".join(str(item.get("text") or "").split()).lstrip("-• ").strip()
            why = check_bullet(text, [ids[s] for s in sources])
            if why:
                problems.append(f'{"+".join(sources)} "{text[:70]}{"…" if len(text) > 70 else ""}": {"; ".join(why)}')
                chosen += [ids[s] for s in sources]  # the profile's own wording
                flags += [extra[s] for s in sources]
            else:
                chosen.append(text)
                flags.append(all(extra[s] for s in sources))
        # Every bullet given to the model prints (the tags already chose them): one it left out
        # goes at the end, in the profile's words.
        missing = [key for key in ids if key not in used]
        if missing:
            notes.append(f"{role.title}: added {len(missing)} bullet(s) the answer left out ({', '.join(missing)})"
                         if chosen else f"{role.title}: kept the profile's bullets as written (none were picked)")
        chosen += [ids[key] for key in missing]
        flags += [extra[key] for key in missing]
        bullets[role.key], optional[role.key] = chosen, flags
        unused[role.key] = []
    wanted = {}
    for item in answer.get("skills") or []:
        if isinstance(item, dict):
            wanted.setdefault(_norm(str(item.get("label") or "")), item.get("items") or [])
    rows = {}
    for label, allowed in skills.items():
        spelled = {x.lower(): x for x in allowed}
        picked: list[str] = []
        for x in wanted.get(_norm(label), []):
            name = spelled.get(str(x).strip().lower())
            if name is None:
                notes.append(f'{label}: left out "{str(x).strip()}", which is not in your profile')
            elif name not in picked:
                picked.append(name)
        rows[label] = picked if len(picked) >= min(2, len(allowed)) else list(allowed)
    changes = [" ".join(str(c).split()) for c in answer.get("changes") or [] if str(c).strip()][:5]
    return Plan(headline, bullets, unused, rows, changes, problems, notes, optional=optional)


def cut_optional(plan: Plan) -> str | None:
    """Move one optional bullet into the // comments: the last one of the oldest role that has any. None: none left."""
    for key in reversed(list(plan.bullets)):
        flags = plan.optional.get(key, [])
        for i in range(len(flags) - 1, -1, -1):
            if flags[i]:
                flags.pop(i)
                text = plan.bullets[key].pop(i)
                plan.unused.setdefault(key, []).append(text)
                return text
    return None


# --- the model -----------------------------------------------------------------------------

SYSTEM = f"""\
You tailor a software engineer's one-page CV to one job posting. Code builds the \
CV from your answer and has already chosen which bullets it prints; you order and \
reword. There is no summary section.

Return:
- headline: one of the allowed headlines, word for word, the closest to the \
posting's title. You may add " - " and a focus of 2 to 4 words taken from the \
bullets or skills, e.g. "Backend Engineer - Python & AWS".
- roles: for each role (R1, R2, ...), every one of its bullets, the most relevant \
to this posting first. All of them print: one you leave out is added at the end in \
its original words. Each bullet has sources (the id of the one bullet it rewords) \
and text.
- skills: for each skills row, its items, the ones the posting asks for first. \
Only items from that row. Leave out an item only when it clearly does not matter \
for this job.
- changes: 2 to 4 short lines telling the engineer what you put first and why.

Rewording rules. Code checks each bullet; one that breaks a rule is printed in \
its original words instead:
- Same work, same scope, same results as the bullets it cites. Keep their \
numbers exactly, next to the same words ("800+ concurrent Python jobs").
- Never add a tool, language, number, team size, employer, title, result or \
responsibility that is not in the cited bullets. The posting's words describe \
the job, not the engineer.
- You may cut words, reorder, and use the posting's term for something the \
bullet already says ("REST APIs" for "RESTful APIs"). At most {MAX_NEW_WORDS} words \
that are not in the cited bullets.
- At most {MAX_BULLET_WORDS} words per bullet. Plain words, no buzzwords.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "roles": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "role": {"type": "string"},
                "bullets": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"sources": {"type": "array", "items": {"type": "string"}},
                                   "text": {"type": "string"}},
                    "required": ["sources", "text"], "additionalProperties": False,
                }},
            },
            "required": ["role", "bullets"], "additionalProperties": False,
        }},
        "skills": {"type": "array", "items": {
            "type": "object",
            "properties": {"label": {"type": "string"}, "items": {"type": "array", "items": {"type": "string"}}},
            "required": ["label", "items"], "additionalProperties": False,
        }},
        "changes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "roles", "skills", "changes"],
    "additionalProperties": False,
}

EXAMPLE = json.dumps({
    "headline": "Backend Engineer - Python & AWS",
    "roles": [{"role": "R1", "bullets": [{"sources": ["R1.2"], "text": "..."},
                                         {"sources": ["R1.1"], "text": "..."}]},
              {"role": "R2", "bullets": [{"sources": ["R2.1"], "text": "..."}]}],
    "skills": [{"label": "Languages", "items": ["Python", "SQL"]}],
    "changes": ["..."],
})


def _prompt(job, company: str, roles: list[Role], skills: dict[str, list[str]], headlines: list[str]) -> str:
    lines = [
        f"Job: {job['title']} at {company}", "",
        "The posting (use it to decide what matters; nothing in it is a fact about the engineer):",
        (job["description"] or "(no description)")[:MAX_POSTING_CHARS], "",
        "Allowed headlines: " + " | ".join(headlines), "",
        "Roles, newest first, with their bullets (the only facts you may use):",
    ]
    for role in roles:
        lines.append(f"{role.key}: {role.title} ({role.dates})")
        lines += [f"  {role.key}.{n}: {b}" for n, b in enumerate(role.bullets, 1)]
    lines += ["", "Skills rows (only these items):"] + [f"{k}: {', '.join(v)}" for k, v in skills.items()]
    return "\n".join(lines)


class CvWriter:
    def __init__(self, model: JsonModel):
        self.model = model

    def plan(self, job, company: str, roles: list[Role], skills: dict[str, list[str]], headlines: list[str],
             profile: Profile) -> tuple[Plan, Usage, int]:
        messages: list[dict] = [{"role": "user", "content": _prompt(job, company, roles, skills, headlines)}]
        usage = Usage()
        plan, attempt = None, 0
        for attempt in (1, 2):
            answer = self.model.ask(SYSTEM, messages, SCHEMA, usage, EXAMPLE)
            plan = plan_from(answer, roles, skills, headlines, profile)
            if not plan.problems:
                break
            messages += [
                {"role": "assistant", "content": json.dumps(answer)},
                {"role": "user", "content": "Code will print the original words instead of these, because they "
                    "break the rules: " + "; ".join(plan.problems) + ". Answer again with the whole JSON, "
                    "fixing these."},
            ]
        plan.notes += [f"Overruled by the fact check: {p}" for p in plan.problems]
        return plan, usage, attempt


def tailor_note(config: OutreachConfig) -> str | None:
    """Why tailoring is off, or None."""
    folder = Path(config.resume_dir).expanduser()
    for name in ("resume.md", "build.py"):
        try:
            with (folder / name).open("rb") as f:
                f.read(1)
        except PermissionError:
            # macOS keeps background jobs (the daily run) out of ~/Documents, ~/Desktop and ~/Downloads.
            return (f"Tailoring cannot read {config.resume_dir} from here (macOS blocks background jobs from "
                    "Documents): use Tailor CV in the app, or move resume_dir out of ~/Documents")
        except OSError:
            return f"Tailoring needs {name} in {config.resume_dir} (resume_dir in config/outreach.json)"
    return key_note(config.cv_model, "Tailoring")


def build_cv_writer(config: OutreachConfig, claude=None) -> tuple[CvWriter | None, str | None]:
    note = tailor_note(config)
    if note:
        return None, note
    model, note = json_model(config.cv_model, "Tailoring", claude=claude)
    return (CvWriter(model), None) if model else (None, note)


# --- the file and the PDF ---------------------------------------------------------------


def render(lines: list[str], matched: dict[int, Role], rows: dict[int, str], plan: Plan, note: str,
           compact: bool = False) -> str:
    """resume.md with the headline, the matched roles' bullets and the skills rows replaced. Comments are dropped."""
    out = [f"// {note}"]
    in_header, skipping = True, False
    for i, raw in enumerate(lines):
        s = raw.strip()
        if s.startswith("//"):
            continue
        if s.startswith("## "):
            if in_header and compact:
                end = len(out)
                while end > 0 and not out[end - 1].strip():
                    end -= 1
                out.insert(end, "compact: yes")
            in_header, skipping = False, False
        elif in_header:
            key = s.split(":", 1)[0].strip().lower() if ":" in s else ""
            if key == "title":
                out.append(f"title: {plan.headline}")
                continue
            if key == "compact":
                continue
        elif s.startswith("### "):
            skipping = False
        elif i in matched:
            key = matched[i].key
            title = raw.replace(s, plan.titles[key]) if plan.titles.get(key) else raw
            out += ([title] + [f"- {b}" for b in plan.bullets[key]] + [f"// - {b}" for b in plan.unused[key]]
                    + [f"// {b}" for b in plan.skipped.get(key, [])])
            skipping = True
            continue
        elif skipping and s.startswith("- "):
            continue
        elif i in rows:
            out.append(f"{rows[i]}: {', '.join(plan.skills[rows[i]])}")
            continue
        out.append(raw)
    return "\n".join(out).rstrip() + "\n"


def build_pdf(folder: Path, source: Path) -> tuple[Path, int]:
    """Run the resume folder's build.py on one version: (the PDF it wrote, its page count)."""
    try:
        done = subprocess.run([sys.executable, "build.py", str(source.relative_to(folder))], cwd=folder,
                              capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TailorError(f"build.py did not finish: {exc}") from exc
    wrote = re.search(r"Wrote (\S+\.pdf) \((\d+) pages?\)", done.stdout)
    if done.returncode != 0 or not wrote:
        tail = (done.stderr or done.stdout).strip().splitlines()[-1:]
        raise TailorError("build.py failed" + (f": {tail[0][:300]}" if tail else ""))
    return folder / wrote.group(1), int(wrote.group(2))


_ROLE_NOISE = {"engineer", "engineering", "developer", "programmer", "remote", "ii", "iii", "iv"}


def _camel(text: str) -> str:
    return "".join(w[:1].upper() + w[1:] for w in re.split(r"[^A-Za-z0-9]+", text) if w)


def role_label(title: str) -> str:
    """'Senior Backend Engineer (Python)' -> 'Backend', like build.py's `new Backend Stripe`."""
    words = [w for w in re.findall(r"[A-Za-z0-9]+", role_family(re.split(r"[,/]", title)[0]))
             if w.lower() not in _ROLE_NOISE]
    return _camel(" ".join(words[:2])) or "Engineer"


def _new_stem(folder: Path, title: str, company: str, now: datetime) -> str:
    """Backend_Acme_Sep2026, with _2, _3... when that name is taken (never overwrite a CV made by hand)."""
    base = f"{role_label(title)}_{_camel(company)[:30] or 'Company'}_{now:%b%Y}"
    taken = {p.stem for p in (folder / "versions").glob("*.md")} | {p.stem for p in (folder / "output").glob("*.pdf")}
    stem, n = base, 1
    while stem in taken or any(t.endswith(f"_{stem}") for t in taken):
        n += 1
        stem = f"{base}_{n}"
    return stem


def tailored_of(app) -> dict | None:
    return json.loads(app["cv_tailored_json"]) if app is not None and app["cv_tailored_json"] else None


def tailor_for_job(store: JobStore, job_id: int, writer: CvWriter, profile_path: Path, config: OutreachConfig,
                   now: datetime, builder=None, pick: bool = True) -> dict:
    """Write versions/<name>.md, build the PDF, and make it the job's attachment.

    Tailoring the same job again rewrites its own file. The PDF becomes the attachment when
    `pick` (your click), or when you had not picked another CV.
    """
    builder = builder or build_pdf
    job = store.get(job_id)
    if job is None:
        raise TailorError(f"no job #{job_id}")
    folder = Path(config.resume_dir).expanduser()
    master = folder / "resume.md"
    if not master.is_file():
        raise TailorError(f"No resume.md in {config.resume_dir}")
    lines = master.read_text().splitlines()
    roles, skills, headlines = load_facts(profile_path)
    matched, rows = scan(lines, roles, skills)
    roles = [r for r in roles if r in matched.values()]
    skills = {label: skills[label] for label in rows.values()}
    if not roles or not headlines:
        raise TailorError("No role in resume.md matches a role (title and dates) in profile/master_profile.md")
    profile = load_profile(profile_path)
    company, _ = clean_company_name(job["company"])
    app = tracking.ensure_application(store, job_id, now)
    old = tailored_of(app)
    store.commit()  # no write lock held during the model call

    tags = job_tags(job["title"], job["description"] or "", {**TAG_RULES, **(config.cv_tags or {})})
    roles, skipped = select(roles, tags)
    plan, usage, attempts = writer.plan(job, company, roles, skills, headlines, profile)
    plan.skipped = skipped
    plan.titles = {r.key: t for r in roles if (t := printed_title(r, tags))}
    picked = "; ".join(f"{tag} ({why})" for tag, why in tags.items())
    plan.changes.insert(0, f"Optional bullets for: {picked}" if tags else
                        "Core bullets only: the posting matches no optional tag (lead, fullstack, automation...)")
    stem = old["stem"] if old else _new_stem(folder, job["title"], company, now)
    source = folder / "versions" / f"{stem}.md"
    source.parent.mkdir(exist_ok=True)
    note = (f"TAILORED by jobhunter for {company} - {job['title']} (job #{job_id}, {now:%b %Y}). "
            "Tailor again in the app rewrites this file.")
    for compact in (False, True):
        source.write_text(render(lines, matched, rows, plan, note, compact))
        pdf, pages = builder(folder, source)
        if pages <= 1:
            break
    # Still too long: optional bullets go (never core ones) until it fits.
    while pages > 1 and (cut := cut_optional(plan)):
        plan.notes.append(f'Cut to fit one page (an optional bullet, kept as a comment): "{cut[:60]}…"')
        source.write_text(render(lines, matched, rows, plan, note, True))
        pdf, pages = builder(folder, source)
    if pages > 1:
        plan.notes.append(f"It is {pages} pages even in compact mode: cut a bullet in {source}")
    attachable = pdf.parent.resolve() == Path(config.cv_dir).expanduser().resolve()
    if not attachable:
        plan.notes.append(f"build.py wrote {pdf.parent}, not cv_dir ({config.cv_dir}), so it cannot be attached")
    tracker = folder / "applications.csv"
    if old is None and tracker.is_file():
        with tracker.open("a", newline="") as f:
            csv.writer(f).writerow([company, job["title"], str(pdf.relative_to(folder)), now.date().isoformat(), "",
                                    "Draft", f"jobhunter job #{job_id}"])

    posting = f"{job['title']}\n{job['description'] or ''}"
    meta = {
        "stem": stem, "file": pdf.name, "path": str(pdf), "source": str(source.relative_to(folder)), "pages": pages,
        "headline": plan.headline, "changes": plan.changes, "notes": plan.notes,
        "tags": tags, "titles": plan.titles,
        "gaps": sorted(set(extract_skills(posting)) - profile.skills),
        "model": writer.model.model, "cost_usd": usage.cost(writer.model.model) or 0.0, "attempts": attempts,
        "written_at": iso(now),
    }
    attach = attachable and (pick or not app["cv_file"] or (old is not None and app["cv_file"] == old["file"]))
    store.conn.execute(
        "UPDATE applications SET cv_tailored_json = ?, cv_file = CASE WHEN ? THEN ? ELSE cv_file END, updated_at = ? "
        "WHERE job_id = ?",
        (json.dumps(meta), 1 if attach else 0, pdf.name, iso(now), job_id),
    )
    tracking.add_event(store, job_id, "cv", f"CV tailored: {pdf.name}" + (" (again)" if old else ""), now)
    store.commit()
    return meta
