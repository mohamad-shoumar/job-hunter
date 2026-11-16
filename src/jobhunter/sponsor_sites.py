"""Visa-sponsorship job sites as visa evidence (the user's call, 2026-11-16).

The Stack and JobDelulu list only employers they found sponsoring visas: they
check it themselves, and a company's own posting often says nothing about
visas. So a role they list counts as evidence, like a government register
(visa.py, code `sponsor_site`):

  The Stack   per role: the daily board discovery (discovery.py) saves every
              listing it reads, and a stored job counts when its company and
              title match one, in the same country. The Stack marks every job
              "visa: yes", so a company it lists for other roles proves nothing
              about this one.
  JobDelulu   per company: its terms forbid automated use, so the user exports
              the employers by hand (`jobhunter sponsors --import-sites FILE
              --site JobDelulu`, a CSV of Company,Country).

Kept in data/sponsors/sites.json (git-ignored, like the registers). Only a job
the rules would otherwise reject `no_visa_evidence` is helped: a refusal, a
language, the age or the title still reject it. A remote role for people living
there is not: such roles rarely come with a visa, as with the registers.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .identity import company_key, title_key

FILE = "sites.json"


@dataclass
class SiteEntry:
    site: str  # "The Stack", "JobDelulu"
    company: str
    country: str  # a visa-list code: "de", "uk"
    title: str = ""  # "" = the whole company
    url: str = ""
    seen: str = ""  # the day it was last listed, YYYY-MM-DD

    def quote(self) -> str:
        if self.title:
            return f'{self.site}, a visa-sponsorship job site, lists "{self.title}" at {self.company} (seen {self.seen})'
        return f"{self.company} is on {self.site}'s list of visa-sponsoring employers (imported {self.seen})"


@dataclass
class SponsorSites:
    path: Path | None = None
    entries: list[SiteEntry] = field(default_factory=list)
    _index: dict[tuple[str, str], list[SiteEntry]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._index = {}
        for entry in self.entries:
            self._index.setdefault((company_key(entry.company), entry.country), []).append(entry)

    @classmethod
    def load(cls, folder: Path) -> SponsorSites:
        path = Path(folder) / FILE
        rows = json.loads(path.read_text()).get("entries", []) if path.exists() else []
        return cls(path, [SiteEntry(**row) for row in rows])

    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"entries": [asdict(e) for e in self.entries]}, indent=1) + "\n")

    def add(self, entry: SiteEntry) -> bool:
        """Add or refresh one entry; True when it is new."""
        key = (company_key(entry.company), entry.country)
        for old in self._index.get(key, []):
            if old.site == entry.site and title_key(old.title) == title_key(entry.title):
                old.seen, old.url = entry.seen or old.seen, entry.url or old.url
                return False
        self.entries.append(entry)
        self._index.setdefault(key, []).append(entry)
        return True

    def find(self, company: str, title: str, country: str) -> SiteEntry | None:
        """A listing of this role, else of the whole company, in this country."""
        found = self._index.get((company_key(company or ""), country), [])
        wanted = title_key(title or "")
        return (next((e for e in found if e.title and title_key(e.title) == wanted), None)
                or next((e for e in found if not e.title), None))


def import_csv(sites: SponsorSites, path: Path, site: str, codes: dict[str, str], now: datetime) -> tuple[int, list[str]]:
    """A Company,Country CSV ("Germany / United Kingdom" names several). `codes`: country name -> code.

    Returns how many entries are new and the country names it could not place (not on the visa list).
    """
    added, unknown = 0, []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            company = (row.get("Company") or "").strip()
            for name in (row.get("Country") or "").split("/"):
                code = codes.get(name.strip().lower())
                if not code:
                    unknown.append(name.strip())
                elif company:
                    added += sites.add(SiteEntry(site, company, code, seen=now.date().isoformat()))
    return added, sorted(set(unknown))
