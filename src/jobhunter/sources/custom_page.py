"""A company careers page with no ATS API.

Config per page: `url` (the listing page), `job_link_pattern` (regex a job
URL must match, tested after relative links are made absolute), and optional
`default_location`, `default_workplace_type`, `max_jobs`.

Each job page is read from its schema.org JobPosting JSON-LD when present
(many careers pages embed it for Google), else from its <h1> and body text.
"""

from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin, urlsplit

from ..extract import normalize_workplace
from ..models import Job
from ..text import html_to_text, parse_datetime
from .base import Source, SourceResult, describe_error, enabled_entries

_HREF = re.compile(r"""href\s*=\s*["']([^"'#]+)["']""", re.I)
_JSON_LD = re.compile(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", re.I | re.S)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_BODY = re.compile(r"<body[^>]*>(.*)</body>", re.I | re.S)


class CustomPageSource(Source):
    name = "custom_page"

    def __init__(self, pages: list[dict]):
        self.pages = pages

    def fetch(self, http) -> SourceResult:
        result = SourceResult(self.name)
        for page in self.pages:
            try:
                listing = http.get_text(page["url"])
            except Exception as exc:
                result.errors.append(f"{page['company']}: {describe_error(exc)}")
                continue
            pattern = re.compile(page["job_link_pattern"])
            links = list(dict.fromkeys(urljoin(page["url"], html.unescape(h)) for h in _HREF.findall(listing)))
            links = [link for link in links if pattern.search(link)]
            if not links:
                result.notes.append(f"{page['company']}: no links matched job_link_pattern")
            for link in links[: int(page.get("max_jobs", 25))]:
                try:
                    result.jobs.append(parse_job_page(http.get_text(link), link, page))
                except Exception as exc:
                    result.errors.append(f"{page['company']} {link}: {describe_error(exc)}")
        return result


def _job_posting(page_html: str) -> dict | None:
    for block in _JSON_LD.findall(page_html):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                kind = node.get("@type")
                if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
                    return node
                stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
    return None


def _ld_locations(posting: dict) -> list[str]:
    requirements = posting.get("applicantLocationRequirements") or []
    if isinstance(requirements, dict):
        requirements = [requirements]
    return [r.get("name") for r in requirements if isinstance(r, dict) and r.get("name")]


def parse_job_page(page_html: str, url: str, page: dict) -> Job:
    posting = _job_posting(page_html) or {}
    h1 = _H1.search(page_html)
    title_tag = _TITLE.search(page_html)
    title = posting.get("title") or html_to_text(h1.group(1) if h1 else "") or html_to_text(title_tag.group(1) if title_tag else "")
    if posting.get("description"):
        description = html_to_text(posting["description"])
    else:
        body = _BODY.search(page_html)
        description = html_to_text(body.group(1) if body else page_html)
    workplace = "remote" if posting.get("jobLocationType") == "TELECOMMUTE" else page.get("default_workplace_type")
    allowed = _ld_locations(posting)
    location = ", ".join(allowed) or page.get("default_location")
    org = posting.get("hiringOrganization") or {}
    return Job(
        source="custom_page",
        source_job_id=urlsplit(url).path.rstrip("/") or url,
        source_url=url,
        company=page.get("company") or (org.get("name") if isinstance(org, dict) else "") or "",
        title=title,
        description=description,
        application_url=url,
        company_location=page.get("company_location"),
        location_raw=location,
        allowed_locations=allowed,
        remote_status=normalize_workplace(workplace),
        employment_type=posting.get("employmentType") if isinstance(posting.get("employmentType"), str) else None,
        posted_at=parse_datetime(posting.get("datePosted")),
    )


def from_config(section) -> CustomPageSource | None:
    pages = [p for p in enabled_entries(section) if p.get("url") and p.get("job_link_pattern")]
    return CustomPageSource(pages) if pages else None
