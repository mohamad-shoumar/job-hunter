"""The home countries the location rules know (geo.Home), by ISO code.

Lebanon is the default and the one the rules were written for. The others are a short,
tested list (tests/test_homes.py): which region names include a country is a judgment, so
each entry stays conservative: a region a company might mean either way is left out, so
the job reads as restricted, never as open. Notes per country:

- Egypt: in MENA, the Middle East and EMEA, and in Africa / North Africa.
- Pakistan, India: South Asia, Asia and APAC; not EMEA or the Middle East.
- Nigeria, Kenya: EMEA and Africa / Sub-Saharan Africa.
- Brazil, Argentina, Colombia: LATAM, Latin America, South America, the Americas and AMER;
  "North America" stays a restriction (it usually means the US and Canada). A US time zone
  within 3 hours of their clock fits them ("EST hours"); one further away ("Pacific Time" for
  Brazil) is a restriction, as it is for Lebanon.
- Philippines: APAC, Asia, Southeast Asia.
- Jordan is left out: "Jordan" is a common first name, so prose would read people as places.

UTC offsets are winter and summer where the country changes its clocks (Egypt does again
since 2023; Brazil stopped in 2019).
"""

from __future__ import annotations

from .geo import LEBANON_HOME, Home

_LATAM = ("latam", "latin america", "south america", "americas", "amer")

HOMES: dict[str, Home] = {
    "LB": LEBANON_HOME,
    "EG": Home("EG", "Egypt", ("egypt", "egyptian", "cairo", "alexandria", "giza"), ("egypt", "cairo", "alexandria"),
               (2.0, 3.0), ("emea", "mena", "menat", "middle east", "middle eastern", "near east", "arab world",
                            "arab region", "arab countries", "eastern mediterranean", "africa", "north africa")),
    "PK": Home("PK", "Pakistan", ("pakistan", "pakistani", "karachi", "lahore", "islamabad"),
               ("pakistan", "karachi", "lahore", "islamabad"), (5.0,), ("south asia", "asia", "apac", "asia pacific")),
    "IN": Home("IN", "India", ("india", "indian", "bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "delhi",
                               "new delhi", "gurgaon", "gurugram", "noida", "chennai", "kolkata"),
               ("india", "bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "new delhi", "gurugram", "chennai"),
               (5.5,), ("south asia", "asia", "apac", "asia pacific")),
    "NG": Home("NG", "Nigeria", ("nigeria", "nigerian", "lagos", "abuja"), ("nigeria", "lagos", "abuja"),
               (1.0,), ("emea", "africa", "sub saharan africa", "west africa")),
    "KE": Home("KE", "Kenya", ("kenya", "kenyan", "nairobi"), ("kenya", "nairobi"),
               (3.0,), ("emea", "africa", "sub saharan africa", "east africa")),
    "BR": Home("BR", "Brazil", ("brazil", "brasil", "brazilian", "sao paulo", "rio de janeiro"),
               ("brazil", "brasil", "são paulo", "sao paulo", "rio de janeiro"), (-3.0,), _LATAM),
    "AR": Home("AR", "Argentina", ("argentina", "argentinian", "argentine", "buenos aires"), ("argentina", "buenos aires"),
               (-3.0,), _LATAM),
    "CO": Home("CO", "Colombia", ("colombia", "colombian", "bogota", "medellin"),
               ("colombia", "bogota", "bogotá", "medellin", "medellín"), (-5.0,), _LATAM),
    "PH": Home("PH", "Philippines", ("philippines", "filipino", "manila", "cebu"), ("philippines", "manila"),
               (8.0,), ("apac", "asia pacific", "asia", "southeast asia", "south east asia")),
}


def home_from(value: str | dict | None) -> Home:
    """`home` in filters.json: an ISO code ("EG"), a full entry, or nothing (Lebanon)."""
    if not value:
        return LEBANON_HOME
    if isinstance(value, str):
        code = value.strip().upper()
        if code not in HOMES:
            raise ValueError(f"unknown home country {value!r}: known ones are {', '.join(sorted(HOMES))}")
        return HOMES[code]
    fields = dict(value)
    for key in ("names", "prose", "utc_offsets", "regions"):
        fields[key] = tuple(fields.get(key, ()))
    return Home(**fields)
