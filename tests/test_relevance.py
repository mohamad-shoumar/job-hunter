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
        # Missed before 2026-10-19: postings open to Lebanon that died on the title.
        "AI Harness Engineer (100% Remote, Worldwide)",
        "AI-Native Engineers & Operators",
        "AI Experience Engineer (Conversational AI)",
        "Cloud Platform Engineer",
        "Senior Web Engineer",
        "Low-code / No-code Automation Developer",
        "Microservices Engineer",
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
        # The AI-role rule comes after the exclusions, and needs a role noun.
        ("AI Sales Engineer, (EMEA)", "title_excluded"),
        ("AI Security Engineer", "title_excluded"),
        ("Backend Engineering Specialist - AI Trainer", "title_excluded"),
        ("AI Growth Ops", "title_not_target"),
        ("Machine Learning Engineer", "title_not_target"),
        ("Technical Lead", "title_not_target"),
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


def test_years_reason_quotes_the_posting(filters):
    job = enrich(make_job(description="We ship fast. 7+ years building production backend systems. Remote."))
    assessment, _ = assess_relevance(job, filters)
    assert assessment.reasons == ['Asks for 7+ years of experience: "7+ years building production backend systems."']


def test_fit_score_counts_profile_skills(filters):
    _, score = assess_relevance(enrich(make_job()), filters)
    assert score >= 3 + 3 + 2 + 2  # python, fastapi, postgresql, aws


# AI and forward-deployed roles only at junior level (the user's call 2026-10-20).
@pytest.mark.parametrize(
    "title, description, reason",
    [
        ("Senior AI Engineer", "Python.", '"ai engineer" roles are junior-only, and the title says "senior"'),
        ("Sr. Forward Deployed Engineer", "Python.",
         '"forward deployed" roles are junior-only, and the title says "senior"'),
        ("Lead AI Deployment Engineer", "Python.", '"ai deployment engineer" roles are junior-only, and the title says "lead"'),
        ("AI Automation Engineer", "3+ years building automation workflows. Python.",
         '"ai automation" roles are junior-only, and it asks for 3+ years: "3+ years building automation workflows."'),
        ("Forward Deployed Engineer", "You bring 5+ years of engineering experience.",
         '"forward deployed" roles are junior-only, and it asks for 5+ years: '
         '"You bring 5+ years of engineering experience."'),
    ],
)
def test_ai_and_forward_deployed_roles_are_junior_only(title, description, reason, filters):
    assessment, _ = assess_relevance(enrich(make_job(title=title, description=description)), filters)
    assert (assessment.verdict, assessment.code, assessment.reasons) == (IRRELEVANT, "junior_only", [reason])


@pytest.mark.parametrize(
    "title, description",
    [
        ("AI Engineer", "2+ years of software engineering. Python."),
        ("Forward Deployed Engineer", "Python and customers."),  # no years stated: kept
        # The other target roles keep the usual rules.
        ("Senior Backend Engineer", "3+ years of Python."),
        ("Solutions Engineer", "4+ years of Python."),
        ("Senior Python / AI Backend Engineer", "Python."),
    ],
)
def test_junior_only_leaves_the_rest(title, description, filters):
    assessment, _ = assess_relevance(enrich(make_job(title=title, description=description)), filters)
    assert assessment.verdict != IRRELEVANT
