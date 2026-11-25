"""Where a CV shows a posting's must-haves: in the top part a recruiter skims, anywhere printed, or not
at all (mirror-cv's skim zone, scored by code so mirroring gets a quality number next to its minutes:
the user's ask, 2026-11-25).

The top part is mirror-cv's skim zone: the headline (`title:`), the first SKILLS_SEEN items of each
skills row and the newest role's first BULLETS_SEEN printed bullets. A term counts only in the
posting's own words (any case), as an ATS filter reads it: "Postgres" is not "PostgreSQL". The model
picks the must-have terms; this only says where they are.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SKILLS_SEEN = 4
BULLETS_SEEN = 3


def _clean(text: str) -> str:
    return " ".join(text.replace("**", "").split())


def _items(row: str) -> list[str]:
    """A skills row's items: commas inside brackets stay in their item ("AWS (Lambda, SQS)")."""
    out, depth, cur = [], 0, ""
    for ch in row:
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if ch == "," and depth <= 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return [x for x in (*out, cur.strip()) if x]


def _sections(md: str) -> dict[str, list[str]]:
    """The printed lines under each `## ` heading (lines starting `//` never print)."""
    out: dict[str, list[str]] = {"": []}
    name = ""
    for line in md.splitlines():
        if line.lstrip().startswith("//"):
            continue
        if line.startswith("## "):
            name = line[3:].strip().lower()
            out.setdefault(name, [])
        else:
            out[name].append(line)
    return out


def top_part(md: str) -> str:
    parts = _sections(md)
    head = [ln.split(":", 1)[1] for ln in parts[""] if ln.lower().startswith("title:")]
    skills = []
    for name, lines in parts.items():
        if "skill" in name:
            for ln in lines:
                if ":" in ln:
                    skills += _items(ln.split(":", 1)[1])[:SKILLS_SEEN]
    bullets: list[str] = []
    for name, lines in parts.items():
        if "experience" in name:
            roles = 0
            for ln in lines:
                if ln.startswith("### "):
                    roles += 1
                elif roles == 1 and ln.startswith("- ") and len(bullets) < BULLETS_SEEN:
                    bullets.append(ln[2:])
            break
    return _clean("\n".join([*head, *skills, *bullets]))


def printed(md: str) -> str:
    """Everything the CV prints after its contact lines (from the first `## ` heading on)."""
    return _clean("\n".join(ln for name, lines in _sections(md).items() if name for ln in lines))


def has(term: str, text: str) -> bool:
    """The term as a whole phrase: no letter or digit right before or after it ("Java" is not in
    "JavaScript"), so "C#" and "Node.js" match too, where a regex word boundary would fail."""
    term = _clean(term)
    return bool(term) and re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text, re.I) is not None


def terms(text: str) -> list[str]:
    """The skill's `--must "a; b; c"`: one term per semicolon, blanks and repeats dropped."""
    seen: dict[str, str] = {}
    for t in text.split(";"):
        t = _clean(t)
        if t:
            seen.setdefault(t.lower(), t)
    return list(seen.values())


@dataclass
class Score:
    terms: list[str]
    top: list[str]  # in the top part
    on_cv: list[str]  # printed anywhere (the top part included)

    @property
    def missing(self) -> list[str]:
        return [t for t in self.terms if t not in self.on_cv]


def score(must: list[str], md: str) -> Score:
    top, body = top_part(md), printed(md)
    return Score(must, [t for t in must if has(t, top)], [t for t in must if has(t, body) or has(t, top)])
