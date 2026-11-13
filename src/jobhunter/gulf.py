"""Gulf countries you would work for from Lebanon, but would not move to (Kuwait and Bahrain).

The relocation countries (relocation.py) are the ones you would move to, so an on-site job
there is fine. These are the opposite: you want the companies, not the move (your call
2026-11-13). So only a **remote** job counts, and nothing here ever shortlists on its own:

  remote, location says Kuwait or Bahrain   `unclear`, quoting the location, so the daily AI
                                            check asks whether they can hire someone living in
                                            Lebanon and rejects it with a quote if they cannot
  on-site or hybrid there                   rejected like anywhere else (not_remote)
  the posting wants someone already there   rejected (local_only), quoting the sentence

"Only" means the location names no other place: "Remote - Kuwait" counts, "Remote - Kuwait
or India" does not (the leftover text is classified again, and a place found there rejects
the job as before).

The places are the "gulf_remote" section of config/filters.json; the "already in the country"
phrases are the relocation section's `local_only`, shared so the list is written once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .geo import RESTRICTED, classify_place
from .text import normalize_words


@dataclass
class GulfRemote:
    places: list[str] = field(default_factory=list)  # normalized words: "kuwait", "manama"
    countries: str = ""  # for reason lines: "Kuwait or Bahrain"
    local_only: re.Pattern | None = None

    @classmethod
    def from_dict(cls, data: dict | None, local_only: re.Pattern | None = None) -> GulfRemote | None:
        if not data or not data.get("places"):
            return None
        places = [w for w in (normalize_words(p) for p in data["places"]) if w]
        return cls(places=sorted(set(places), key=len, reverse=True),
                   countries=data.get("countries", ""), local_only=local_only)

    def names_place(self, text: str) -> bool:
        words = f" {normalize_words(text)} "
        return any(f" {p} " in words for p in self.places)

    def _without_places(self, text: str) -> str:
        """The location text with the Kuwait/Bahrain words taken out, so what is left can be judged."""
        words = f" {normalize_words(text)} "
        for place in self.places:  # longest first, so "kuwait city" goes before "kuwait"
            words = words.replace(f" {place} ", "  ")
        return words.strip()

    def only_place(self, texts: list[str]) -> str | None:
        """The first text naming one of these countries, when no text names anywhere else."""
        found = None
        for text in texts:
            if classify_place(self._without_places(text)).kind == RESTRICTED:
                return None
            if found is None and self.names_place(text):
                found = text
        return found
