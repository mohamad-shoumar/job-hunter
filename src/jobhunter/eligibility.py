"""Can this company hire someone who lives in Lebanon? Deterministic first pass.

Verdicts:
  eligible  the posting says so (Lebanon listed, or open worldwide)
  likely    a region/time zone that includes Lebanon, or an employer-of-record hint
  unclear   remote, but nothing decisive - or the signals contradict each other
  rejected  onsite/hybrid, or limited to places that do not include Lebanon

The rules only reject on evidence they can quote back. When a positive and a
negative signal disagree ("Worldwide" in the location field, "must be based in
the US" in the text) the answer is `unclear`, not a guess. `unclear` jobs are
the ones an LLM or a human should look at.

"Remote" alone never counts as international: it is `unclear`.
"""

from __future__ import annotations

import re

from .extract import extract_contractor_mentions, extract_eor_mentions
from .geo import (
    LEBANON,
    POSITIVE_KINDS,
    REGION_OK,
    RESTRICTED,
    WORLDWIDE,
    PlaceMatch,
    classify_place,
    scan_title,
    timezone_signal,
    utc_offsets_allow_lebanon,
)
from .models import ELIGIBLE, HYBRID, LIKELY, NOT_ELIGIBLE, ONSITE, UNCLEAR, Assessment, Job

# --- description scanning ---------------------------------------------------

_PREFIX = r"(?:the\s+|one\s+of\s+the\s+following\s+(?:countries|locations|states|regions)\s*:?\s*)?"
_PLACE = r"(?P<place>[A-Za-z][A-Za-z .,&/()'\u2019-]{1,60}?)"
_END = (
    r"(?=\s*(?:[.;:!?\n]|$)|\s+(?:to|with|who|where|without|at|for|as|is|are|if|during|in order|"
    r"and\s+(?:have|be|are|possess|hold|able|eligible|can|will|must)))"
)
_WHO = r"(?:(?:who\s+(?:are|live)\s+)?(?:located|based|residing|living)\s+)?"
_PEOPLE = r"(?:(?:candidates|applicants|residents|people|individuals|those|talent|employees|contractors|anyone)\s+)?"

_RESIDENCY_PATTERNS = [re.compile(p, re.I) for p in (
    r"\b(?:must|should|need\s+to|needs\s+to|required\s+to|have\s+to|has\s+to|will\s+need\s+to)\s+(?:be\s+)?"
    r"(?:currently\s+|physically\s+|permanently\s+|legally\s+)?(?:located|based|residing|resident|reside|living|live|situated)"
    r"\s+(?:in|within)\s+" + _PREFIX + _PLACE + _END,
    r"\b(?:only|exclusively)\s+(?:open|available|hiring|accepting\s+(?:applications|applicants|candidates))\s+"
    r"(?:to|for|from|in)\s+" + _PEOPLE + _WHO + r"(?:(?:in|from|within)\s+)?" + _PREFIX + _PLACE + _END,
    r"\b(?:open|available)\s+(?:only\s+)?to\s+" + _PEOPLE + r"(?:who\s+(?:are|live)\s+)?(?:located|based|residing|living)\s+"
    r"(?:in|within)\s+" + _PREFIX + _PLACE + _END,
    r"\b(?:authori[sz]ed|eligible|legally\s+(?:able|authori[sz]ed|permitted|entitled)|permitted|entitled|right)\s+to\s+work\s+"
    r"(?:in|within|for)\s+" + _PREFIX + _PLACE + _END,
    r"\bremote\s+(?:within|in|across|from)\s+" + _PREFIX + _PLACE + _END,
    r"\b(?:we|you)\s+(?:can|are\s+able\s+to|will)\s+only\s+(?:hire|employ|consider|work\s+with)\s+" + _PEOPLE + _WHO
    + r"(?:in|from|within)\s+" + _PREFIX + _PLACE + _END,
    r"\b(?:unable|not\s+able|cannot|can't|can\s+not|do\s+not|don't|won't|will\s+not)\s+(?:to\s+)?(?:hire|employ|consider|accept)\s+"
    + _PEOPLE + _WHO + r"(?:from\s+)?outside\s+(?:of\s+)?" + _PREFIX + _PLACE + _END,
)]
# Capitalized forms only, so ordinary words are not read as places. "US-based
# employees" is left out on purpose: it is E-Verify/benefits boilerplate about
# existing staff, not a rule about who may apply.
_PLACE_QUALIFIER_PATTERNS = [
    re.compile(r"\b(?P<place>US|U\.S\.|USA|UK|EU|EEA|[A-Z][a-z]+)[- ]based\s+(?:candidates|applicants|talent|engineers|"
               r"individuals|contractors|only|role|position)\b"),
    re.compile(r"\b(?P<place>US|U\.S\.|USA|UK|EU|EEA|[A-Z][a-z]+)\s+(?:citizens?|residents?|nationals?|citizenship|residency|"
               r"work\s+authori[sz]ation)\s+(?:only|required|is\s+required|is\s+a\s+must)\b"),
]
# Not case-insensitive as a whole: "US citizen" must not match "join us, citizen".
_US_ONLY_BLOCKERS = re.compile(
    r"(?i:\b(?:security\s+clearance|active\s+clearance|ts/sci|top\s+secret\s+clearance|public\s+trust\s+clearance|itar|green\s+card)\b)"
    r"|(?:\bUS|\bU\.S\.|(?i:\bunited\s+states))\s+(?i:citizen(?:ship)?s?)\b"
)
# About WHO is hired, not how the team works: "we hire globally" counts,
# "work in a globally distributed environment" does not.
_WORLDWIDE_PROSE = re.compile(
    r"\b(?:hire|hiring|hires|recruit|recruiting|employ|employing|open\s+to\s+(?:candidates|applicants|people|talent)|"
    r"welcome\s+(?:candidates|applicants)|candidates|applicants|talent)\b[^.\n]{0,40}?\b"
    r"(?:from\s+anywhere\s+in\s+the\s+world|anywhere\s+in\s+the\s+world|worldwide|globally(?!\s+distributed)|from\s+any\s+country|"
    r"in\s+any\s+country|around\s+the\s+world|across\s+the\s+(?:globe|world)|regardless\s+of\s+(?:your\s+|their\s+)?location)\b"
    r"|\b(?:fully|100%|completely)[ -]remote\b[^.\n]{0,25}?\b(?:worldwide|anywhere\s+in\s+the\s+world|globally)\b"
    r"|\bwork\s+from\s+anywhere\b(?!\s+(?:in|within|across)\s+(?!(?:the\s+)?world\b))"
    r"|\blocation[- ]independent\b",
    re.I,
)
_LEBANON_PROSE = re.compile(r"\b(?:lebanon|beirut)\b", re.I)


def _snippet(text: str, start: int, end: int, width: int = 160) -> str:
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start)) + 1
    right_candidates = [i for i in (text.find(".", end), text.find("\n", end)) if i != -1]
    right = min(right_candidates) if right_candidates else len(text)
    snippet = " ".join(text[left:right].split())
    return snippet if len(snippet) <= width else snippet[: width - 1].rstrip() + "\u2026"


class DescriptionSignals:
    """Everything the description says about where candidates may live."""

    def __init__(self, description: str):
        text = description or ""
        self.restrictions: list[str] = []
        # "must be based in Europe or the Middle East": a rule naming a place that fits.
        self.place_positives: list[str] = []
        for pattern in _RESIDENCY_PATTERNS + _PLACE_QUALIFIER_PATTERNS:
            for m in pattern.finditer(text):
                kind = classify_place(m.group("place")).kind
                if kind == RESTRICTED:
                    self.restrictions.append(_snippet(text, m.start(), m.end()))
                elif kind in POSITIVE_KINDS or kind == LEBANON:
                    self.place_positives.append(_snippet(text, m.start(), m.end()))
        for m in _US_ONLY_BLOCKERS.finditer(text):
            self.restrictions.append(_snippet(text, m.start(), m.end()))
        # "we hire around the world": often company boilerplate, not about this role.
        m = _WORLDWIDE_PROSE.search(text)
        self.worldwide_prose = _snippet(text, m.start(), m.end()) if m else None
        m = _LEBANON_PROSE.search(text)
        self.lebanon = _snippet(text, m.start(), m.end()) if m else None
        self.eor = extract_eor_mentions(text)
        self.contractor = extract_contractor_mentions(text)
        self.timezone = timezone_signal(text)
        self.restrictions = list(dict.fromkeys(self.restrictions))
        self.place_positives = list(dict.fromkeys(self.place_positives))

    @property
    def specific_positive(self) -> str | None:
        """Strong enough to doubt a location the posting itself states.

        Company boilerplate ("GitLab hires in countries around the world") is
        not: it appears on every posting, including the ones limited to one
        country.
        """
        if self.lebanon:
            return self.lebanon
        if self.place_positives:
            return self.place_positives[0]
        if self.eor:
            return "hires through an employer of record (" + ", ".join(self.eor) + ")"
        return None

    @property
    def strong_positive(self) -> str | None:
        """Strong enough to doubt a residency rule found in the description."""
        return self.specific_positive or self.worldwide_prose


# --- decision ---------------------------------------------------------------


def _quote(matches: list[PlaceMatch]) -> str:
    return "; ".join(dict.fromkeys(f'"{m.evidence}"' for m in matches))


def assess_eligibility(job: Job) -> Assessment:
    field_texts = job.allowed_locations or ([job.location_raw] if job.location_raw else [])
    field_matches = [classify_place(t, field=True) for t in field_texts]
    title_matches = scan_title(job.title)
    everything = field_matches + title_matches

    lebanon = [m for m in everything if m.kind == LEBANON]
    if lebanon:
        return Assessment(ELIGIBLE, [f"Lebanon is listed: {_quote(lebanon)}"], "lebanon_listed")

    if job.remote_status in (ONSITE, HYBRID):
        where = job.location_raw or ", ".join(job.allowed_locations) or "no location given"
        return Assessment(NOT_ELIGIBLE, [f'Not remote ({job.remote_status}): "{where}"'], "not_remote")

    tz_conflict = None
    if job.allowed_utc_offsets and not utc_offsets_allow_lebanon(job.allowed_utc_offsets):
        offsets = ", ".join(f"UTC{o:+g}" for o in sorted(set(job.allowed_utc_offsets)))
        tz_conflict = f"candidates must be in these time zones: {offsets}"

    desc = DescriptionSignals(job.description)
    notes = []
    if desc.contractor:
        notes.append("Mentions contractor hiring: " + ", ".join(desc.contractor))
    if desc.eor:
        notes.append("Mentions an employer of record: " + ", ".join(desc.eor))

    field_positive = [m for m in field_matches if m.kind in POSITIVE_KINDS]
    title_positive = [m for m in title_matches if m.kind in POSITIVE_KINDS]
    positive = field_positive + title_positive
    field_restricted = [m for m in field_matches if m.kind == RESTRICTED]
    title_restricted = [m for m in title_matches if m.kind == RESTRICTED]

    if positive:
        # Alternatives inside one place (a list of locations, one field) are
        # an OR, so a positive wins there. A restriction from somewhere else
        # (the title, the description) contradicts it.
        conflicts = list(desc.restrictions) + ([tz_conflict] if tz_conflict else [])
        if title_restricted and not title_positive:
            conflicts.append(f"title: {_quote(title_restricted)}")
        if field_restricted and not field_positive:
            conflicts.append(f"location: {_quote(field_restricted)}")
        kinds = {m.kind for m in positive}
        if conflicts:
            return Assessment(
                UNCLEAR,
                [f"Location says {_quote(positive)}, but: " + " | ".join(conflicts)] + notes,
                "conflict",
            )
        if WORLDWIDE in kinds:
            return Assessment(ELIGIBLE, [f"Open worldwide: {_quote(positive)}"] + notes, "worldwide")
        if REGION_OK in kinds:
            return Assessment(LIKELY, [f"Region includes Lebanon: {_quote(positive)}"] + notes, "region_ok")
        return Assessment(LIKELY, [f"Time zone window includes Lebanon: {_quote(positive)}"] + notes, "timezone_ok")

    restricted = field_restricted + title_restricted
    if restricted:
        # "Remote - Europe (UTC-1 to UTC+3)": the place may be loose wording
        # for a time zone window that does include Lebanon.
        tz_in_field = next((timezone_signal(t) for t in field_texts if timezone_signal(t)), None)
        doubt = desc.specific_positive or (f"time zone window {tz_in_field}" if tz_in_field else None)
        if doubt:
            return Assessment(UNCLEAR, [f"Restricted to {_quote(restricted)}, but: {doubt}"] + notes, "conflict")
        return Assessment(NOT_ELIGIBLE, [f"Restricted to {_quote(restricted)}"] + notes, "location_restricted")

    if tz_conflict:
        return Assessment(NOT_ELIGIBLE, [tz_conflict[0].upper() + tz_conflict[1:]], "timezone_restricted")

    # Nothing usable in the location fields: the description decides.
    if desc.restrictions:
        if desc.strong_positive:
            return Assessment(
                UNCLEAR,
                [f'Description limits location: "{desc.restrictions[0]}", but also: "{desc.strong_positive}"'] + notes,
                "conflict",
            )
        return Assessment(NOT_ELIGIBLE, [f'Description limits location: "{desc.restrictions[0]}"'], "residency_required")
    if desc.lebanon:
        return Assessment(LIKELY, [f'Description mentions Lebanon: "{desc.lebanon}"'] + notes, "description_lebanon")
    positive = desc.place_positives[0] if desc.place_positives else desc.worldwide_prose
    if positive:
        return Assessment(LIKELY, [f'Description: "{positive}"'] + notes, "description_positive")
    if desc.eor:
        return Assessment(LIKELY, notes, "eor")
    if desc.timezone:
        return Assessment(LIKELY, [f'Time zone window includes Lebanon: "{desc.timezone}"'] + notes, "timezone_ok")
    location = job.location_raw or "none given"
    return Assessment(
        UNCLEAR,
        [f'Remote, but the posting does not say where candidates may live (location: "{location}")'] + notes,
        "no_location_info",
    )
