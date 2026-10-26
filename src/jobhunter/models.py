"""The one internal job shape. Every source adapter produces these."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# remote_status values
REMOTE = "remote"
HYBRID = "hybrid"
ONSITE = "onsite"
UNKNOWN = "unknown"

# employment_type values
FULL_TIME = "full_time"
PART_TIME = "part_time"
CONTRACT = "contract"
INTERNSHIP = "internship"
TEMPORARY = "temporary"

# Can someone living in Lebanon be hired? (eligibility)
ELIGIBLE = "eligible"  # the posting says so: worldwide, or Lebanon listed
LIKELY = "likely"  # a region or time zone that includes Lebanon (EMEA, UTC+2)
UNCLEAR = "unclear"  # remote, but nothing decisive either way
NOT_ELIGIBLE = "rejected"
# In a country you would move to on a work visa (visa.py), with evidence the employer sponsors one.
VISA_SPONSOR = "visa_sponsor"

# Is this a role worth applying to? (relevance)
MATCH = "match"  # target title and Python in the posting
MAYBE = "maybe"  # target title, no Python evidence
IRRELEVANT = "rejected"

# What the AI web check found (ai_check.py), for jobs the rules left unclear
CAN_HIRE = "can_hire"
CANNOT_HIRE = "cannot_hire"
UNKNOWN_HIRE = "unknown"
# Not remote from Lebanon, but the company sponsors a work visa to move for it, in any country
# (decision 2026-10-22, see docs/decisions.md).
SPONSORS_VISA = "sponsors_visa"

# Final status, which decides where a job shows up
SHORTLISTED = "shortlisted"
NEEDS_REVIEW = "needs_review"
REJECTED = "rejected"
# The separate list of jobs abroad that sponsor a work visa (visa.py): not in the shortlist or "To apply".
VISA_LIST = "visa_list"

# Where you are with a job (applications.stage; tracking.py moves jobs between them)
NEW = "new"
SAVED = "saved"
REACHED_OUT = "reached_out"
REPLIED = "replied"
INTERVIEWING = "interviewing"
OFFER = "offer"
CLOSED = "closed"
STAGES = [NEW, SAVED, REACHED_OUT, REPLIED, INTERVIEWING, OFFER, CLOSED]
STAGE_LABELS = {
    NEW: "New", SAVED: "Saved", REACHED_OUT: "Reached out", REPLIED: "Replied",
    INTERVIEWING: "Interviewing", OFFER: "Offer", CLOSED: "Closed",
}


@dataclass
class Job:
    source: str
    source_job_id: str
    source_url: str
    company: str
    title: str
    description: str = ""
    application_url: str | None = None
    company_location: str | None = None
    # Location text exactly as the source shows it (for humans and as a fallback).
    location_raw: str | None = None
    # Where candidates may live, when the source states it as a list
    # (e.g. Himalayas "locationRestrictions", WWR "country"). Takes priority
    # over location_raw when deciding eligibility.
    allowed_locations: list[str] = field(default_factory=list)
    # UTC offsets candidates must be in, when the source states them.
    allowed_utc_offsets: list[float] = field(default_factory=list)
    remote_status: str = UNKNOWN
    employment_type: str | None = None
    # Contractor / employer-of-record mentions, e.g. ["deel", "independent contractor"].
    contract_info: list[str] = field(default_factory=list)
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    salary_raw: str | None = None
    required_yoe: int | None = None
    skills: list[str] = field(default_factory=list)
    # Source-provided tags. Used to extract skills, not stored.
    tags: list[str] = field(default_factory=list)
    posted_at: datetime | None = None
    # Set by the store.
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    ai_check: AiCheck | None = None
    date_check: DateCheck | None = None


@dataclass
class AiCheck:
    """What the AI web check found for a job the rules left unclear (see ai_check.py)."""

    verdict: str  # can_hire | cannot_hire | sponsors_visa | unknown
    reason: str  # one sentence from the model
    quote: str = ""
    source_url: str = ""
    # The quote was found word for word in the job description or a page the
    # model opened. Only a verified quote can change a job's status.
    verified: bool = False
    model: str = ""
    checked_at: str = ""
    searches: int = 0
    cost_usd: float | None = None


@dataclass
class DateCheck:
    """When an undated job was posted, as found on a page (see posted_date.py)."""

    posted_at: str | None  # ISO date code read from the quote; None when nothing was found
    quote: str = ""
    source_url: str = ""
    # "page" (code read the page's schema.org datePosted) or the model that searched the web.
    found_by: str = ""
    reason: str = ""
    checked_at: str = ""


@dataclass
class Assessment:
    verdict: str
    reasons: list[str]
    # Short machine-readable reason for the verdict, used for report stats.
    code: str = ""


@dataclass
class Classification:
    status: str
    eligibility: Assessment
    relevance: Assessment
    fit_score: int
    reject_reason: str | None = None
    reject_code: str | None = None
