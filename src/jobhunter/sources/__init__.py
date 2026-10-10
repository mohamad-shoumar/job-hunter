"""Source registry: config/sources.json section name -> adapter.

To add a source: write a module with a Source subclass and a
from_config(section) function, then add it to BUILDERS.
"""

from __future__ import annotations

from . import (
    ashby,
    bamboohr,
    custom_page,
    getro,
    greenhouse,
    hackernews,
    himalayas,
    lever,
    nodesk,
    pinpoint,
    remoteok,
    remotive,
    serpapi,
    smartrecruiters,
    teamtailor,
    weworkremotely,
)
from .base import Source, SourceResult

BUILDERS = {
    "greenhouse_boards": greenhouse.from_config,
    "lever_boards": lever.from_config,
    "ashby_boards": ashby.from_config,
    "custom_pages": custom_page.from_config,
    "serpapi": serpapi.from_config,
    "remote_api": remotive.from_config,
    "himalayas": himalayas.from_config,
    "remoteok": remoteok.from_config,
    "weworkremotely": weworkremotely.from_config,
    "hackernews": hackernews.from_config,
    "nodesk": nodesk.from_config,
    "getro": getro.from_config,
    "teamtailor_boards": teamtailor.from_config,
    "bamboohr_boards": bamboohr.from_config,
    "smartrecruiters_boards": smartrecruiters.from_config,
    "pinpoint_boards": pinpoint.from_config,
}

# Sections that configure something other than one source (boards.py reads "watch_boards").
SETTINGS = {"watch_boards"}

# Checked 2026-09-25. Listed here so a config section for them is explained
# instead of silently ignored.
NOT_IMPLEMENTED = {
    "hiringcafe": "hiring.cafe answers automated requests with HTTP 403 (Cloudflare) and has no public API",
    "remote100k": "no API or feed, HTML pages only; its listings are mostly US/EU-restricted ATS jobs",
    "linkedin": "blocks automated access and forbids scraping; use the serpapi (Google Jobs) source instead",
    "wellfound": "bot protection on every page, no public API",
    "workatastartup": "requires a logged-in account (HTTP 406 without one)",
}


def build_sources(config: dict) -> tuple[list[Source], list[str]]:
    """Enabled adapters, plus notes about config sections that were not used."""
    sources: list[Source] = []
    notes: list[str] = []
    for key, section in config.items():
        if key.startswith("_") or key in SETTINGS:
            continue
        if key in BUILDERS:
            source = BUILDERS[key](section)
            if source is not None:
                sources.append(source)
        elif key in NOT_IMPLEMENTED:
            if not isinstance(section, dict) or section.get("enabled", True):
                notes.append(f"{key}: not implemented ({NOT_IMPLEMENTED[key]})")
        else:
            notes.append(f"{key}: unknown config section, ignored")
    return sources, notes


__all__ = ["BUILDERS", "NOT_IMPLEMENTED", "Source", "SourceResult", "build_sources"]
