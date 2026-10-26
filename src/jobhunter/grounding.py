"""The fact check's building blocks, shared by the email (pitch.check_draft), the CV
(cv.check_bullet) and the cover letter (cover.check_sentence).

The rule: a generated line may only use numbers, names, skills and seniority words found
in the profile facts it cites (profile/master_profile.md, the only source of facts about
you; see .claude/CLAUDE.md). Each check decides which facts a line may cite and what happens to a
line that fails; these helpers decide what counts as the same number, name or word. So a
change here changes what all three let through.
"""

from __future__ import annotations

import re

# Words that claim a level. A line may only say one its facts say.
SENIORITY = ("senior", "staff", "principal", "architect", "head", "manager", "cto", "director", "vp", "chief", "lead")
# The word after a number that makes it years of experience ("3+ years").
YEAR_WORDS = frozenset({"year", "years", "yr", "yrs"})
_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
    "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "twenty": "20", "fifty": "50", "hundred": "100",
}
_NUMBER_RE = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*(\+|%|k\b|x\b)?", re.I)


def digits(text: str) -> str:
    """Number words as digits ("five engineers" -> "5 engineers"), so a spelled-out number is checked too."""
    return re.sub(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b", lambda m: _NUMBER_WORDS[m.group(1).lower()], text,
                  flags=re.I)


def word_list(text: str) -> list[str]:
    """The text's words and numbers, lowercased, without punctuation: "800+ AWS-Lambda" -> ["800", "aws", "lambda"]."""
    return re.findall(r"[a-z0-9]+", text.lower())


def stem(word: str) -> str:
    """A plural's singular ("jobs" -> "job"), so "800+ concurrent job" matches "800+ concurrent jobs"."""
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


def number_context(text: str) -> list[tuple[str, str, str | None]]:
    """Every number, its suffix and the word right after it: "800+ concurrent" -> ("800", "+", "concurrent")."""
    text = digits(text)
    found = []
    for m in _NUMBER_RE.finditer(text):
        after = word_list(text[m.end():])
        found.append((m.group(1).replace(",", ""), m.group(2) or "", after[0] if after else None))
    return found


def fact_has(number: str, word: str | None, fact: str) -> bool:
    """True only when the fact has this number with `word` among the next four words ("800+ concurrent Python jobs")."""
    for m in _NUMBER_RE.finditer(digits(fact)):
        if m.group(1).replace(",", "") != number:
            continue
        after = {stem(w) for w in word_list(digits(fact)[m.end():])[:4]}
        if word is None or stem(word) in after:
            return True
    return False


def capitalized_words(text: str) -> list[str]:
    """Capitalized words that do not start a sentence: likely names of tools or companies.

    Only the sentence's first word is skipped, so in "I used Workato" the name still counts.
    """
    found = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        sentence = sentence.lstrip("\"'“‘(")
        found += [m.group(0) for m in re.finditer(r"\b[A-Z][\w.#+-]*[\w#+]", sentence) if m.start() > 0]
    return found


def check_years(number: str, suffix: str, years: float | None) -> str | None:
    """Why a claim of `number` years cannot print (more than the profile's whole years, or it states none), or None."""
    if years is None or float(number) > int(years):
        return (f"claims {number}{suffix} years; the profile has about "
                f"{years if years is not None else 'no stated'} years")
    return None


def unsupported_seniority(text: str, source: str) -> list[str]:
    """The seniority words `text` says that `source` does not, each as a whole word, ignoring case."""
    return [word for word in SENIORITY
            if re.search(rf"\b{word}\b", text, re.I) and not re.search(rf"\b{word}\b", source, re.I)]
