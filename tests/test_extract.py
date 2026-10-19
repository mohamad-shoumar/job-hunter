from datetime import datetime, timezone

import pytest

from jobhunter.extract import (
    extract_eor_mentions,
    extract_required_yoe,
    extract_salary,
    extract_skills,
    find_required_yoe,
    normalize_employment_type,
)
from jobhunter.text import fix_mojibake, html_to_text, normalize_words, parse_datetime


@pytest.mark.parametrize(
    "text, years",
    [
        ("5+ years of professional software engineering experience", 5),
        ("3-5 years experience with Python", 3),
        ("At least 4 years of experience building APIs.\n2+ years of AWS experience", 4),
        ("Nice to have: 8+ years of experience with Kafka", None),
        ("our 15 years of experience serving clients", None),
        ("Competitive salary", None),
        # Real postings the rules once missed (Enveritas #869, Splitero #912).
        ("- A minimum of seven years of full-time professional experience as a backend software engineer.", 7),
        ("- 6+ years in software engineering with at least 2 years of focused experience building production AI", 6),
        ("Seven (7) years of experience with Python", 7),
        ("Someone years ahead", None),
        # A company boast at the start of a sentence (#836).
        ("We build media tools. With more than 10 years of experience in this field and 40 employees", None),
        ("Candidates with more than 5 years of experience in Python", 5),
        # Real postings without "experience" next to the count (2026-10-19).
        ("5+ years building production backend systems in Python, with real async I/O", 5),
        ("Senior experience (typically 8+ years) building and operating backend systems", 8),
        ("Strong Python coding skills - 7+ years.", 7),
        ("· Proficiency (5+ yrs) in Python (especially pipelines) or Typescript (large codebases a plus.", 5),
        ("Base JD: Experience • Minimum 5 years of development and design experience in Python", 5),
        ("Proven track record of 4-7 years in back-end API development using Python.", 4),
        ("Experience level: 2–5 years", 2),
        ("- Experience working with Python on web frameworks (minimum of 2 years).", 2),
        ("3-8+ years in a customer-facing technical role", 3),
        ("- 5+ years shipping production software, 2+ building with LLMs in production", 5),
        # One long line: a "nice to have" in another sentence does not hide the requirement.
        ("Kafka is a plus. Requirements: 4+ years of hands-on full-stack engineering experience", 4),
        ("5+ years of work experience in Python and JavaScript, ideally in fast-paced startups", 5),
        ("2+ years of Rust experience preferred", None),
        ("Bonus points if you have 7+ years in fintech", None),
        # Asides, benefits and company history.
        ("- 3+ years of experience (5+ years for seniors) building backend services.", 3),
        ("Strong experience (7+ years) building full stack web applications", 7),
        ("A staffing firm servicing clients in America for the past 12+ years.", None),
        ("Paid sabbatical after 5+ years with us.", None),
        ("We're a small senior team: the team skews toward 7+ years.", None),
        ("Founded 10+ years ago in Berlin.", None),
        ("A team with 30+ years combined experience", None),
        ("0–4 years of experience (recent grads welcome)", None),
    ],
)
def test_required_yoe(text, years):
    assert extract_required_yoe(text) == years


def test_required_yoe_quotes_its_sentence():
    years, quote = find_required_yoe("Great team. 5+ years building production backend systems. Python a plus.")
    assert years == 5
    assert quote == "5+ years building production backend systems."


@pytest.mark.parametrize(
    "text, low, high, currency, period",
    [
        ("The US base salary range is $95.4K–$190K annually.", 95400, 190000, "USD", "year"),
        ("€75k–110k", 75000, 110000, "EUR", "year"),
        ("$150 - 210K USD", 150000, 210000, "USD", "year"),
        ("USD 100,000 - 130,000 per year", 100000, 130000, "USD", "year"),
        ("$40 - $60 per hour", 40, 60, "USD", "hour"),
    ],
)
def test_salary(text, low, high, currency, period):
    found = extract_salary(text)
    assert (found["salary_min"], found["salary_max"], found["salary_currency"], found["salary_period"]) == (
        low, high, currency, period,
    )


def test_salary_ignores_ambiguous_small_ranges():
    assert extract_salary("raised $5 - 10 in seed funding") is None


def test_salary_raw_keeps_the_whole_phrase():
    assert extract_salary("$95.4K–$190K annually")["salary_raw"] == "$95.4K–$190K annually"


def test_skills():
    assert extract_skills("Python, FastAPI, Postgres, AWS, JavaScript") == [
        "python", "fastapi", "postgresql", "aws", "javascript",
    ]
    assert "java" not in extract_skills("JavaScript only")


def test_eor_mentions():
    assert extract_eor_mentions("We hire through Deel as our employer of record (EOR).") == [
        "deel", "employer of record", "eor",
    ]
    assert extract_eor_mentions("a force multiplier for the team") == []


def test_employment_type():
    assert normalize_employment_type("Full-time (remote)") == "full_time"
    assert normalize_employment_type("FullTime") == "full_time"
    assert normalize_employment_type("freelance") == "contract"
    assert normalize_employment_type("Intern") == "internship"


def test_html_to_text_keeps_structure():
    text = html_to_text("<p>Hello&nbsp;world</p><ul><li>One</li><li>Two</li></ul><script>x()</script>")
    assert text == "Hello world\n\n- One\n\n- Two"


def test_normalize_words():
    assert normalize_words("Sr. Back-End Dev (Node.js)") == "senior backend developer nodejs"
    assert normalize_words("Full Stack Engineers") == "fullstack engineer"


def test_parse_datetime_formats():
    utc = timezone.utc
    assert parse_datetime(1790320924) == datetime(2026, 9, 25, 7, 22, 4, tzinfo=utc)
    assert parse_datetime(1605753685375) == datetime(2020, 11, 19, 2, 41, 25, tzinfo=utc)
    assert parse_datetime("2026-07-24T09:08:01.643+00:00") == datetime(2026, 7, 24, 9, 8, 1, tzinfo=utc)
    assert parse_datetime("Thu, 17 Sep 2026 10:51:23 +0000") == datetime(2026, 9, 17, 10, 51, 23, tzinfo=utc)
    assert parse_datetime("2026-09-21T12:55:11") == datetime(2026, 9, 21, 12, 55, 11, tzinfo=utc)
    assert parse_datetime("not a date") is None


def test_fix_mojibake():
    assert fix_mojibake("MecÃ¡nico") == "Mecánico"
    assert fix_mojibake("Mecánico") == "Mecánico"
    assert fix_mojibake(None) == ""
