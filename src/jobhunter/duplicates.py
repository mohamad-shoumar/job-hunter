"""The same role stored twice: one company, one title, one place, two postings.

Dedup (identity.py) keeps two postings with different ATS ids apart on purpose: one company
can post "Backend Engineer" for EMEA and for the US, and merging those would hide the one
open to Lebanon. But a company also re-posts the SAME opening under a new id (Databricks'
London "Forward Deployed Engineer" on 8 October and again on 28 October, Axle Energy's
London "Software Engineer" four times), and two aggregators hand the same posting on with
different links. Those copies filled the shortlist and the To apply column with one role
two and three times, and brought back roles already applied to: on 2026-11-13 the stored
jobs held 19 such roles, 24 copies in all (the user's call, 2026-11-14).

So after the rules have judged a job, the copies of one role are gathered and all but one
are rejected, code `duplicate_role`, the reason naming the job that was kept. It is a
status, not a display rule, so the report, Today's list, the daily CV step and the app all
see one job per role. Nothing is deleted: a copy stays stored, under Rejected, and
`reclassify` works the rule out again from scratch, so changing it undoes it.

Which copy stays:

- the one carrying your work - you applied, reached out, wrote a LinkedIn note, or skipped
  it - so the application, the tailored CV and the history are never the copy that is hidden
  (the user's call, 2026-11-14: a role they already acted on should not come back when the
  company re-posts it);
- else the newest posting, which is the one still open: a re-post gets a new ATS id and the
  old link usually dies.

Place is part of being the same role, because the same title in another country is another
job, judged by other rules: Resonance posts "Applied AI Engineer" in London and in Berlin,
two visa routes, and both stay. Two texts name the same place when one's words are the
other's, or a subset of them, so "London" = "London, UK" = "London (hybrid), United Kingdom"
while "London" and "Berlin" stay apart; neither naming a place ("Remote", "Worldwide") also
counts as the same, but one naming a place and the other not ("Remote - India" against
"Remote") does not.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from .models import CLOSED, NEW, SAVED, STAGE_LABELS
from .store import JobStore
from .store.lists import role_copies
from .text import strip_accents

# Dropped before two locations are compared: how you work there, not where it is. "Remote" and
# "Worldwide" leave nothing behind, which is how two remote copies of one role still match.
_PLACE_NOISE = {
    "remote", "remotely", "hybrid", "onsite", "office", "wfh", "flexible", "anywhere",
    "worldwide", "global", "globally", "fully", "100", "distributed", "and", "or", "the",
    "area", "region", "based", "in", "at", "of",
}
# Both spellings of one place, so "Bristol, UK" and "Bristol, United Kingdom" are one place.
_PLACE_SAME = {
    "uk": "united kingdom", "gb": "united kingdom", "gbr": "united kingdom",
    "usa": "united states", "us": "united states", "america": "united states",
    "nl": "netherlands", "nederland": "netherlands", "holland": "netherlands",
    "de": "germany", "deutschland": "germany", "uae": "united arab emirates",
    "nyc": "new york", "sf": "san francisco", "espana": "spain", "italia": "italy",
}


def place_words(text: str | None) -> set[str]:
    """The words that say where a job is: lowercase, no accents, no punctuation, no work mode.

    "London (hybrid), United Kingdom" -> {"london", "united", "kingdom"}; "Remote" -> set().
    """
    words: set[str] = set()
    for word in re.sub(r"[^a-z0-9]+", " ", strip_accents(text or "").lower()).split():
        words.update(w for w in _PLACE_SAME.get(word, word).split() if w not in _PLACE_NOISE)
    return words


def same_place(left: str | None, right: str | None) -> bool:
    """Whether two location texts name the same place: one's words are the other's, or a subset."""
    x, y = place_words(left), place_words(right)
    if not x or not y:
        return not x and not y  # both say only "Remote": the same place. One of them naming a city: not.
    return x <= y or y <= x


def acted_on(row: sqlite3.Row) -> bool:
    """Whether you have done something with this job yourself.

    A tailored CV does not count: the daily run writes those on its own (`outreach.to_prepare`).
    """
    stage = row["stage"]
    return bool((stage and stage not in (NEW, SAVED)) or row["applied_at"] or row["linkedin_url"])


# How a closed job reads in the reason: "they turned you down" says more than "it is under Closed".
_WHY_CLOSED = {"skipped": "you skipped it", "rejected": "they turned you down", "ghosted": "it went quiet"}


def _what_you_did(row: sqlite3.Row) -> str:
    """Your own words for why this copy is the one kept, so the rejection quotes a fact you can check."""
    stage = row["stage"]
    if stage == CLOSED:
        return _WHY_CLOSED.get(row["closed_reason"], "you closed it")
    if row["applied_at"]:
        return "you applied to it"
    if stage and stage not in (NEW, SAVED):
        return f"it is under {STAGE_LABELS.get(stage, stage)}"
    return "you wrote its LinkedIn note"


def _rank(row: sqlite3.Row) -> tuple:
    """Best copy first: the one you acted on, then the newest posting, then the newest row."""
    return (acted_on(row), row["posted_at"] or row["first_seen"] or "", row["id"])


def clusters(rows: list[sqlite3.Row]) -> list[list[sqlite3.Row]]:
    """Copies of one role grouped by place, each group best copy first.

    Rows must already share a fingerprint (company + title). The best copy opens a group and
    every later row joins the first group whose opener names the same place, so the groups do
    not depend on the order the rows came in.
    """
    groups: list[list[sqlite3.Row]] = []
    for row in sorted(rows, key=_rank, reverse=True):
        for group in groups:
            if same_place(group[0]["location_raw"], row["location_raw"]):
                group.append(row)
                break
        else:
            groups.append([row])
    return groups


@dataclass
class Duplicate:
    """A copy that is being rejected, and the copy of the same role that is kept."""

    job_id: int
    kept_id: int
    company: str
    title: str
    reason: str


def _reason(keeper: sqlite3.Row) -> str:
    where = " ".join((keeper["location_raw"] or "").split()) or "no location given"
    posted = (keeper["posted_at"] or keeper["first_seen"] or "")[:10]
    why = _what_you_did(keeper) if acted_on(keeper) else "the newest posting of this role"
    return (f'Same role, already kept as job #{keeper["id"]}: "{keeper["title"]}" at {keeper["company"]}, '
            f'{where}, posted {posted} ({why})')


def duplicates(rows: list[sqlite3.Row]) -> list[Duplicate]:
    """Which copies of a role to reject, given every copy still shortlisted or on the visa list."""
    out = []
    for group in clusters(rows):
        keeper, *copies = group
        out += [Duplicate(r["id"], keeper["id"], r["company"], r["title"], _reason(keeper)) for r in copies]
    return out


def fold(store: JobStore, fingerprint: str) -> list[Duplicate]:
    """Reject every copy of one role but the one to keep. The caller commits.

    Both the daily run (`pipeline.ingest`, for the role a new job belongs to) and
    `jobhunter reclassify` (for every role) come through here, so the two can never disagree.
    """
    found = duplicates(role_copies(store, fingerprint))
    for copy in found:
        store.mark_duplicate(copy.job_id, copy.reason)
    return found
