"""The real application page of a job a board listed, and whether the posting is closed (the user's ask,
2026-11-26: on the 2026-11-25 apply-job run, looking for the employer's own form by hand was the biggest
part of the 8.5 minutes spent checking postings, and two jobs turned out closed on LinkedIn).

- freehire: `/api/v1/go/<slug>` (its own Apply button) redirects to the posting it indexed (Workday,
  Greenhouse, LinkedIn, an Adzuna page...), and its job API carries `closed_at` once it sees the posting go.
- Arbeitnow: `<job page>/apply` redirects to the company's form, often through a short link (grnh.se).
- LinkedIn: the logged-out job page (`sources.linkedin.POSTING`) marks a closed posting with
  `closed-job__flavor--closed` ("No longer accepting applications"), and answers 404 for one taken down.
- Adzuna answers scripts with 403, so a job whose trail ends there keeps the Adzuna link: apply-job
  searches once for the company's own page, then skips it as aggregator-only.

Only redirect headers are read (Http.final_url), plus freehire's JSON and LinkedIn's job page; every
request waits `pause`. `application_url` gets the page found (utm_* and ref dropped), even one that
refuses scripts (jobgether's 403: a repost by an agency is worth seeing as one); `source_url` and the
identity keys never change. A closed posting is only reported: `jobhunter links --skip-closed` (the
apply-job skill's setup) moves it to Closed as skipped, quoting why.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .sources.base import describe_error
from .sources.linkedin import POSTING as LINKEDIN_POSTING

FREEHIRE_GO = "https://freehire.me/api/v1/go/{slug}?src=web"
FREEHIRE_JOB = "https://freehire.me/api/v1/jobs/{slug}"
_LINKEDIN_JOB = re.compile(r"linkedin\.com/jobs/view/(?:[^/?#]*-)?(\d{6,})")
_LINKEDIN_CLOSED = "closed-job__flavor--closed"
# LinkedIn answers about one request a second with HTTP 429 (sources/linkedin.py waits 2.5 s): never faster.
LINKEDIN_PAUSE = 2.5


@dataclass
class Link:
    job_id: int
    url: str | None = None  # the application page found, when it differs from the stored link
    closed: str | None = None  # why the posting is closed, in the site's words
    note: str = ""  # what could not be followed


def _host(url: str | None) -> str:
    return (urlsplit(url or "").hostname or "").lower()


def clean(url: str) -> str:
    """The link without tracking parameters (utm_*, ref=arbeitnow.com); every other one (gh_jid) kept."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() != "ref"]
    return urlunsplit(parts._replace(query=urlencode(query)))


def on_listing(url: str | None) -> bool:
    """No link, or freehire's or Arbeitnow's own page (arbeitnow.com, www.arbeitnow.co.uk...)."""
    host = _host(url)
    return not host or host == "freehire.me" or host.endswith(".freehire.me") or "arbeitnow." in host


def wanted(row) -> bool:
    """A job worth a look: any freehire job (closed?), an Arbeitnow one not resolved yet, one on LinkedIn."""
    return (row["source"] == "freehire" or row["source"] == "arbeitnow" and on_listing(row["application_url"])
            or bool(_LINKEDIN_JOB.search(row["application_url"] or "")))


def resolve(http, row, pause: float = 1.0) -> Link:
    """One job's Link. A request that fails costs only its own part (noted), never the run."""
    link = Link(row["id"])

    def get(fn, url, wait=pause):
        if wait:
            time.sleep(wait)
        return fn(url)

    slug = (row["source_url"] or "").rstrip("/").rsplit("/", 1)[-1]
    try:
        if row["source"] == "freehire" and slug:
            data = get(http.get_json, FREEHIRE_JOB.format(slug=slug))
            data = data.get("data", data) if isinstance(data, dict) else {}
            if data.get("closed_at"):
                link.closed = f"freehire marks it closed (closed_at {str(data['closed_at'])[:10]})"
            if on_listing(row["application_url"]):
                link.url = clean(get(http.final_url, FREEHIRE_GO.format(slug=slug)))
        elif row["source"] == "arbeitnow" and on_listing(row["application_url"]) and row["source_url"]:
            link.url = clean(get(http.final_url, row["source_url"].rstrip("/") + "/apply"))
    except Exception as exc:
        link.note = f"could not follow the listing: {describe_error(exc)}"
    if link.url and (on_listing(link.url) or link.url == row["application_url"]):
        link.url = None  # the trail ended on the listing itself: nothing better than what is stored
    found = _LINKEDIN_JOB.search(link.url or row["application_url"] or "")
    if found and not link.closed:
        try:
            page = get(http.get_text, LINKEDIN_POSTING.format(id=found.group(1)), pause and max(pause, LINKEDIN_PAUSE))
            if _LINKEDIN_CLOSED in page:
                link.closed = "LinkedIn: No longer accepting applications"
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:  # the poster took it down: its /jobs/view page is a 404 too
                link.closed = "LinkedIn: the job page is gone (HTTP 404)"
            else:
                link.note = (link.note + "; " if link.note else "") + f"LinkedIn page: {describe_error(exc)}"
        except Exception as exc:
            link.note = (link.note + "; " if link.note else "") + f"LinkedIn page: {describe_error(exc)}"
    return link


def to_apply(store, now: datetime) -> list:
    """The Pipeline's To apply column: shortlisted jobs not acted on, visa-list ones posted in the last 2 days."""
    from .store.lists import job_list

    return [*job_list(store, "shortlisted"), *job_list(store, "visa_list", posted_since=now - timedelta(days=2))]


def save(store, links: list[Link], now: datetime, skip_closed: bool = False) -> None:
    """Write each page found; with `skip_closed`, move each closed posting to Closed as skipped (the Skip
    button's reason "Not open to me"), quoting why. The caller commits."""
    from .models import CLOSED
    from .tracking import set_stage

    for link in links:
        if link.url:
            store.set_application_url(link.job_id, link.url)
        if skip_closed and link.closed:
            set_stage(store, link.job_id, CLOSED, now, reason="skipped", skip_reason="not_open",
                      skip_note=f"Closed: {link.closed} (jobhunter links)")


def line(row, link: Link) -> str:
    parts = [f"#{row['id']:<6} {row['company']} — {row['title']}"]
    if link.closed:
        parts.append(f"CLOSED: {link.closed}")
    if link.url:
        parts.append(f"apply: {link.url}")
    if link.note:
        parts.append(link.note)
    return "\n         ".join(parts)
