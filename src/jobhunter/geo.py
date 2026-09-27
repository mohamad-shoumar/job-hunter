"""Does a piece of location text include someone living in Lebanon?

classify_place() sorts text into one of:

  lebanon      Lebanon/Beirut named
  worldwide    worldwide, anywhere, global, ...
  region_ok    a region that contains Lebanon: EMEA, MENA, Middle East
  timezone_ok  a time zone window that contains Lebanon (UTC+2 / UTC+3)
  restricted   a named place that does not contain Lebanon: US, Europe, India, ...
  unknown      nothing recognizable ("Remote", "Flexible")

Free prose (titles, descriptions) only counts KNOWN vocabulary: an unknown
word there is never read as a restriction. A dedicated location FIELD
(field=True) is stricter: whatever is left after removing words like "remote"
is almost always a place ("Remote, Bangalore"), so leftover text counts as a
restriction there.

Europe is treated as a restriction on purpose: "Remote (Europe)" usually means
the company can only employ people with EU residency. "European time zones" is
not a residency rule, and Lebanon (UTC+2/+3) fits it, so it is timezone_ok.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .text import strip_accents

LEBANON = "lebanon"
WORLDWIDE = "worldwide"
REGION_OK = "region_ok"
TIMEZONE_OK = "timezone_ok"
RESTRICTED = "restricted"
UNKNOWN = "unknown"

POSITIVE_KINDS = {WORLDWIDE, REGION_OK, TIMEZONE_OK}

# Lebanon is UTC+2 in winter and UTC+3 in summer.
LEBANON_UTC_OFFSETS = (2.0, 3.0)


@dataclass(frozen=True)
class PlaceMatch:
    kind: str
    evidence: str


def _words(text: str) -> str:
    s = strip_accents(text).lower().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def _alternation(terms) -> re.Pattern:
    normalized = sorted({_words(t) for t in terms}, key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(re.escape(t) for t in normalized) + r")\b")


_LEBANON_RE = re.compile(r"\b(?:lebanon|lebanese|beirut)\b")
_WORLDWIDE_RE = _alternation([
    "worldwide", "world wide", "anywhere", "everywhere", "global", "globally", "international",
    "internationally", "intl", "all countries", "any country", "any location", "location independent",
    "location agnostic", "planet earth",
])
_REGION_OK_RE = _alternation([
    "emea", "mena", "menat", "middle east", "middle eastern", "levant", "west asia", "western asia",
    "near east", "arab world", "arab region", "arab countries", "eastern mediterranean",
])

_COUNTRIES = [
    "afghanistan", "albania", "algeria", "andorra", "angola", "antigua and barbuda", "argentina",
    "armenia", "australia", "austria", "azerbaijan", "bahamas", "bahrain", "bangladesh", "barbados",
    "belarus", "belgium", "belize", "benin", "bhutan", "bolivia", "bosnia and herzegovina", "bosnia",
    "botswana", "brazil", "brunei", "bulgaria", "burkina faso", "burundi", "cabo verde", "cape verde",
    "cambodia", "cameroon", "canada", "central african republic", "chad", "chile", "china",
    "colombia", "comoros", "congo", "costa rica", "cote d ivoire", "ivory coast", "croatia", "cuba",
    "cyprus", "czechia", "czech republic", "denmark", "djibouti", "dominica", "dominican republic",
    "ecuador", "egypt", "el salvador", "equatorial guinea", "eritrea", "estonia", "eswatini",
    "ethiopia", "fiji", "finland", "france", "gabon", "gambia", "georgia", "germany", "ghana",
    "greece", "grenada", "guatemala", "guinea", "guinea bissau", "guyana", "haiti", "honduras",
    "hong kong", "hungary", "iceland", "india", "indonesia", "iran", "iraq", "ireland", "israel",
    "italy", "jamaica", "japan", "jordan", "kazakhstan", "kenya", "kiribati", "kosovo", "kuwait",
    "kyrgyzstan", "laos", "latvia", "lesotho", "liberia", "libya", "liechtenstein", "lithuania",
    "luxembourg", "macau", "madagascar", "malawi", "malaysia", "maldives", "mali", "malta",
    "marshall islands", "mauritania", "mauritius", "mexico", "micronesia", "moldova", "monaco",
    "mongolia", "montenegro", "morocco", "mozambique", "myanmar", "namibia", "nauru", "nepal",
    "netherlands", "holland", "new zealand", "nicaragua", "niger", "nigeria", "north korea",
    "north macedonia", "macedonia", "norway", "oman", "pakistan", "palau", "palestine", "panama",
    "papua new guinea", "paraguay", "peru", "philippines", "poland", "portugal", "puerto rico",
    "qatar", "romania", "russia", "russian federation", "rwanda", "saint lucia", "samoa",
    "san marino", "saudi arabia", "saudi", "senegal", "serbia", "seychelles", "sierra leone",
    "singapore", "slovakia", "slovenia", "solomon islands", "somalia", "south africa",
    "south korea", "korea", "south sudan", "spain", "sri lanka", "sudan", "suriname", "sweden",
    "switzerland", "syria", "taiwan", "tajikistan", "tanzania", "thailand", "timor leste", "togo",
    "tonga", "trinidad and tobago", "tunisia", "turkey", "turkiye", "turkmenistan", "tuvalu",
    "uganda", "ukraine", "united arab emirates", "emirates", "united kingdom", "great britain",
    "britain", "england", "scotland", "wales", "northern ireland", "united states",
    "united states of america", "america", "uruguay", "uzbekistan", "vanuatu", "vatican",
    "venezuela", "vietnam", "viet nam", "yemen", "zambia", "zimbabwe",
]
_US_STATES_AND_PROVINCES = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware",
    "florida", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi", "missouri",
    "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
    "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming", "ontario", "quebec", "british columbia",
    "alberta",
]
_CITIES = [
    "san francisco", "bay area", "silicon valley", "new york city", "seattle", "austin", "boston",
    "chicago", "los angeles", "denver", "atlanta", "miami", "toronto", "vancouver", "montreal",
    "london", "berlin", "munich", "hamburg", "paris", "amsterdam", "dublin", "madrid", "barcelona",
    "lisbon", "warsaw", "krakow", "prague", "vienna", "zurich", "stockholm", "copenhagen", "oslo",
    "helsinki", "tallinn", "bucharest", "sofia", "athens", "istanbul", "tel aviv", "cairo", "dubai",
    "abu dhabi", "riyadh", "jeddah", "doha", "manama", "muscat", "bangalore", "bengaluru",
    "hyderabad", "pune", "mumbai", "delhi", "new delhi", "gurgaon", "gurugram", "noida", "chennai",
    "karachi", "lahore", "kuala lumpur", "bangkok", "jakarta", "manila", "ho chi minh", "hanoi",
    "tokyo", "seoul", "taipei", "shanghai", "beijing", "shenzhen", "sydney", "melbourne",
    "auckland", "sao paulo", "buenos aires", "mexico city", "bogota", "santiago", "lima",
]
_REGIONS_WITHOUT_LEBANON = [
    "north america", "northern america", "south america", "latin america", "latam",
    "central america", "americas", "caribbean", "europe", "european", "european union",
    "european economic area", "eea", "schengen", "western europe", "eastern europe",
    "central europe", "northern europe", "southern europe", "cee", "dach", "nordics", "nordic",
    "scandinavia", "benelux", "baltics", "balkans", "iberia", "apac", "asia pacific", "asia",
    "east asia", "south asia", "southeast asia", "south east asia", "oceania", "anz",
    "australasia", "africa", "sub saharan africa", "north africa", "gcc", "gulf region",
    "american", "canadian", "british",
    # US time zones: a hard US-hours window rules out Lebanon (UTC+2/+3) in practice.
    "pst", "pdt", "est", "edt", "cst", "cdt", "mst", "mdt", "pacific time", "eastern time",
    "central time", "mountain time",
]
_RESTRICTED_RE = _alternation(_COUNTRIES + _US_STATES_AND_PROVINCES + _CITIES + _REGIONS_WITHOUT_LEBANON)
# Short codes only count in capitals, so the pronoun "us" never reads as the US.
_SHORT_CODES_RE = re.compile(r"(?<![A-Za-z])(?:U\.S\.A\.?|U\.S\.?|USA|US|UK|U\.K\.?|EU|UAE|KSA|NYC|SF)(?![A-Za-z])")

# Words that describe the arrangement, not the place. What is left after
# removing them from a location field is the place.
_FILLER = set(
    "remote remotely fully full first friendly work working from home homebased wfh hybrid onsite "
    "on site office offices in distributed telecommute telecommuting virtual flexible multiple various "
    "location locations or and only based the of within team available open to candidates position "
    "role roles job time zone zones timezone timezones hours tbd n a not specified any other possible "
    "preferred optional part contract permanent opportunity options option yes with occasional "
    "travel hq headquarters country countries region regions async asynchronous day days wk week weeks "
    "per month quarterly offsite overlap visa sponsorship relocation relo ok allowed some required "
    "welcome considered also plus is are for eng engineering product all level levels".split()
)


# --- time zones -------------------------------------------------------------

_TZ_NAMED_OK = re.compile(
    r"\b(?:eet|eest|eastern european(?: summer)? time|cet|cest|central european(?: summer)? time|"
    r"(?:europe(?:an)?|eu|emea|cet)\s*(?:time ?zones?|timezones?|hours|business hours|working hours))\b",
    re.I,
)
_TZ_OFFSET = re.compile(r"\b(utc|gmt)\s*([+\-−–]\s*\d{1,2}(?:[:.]\d{2})?)?", re.I)
_TZ_PLUS_MINUS = re.compile(
    r"\b(cet|cest|utc|gmt)\s*(?:±|\+/-|\+-|\+/−|plus or minus)\s*(\d{1,2})\s*(?:h\b|hours?)?", re.I
)
_TZ_WITHIN = re.compile(r"\bwithin\s+(\d{1,2})\s+hours?\s+of\s+(cet|cest|utc|gmt)\b", re.I)
_TZ_BASE = {"utc": 0.0, "gmt": 0.0, "cet": 1.0, "cest": 2.0}
_RANGE_JOINER = re.compile(r"^\s*(?:to|-|–|—|and|through|until|/)\s*$", re.I)


def _offset_value(raw: str | None) -> float:
    if not raw:
        return 0.0
    raw = raw.replace("−", "-").replace("–", "-").replace(" ", "")
    sign = -1 if raw.startswith("-") else 1
    hours, _, minutes = raw.lstrip("+-").replace(".", ":").partition(":")
    return sign * (int(hours) + (int(minutes) / 60 if minutes else 0))


def _window_has_lebanon(low: float, high: float) -> bool:
    return any(low - 0.01 <= o <= high + 0.01 for o in LEBANON_UTC_OFFSETS)


def timezone_signal(text: str | None) -> str | None:
    """The phrase that puts Lebanon inside a stated time zone window, if any."""
    if not text:
        return None
    m = _TZ_NAMED_OK.search(text)
    if m:
        return m.group(0)
    for m in _TZ_PLUS_MINUS.finditer(text):
        base, spread = _TZ_BASE[m.group(1).lower()], int(m.group(2))
        if _window_has_lebanon(base - spread, base + spread):
            return m.group(0)
    for m in _TZ_WITHIN.finditer(text):
        spread, base = int(m.group(1)), _TZ_BASE[m.group(2).lower()]
        if _window_has_lebanon(base - spread, base + spread):
            return m.group(0)
    offsets = list(_TZ_OFFSET.finditer(text))
    for i, m in enumerate(offsets):
        value = _offset_value(m.group(2))
        if i + 1 < len(offsets) and _RANGE_JOINER.match(text[m.end():offsets[i + 1].start()]):
            other = _offset_value(offsets[i + 1].group(2))
            if _window_has_lebanon(min(value, other), max(value, other)):
                return text[m.start():offsets[i + 1].end()]
        elif m.group(2) and _window_has_lebanon(value, value):
            return m.group(0)
    return None


def _strip_timezones(text: str) -> str:
    for pattern in (_TZ_NAMED_OK, _TZ_PLUS_MINUS, _TZ_WITHIN, _TZ_OFFSET):
        text = pattern.sub(" ", text)
    return text


def utc_offsets_allow_lebanon(offsets: list[float]) -> bool:
    return any(abs(float(o) - lb) <= 0.5 for o in offsets for lb in LEBANON_UTC_OFFSETS)


# --- places -----------------------------------------------------------------

_ANYWHERE_IN_WORLD = re.compile(r"\banywhere (?:in|within|across|from) (?:the )?(?:world|globe|planet)\b")
_ANYWHERE_IN = re.compile(r"\banywhere (?:in|within|across|from) (?:the )?")


def _leftover(words: str) -> str:
    return " ".join(w for w in words.split() if w not in _FILLER and not any(c.isdigit() for c in w) and len(w) > 1)


# A preference is a wish, not a rule, so it is removed before classifying:
# "REMOTE (US ONLY, LA/SF preferred)" is still US-only, "Remote (US preferred)"
# says nothing. A leading "preferred" covers the rest of its bracket group
# ("(preferred Spain, UK, Poland)"); a trailing one covers only its own part.
_PREF_LEADING = re.compile(r"(?:(?<=[(\[,;|])|^)\s*(?:preferred|preferably|ideally)\b[^()\[\]]*", re.I)
_PREF_TRAILING = re.compile(r"[^,;()\[\]|]*\b(?:preferred|preferably|ideally|nice to have|is a plus|a plus|bonus)\b", re.I)
# "NYC or Remote": the remote option names no place, so the field as a whole
# does not restrict anyone. Only split on separators that mean "or".
_ALTERNATIVES = re.compile(r"\s+or\s+|\s+/\s+|\s*\|\s*", re.I)
_BARE_REMOTE = re.compile(r"^\W*(?:fully\s+|100%\s+)?remote(?:ly)?(?:\s+(?:ok|possible|friendly|first))?\W*$", re.I)


def _drop_preferences(text: str) -> str:
    return _PREF_TRAILING.sub(" ", _PREF_LEADING.sub(" ", text))


def _classify_one(text: str, field: bool, evidence: str) -> PlaceMatch:
    words = _words(text)
    if _LEBANON_RE.search(words):
        return PlaceMatch(LEBANON, evidence)
    # "Anywhere in the US" is a restriction; "anywhere in the world" is not.
    words = _ANYWHERE_IN.sub(" ", _ANYWHERE_IN_WORLD.sub(" worldwide ", words))
    if _WORLDWIDE_RE.search(words):
        return PlaceMatch(WORLDWIDE, evidence)
    if _REGION_OK_RE.search(words):
        return PlaceMatch(REGION_OK, evidence)
    # A named place beats a time zone next to it: "Remote - EU (CET)" is an EU
    # residency rule. Strip time zone phrases first so "European time zones"
    # does not read as "Europe".
    without_tz = _strip_timezones(text)
    if _RESTRICTED_RE.search(_words(without_tz)) or _SHORT_CODES_RE.search(without_tz):
        return PlaceMatch(RESTRICTED, evidence)
    if timezone_signal(text):
        return PlaceMatch(TIMEZONE_OK, evidence)
    if field and _leftover(_words(without_tz)):
        return PlaceMatch(RESTRICTED, evidence)
    return PlaceMatch(UNKNOWN, evidence)


def classify_place(text: str | None, field: bool = False) -> PlaceMatch:
    raw = " ".join((text or "").split())
    if not raw:
        return PlaceMatch(UNKNOWN, "")
    if _LEBANON_RE.search(_words(raw)):
        return PlaceMatch(LEBANON, raw)
    cleaned = _drop_preferences(raw)
    alternatives = [a for a in _ALTERNATIVES.split(cleaned) if a.strip()] if field else []
    if len(alternatives) < 2:
        return _classify_one(cleaned, field, raw)
    matches = [_classify_one(a, field, raw) for a in alternatives]
    for kind in (WORLDWIDE, REGION_OK, TIMEZONE_OK):
        if any(m.kind == kind for m in matches):
            return PlaceMatch(kind, raw)
    if any(_BARE_REMOTE.match(a) for a in alternatives):
        return PlaceMatch(UNKNOWN, raw)
    if any(m.kind == RESTRICTED for m in matches):
        return PlaceMatch(RESTRICTED, raw)
    return PlaceMatch(UNKNOWN, raw)


_TITLE_WORLDWIDE = re.compile(
    r"^\s*(?:remote\s*[-,/:]?\s*)?(?:worldwide|anywhere|global|international|anywhere in the world)"
    r"(?:\s*[-,/:]?\s*remote)?\s*$",
    re.I,
)
# A dash with a space on at least one side ("Engineer- LATAM"), never a
# hyphen inside a word ("Full-Stack").
_TITLE_PART_SPLIT = re.compile(r"\s+[-–—|]\s*|\s*[-–—|]\s+")


def scan_title(title: str) -> list[PlaceMatch]:
    """Places named in a title's qualifiers: '(Remote, US)', '- EMEA'.

    Only parenthesized and dash-separated parts are read, and 'worldwide' only
    counts when the part says nothing else, so 'Global Payments Engineer' is
    not read as a worldwide role.
    """
    parts = re.findall(r"\(([^)]*)\)|\[([^\]]*)\]", title or "")
    candidates = [a or b for a, b in parts]
    pieces = _TITLE_PART_SPLIT.split(title or "")
    candidates += pieces[1:]
    matches = []
    for part in candidates:
        part = part.strip()
        if not part:
            continue
        if _TITLE_WORLDWIDE.match(part):
            matches.append(PlaceMatch(WORLDWIDE, part))
            continue
        m = classify_place(part)
        if m.kind in (LEBANON, REGION_OK, RESTRICTED, TIMEZONE_OK):
            matches.append(m)
    return matches
