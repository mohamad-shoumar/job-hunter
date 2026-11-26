"""links.py: the employer's own form behind a board's listing, and closed postings. Requests go to
httpx.MockTransport (no network), by URL."""

import httpx
import pytest

from jobhunter import links
from jobhunter.http import Http
from jobhunter.models import CLOSED
from jobhunter.store import JobStore

from .conftest import NOW, store_job

GREENHOUSE = "https://job-boards.greenhouse.io/acme/jobs/123"


def web(pages: dict):
    """An Http answering each URL (query dropped) from `pages`: an int status, a str redirect target, a
    dict JSON body, ("html", text) or "drop" (a network error); any other URL is a 404. Also the list of URLs asked for."""
    asked = []

    def handler(request):
        url = str(request.url.copy_with(query=None))
        asked.append(str(request.url))
        answer = pages.get(url, 404)
        if answer == "drop":
            raise httpx.ConnectError("refused", request=request)
        if isinstance(answer, int):
            return httpx.Response(answer)
        if isinstance(answer, str):
            return httpx.Response(302, headers={"Location": answer})
        if isinstance(answer, dict):
            return httpx.Response(200, json=answer)
        return httpx.Response(200, text=answer[1])

    return Http(retries=0, transport=httpx.MockTransport(handler)), asked


def row(**values):
    base = {"id": 7, "source": "freehire", "company": "Acme", "title": "Backend Engineer",
            "source_url": "https://freehire.me/jobs/backend-engineer-acme-x1", "application_url": None}
    return {**base, **values}


def test_freehire_apply_redirects_lead_to_the_employer_form_without_tracking():
    http, _ = web({
        links.FREEHIRE_JOB.format(slug="backend-engineer-acme-x1"): {"data": {"closed_at": None}},
        "https://freehire.me/api/v1/go/backend-engineer-acme-x1": "https://grnh.se/abc",
        "https://grnh.se/abc": GREENHOUSE + "?gh_src=abc&utm_source=freehire.me",
        GREENHOUSE: ("html", "<html>apply</html>"),
    })
    link = links.resolve(http, row(), pause=0)
    assert (link.url, link.closed, link.note) == (GREENHOUSE + "?gh_src=abc", None, "")


def test_arbeitnow_apply_link_is_followed_and_its_ref_dropped():
    page = "https://www.arbeitnow.com/jobs/companies/acme/product-engineer-berlin-1"
    ashby = "https://jobs.ashbyhq.com/acme/9a39/application"
    http, _ = web({page + "/apply": ashby + "?ref=arbeitnow.com", ashby: ("html", "form")})
    link = links.resolve(http, row(source="arbeitnow", source_url=page, application_url=page), pause=0)
    assert link.url == ashby


def test_a_last_address_that_refuses_scripts_still_counts():
    """jobgether answers scripts with 403: its address still shows the job is an agency's repost."""
    jobgether = "https://jobgether.com/offer/6b05-software-developer"
    http, _ = web({links.FREEHIRE_JOB.format(slug="backend-engineer-acme-x1"): {"data": {}},
                   "https://freehire.me/api/v1/go/backend-engineer-acme-x1": jobgether, jobgether: 403})
    assert links.resolve(http, row(), pause=0).url == jobgether


def test_a_trail_that_ends_on_the_listing_keeps_the_stored_link():
    http, _ = web({links.FREEHIRE_JOB.format(slug="backend-engineer-acme-x1"): {"data": {}},
                   "https://freehire.me/api/v1/go/backend-engineer-acme-x1": 404})
    assert links.resolve(http, row(), pause=0).url is None


@pytest.mark.parametrize("answer, closed", [
    (("html", '<div class="closed-job closed-job__flavor--closed">No longer accepting applications</div>'),
     "LinkedIn: No longer accepting applications"),
    (404, "LinkedIn: the job page is gone (HTTP 404)"),
    (("html", '<button class="apply-button">Apply</button>'), None),
])
def test_linkedin_says_when_a_posting_is_closed(answer, closed):
    http, _ = web({"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4494496507": answer})
    link = links.resolve(http, row(source="linkedin", application_url="https://www.linkedin.com/jobs/view/4494496507"),
                         pause=0)
    assert (link.url, link.closed) == (None, closed)


def test_freehire_closed_at_is_reported():
    http, _ = web({links.FREEHIRE_JOB.format(slug="backend-engineer-acme-x1"): {"data": {"closed_at": "2026-11-23T10:00:00Z"}},
                   "https://freehire.me/api/v1/go/backend-engineer-acme-x1": GREENHOUSE, GREENHOUSE: ("html", "")})
    assert links.resolve(http, row(), pause=0).closed == "freehire marks it closed (closed_at 2026-11-23)"


def test_a_failing_listing_costs_only_its_own_job():
    http, _ = web({links.FREEHIRE_JOB.format(slug="backend-engineer-acme-x1"): "drop"})
    link = links.resolve(http, row(), pause=0)
    assert link.url is None and link.note.startswith("could not follow the listing: ConnectError")


def test_which_jobs_are_looked_up():
    assert links.wanted(row())  # every freehire job: is it closed?
    assert links.wanted(row(source="arbeitnow", application_url="https://www.arbeitnow.nl/jobs/x"))
    assert not links.wanted(row(source="arbeitnow", application_url=GREENHOUSE))  # resolved already
    assert links.wanted(row(source="serpapi", application_url="https://ae.linkedin.com/jobs/view/ai-engineer-at-gbm-4493619427"))
    assert not links.wanted(row(source="greenhouse", application_url=GREENHOUSE))


def test_save_writes_the_link_and_skips_a_closed_posting_only_when_asked(tmp_path, filters):
    store = JobStore(tmp_path / "jobs.sqlite")
    try:
        first = store_job(store, filters, source_job_id="1", title="Backend Engineer (Python)")
        second = store_job(store, filters, source_job_id="2", company="Other Co", title="Python Developer")
        found = [links.Link(first, url=GREENHOUSE), links.Link(second, closed="LinkedIn: No longer accepting applications")]
        links.save(store, found, NOW)
        assert store.get(first)["application_url"] == GREENHOUSE
        assert store.get(first)["ats_key"] is None or "greenhouse" not in (store.get(first)["ats_key"] or "")
        app = store.conn.execute("SELECT stage FROM applications WHERE job_id = ?", (second,)).fetchone()
        assert app is None or app["stage"] != CLOSED
        links.save(store, found, NOW, skip_closed=True)
        app = store.conn.execute("SELECT stage, closed_reason, skip_reason, skip_note FROM applications WHERE job_id = ?",
                                 (second,)).fetchone()
        assert tuple(app) == (CLOSED, "skipped", "not_open",
                              "Closed: LinkedIn: No longer accepting applications (jobhunter links)")
    finally:
        store.close()


def test_final_url_raises_only_when_the_first_request_fails():
    http, _ = web({"https://a.example/x": "drop"})
    with pytest.raises(httpx.ConnectError):
        http.final_url("https://a.example/x")
    http, _ = web({"https://a.example/x": "https://b.example/y", "https://b.example/y": "drop"})
    assert http.final_url("https://a.example/x") == "https://b.example/y"
