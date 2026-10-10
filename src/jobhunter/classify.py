"""Eligibility + relevance + freshness -> one status per job.

The rules in eligibility.py come first. Only when they say `unclear` does a
stored AI web check (ai_check.py) get a say, and only with a verified quote.
"""

from __future__ import annotations

import re
from datetime import datetime

from .config import Filters
from .eligibility import assess_eligibility
from .identity import company_key
from .models import (
    CAN_HIRE,
    CANNOT_HIRE,
    ELIGIBLE,
    IRRELEVANT,
    LIKELY,
    NEEDS_REVIEW,
    NOT_ELIGIBLE,
    REJECTED,
    SHORTLISTED,
    UNCLEAR,
    UNKNOWN_HIRE,
    AiCheck,
    Assessment,
    Classification,
    Job,
)
from .relevance import assess_relevance

# Sources that read a company's own careers page (watched boards included): a job
# listed there is open, so it gets max_posting_age_days_company_boards.
COMPANY_BOARD_SOURCES = {"greenhouse", "lever", "ashby", "custom_page", "teamtailor", "bamboohr",
                         "smartrecruiters", "pinpoint"}


def apply_ai_check(rule: Assessment, check: AiCheck) -> Assessment:
    """Combine an `unclear` rule verdict with the AI check. The rule's reasons stay listed."""
    evidence = f'"{check.quote}" ({check.source_url})'
    rule_reasons = [f"Rules: {rule.reasons[0]}", *rule.reasons[1:]] if rule.reasons else []
    if check.verified and check.verdict == CANNOT_HIRE:
        return Assessment(NOT_ELIGIBLE, [f"AI check: {check.reason} {evidence}", *rule_reasons], "ai_cannot_hire")
    if check.verified and check.verdict == CAN_HIRE:
        return Assessment(LIKELY, [f"AI check: {check.reason} {evidence}", *rule_reasons], "ai_can_hire")
    if check.verdict == UNKNOWN_HIRE:
        note = f"AI check found nothing decisive: {check.reason}"
    else:
        said = check.verdict.replace("_", " ")
        note = f"AI check says {said}, but its quote was not found on the page, so it is not used: {evidence} {check.reason}"
    return Assessment(UNCLEAR, [*rule.reasons, note], rule.code)


def classify(job: Job, filters: Filters, now: datetime, check_age: bool = True) -> Classification:
    """check_age=False for a job inside an explicitly requested date range:
    asking for "Sep 1 - Sep 7" means those postings are wanted, however old."""
    eligibility = assess_eligibility(job, filters.relocation)
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
    if job.source in COMPANY_BOARD_SOURCES and filters.max_posting_age_days_company_boards is not None:
        limit = filters.max_posting_age_days_company_boards
    if check_age and job.posted_at and limit is not None:
        age = (found - job.posted_at).days
        if age > limit:
            reason = f"Posted {age} days before it was found (limit {limit})"
            return Classification(REJECTED, eligibility, relevance, score, reason, "too_old")

    if relevance.verdict == IRRELEVANT:
        return Classification(REJECTED, eligibility, relevance, score, relevance.reasons[0], relevance.code)
    if eligibility.verdict == NOT_ELIGIBLE:
        return Classification(REJECTED, eligibility, relevance, score, eligibility.reasons[0], eligibility.code)
    status = SHORTLISTED if eligibility.verdict in (ELIGIBLE, LIKELY) else NEEDS_REVIEW
    if status == SHORTLISTED and not job.posted_at:
        # An unknown age is not a fresh one: some sources re-list months-old jobs undated.
        status = NEEDS_REVIEW
        relevance = Assessment(relevance.verdict, [*relevance.reasons, "No posting date, so its age is unknown"],
                               relevance.code)
    return Classification(status, eligibility, relevance, score)
