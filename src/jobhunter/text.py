"""Small text helpers shared by every adapter: HTML to text, dates, title words."""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
    "tr", "table", "section", "article", "blockquote", "pre", "hr",
}
# Page chrome and non-content. Skipped entirely, including everything inside.
_SKIP_TAGS = {"script", "style", "noscript", "svg", "head", "nav", "footer", "form", "button", "iframe", "template"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif not self._skip:
            if tag == "li":
                self.parts.append("\n- ")
            elif tag in _BLOCK_TAGS:
                self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif not self._skip and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\r", "")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.split("\n")]
    lines = [line for line in lines if line != "-"]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def html_to_text(value: str | None) -> str:
    """Readable plain text from an HTML fragment or page. Keeps line breaks and bullets."""
    if not value:
        return ""
    if "<" not in value:
        return clean_text(html.unescape(value))
    parser = _TextExtractor()
    try:
        parser.feed(value)
        parser.close()
    except Exception:  # badly broken markup: strip tags the blunt way
        return clean_text(html.unescape(re.sub(r"<[^>]+>", " ", value)))
    return clean_text("".join(parser.parts))


_MOJIBAKE = re.compile("[Â-ô][\u0080-¿]")


def fix_mojibake(value: str | None) -> str:
    """Undo UTF-8 text that was decoded as Latin-1 once too often ('MecÃ¡nico' -> 'Mecánico')."""
    if not value or not _MOJIBAKE.search(value):
        return value or ""
    for codec in ("latin-1", "cp1252"):
        try:
            return value.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return value


def strip_accents(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


# Rewrites so that "Back-End Sr. Dev" and "senior backend developer" compare equal.
_WORD_SYNONYMS = [
    (r"\bback[\s-]?end\b", "backend"),
    (r"\bfront[\s-]?end\b", "frontend"),
    (r"\bfull[\s-]?stack\b", "fullstack"),
    (r"\bsr\b\.?", "senior"),
    (r"\bjr\b\.?", "junior"),
    (r"\bswe\b", "software engineer"),
    (r"\bdevs?\b", "developer"),
    (r"\bengineers\b", "engineer"),
    (r"\bdevelopers\b", "developer"),
    (r"\bnode\s*\.?\s*js\b", "nodejs"),
    (r"(?<![a-z0-9])\.net\b", " dotnet"),
    (r"\bc\+\+", "cpp"),
    (r"\bc#", "csharp"),
    (r"\bgen[\s-]?ai\b", "genai"),
    (r"\b(?:ai\s*/\s*ml|ml\s*/\s*ai)\b", "ai ml"),
]


def normalize_words(value: str) -> str:
    """Lowercase, accent-free, synonym-folded words separated by single spaces."""
    s = strip_accents(value or "").lower().replace("&", " and ")
    for pattern, replacement in _WORD_SYNONYMS:
        s = re.sub(pattern, replacement, s)
    s = re.sub(r"[^a-z0-9+#]+", " ", s)
    return " ".join(s.split())


def has_phrase(normalized_text: str, normalized_phrase: str) -> bool:
    """Whole-word phrase match on two normalize_words() outputs."""
    return f" {normalized_phrase} " in f" {normalized_text} "


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def parse_datetime(value) -> datetime | None:
    """Epoch seconds/milliseconds, ISO 8601, or RFC 2822 (RSS) -> aware UTC datetime."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
            ts = float(value)
            if ts > 1e12:  # milliseconds
                ts /= 1000
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        else:
            s = str(value).strip()
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                dt = parsedate_to_datetime(s)
    except (ValueError, TypeError, OverflowError, IndexError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


_RELATIVE_AGE = re.compile(r"(\d+)\+?\s*(minute|hour|day|week|month)s?\s+ago", re.I)
_UNIT_DAYS = {"minute": 1 / 1440, "hour": 1 / 24, "day": 1, "week": 7, "month": 30}


def parse_relative_age(value: str | None, now: datetime) -> datetime | None:
    """'3 days ago' -> now minus three days."""
    if not value:
        return None
    m = _RELATIVE_AGE.search(value)
    if not m:
        return None
    return (now - timedelta(days=int(m.group(1)) * _UNIT_DAYS[m.group(2).lower()])).replace(microsecond=0)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat() if dt else None
