"""Reading the profile: its sections, tags and notes, and the facts load_profile gives the email and the fit grade."""

from jobhunter.profile import load_profile, sections, skills_in, split_tags, strip_notes, years_in

from .conftest import FIXTURES

PROFILE_FILE = FIXTURES / "profile" / "master_profile.md"


def test_profile_facts_leave_out_contact_details_and_salary():
    profile = load_profile(PROFILE_FILE)
    text = profile.facts_text
    assert "800+ concurrent Python jobs" in text and "team of 5 engineers" in text
    assert "7788" not in text and "4200" not in text and "me@example.com" not in text and "TODO" not in text
    assert "Confirmed by me" not in text and "[core]" not in text  # notes and tags never reach a model
    assert profile.years == 3.3
    assert profile.linkedin == "linkedin.com/in/example" and "kafka" not in profile.skills


def test_sections_are_read_by_title():
    text = "# Master profile\nintro\n## Basics\n- Name: X\n## Experience \n### Role\n- [core] Built it\n"
    assert sections(text) == {"Basics": "- Name: X\n", "Experience": "### Role\n- [core] Built it\n"}


def test_tags_and_notes_come_off_a_bullet():
    assert split_tags("[fullstack, lead] Built the chart") == (frozenset({"fullstack", "lead"}), "Built the chart")
    assert split_tags("Built the chart") == (frozenset({"core"}), "Built the chart")
    assert strip_notes("Built the API. (Confirmed by me 2026-09-30: my commits.)") == "Built the API."


def test_skills_and_years_are_what_the_facts_state():
    assert skills_in("Built distributed/backend systems in Python") >= {"python", "distributed systems"}
    assert years_in("About 3.3 years of software engineering") == 3.3
    assert years_in("Three years of software engineering") is None
