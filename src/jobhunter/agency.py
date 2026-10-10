"""Is this posting from a staffing agency or talent marketplace instead of the employer?

They repost real companies' jobs (Jobs for Humanity), sell vetted developers
(Toptal, Proxify) or pay per task (micro1, Xperteez). Three checks, each
quoting what it matched, all set in the "agencies" section of
config/filters.json:

  names                 known agencies, matched like blocked_companies
  name_words            whole words in the company name: "talent", "staffing"
  description_phrases   sentences only an agency writes: "on behalf of our client"

`not_agencies` lists real companies a name word would catch. Phrases that real
companies also use ("our clients", "talent pool", "talent network") are left
out on purpose: they are in footers of product companies' boards.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .identity import company_key
from .text import normalize_words


@dataclass
class AgencyRules:
    names: dict[str, str] = field(default_factory=dict)  # company_key -> name as written
    name_words: re.Pattern | None = None
    description_phrases: re.Pattern | None = None
    not_agencies: set[str] = field(default_factory=set)

    @classmethod
    def from_dict(cls, data: dict | None) -> AgencyRules:
        data = data or {}

        def alternation(items: list[str]) -> re.Pattern | None:
            words = sorted({w for w in (normalize_words(x) for x in items) if w}, key=len, reverse=True)
            return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b") if words else None

        return cls(
            names={company_key(n): n for n in data.get("names", []) if company_key(n)},
            name_words=alternation(data.get("name_words", [])),
            description_phrases=alternation(data.get("description_phrases", [])),
            not_agencies={company_key(n) for n in data.get("not_agencies", []) if company_key(n)},
        )

    def check(self, company: str, description: str) -> str | None:
        """The reason this looks like an agency, quoting the match, or None."""
        key = company_key(company)
        if not key or key in self.not_agencies:
            return None
        if key in self.names:
            return f'Staffing agency or talent marketplace on your list: "{self.names[key]}"'
        if self.name_words:
            m = self.name_words.search(normalize_words(company))
            if m:
                return f'Company name says it is an agency ("{m.group(0)}"): "{company}"'
        if self.description_phrases and description:
            m = self.description_phrases.search(normalize_words(description))
            if m:
                return f'Posting is written by an agency: "{_sentence(description, m.group(0))}"'
        return None


def _sentence(text: str, phrase: str) -> str:
    """The sentence that holds the phrase, as written, for the reason line."""
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        if phrase in normalize_words(sentence):
            sentence = " ".join(sentence.split())
            return sentence if len(sentence) <= 200 else sentence[:199] + "…"
    return phrase
