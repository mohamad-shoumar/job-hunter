"""Government lists of employers that sponsor work visas: evidence for the visa list.

  uk  Home Office "Register of licensed sponsors: workers", a CSV updated every
      working day. Only "Skilled Worker" rows count: the visa a software job uses.
  nl  IND "Public register recognised sponsors: work", an HTML table updated
      monthly. A Dutch employer must be on it to sponsor a highly skilled migrant.
  ie  DETE "Employment permits issued to companies", a spreadsheet per year.
      A company that got permits this year or last has sponsored people; not
      being on it proves nothing.

Germany, Finland, Spain and Italy keep no such list (a Blue Card needs no
licensed employer), so jobs there need the posting itself to offer a visa.

`jobhunter sponsors --update` saves each list as data/sponsors/<country>.json;
the daily run refreshes them every `refresh_days` (config/filters.json,
"visa_list"). A job in one of these countries at a company on its list goes to
the visa list with the row quoted.

Names are matched with company_key, also without trailing words such as "UK",
"Holdings" or "Payments" ("Stripe Payments UK Ltd" -> "stripe"), and both
sides of "t/a" ("Roofoods Ltd t/a Deliveroo"). A one-word name is often an
ordinary word ("Ramp", "Cursor"), so on the UK list it counts only when the
register's town is in the job's location: "Cursor Ltd, Lincoln" is not Cursor
in London. Checked 2026-10-13 against the stored jobs: every wrong match was a
one-word name in another town.
"""

from __future__ import annotations

import csv
import html
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree

from .identity import company_key
from .text import iso, normalize_words, parse_datetime

UK_CONTENT_API = "https://www.gov.uk/api/content/government/publications/register-of-licensed-sponsors-workers"
NL_REGISTER = "https://ind.nl/en/public-register-recognised-sponsors/public-register-work"
IE_STATS = "https://enterprise.gov.ie/en/publications/employment-permit-statistics-{year}.html"
IE_SITE = "https://enterprise.gov.ie"

LISTS = {
    "uk": "the UK register of licensed sponsors",
    "nl": "the IND register of recognised sponsors",
    "ie": "Ireland's list of companies issued employment permits",
}

# Dropped from the end of a register name, one at a time: "Stripe Payments UK" -> "stripe".
_TRAILING = {
    "uk", "gb", "england", "europe", "emea", "eu", "international", "intl", "global", "worldwide",
    "holdings", "holding", "group", "nederland", "netherlands", "ireland", "irl", "dac", "uc", "unlimited",
    "technologies", "technology", "tech", "payments", "bank", "software", "labs", "digital", "platforms", "ai",
}
_TRADING_AS = re.compile(r"\s+(?:t/a|trading\s+as)\s+", re.I)
_DOTTED = re.compile(r"(?<![A-Za-z])((?:[A-Za-z]\.){2,})")  # "B.V." -> "BV", so company_key drops it
_R_AND_D = re.compile(r"\bR\s*&\s*D\b", re.I)  # "Intercom R&D Unlimited Company"


@dataclass(frozen=True)
class Sponsor:
    country: str
    name: str  # as the list writes it
    town: str = ""
    detail: str = ""  # "Worker (A rating), Skilled Worker" | "KvK 34117849" | "62 permits in 2026"

    def quote(self) -> str:
        return ", ".join(p for p in (self.name, self.town, self.detail) if p)


def name_keys(name: str) -> set[str]:
    """Every key a register name is matched on."""
    keys: set[str] = set()
    for part in _TRADING_AS.split(name or ""):
        key = company_key(_R_AND_D.sub(" ", _DOTTED.sub(lambda m: m.group(1).replace(".", ""), part)))
        words = key.split()
        while words:
            keys.add(" ".join(words))
            keys.add("".join(words))  # "Eleven Labs" is "ElevenLabs" on a job board
            if len(words) == 1 or words[-1] not in _TRAILING:
                break
            words = words[:-1]
    keys.discard("")
    return keys


@dataclass
class Registers:
    """The lists in data/sponsors/, indexed by name key."""

    index: dict[str, dict[str, list[Sponsor]]] = field(default_factory=dict)  # country -> key -> rows
    meta: dict[str, dict] = field(default_factory=dict)  # country -> {"source", "updated", "fetched_at", "rows"}

    @classmethod
    def from_rows(cls, country: str, rows: list[Sponsor], meta: dict | None = None,
                  into: Registers | None = None) -> Registers:
        registers = into or cls()
        table = registers.index.setdefault(country, {})
        for row in rows:
            for key in name_keys(row.name):
                table.setdefault(key, []).append(row)
        registers.meta[country] = {**(meta or {}), "rows": len(rows)}
        return registers

    @classmethod
    def load(cls, folder: Path) -> Registers:
        registers = cls()
        for country in LISTS:
            path = folder / f"{country}.json"
            if path.exists():
                data = json.loads(path.read_text())
                rows = [Sponsor(country, *row) for row in data.pop("rows")]
                cls.from_rows(country, rows, data, registers)
        return registers

    def find(self, country: str, company: str, places: list[str]) -> Sponsor | None:
        """The list row for this company, when the job is in that list's country."""
        key = company_key(company)
        rows = self.index.get(country, {}).get(key) or self.index.get(country, {}).get(key.replace(" ", ""))
        if not rows:
            return None
        if len(key.split()) > 1:
            return rows[0]
        where = " " + " ".join(normalize_words(p) for p in places) + " "
        for row in rows:
            if not row.town:  # the NL and IE lists name no town: the country is the check
                return row
            if f" {normalize_words(row.town)} " in where:
                return row
        return None


# --- parsing --------------------------------------------------------------------


def parse_uk(text: str) -> list[Sponsor]:
    rows = []
    for raw in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        route = (raw.get("Route") or "").strip()
        name = (raw.get("Organisation Name") or "").strip()
        if route != "Skilled Worker" or not name:
            continue
        town = (raw.get("Town/City") or "").strip().strip(",").strip()
        rows.append(Sponsor("uk", name, town, f"{(raw.get('Type & Rating') or '').strip()}, {route}"))
    return list(dict.fromkeys(rows))  # Monzo is listed twice, "London" and "London "


_NL_ROW = re.compile(r'<tr>\s*<th scope="row">(.*?)</th>\s*<td>(.*?)</td>\s*</tr>', re.S)


def parse_nl(page: str) -> list[Sponsor]:
    rows = []
    for name, kvk in _NL_ROW.findall(page):
        name = " ".join(html.unescape(re.sub(r"<[^>]+>", "", name)).replace('""', '"').split())
        kvk = html.unescape(kvk).strip().replace("\xa0", "")
        if name:
            rows.append(Sponsor("nl", name, "", f"KvK {kvk}" if kvk else ""))
    return list(dict.fromkeys(rows))


_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def xlsx_rows(data: bytes) -> list[list[str]]:
    """The first sheet's cells as text, row by row. Enough for the plain lists published as xlsx."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ElementTree.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
        sheet = ElementTree.fromstring(z.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in sheet.iter(f"{{{_NS['m']}}}row"):
        cells: dict[int, str] = {}
        for c in row.findall("m:c", _NS):
            column = 0
            for ch in re.match(r"[A-Z]+", c.get("r", "A")).group(0):
                column = column * 26 + ord(ch) - 64
            kind, value = c.get("t"), c.find("m:v", _NS)
            if kind == "s" and value is not None:
                text = shared[int(value.text)]
            elif kind == "inlineStr":
                text = "".join(t.text or "" for t in c.iter(f"{{{_NS['m']}}}t"))
            else:
                text = value.text if value is not None and value.text else ""
            cells[column - 1] = text
        rows.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
    return rows


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def parse_ie(data: bytes, year: int) -> list[Sponsor]:
    """Employer name in the first column, the year's total in the column headed "... Total".

    Most permits first, so a company with several entities is quoted by its biggest.
    """
    rows, total_col = [], None
    for cells in xlsx_rows(data):
        if total_col is None:
            headed = [i for i, c in enumerate(cells) if "total" in c.lower()]
            if headed and not _number(cells[headed[-1]] or "x"):
                total_col = headed[-1]
            continue
        name = " ".join((cells[0] if cells else "").split())
        count = _number(cells[total_col]) if len(cells) > total_col else None
        if not name or not count or name.lower() in ("total", "grand total"):
            continue
        rows.append((count, Sponsor("ie", name, "", f"{count:g} employment permit{'s' if count != 1 else ''} in {year}")))
    return [row for _, row in sorted(rows, key=lambda r: -r[0])]


# --- fetching -------------------------------------------------------------------


def fetch_uk(http) -> tuple[list[Sponsor], dict]:
    info = http.get_json(UK_CONTENT_API)
    url = next(a["url"] for a in info["details"]["attachments"] if a.get("content_type") == "text/csv")
    return parse_uk(http.get_text(url)), {"source": url, "updated": (info.get("public_updated_at") or "")[:10]}


def fetch_nl(http) -> tuple[list[Sponsor], dict]:
    page = http.get_text(NL_REGISTER)
    m = re.search(r"last updated on (\d{1,2} \w+ \d{4})", page)
    return parse_nl(page), {"source": NL_REGISTER, "updated": m.group(1) if m else ""}


def fetch_ie(http, now: datetime) -> tuple[list[Sponsor], dict]:
    """This year's and last year's lists (the new year's file starts small), this year's rows first."""
    rows, sources = [], []
    for year in (now.year, now.year - 1):
        page = http.get_text(IE_STATS.format(year=year))
        m = re.search(r'href="([^"]*issued-to-companies[^"]*\.xlsx)"', page, re.I)
        if not m:
            continue
        url = m.group(1) if m.group(1).startswith("http") else IE_SITE + m.group(1)
        rows += parse_ie(http.get_bytes(url), year)
        sources.append(url)
    if not sources:
        raise ValueError(f"no 'issued to companies' spreadsheet on {IE_STATS.format(year=now.year)}")
    return rows, {"source": " ".join(sources), "updated": str(now.year)}


FETCHERS = {"uk": lambda http, now: fetch_uk(http), "nl": lambda http, now: fetch_nl(http), "ie": fetch_ie}


def save(folder: Path, country: str, rows: list[Sponsor], meta: dict, now: datetime) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{country}.json"
    data = {**meta, "fetched_at": iso(now), "rows": [[r.name, r.town, r.detail] for r in rows]}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.replace(path)
    return path


def stale(folder: Path, refresh_days: int, now: datetime) -> list[str]:
    """The lists never fetched, or fetched more than refresh_days ago."""
    out = []
    for country in LISTS:
        path = folder / f"{country}.json"
        if not path.exists():
            out.append(country)
            continue
        fetched = parse_datetime(json.loads(path.read_text()).get("fetched_at"))
        if not fetched or now - fetched > timedelta(days=refresh_days):
            out.append(country)
    return out


def update(http, folder: Path, now: datetime, countries: list[str] | None = None) -> tuple[list[str], list[str]]:
    """Download the lists. Returns (lines saying what was saved, errors). A failed list keeps its old file."""
    done, errors = [], []
    for country in countries or list(LISTS):
        try:
            rows, meta = FETCHERS[country](http, now)
            if not rows:
                raise ValueError("the list came back empty")
            save(folder, country, rows, meta, now)
            done.append(f"{country}: {len(rows):,} employers from {LISTS[country]}"
                        + (f" (updated {meta['updated']})" if meta.get("updated") else ""))
        except Exception as exc:  # one list must not stop the others
            from .sources.base import describe_error
            errors.append(f"{country}: {describe_error(exc)}")
    return done, errors
