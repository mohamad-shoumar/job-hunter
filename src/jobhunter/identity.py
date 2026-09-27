"""Job identity: when are two listings the same job?

Three keys, strongest first:

1. (source, source_job_id): the same listing seen again on the same source.
2. ats_key: the ATS posting id (Greenhouse/Lever/Ashby/Workable) found in any
   of the job's URLs. Aggregators often link straight to the ATS page, so this
   joins e.g. a We Work Remotely listing to the company's Greenhouse posting.
3. fingerprint: normalized company + normalized title. Catches the same job on
   two boards that link nowhere useful. It is NOT used when both listings carry
   different ATS ids - that is one company posting the same title twice (say
   "Backend Engineer" for EMEA and for the US), and merging those could hide
   the one that is open to Lebanon.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .text import normalize_words, strip_accents

_COMPANY_SUFFIXES = {
    "inc", "incorporated", "llc", "ltd", "limited", "gmbh", "corp", "corporation", "co",
    "company", "sa", "sas", "sarl", "bv", "nv", "ag", "plc", "pty", "srl", "oy", "ab",
    "as", "aps", "kft", "spa", "sl", "llp", "lp", "pte",
}


def company_key(name: str) -> str:
    s = strip_accents(name or "").lower()
    s = re.sub(r"\((?:yc|y combinator)[^)]*\)", " ", s)  # "Acme (YC S21)"
    s = re.sub(r"\.(?:com|io|so|ai|co|app|dev|net|org|xyz|tech)\b", " ", s)  # "Circle.so"
    s = s.replace("&", " and ")
    words = [w for w in re.sub(r"[^a-z0-9]+", " ", s).split() if w not in _COMPANY_SUFFIXES]
    if len(words) > 1 and words[0] == "the":
        words = words[1:]
    return " ".join(words)


_GENDER_MARKER = re.compile(r"\(\s*(?:[mfwdxh]\s*/\s*){1,3}[mfwdxh]\s*\)|\(\s*all genders\s*\)", re.I)
_TITLE_NOISE = {"remote", "fully", "100", "hybrid", "onsite", "wfh", "anywhere", "worldwide"}


def title_key(title: str) -> str:
    words = normalize_words(_GENDER_MARKER.sub(" ", title or "")).split()
    return " ".join(w for w in words if w not in _TITLE_NOISE)


def fingerprint(company: str, title: str) -> str:
    return f"{company_key(company)}|{title_key(title)}"


_ATS_PATTERNS = [
    (re.compile(r"greenhouse\.io/(?:[\w.-]+/)?jobs/(\d+)", re.I), "greenhouse"),
    (re.compile(r"greenhouse\.io/embed/job_app\?(?:[^#]*&)?token=(\d+)", re.I), "greenhouse"),
    (re.compile(r"[?&]gh_jid=(\d+)", re.I), "greenhouse"),
    (re.compile(r"jobs\.(?:eu\.)?lever\.co/[^/?#]+/([0-9a-f]{8}-[0-9a-f-]{27})", re.I), "lever"),
    (re.compile(r"jobs\.ashbyhq\.com/[^/?#]+/([0-9a-f]{8}-[0-9a-f-]{27})", re.I), "ashby"),
    (re.compile(r"apply\.workable\.com/[^/?#]+/j/([0-9a-z]+)", re.I), "workable"),
]


def ats_key_from_url(url: str | None) -> str | None:
    """'https://job-boards.greenhouse.io/gitlab/jobs/855' -> 'greenhouse:855'."""
    if not url:
        return None
    for pattern, ats in _ATS_PATTERNS:
        m = pattern.search(url)
        if m:
            return f"{ats}:{m.group(1).lower()}"
    return None


_URL_RE = re.compile(r"""https?://[^\s"'<>)\]]+""")


def find_ats_url(text: str | None) -> str | None:
    """First URL in some text/HTML that points at a specific ATS posting."""
    for url in _URL_RE.findall(text or ""):
        url = url.rstrip(".,;")
        if ats_key_from_url(url):
            return url
    return None


_TRACKING_PARAMS = re.compile(r"^(?:utm_\w+|ref|refs|source|src|gh_src|lever-source|lever-origin|via|trk)$", re.I)


def canonical_url(url: str | None) -> str | None:
    """Stable form of a URL: https, lowercase host, no fragment, no tracking params."""
    if not url:
        return None
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.netloc:
        return url
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING_PARAMS.match(k)])
    path = parts.path.rstrip("/") or "/"
    scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
    return urlunsplit((scheme, parts.netloc.lower(), path, query, ""))
