"""The fit score: 100 points from the user's rubric (the user's call 2026-11-15, decision 26).

Sorting only, like the grade it replaced: it never changes a status, never hides or
rejects a job. Code adds the points up; the model never does.

  Skills match            40  seniority 15, technical skills 12, years 8, domain 5
  Visa and location       30  the best row that has evidence (see visa_points)
  Salary and company      30  base salary 7, benefits 1, equity 2, interview style 20

Code scores what the database already knows: years (`required_yoe`), the visa and
location row (the posting's own visa sentences, the sponsor registers in the
eligibility reasons, the AI check), the salary against the country's floor (in .env,
never a tracked file), and which required skills the profile names. The model
(fitgrade.py) only reads the posting for the seniority level, the required skills,
the domain, benefits, equity and the interview process, each with a quote code finds
in the posting; a quote it cannot find scores nothing.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass, field

from .extract import extract_skills
from .models import ELIGIBLE, REMOTE, VISA_LIST
from .relocation import Relocation
from .sponsors import LISTS
from .text import normalize_words
from .visa import VisaRules, offers_relocation

# --- skills match: 40 --------------------------------------------------------

# Your level is mid (about 3 years). One level below scores like your own (the rubric).
SENIORITY = {"junior": 15, "mid": 15, "not_stated": 15, "senior": 9, "staff_or_above": 0}
DOMAIN = {"direct": 5, "transferable": 3, "unrelated": 0}
SKILLS_MAX = 12


def years_points(required: int | None, mine: float | None) -> tuple[int, str]:
    """8 when you meet it (or none is stated), 5 one year short, 3 two years short, else 0."""
    if required is None:
        return 8, "no years stated"
    have = int(mine or 0)
    short = required - have
    points = 8 if short <= 0 else 5 if short == 1 else 3 if short == 2 else 0
    return points, f"asks {required}+ years, you have {have}"


def skill_is_yours(skill: str, profile_skills: set[str], profile_text: str) -> bool:
    """A required skill counts when the profile names it: the same skill word, or the phrase itself."""
    if set(extract_skills(skill)) & profile_skills:
        return True
    words = normalize_words(skill)
    return bool(words) and f" {words} " in f" {normalize_words(profile_text)} "


def skills_points(required: list, profile_skills: set[str], profile_text: str) -> tuple[int, str]:
    """Matched required skills / required skills x 12. No skills read: half.

    Each item is a skill name, or {"skill", "profile_words"}: the words in the profile the model says
    cover it ("REST APIs" -> "API design"). They count only when code finds them in the profile text.
    """
    items = []
    for item in required[:20]:
        skill, words = (item.get("skill"), item.get("profile_words")) if isinstance(item, dict) else (item, "")
        skill = " ".join(str(skill or "").split())
        if skill and skill.lower() not in {s.lower() for s, _ in items}:
            items.append((skill, " ".join(str(words or "").split())))
    if not items:
        return SKILLS_MAX // 2, "no required skills read"
    profile = f" {normalize_words(profile_text)} "
    matched = [s for s, words in items if skill_is_yours(s, profile_skills, profile_text)
               or (normalize_words(words) and f" {normalize_words(words)} " in profile)]
    missing = [s for s, _ in items if s not in matched]
    points = round(SKILLS_MAX * len(matched) / len(items))
    said = f"{len(matched)} of {len(items)} required skills"
    return points, said + (f" (missing: {', '.join(missing[:5])})" if missing else "")


# --- visa and location: 30 ---------------------------------------------------

VISA_AND_RELOCATION = 30  # accepts international applicants, with visa and relocation help
HIRES_ABROAD = 27  # a visa (or help moving) offered, no relocation help named
TRACK_RECORD = 23  # evidence of earlier international hires (a sponsor register, another posting)
REMOTE_FROM_LEBANON = 20  # a remote role that says it can be done from Lebanon
UNCONFIRMED = 15  # nothing against it, international hiring not confirmed

def _short(text: str, width: int = 140) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _ai_check(row: sqlite3.Row) -> dict:
    try:
        return json.loads(row["ai_check_json"] or "{}") or {}
    except (KeyError, IndexError, ValueError):
        return {}


def _visa_offer(why: str, text: str, quote: str) -> tuple[int, str]:
    """30 when the posting also offers help moving (not negated), else 27."""
    moves = offers_relocation(text)
    if moves:
        return VISA_AND_RELOCATION, f'{why}: "{_short(quote)}", and help moving: "{_short(moves, 100)}"'
    return HIRES_ABROAD, f'{why}: "{_short(quote)}"'


def _quoted_after(reason: str, marker: str) -> str:
    """The quote a rule's reason carries after `marker` ('the posting offers a visa: "..."')."""
    rest = reason.split(marker, 1)[1] if marker in reason else ""
    m = re.search(r'"(.+)"', rest)
    return m.group(1) if m else rest.strip()


def visa_points(row: sqlite3.Row, relocation: Relocation | None = None,
                other_offer: str | None = None) -> tuple[int, str]:
    """The best row of the visa and location table that this job has evidence for.

    Read from the verdict the rules already wrote (its first reason's fixed wording: visa.assess_visa,
    relocation.assess_relocation), so the score and the reason on screen never disagree; the AI check's
    verified quote for the rest. `other_offer` is the company's track record (fitgrade.other_offer), or None.
    """
    reasons = json.loads(row["eligibility_reasons_json"] or "[]")
    first = reasons[0] if reasons else ""
    text = row["description"] or ""
    check = _ai_check(row)
    verified = bool(check.get("verified"))
    register = next((name for name in LISTS.values() if name in " ".join(reasons)), None)

    if row["status"] == VISA_LIST:
        if "the posting offers a visa:" in first:
            return _visa_offer("offers a visa", text, _quoted_after(first, "the posting offers a visa:"))
        if "offers help moving" in first:
            return HIRES_ABROAD, f'offers help moving: "{_short(_quoted_after(first, "(ask):"))}"'
    elif "a country you would move to; the posting offers:" in first:  # the UAE or Qatar
        return _visa_offer("offers", text, _quoted_after(first, "the posting offers:"))
    elif row["remote_status"] == REMOTE:
        if row["eligibility"] == ELIGIBLE:
            return REMOTE_FROM_LEBANON, f"remote, open to Lebanon: {_short(first)}"
        if verified and check.get("verdict") == "can_hire":
            return REMOTE_FROM_LEBANON, f'remote, the AI check found it can hire from Lebanon: "{_short(check.get("quote", ""))}"'
    if verified and check.get("verdict") == "sponsors_visa":
        return _visa_offer("the AI check found a visa offer", check.get("quote", ""), check.get("quote", ""))
    if register:
        return TRACK_RECORD, f"the company is on {register}"
    site = next((r for r in reasons if "a visa-sponsorship job site, lists" in r or "list of visa-sponsoring employers" in r), None)
    if site:  # sponsor_sites.py: the site checked the sponsorship, the posting does not say it
        return TRACK_RECORD, _short(site.split("; ", 1)[-1].split(". The posting", 1)[0], 200)
    if other_offer and row["remote_status"] != REMOTE:
        return TRACK_RECORD, f'their other postings offered a visa: "{_short(other_offer, 200)}"'
    if row["remote_status"] == REMOTE and row["status"] != VISA_LIST:
        return UNCONFIRMED, "remote, hiring from Lebanon not confirmed"
    return UNCONFIRMED, "nothing against it, international hiring not confirmed"


# --- salary: 7 ----------------------------------------------------------------

SALARY_MAX = 7
# Rough rates to US dollars, only to compare a salary with a floor in another currency.
USD_PER = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "CHF": 1.12, "CAD": 0.72, "AUD": 0.65, "SGD": 0.74,
           "AED": 1 / 3.6725, "QAR": 1 / 3.64, "SAR": 1 / 3.75}
_PER_YEAR = {"year": 1, "month": 12, "hour": 2080}
_FLOOR = re.compile(r"^\s*([a-z]+)\s*=\s*(\d+(?:\.\d+)?)\s*([A-Za-z]{3})?\s*$")


@dataclass
class SalaryFloors:
    """The yearly salary each country needs (FIT_SALARY_FLOORS in .env, never a tracked file).

    "nl=<amount> EUR, uk=<amount> GBP, default=<amount> USD": a visa-list country's own
    floor, else `default`. The UAE and Qatar use RELOCATION_MIN_MONTHLY_USD (relocation.py).
    """

    floors: dict[str, tuple[float, str]] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> SalaryFloors:
        return cls.parse(os.environ.get("FIT_SALARY_FLOORS", ""))

    @classmethod
    def parse(cls, text: str) -> SalaryFloors:
        floors = {}
        for part in (text or "").split(","):
            m = _FLOOR.match(part)
            if m:
                floors[m.group(1).lower()] = (float(m.group(2)), (m.group(3) or "USD").upper())
        return cls(floors)

    def floor_for(self, code: str | None) -> tuple[float, str] | None:
        return self.floors.get(code or "") or self.floors.get("default")


def yearly_usd(amount: float | None, currency: str | None, period: str | None) -> float | None:
    rate, times = USD_PER.get((currency or "").upper()), _PER_YEAR.get(period or "")
    return amount * rate * times if amount and rate and times else None


def salary_points(row: sqlite3.Row, visa: VisaRules | None, relocation: Relocation | None,
                  floors: SalaryFloors) -> tuple[int, str]:
    """7 when the top of the stated range reaches the country's floor, 0 below it or when no pay is stated."""
    if not row["salary_max"] and not row["salary_min"]:
        return 0, "no pay stated"
    top = row["salary_max"] or row["salary_min"]
    places = [row["location_raw"] or "", *json.loads(row["allowed_locations_json"] or "[]")]
    if relocation and relocation.min_monthly_usd and relocation.place_in(places):
        pay = yearly_usd(top, row["salary_currency"], row["salary_period"])
        if pay is None:
            return 0, f"pay stated in a form code cannot compare: {row['salary_raw']}"
        ok = pay >= relocation.min_monthly_usd * 12
        return (SALARY_MAX if ok else 0), f"{row['salary_raw']}: {'meets' if ok else 'below'} your relocation floor"
    found = visa.place_in(places) if visa else None
    code = found[1].code if found else None
    floor = floors.floor_for(code)
    if floor is None:
        return 0, "no salary floor set (FIT_SALARY_FLOORS in .env)"
    amount, currency = floor
    period = row["salary_period"]
    if (row["salary_currency"] or "").upper() == currency and period in _PER_YEAR:
        pay, need = top * _PER_YEAR[period], amount
    else:
        pay, need = yearly_usd(top, row["salary_currency"], period), amount * USD_PER.get(currency, 0)
    if pay is None or not need:
        return 0, f"pay stated in a form code cannot compare: {row['salary_raw']}"
    ok = pay >= need
    where = found[1].name if found else "remote"
    return (SALARY_MAX if ok else 0), f"{row['salary_raw']}: {'meets' if ok else 'below'} your floor for {where}"


# --- interview style: 20 ------------------------------------------------------

INTERVIEW_MAX = 20
INTERVIEW_UNKNOWN = 10
GOOD, BAD = "good", "bad"  # the star next to the score: green, red


@dataclass
class Interview:
    live_coding: str = "unknown"  # yes | no | unknown
    rounds: int | None = None
    quote: str = ""
    source: str = ""  # "posting", or the page the company lookup quoted

    @classmethod
    def from_dict(cls, data: dict | None) -> Interview:
        data = data or {}
        rounds = data.get("rounds")
        return cls(str(data.get("live_coding") or "unknown"), rounds if isinstance(rounds, int) and rounds > 0 else None,
                   str(data.get("quote") or ""), str(data.get("source") or ""))


def interview_points(found: Interview) -> tuple[int, str | None, str]:
    """(points, star, why). Live coding or a coding test named: 0 and a red star. None: 20 and a green
    star, less for many rounds (4: 18, 5 or more: 15). Not known: 10, no star."""
    where = f' ({found.source}): "{_short(found.quote, 120)}"' if found.quote else ""
    if found.live_coding == "yes":
        return 0, BAD, f"live coding or a coding test{where}"
    if found.live_coding == "no":
        rounds = found.rounds
        points = INTERVIEW_MAX if rounds is None or rounds <= 3 else 18 if rounds == 4 else 15
        said = f", {rounds} rounds" if rounds else ""
        return points, GOOD, f"no live coding{said}{where}"
    return INTERVIEW_UNKNOWN, None, "interview process not known yet"


# --- the total ----------------------------------------------------------------

BENEFITS_MAX, EQUITY_MAX = 1, 2
RUBRIC_VERSION = 1


def total(parts: dict[str, list]) -> int:
    return int(sum(points for points, _ in parts.values()))
