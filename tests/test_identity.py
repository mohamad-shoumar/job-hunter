import pytest

from jobhunter.identity import ats_key_from_url, canonical_url, company_key, find_ats_url, fingerprint


@pytest.mark.parametrize(
    "url, key",
    [
        ("https://job-boards.greenhouse.io/gitlab/jobs/8556658002", "greenhouse:8556658002"),
        ("https://boards.greenhouse.io/gitlab/jobs/8556658002?gh_src=abc", "greenhouse:8556658002"),
        ("https://boards.greenhouse.io/embed/job_app?for=gitlab&token=8556658002", "greenhouse:8556658002"),
        ("https://about.gitlab.com/jobs/apply/?gh_jid=8556658002", "greenhouse:8556658002"),
        ("https://jobs.lever.co/metabase/5eca795c-48dd-496a-be23-2181068a5450/apply", "lever:5eca795c-48dd-496a-be23-2181068a5450"),
        ("https://jobs.ashbyhq.com/percona/99ee2a07-7925-4b8e-9b3c-fb5e43cacc50", "ashby:99ee2a07-7925-4b8e-9b3c-fb5e43cacc50"),
        ("https://apply.workable.com/modash/j/C1507B65C3", "workable:c1507b65c3"),
        ("https://remotive.com/remote-jobs/software-dev/backend-123", None),
        (None, None),
    ],
)
def test_ats_key(url, key):
    assert ats_key_from_url(url) == key


def test_find_ats_url_in_html():
    html = '<p>Apply <a href="https://jobs.lever.co/acme/5eca795c-48dd-496a-be23-2181068a5450">here</a></p>'
    assert find_ats_url(html) == "https://jobs.lever.co/acme/5eca795c-48dd-496a-be23-2181068a5450"
    assert find_ats_url("<a href='https://acme.com/careers'>x</a>") is None


def test_company_key_ignores_legal_suffixes_and_domains():
    assert company_key("GitLab Inc.") == company_key("Gitlab") == "gitlab"
    assert company_key("Circle.so") == "circle"
    assert company_key("Acme (YC S21)") == "acme"


def test_fingerprint_ignores_formatting_and_remote_noise():
    a = fingerprint("GitLab Inc.", "Sr. Back-End Engineer (Remote)")
    b = fingerprint("GitLab", "Senior Backend Engineer")
    assert a == b
    assert fingerprint("Acme", "Backend Engineer (m/f/d)") == fingerprint("Acme", "Backend Engineer")


def test_canonical_url_drops_tracking():
    assert canonical_url("HTTP://Jobs.Example.com/a/b/?utm_source=x&id=3#top") == "https://jobs.example.com/a/b?id=3"
