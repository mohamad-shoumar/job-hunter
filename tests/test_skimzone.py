"""skimzone.py: where a CV shows the posting's must-haves, in the posting's own words."""

from jobhunter import skimzone

CV = """// TAILORED by jobhunter for Acme
# Jane Doe
title: Backend Engineer
email: jane@example.com

## Summary
Builds things in **Go** at night.

## Professional Experience

### Acme, Dubai | 2025 - Present
Software Engineer
- Built an event-driven **Node.js** gateway.
- Cut costs by **80%** with AWS Lambda.
// - Wrote Rust tooling.
- Ran the C# migration.
- Managed PostgreSQL backups.

### Beta, Beirut | 2023 - 2025
Full Stack Engineer
- Built React dashboards.

## Skills
Languages: Python, SQL, TypeScript, JavaScript, Java
Tools: Docker, AWS (Lambda, SQS), Git, Datadog, Kubernetes
"""


def test_the_top_part_is_the_headline_four_skills_a_row_and_the_newest_roles_first_three_bullets():
    top = skimzone.top_part(CV)
    assert "Backend Engineer" in top and "AWS (Lambda, SQS)" in top and "Datadog" in top
    assert "Java" not in top.replace("JavaScript", "")  # the 5th item of its row
    assert "Kubernetes" not in top
    assert "C# migration" in top  # the hidden Rust line doesn't take a place
    assert "PostgreSQL" not in top and "React" not in top
    assert "Go" not in top  # the Summary is not in it


def test_terms_match_whole_and_in_any_case_where_word_boundaries_would_fail():
    assert skimzone.has("c#", "Ran the C# migration")
    assert skimzone.has("Node.js", "an event-driven Node.js gateway")
    assert not skimzone.has("Java", "TypeScript, JavaScript")
    assert skimzone.has("AWS Lambda", "with AWS Lambda.")
    assert skimzone.has("80%", "by **80%** with")  # bold is stripped first
    assert not skimzone.has("", "anything")


def test_a_score_says_top_part_on_the_cv_or_missing_and_hidden_lines_never_count():
    must = skimzone.terms("Python; PostgreSQL; Rust; python; ; Kubernetes")
    assert must == ["Python", "PostgreSQL", "Rust", "Kubernetes"]
    sc = skimzone.score(must, CV)
    assert sc.top == ["Python"]
    assert sc.on_cv == ["Python", "PostgreSQL", "Kubernetes"]
    assert sc.missing == ["Rust"]
