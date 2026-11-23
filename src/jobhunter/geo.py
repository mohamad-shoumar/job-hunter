"""Does a piece of location text include someone living in your home country?

The home is Lebanon unless a `Home` is passed (homes.py has the others; `home` in
config/filters.json picks one). Every rule below reads "Lebanon" as "the home".

classify_place() sorts text into one of:

  lebanon      the home named (Lebanon/Beirut); the kind keeps its old name
  worldwide    worldwide, anywhere, global, ...
  region_ok    a region that contains the home: EMEA, MENA, Middle East
  timezone_ok  a time zone window that contains the home (UTC+2 / UTC+3)
  restricted   a named place that does not contain the home: US, Europe, India, ...
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
from functools import cache

from .text import strip_accents

LEBANON = "lebanon"
HOME = LEBANON  # the kind for "the home is named"; the value predates other homes
WORLDWIDE = "worldwide"
REGION_OK = "region_ok"
TIMEZONE_OK = "timezone_ok"
RESTRICTED = "restricted"
UNKNOWN = "unknown"

POSITIVE_KINDS = {WORLDWIDE, REGION_OK, TIMEZONE_OK}

@dataclass(frozen=True)
class Home:
    """Where the job seeker lives: the place every location rule is judged against."""

    code: str  # ISO 3166 alpha-2: "LB"
    name: str  # in reasons: "Region includes Lebanon"
    names: tuple[str, ...]  # words that name it in a location: country, demonym, cities
    prose: tuple[str, ...]  # words that name it in free text: no demonyms ("Indian Ocean")
    utc_offsets: tuple[float, ...]  # winter and summer
    regions: tuple[str, ...]  # region names that include it: "EMEA", "LATAM"
    word: str = "home"  # in reject codes: "home_listed" ("lebanon_listed" for Lebanon, as stored)


LEBANON_HOME = Home(
    code="LB",
    name="Lebanon",
    names=("lebanon", "lebanese", "beirut"),
    prose=("lebanon", "beirut"),
    # Lebanon is UTC+2 in winter and UTC+3 in summer.
    utc_offsets=(2.0, 3.0),
    regions=(
        "emea", "mena", "menat", "middle east", "middle eastern", "levant", "west asia", "western asia",
        "near east", "arab world", "arab region", "arab countries", "eastern mediterranean",
    ),
    word="lebanon",
)
LEBANON_UTC_OFFSETS = LEBANON_HOME.utc_offsets


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


_WORLDWIDE_RE = _alternation([
    "worldwide", "world wide", "anywhere", "everywhere", "global", "globally", "international",
    "internationally", "intl", "all countries", "any country", "any location", "location independent",
    "location agnostic", "planet earth",
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
# Regions that do not include Lebanon. Every region named here or in a home's `regions` restricts
# a home it does not include.
_OTHER_REGIONS = [
    "north america", "northern america", "south america", "latin america", "latam",
    "central america", "americas", "caribbean", "europe", "european", "european union",
    "european economic area", "eea", "schengen", "western europe", "eastern europe",
    "central europe", "northern europe", "southern europe", "cee", "dach", "nordics", "nordic",
    "scandinavia", "benelux", "baltics", "balkans", "iberia", "apac", "asia pacific", "asia",
    "east asia", "south asia", "southeast asia", "south east asia", "oceania", "anz",
    "australasia", "africa", "sub saharan africa", "north africa", "gcc", "gulf region",
]
_KNOWN_REGIONS = list(LEBANON_HOME.regions) + _OTHER_REGIONS
# Places the lists above leave out: Lebanon itself, and the cities of the other homes (homes.py).
_OTHER_HOME_PLACES = [
    "lebanon", "beirut", "alexandria", "giza", "islamabad", "lagos", "abuja", "nairobi", "medellin",
    "cebu", "kolkata", "rio de janeiro", "brasil",
]
_DEMONYMS = ["american", "canadian", "british"]
# US time zones and their UTC offsets (standard, daylight). Naming one far from the home's clock
# (Lebanon, UTC+2/+3) is a hard US-hours window: a restriction. One within _NEAR_US_HOURS of it
# ("EST" for Bogota) is a time zone that fits.
_US_ZONES = {
    "pacific": (("pst", "pdt", "pacific time"), (-8.0, -7.0)),
    "mountain": (("mst", "mdt", "mountain time"), (-7.0, -6.0)),
    "central": (("cst", "cdt", "central time"), (-6.0, -5.0)),
    "eastern": (("est", "edt", "eastern time"), (-5.0, -4.0)),
}
_NEAR_US_HOURS = 3.0
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
# "European time zones", "CET", "EMEA hours": a home whose clock is within this span fits them.
_EUROPEAN_HOURS = (-1.0, 4.0)


def _us_zones_pattern(zones: list[str]) -> re.Pattern:
    """US time zones as a time zone: capital codes only ("est. 2015" is not one), or the full name."""
    codes = [code.upper() for zone in zones for code in _US_ZONES[zone][0][:2]]
    return re.compile(r"(?<![A-Za-z])(?:" + "|".join(codes) + r")(?![A-Za-z.])"
                      r"|(?i:\b(?:" + "|".join(zones) + r")\s+(?:standard\s+|daylight\s+)?time\b)")


def _window_has(home: Home, low: float, high: float) -> bool:
    return any(low - 0.01 <= o <= high + 0.01 for o in home.utc_offsets)


@dataclass(frozen=True)
class _Rules:
    """One home's patterns, built once (rules_for)."""

    home: re.Pattern  # on _words() text
    prose: re.Pattern  # on raw text
    ok_regions: frozenset[str]
    regions: re.Pattern  # every known region and place, longest first: "southeast asia" is not "asia"
    restricted: re.Pattern  # on _words() text
    zones_ok: tuple[re.Pattern, ...]  # named time zones that fit the home
    zones: tuple[re.Pattern, ...]  # every time zone phrase, removed before reading places


@cache
def rules_for(home: Home) -> _Rules:
    names = {_words(n) for n in home.names}
    ok = frozenset(_words(r) for r in home.regions)
    near = [z for z, (_, offs) in _US_ZONES.items()
            if any(abs(o - h) <= _NEAR_US_HOURS + 0.01 for o in offs for h in home.utc_offsets)]
    far_words = [w for z, (words, _) in _US_ZONES.items() if z not in near for w in words]
    us_ok = (_us_zones_pattern(near),) if near else ()
    # Lebanon and the other homes' cities are places like any other for every other home. They are
    # kept out of Lebanon's own list so its verdicts stay exactly as they were (checked over the
    # 51,241 stored jobs, 2026-11-23), though restricting them there would be right too.
    extra = _OTHER_HOME_PLACES if home.code != LEBANON_HOME.code else []
    all_places = _COUNTRIES + _US_STATES_AND_PROVINCES + _CITIES + extra
    places = [p for p in all_places if _words(p) not in names]
    other_regions = [r for r in _KNOWN_REGIONS if _words(r) not in ok]
    restricted = places + other_regions + _DEMONYMS + far_words
    zones_ok = ((_TZ_NAMED_OK,) if _window_has(home, *_EUROPEAN_HOURS) else ()) + us_ok
    return _Rules(
        home=_alternation(home.names),
        prose=re.compile(r"\b(?:" + "|".join(re.escape(p) for p in home.prose) + r")\b", re.I),
        ok_regions=ok,
        # Places too, so a region word inside a country name is not that region: "South Africa" is
        # not "Africa".
        regions=_alternation(set(_KNOWN_REGIONS) | set(home.regions) | set(all_places)),
        restricted=_alternation(restricted),
        zones_ok=zones_ok,
        zones=(_TZ_NAMED_OK, _TZ_PLUS_MINUS, _TZ_WITHIN, _TZ_OFFSET) + us_ok,
    )


def names_home(text: str | None, home: Home | None = None) -> re.Match | None:
    """Where free text names the home ("Beirut"), if it does."""
    return rules_for(home or LEBANON_HOME).prose.search(text or "")


def _region_ok(words: str, rules: _Rules) -> bool:
    return any(m.group(0) in rules.ok_regions for m in rules.regions.finditer(words))


def _offset_value(raw: str | None) -> float:
    if not raw:
        return 0.0
    raw = raw.replace("−", "-").replace("–", "-").replace(" ", "")
    sign = -1 if raw.startswith("-") else 1
    hours, _, minutes = raw.lstrip("+-").replace(".", ":").partition(":")
    return sign * (int(hours) + (int(minutes) / 60 if minutes else 0))


def timezone_signal(text: str | None, home: Home | None = None) -> str | None:
    """The phrase that puts the home inside a stated time zone window, if any."""
    if not text:
        return None
    home = home or LEBANON_HOME
    for pattern in rules_for(home).zones_ok:
        m = pattern.search(text)
        if m:
            return m.group(0)
    for m in _TZ_PLUS_MINUS.finditer(text):
        base, spread = _TZ_BASE[m.group(1).lower()], int(m.group(2))
        if _window_has(home, base - spread, base + spread):
            return m.group(0)
    for m in _TZ_WITHIN.finditer(text):
        spread, base = int(m.group(1)), _TZ_BASE[m.group(2).lower()]
        if _window_has(home, base - spread, base + spread):
            return m.group(0)
    offsets = list(_TZ_OFFSET.finditer(text))
    for i, m in enumerate(offsets):
        value = _offset_value(m.group(2))
        if i + 1 < len(offsets) and _RANGE_JOINER.match(text[m.end():offsets[i + 1].start()]):
            other = _offset_value(offsets[i + 1].group(2))
            if _window_has(home, min(value, other), max(value, other)):
                return text[m.start():offsets[i + 1].end()]
        elif m.group(2) and _window_has(home, value, value):
            return m.group(0)
    return None


def _strip_timezones(text: str, rules: _Rules) -> str:
    for pattern in rules.zones:
        text = pattern.sub(" ", text)
    return text


def utc_offsets_allow(offsets: list[float], home: Home | None = None) -> bool:
    return any(abs(float(o) - h) <= 0.5 for o in offsets for h in (home or LEBANON_HOME).utc_offsets)


def utc_offsets_allow_lebanon(offsets: list[float]) -> bool:
    return utc_offsets_allow(offsets, LEBANON_HOME)


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


def _classify_one(text: str, field: bool, evidence: str, home: Home) -> PlaceMatch:
    rules = rules_for(home)
    words = _words(text)
    if rules.home.search(words):
        return PlaceMatch(LEBANON, evidence)
    # "Anywhere in the US" is a restriction; "anywhere in the world" is not.
    words = _ANYWHERE_IN.sub(" ", _ANYWHERE_IN_WORLD.sub(" worldwide ", words))
    if _WORLDWIDE_RE.search(words):
        return PlaceMatch(WORLDWIDE, evidence)
    if _region_ok(words, rules):
        return PlaceMatch(REGION_OK, evidence)
    # A named place beats a time zone next to it: "Remote - EU (CET)" is an EU
    # residency rule. Strip time zone phrases first so "European time zones"
    # does not read as "Europe".
    without_tz = _strip_timezones(text, rules)
    if rules.restricted.search(_words(without_tz)) or _SHORT_CODES_RE.search(without_tz):
        return PlaceMatch(RESTRICTED, evidence)
    if timezone_signal(text, home):
        return PlaceMatch(TIMEZONE_OK, evidence)
    if field and _leftover(_words(without_tz)):
        return PlaceMatch(RESTRICTED, evidence)
    return PlaceMatch(UNKNOWN, evidence)


def classify_place(text: str | None, field: bool = False, home: Home | None = None) -> PlaceMatch:
    home = home or LEBANON_HOME
    raw = " ".join((text or "").split())
    if not raw:
        return PlaceMatch(UNKNOWN, "")
    if rules_for(home).home.search(_words(raw)):
        return PlaceMatch(LEBANON, raw)
    cleaned = _drop_preferences(raw)
    alternatives = [a for a in _ALTERNATIVES.split(cleaned) if a.strip()] if field else []
    if len(alternatives) < 2:
        return _classify_one(cleaned, field, raw, home)
    matches = [_classify_one(a, field, raw, home) for a in alternatives]
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


def scan_title(title: str, home: Home | None = None) -> list[PlaceMatch]:
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
        m = classify_place(part, home=home)
        if m.kind in (LEBANON, REGION_OK, RESTRICTED, TIMEZONE_OK):
            matches.append(m)
    return matches
