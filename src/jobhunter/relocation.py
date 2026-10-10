"""Jobs in a country you would move to (the UAE or Qatar): on-site is fine there.

Everywhere else an on-site or hybrid job is rejected. Here it is judged on what
the posting says, each verdict quoting it:

  rejected  only for nationals or people already in the country ("UAE
            Nationals only", "transferable visa", "no visa sponsorship"), or
            the stated pay is under your floor for moving
  likely    otherwise; with the sentence that offers a visa or relocation when
            there is one, and the sentence to ask about ("immediate joiner")
            as a note

"Remote (UAE)" counts here too: it means remote for people living in the UAE.
Never `unclear`, so the AI check (which asks about remote hiring from Lebanon)
is not run on these.

The places and phrases are the "relocation" section of config/filters.json.
The pay floor is RELOCATION_MIN_MONTHLY_USD in .env, so no tracked file holds
it; without it pay is not checked.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .models import HYBRID, LIKELY, NOT_ELIGIBLE, ONSITE, REMOTE, Assessment, Job
from .text import normalize_words

# Both currencies are pegged to the dollar, so these never change.
USD_PER = {"USD": 1.0, "AED": 1 / 3.6725, "QAR": 1 / 3.64}
_MONTHS = {"month": 1, "year": 12}


def _phrases(items) -> re.Pattern | None:
    """Case-insensitive, whole words, any whitespace between them, on the original text (to quote it)."""
    parts = sorted({" ".join(str(x).split()) for x in items or [] if str(x).strip()}, key=len, reverse=True)
    if not parts:
        return None
    alternation = "|".join(r"\s+".join(re.escape(w) for w in p.split()) for p in parts)
    return re.compile(r"(?<![A-Za-z0-9])(?:" + alternation + r")(?![A-Za-z0-9])", re.I)


@dataclass
class Relocation:
    places: list[str] = field(default_factory=list)  # normalized words: "united arab emirates", "dubai"
    countries: str = ""  # for reason lines: "the UAE or Qatar"
    title_local_only: re.Pattern | None = None
    local_only: re.Pattern | None = None
    sponsor: re.Pattern | None = None
    ask_about: re.Pattern | None = None
    min_monthly_usd: float | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> Relocation | None:
        if not data or not data.get("places"):
            return None
        floor = os.environ.get("RELOCATION_MIN_MONTHLY_USD", "").strip()
        return cls(
            places=[w for w in (normalize_words(p) for p in data["places"]) if w],
            countries=data.get("countries", ""),
            title_local_only=_phrases(data.get("title_local_only")),
            local_only=_phrases(data.get("local_only")),
            sponsor=_phrases(data.get("sponsor")),
            ask_about=_phrases(data.get("ask_about")),
            min_monthly_usd=float(floor) if floor.replace(".", "", 1).isdigit() else None,
        )

    def place_in(self, texts: list[str]) -> str | None:
        """The first location text that names a place you would move to."""
        for text in texts:
            words = f" {normalize_words(text)} "
            if any(f" {p} " in words for p in self.places):
                return text
        return None


def _sentence(text: str, m: re.Match, width: int = 200) -> str:
    left = max(text.rfind(".", 0, m.start()), text.rfind("\n", 0, m.start())) + 1
    ends = [i for i in (text.find(".", m.end()) + 1, text.find("\n", m.end())) if i > 0]
    sentence = " ".join(text[left:min(ends) if ends else len(text)].split())
    return sentence if len(sentence) <= width else sentence[:width - 1] + "…"


def monthly_usd(job: Job) -> float | None:
    """The top of the stated pay range per month in dollars, when the currency and period are known."""
    rate, months = USD_PER.get((job.salary_currency or "").upper()), _MONTHS.get(job.salary_period or "")
    amount = job.salary_max or job.salary_min
    if not (rate and months and amount):
        return None
    return amount * rate / months


def assess_relocation(job: Job, place: str, rules: Relocation) -> Assessment:
    text = job.description or ""
    m = rules.title_local_only.search(job.title or "") if rules.title_local_only else None
    if m:
        return Assessment(NOT_ELIGIBLE, [f'Only for nationals or residents (title): "{job.title}"'], "local_only")
    m = rules.local_only.search(text) if rules.local_only else None
    if m:
        return Assessment(NOT_ELIGIBLE, [f'Only for people already in the country: "{_sentence(text, m)}"'], "local_only")

    pay = monthly_usd(job)
    if pay is not None and rules.min_monthly_usd and pay < rules.min_monthly_usd:
        stated = job.salary_raw or f"{job.salary_currency} {job.salary_max or job.salary_min:,.0f} a {job.salary_period}"
        return Assessment(NOT_ELIGIBLE, [f'Pays "{stated}", about ${pay:,.0f} a month, under your '
                                         f'${rules.min_monthly_usd:,.0f} for moving'], "below_relocation_pay")

    if job.remote_status == REMOTE:
        where = f'Remote, for people living in "{place}"'
    else:
        mode = {ONSITE: "On-site", HYBRID: "Hybrid"}.get(job.remote_status, "Based")
        where = f'{mode} in "{place}"'
    sponsor = rules.sponsor.search(text) if rules.sponsor else None
    if sponsor:
        reasons = [f'{where}, a country you would move to; the posting offers: "{_sentence(text, sponsor)}"']
        code = "relocation_offered"
    else:
        reasons = [f"{where}, a country you would move to ({rules.countries}). "
                   "Ask about visa sponsorship and a remote interview"]
        code = "relocation"
    ask = rules.ask_about.search(text) if rules.ask_about else None
    if ask:
        reasons.append(f'Ask before applying, it may want someone already there: "{_sentence(text, ask)}"')
    if pay is not None:
        reasons.append(f"Pay: about ${pay:,.0f} a month")
    return Assessment(LIKELY, reasons, code)
