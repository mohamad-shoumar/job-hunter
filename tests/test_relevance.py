import pytest

from jobhunter.extract import enrich
from jobhunter.models import IRRELEVANT, MATCH, MAYBE
from jobhunter.relevance import assess_relevance

from .conftest import make_job


@pytest.mark.parametrize(
    "title",
    [
        "Senior Backend Engineer (Python)",
        "Back-End Developer",
        "Software Engineer II",
        "Applied AI Engineer",
        "Forward Deployed Engineer",
        "Full-Stack Engineer",
        "Fullstack SWE",
        "Python Developer",
        "Frontend / Backend Engineer",
        "Backend & Frontend Engineer",
        "Algorithmic Trading Engineer",
        "AI agent engineer",
        "Senior Full-Stack Developer - Marketplace Web & Mobile Platform",
    ],
)
def test_target_titles_pass(title, filters):
    assert assess_relevance(enrich(make_job(title=title)), filters)[0].verdict != IRRELEVANT


@pytest.mark.parametrize(
    "title, code",
    [
        ("Senior Software Engineer, Frontend", "title_excluded"),
        ("Staff Backend Engineer", "title_excluded"),
        ("Engineering Manager, Backend", "title_excluded"),
        ("iOS and Android Engineer", "title_excluded"),
        ("QA Automation Engineer", "title_excluded"),
        ("Backend Engineer (Java)", "other_stack"),
        ("Senior Go Engineer", "other_stack"),
        # a split must not escape seniority or stack exclusions
        ("Head of Applied AI & Trading Systems (Iron Man Track)", "title_excluded"),
        ("Software Engineer (m/f/d) – Go / Cloud-Native IMS", "other_stack"),
        ("Account Executive", "title_not_target"),
        ("Data Analyst", "title_not_target"),
    ],
)
def test_other_titles_are_rejected(title, code, filters):
    assessment, _ = assess_relevance(enrich(make_job(title=title)), filters)
    assert (assessment.verdict, assessment.code) == (IRRELEVANT, code)


def test_other_language_is_fine_when_python_is_also_in_the_title(filters):
    assert assess_relevance(enrich(make_job(title="Backend Engineer (Python / Go)")), filters)[0].verdict == MATCH


def test_python_decides_match_vs_maybe(filters):
    python = enrich(make_job(title="Backend Engineer", description="Python and FastAPI."))
    other = enrich(make_job(title="Backend Engineer", description="TypeScript and Postgres."))
    assert assess_relevance(python, filters)[0].verdict == MATCH
    assert assess_relevance(other, filters)[0].verdict == MAYBE


def test_years_of_experience(filters):
    too_many = enrich(make_job(description="You have 8+ years of backend experience with Python."))
    stretch = enrich(make_job(description="You have 5+ years of professional software experience."))
    assert assess_relevance(too_many, filters)[0].code == "too_senior"
    assessment, _ = assess_relevance(stretch, filters)
    assert assessment.verdict == MATCH and any("stretch" in r for r in assessment.reasons)


def test_fit_score_counts_profile_skills(filters):
    _, score = assess_relevance(enrich(make_job()), filters)
    assert score >= 3 + 3 + 2 + 2  # python, fastapi, postgresql, aws
