"""The config files you ship in config/ still load. Rule tests use a frozen copy of filters.json
(the `filters` fixture), so this is the one place that reads your real settings."""

import json
from dataclasses import fields

import pytest

from jobhunter.ai_check import AiCheckConfig
from jobhunter.config import Filters, OutreachConfig, Paths, load_json
from jobhunter.fitgrade import FitGradeConfig
from jobhunter.sources import build_sources

from .conftest import ROOT

SHIPPED = Paths(ROOT)


def _settings(path) -> set[str]:
    """The keys that are settings: "_name" keys are notes for you."""
    return {key for key in json.loads(path.read_text()) if not key.startswith("_")}


def test_the_shipped_filters_load():
    filters = Filters.load(SHIPPED.filters_file)
    assert filters.title_include and filters.fit_weights
    # A misspelled key would be ignored without a word, leaving that rule off.
    known = {f.name for f in fields(Filters)} | {"visa_list"}  # visa_list fills Filters.visa
    assert _settings(SHIPPED.filters_file) <= known


# Missing, these loaders quietly use their defaults, and they skip keys they do not know: so the
# file must exist, and every key in it must be a setting (a typo like "enabeld" would be ignored).
@pytest.mark.parametrize("path, config_class", [
    (SHIPPED.outreach_file, OutreachConfig),
    (SHIPPED.ai_check_file, AiCheckConfig),  # also the posting-date lookup's settings (posted_date.build_finder)
    (SHIPPED.fit_grade_file, FitGradeConfig),
], ids=["outreach", "ai_check", "fit_grade"])
def test_the_shipped_settings_load_with_no_unknown_keys(path, config_class):
    assert path.exists()
    assert isinstance(config_class.load(path), config_class)
    assert _settings(path) <= {f.name for f in fields(config_class)}


def test_the_shipped_sources_build():
    sources, notes = build_sources(load_json(SHIPPED.sources_file))
    assert sources
    assert [note for note in notes if "unknown" in note] == []
