"""Eligibility + relevance + freshness -> one status per job: rejected, shortlisted or visa_list.

The rules in eligibility.py come first. Only when they say `unclear` does a
stored AI web check (ai_check.py) get a say, and only with a verified quote.
needs_review is no longer given (2026-10-27); the jobs left in it were cleared on 2026-10-29
(models.REVIEW_CLEARED).
"""

from __future__ import annotations

import re
from datetime import datetime

from .config import Filters
from .eligibility import assess_eligibility
from .extract import quote_around
from .identity import company_key
from .models import (
    CAN_HIRE,
    CANNOT_HIRE,
    IRRELEVANT,
    LIKELY,
    NOT_ELIGIBLE,
    REJECTED,
    SHORTLISTED,
    SPONSORS_VISA,
    UNCLEAR,
    UNKNOWN_HIRE,
    VISA_LIST,
    VISA_SPONSOR,
    AiCheck,
    Assessment,
    Classification,
    Job,
)
from .relevance import assess_relevance
from .text import parse_datetime
from .visa import read_posting

# A 401(k) is a US-only retirement plan: a remote job that offers one is remote within the US,
# whatever its location says. Rejected on sight (decision 2026-10-19, see docs/decisions.md), even
# with "Worldwide" or a can-hire AI check; Metabase's "Global Remote" posts, which offer one to US
# staff, are lost too. A visa-list job is kept: it sponsors the move, and big companies list every
# country's benefits ("retirement options (401(k)/pension)", Roku Cambridge). Not "$401k" or
# "401K-500K" (pay).
_US_BENEFITS = re.compile(r"(?<![\w$€£.,])401\s?\(?\s?k\s?\)?(?![\w\-–])", re.I)


def us_benefits(description: str) -> str | None:
    """The line that offers a 401(k), quoted around the match, or None."""
    text = description or ""
    m = _US_BENEFITS.search(text)
    if not m:
        return None
    start = text.rfind("\n", 0, m.start()) + 1
    end = text.find("\n", m.end())
    line = text[start:end if end != -1 else len(text)]
    return quote_around(line, m.start() - start, m.end() - start)

def recheck_age(row) -> bool:
    """Whether re-running the rules on a stored job judges its age again.

    A date-range run files each job under its posting day, because those postings were
    asked for however old: their age is not re-judged. Every other job is, so a change
    to the age limit reaches the jobs the daily run found (age is still measured at discovery).
    """
    if not row["report_date"] or row["reject_code"] == "too_old":
        return True
    posted = parse_datetime(row["posted_at"])
    return not posted or posted.astimezone().date().isoformat() != row["report_date"]


def apply_ai_check(rule: Assessment, check: AiCheck) -> Assessment:
    """Combine an `unclear` rule verdict with the AI check. The rule's reasons stay listed."""
    evidence = f'"{check.quote}" ({check.source_url})'
    rule_reasons = [f"Rules: {rule.reasons[0]}", *rule.reasons[1:]] if rule.reasons else []
    if check.verified and check.verdict == CANNOT_HIRE:
        return Assessment(NOT_ELIGIBLE, [f"AI check: {check.reason} {evidence}", *rule_reasons], "ai_cannot_hire")
    if check.verified and check.verdict == CAN_HIRE:
        return Assessment(LIKELY, [f"AI check: {check.reason} {evidence}", *rule_reasons], "ai_can_hire")
    # The visa rules read the quote too: "sponsorship" alone, or "we cannot sponsor", is no offer.
    offer = read_posting(check.quote) if check.verdict == SPONSORS_VISA else None
    if check.verified and offer and offer.offers and not offer.refusals:
        return Assessment(LIKELY, [f"AI check: {check.reason} {evidence}", *rule_reasons], "ai_sponsors_visa")
    if check.verdict == UNKNOWN_HIRE:
        note = f"AI check found nothing decisive: {check.reason}"
    elif check.verified and offer:
        note = f"AI check says it sponsors a visa, but its quote does not offer one, so it is not used: {evidence} {check.reason}"
    else:
        said = check.verdict.replace("_", " ")
        note = f"AI check says {said}, but its quote was not found on the page, so it is not used: {evidence} {check.reason}"
    return Assessment(UNCLEAR, [*rule.reasons, note], rule.code)


def classify(job: Job, filters: Filters, now: datetime, check_age: bool = True) -> Classification:
    """check_age=False for a job inside an explicitly requested date range:
    asking for "Sep 1 - Sep 7" means those postings are wanted, however old."""
    eligibility = assess_eligibility(job, filters.relocation, filters.visa)
    if eligibility.verdict == UNCLEAR and job.ai_check:
        eligibility = apply_ai_check(eligibility, job.ai_check)
    relevance, score = assess_relevance(job, filters)

    # Hacker News names come as "WorkHero https://workhero.pro": the link is not part of the name.
    company = re.sub(r"https?://\S+", " ", job.company or "").strip()
    blocked = filters.blocked_companies.get(company_key(company))
    if blocked:
        name, why = blocked
        reason = f'Company is on your blocked list: "{name}"' + (f" ({why})" if why else "")
        return Classification(REJECTED, eligibility, relevance, score, reason, "blocked_company")
    agency = filters.agencies.check(company, job.description)
    if agency:
        return Classification(REJECTED, eligibility, relevance, score, agency, "agency")

    # Age is measured at discovery, so re-running the rules later does not
    # reject jobs that were fresh when they were found.
    found = job.first_seen or now
    limit = filters.max_posting_age_days
    if check_age and job.posted_at and limit is not None:
        age = (found - job.posted_at).days
        if age > limit:
            reason = f"Posted {age} days before it was found (limit {limit})"
            return Classification(REJECTED, eligibility, relevance, score, reason, "too_old")

    if relevance.verdict == IRRELEVANT:
        return Classification(REJECTED, eligibility, relevance, score, relevance.reasons[0], relevance.code)
    if eligibility.verdict == NOT_ELIGIBLE:
        return Classification(REJECTED, eligibility, relevance, score, eligibility.reasons[0], eligibility.code)
    # After the location rules, so a job they reject keeps its own reason ("no visa evidence").
    benefits = us_benefits(job.description) if eligibility.verdict != VISA_SPONSOR else None
    if benefits:
        reason = f'Offers a 401(k), a US-only retirement plan, so it hires in the US: "{benefits}"'
        return Classification(REJECTED, eligibility, relevance, score, reason, "us_benefits")
    if eligibility.verdict == VISA_SPONSOR:
        # A list of its own, apart from the remote jobs. An unknown posting date is a note there.
        if not job.posted_at:
            relevance = Assessment(relevance.verdict, [*relevance.reasons, "No posting date, so its age is unknown"],
                                   relevance.code)
        return Classification(VISA_LIST, eligibility, relevance, score)
    # A job the rules keep is shortlisted, an `unclear` or undated one too: there is no review list (decision
    # 2026-10-27). The report and the web app show it as `unclear` or "No posting date", and the daily run's AI
    # check and date lookup still reject the ones they find quoted evidence against.
    found = job.date_check
    if found and found.posted_at and job.posted_at:
        relevance = Assessment(relevance.verdict, [*relevance.reasons, f'Posting date {found.posted_at[:10]} '
                                                   f'found on a page: "{found.quote}" ({found.source_url})'],
                               relevance.code)
    if not job.posted_at:
        # An unknown age is not a fresh one: some sources re-list months-old jobs undated.
        relevance = Assessment(relevance.verdict, [*relevance.reasons, "No posting date, so its age is unknown"],
                               relevance.code)
    return Classification(SHORTLISTED, eligibility, relevance, score)
