"""The web app through FastAPI's TestClient, on a temp project folder, with fake outside services."""

import re
import shutil

import pytest
from fastapi.testclient import TestClient

from jobhunter import tracking
from jobhunter.config import OutreachConfig, Paths
from jobhunter.contacts import ContactFinder, save_contact
from jobhunter.hunter import HunterError
from jobhunter.mailer import MailAccount
from jobhunter.store import JobStore
from jobhunter.web.app import Services, create_app

from .conftest import FIXTURES, NOW, ROOT, store_job
from .test_mailer import FakeSender

TOKEN = "test-token"
AUTH = {"X-JH-Token": TOKEN}


class FakeServices(Services):
    def __init__(self, config):
        super().__init__(config)
        self.sender_ = FakeSender()

    def finder(self):
        return None, "no keys in tests"

    def writer(self):
        return None, "no keys in tests"

    def account(self):
        return MailAccount("me@gmail.com", "pw")

    def sender(self, account):
        return self.sender_


@pytest.fixture
def home(tmp_path, filters):
    # The shipped config/ on purpose: the app needs a whole project folder (outreach, sources, cover guidelines).
    shutil.copytree(ROOT / "config", tmp_path / "config")
    shutil.copytree(FIXTURES / "profile", tmp_path / "profile")
    store = JobStore(tmp_path / "data" / "jobs.sqlite")
    store_job(store, filters, company="Acme", description="We build APIs with Python. https://acme.io")
    store_job(store, filters, source_job_id="2", company="Talentuch", title="Python Developer")
    store.commit()
    store.close()
    return tmp_path


@pytest.fixture
def client(home):
    paths = Paths(home)
    services = FakeServices(OutreachConfig.load(paths.outreach_file))
    app = create_app(paths, TOKEN, allowed_hosts=["testserver"], services=services, now=lambda: NOW)
    test_client = TestClient(app)
    test_client.services = services
    return test_client


def test_the_page_carries_the_token(client):
    page = client.get("/")
    assert page.status_code == 200 and TOKEN in page.text and "no-store" in page.headers["cache-control"]
    # After an update the browser must load the new code, not a copy it kept.
    assert re.search(r'src="/static/app\.js\?v=\d+"', page.text) and re.search(r'href="/static/style\.css\?v=\d+"', page.text)
    assert client.get(re.search(r'src="(/static/app\.js\?v=\d+)"', page.text).group(1)).status_code == 200


def test_changes_need_the_token_json_and_the_right_host(client):
    assert client.post("/api/jobs/1/stage", json={"stage": "saved"}).status_code == 403
    assert client.post("/api/jobs/1/stage", json={"stage": "saved"}, headers={"X-JH-Token": "nope"}).status_code == 403
    assert client.post("/api/jobs/1/stage", content="stage=saved", headers={
        **AUTH, "Content-Type": "application/x-www-form-urlencoded"}).status_code == 415
    assert client.post("/api/jobs/1/stage", json={"stage": "saved"}, headers={
        **AUTH, "Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/jobs", headers={"Host": "evil.example"}).status_code == 403


def test_list_and_detail(client):
    jobs = client.get("/api/jobs?view=shortlisted").json()["jobs"]
    assert {j["company"]: j["job_board"] for j in jobs} == {"Acme": False, "Talentuch": True}
    detail = client.get("/api/jobs/1").json()
    assert detail["company"]["suggested_domain"] == "acme.io"
    assert detail["company"]["why"].startswith("Size unknown") and detail["application"] is None


def test_applied_jobs_say_when_you_reached_out(client):
    client.patch("/api/jobs/1/application", json={"applied": True}, headers=AUTH)
    client.post("/api/jobs/2/stage", json={"stage": "saved"}, headers=AUTH)
    jobs = {j["id"]: j for j in client.get("/api/jobs?view=tracked").json()["jobs"]}
    assert jobs[1]["stage"] == "reached_out" and "to_email" not in jobs[1]
    assert jobs[1]["reached_out_at"] == jobs[1]["applied_at"]
    assert jobs[2]["reached_out_at"] is None


def test_track_contact_draft_send(client):
    r = client.post("/api/jobs/1/stage", json={"stage": "saved"}, headers=AUTH)
    assert r.json()["application"]["stage"] == "saved"
    r = client.put("/api/jobs/1/contact", json={"full_name": "Ana Ruiz", "email": "ana@acme.io", "position": "CEO"},
                   headers=AUTH)
    assert r.json()["contact"]["email_status"] == "manual"
    r = client.patch("/api/jobs/1/application", json={
        "subject": "Python backend role", "body": "Hi Ana,\n\nI saw you're hiring. I built RESTful APIs in Python.",
        "draft_version": 0, "notes": "Found via HN"}, headers=AUTH)
    app = r.json()["application"]
    assert app["draft_edited"] == 1 and app["notes"] == "Found via HN"
    assert r.json()["outgoing"]["to"] == "ana@acme.io"
    stale = client.post("/api/jobs/1/send", json={"draft_version": 0, "seq": 0}, headers=AUTH)
    assert stale.status_code == 409 and "draft changed" in stale.json()["error"]
    sent = client.post("/api/jobs/1/send", json={"draft_version": app["draft_version"], "seq": 0}, headers=AUTH)
    assert sent.status_code == 200 and sent.json()["application"]["stage"] == "reached_out"
    assert client.services.sender_.sent[0]["To"] == "ana@acme.io"
    again = client.post("/api/jobs/1/send", json={"draft_version": app["draft_version"], "seq": 0}, headers=AUTH)
    assert again.status_code == 409 and len(client.services.sender_.sent) == 1


def test_status_codes_say_what_went_wrong(client):
    missing = client.get("/api/jobs/99")
    assert missing.status_code == 404 and missing.json() == {"error": "no job #99"}
    assert client.post("/api/jobs/99/stage", json={"stage": "saved"}, headers=AUTH).status_code == 404
    client.put("/api/jobs/1/contact", json={"full_name": "Ana Ruiz", "email": "ana@acme.io"}, headers=AUTH)
    edit = {"subject": "Python backend role", "body": "Hi Ana,\n\nI built RESTful APIs in Python.", "draft_version": 0}
    assert client.patch("/api/jobs/1/application", json=edit, headers=AUTH).status_code == 200
    stale = client.patch("/api/jobs/1/application", json=edit, headers=AUTH)  # the page still shows version 0
    assert stale.status_code == 409 and "Reload" in stale.json()["error"]
    version = client.get("/api/jobs/1").json()["application"]["draft_version"]
    assert client.post("/api/jobs/1/send", json={"draft_version": version, "seq": 0}, headers=AUTH).status_code == 200

    def gmail_down(account):
        raise RuntimeError("Gmail refused the IMAP login")

    client.services.inbox = gmail_down
    down = client.post("/api/inbox/check", json={}, headers=AUTH)
    assert down.status_code == 502 and down.json()["error"].startswith("Checking Gmail failed: RuntimeError")

    class HunterDown:
        def email_verifier(self, email):
            raise HunterError(429, "too_many_requests", "slow down")

    client.services.finder = lambda: (ContactFinder(client.services.config, HunterDown()), None)
    contact_id = client.get("/api/jobs/1").json()["contact"]["id"]
    down = client.post(f"/api/contacts/{contact_id}/verify", json={}, headers=AUTH)
    assert down.status_code == 502 and down.json() == {"error": "Hunter 429 too_many_requests: slow down"}
    assert client.post("/api/contacts/99/verify", json={}, headers=AUTH).status_code == 404


def test_a_bad_value_is_a_400_that_names_the_field(client):
    def error(method, path, **kwargs):
        r = client.request(method, path, headers={**AUTH, **kwargs.pop("headers", {})}, **kwargs)
        assert r.status_code == 400, r.text
        return r.json()["error"]

    assert error("PATCH", "/api/jobs/1/application", json={"contact_id": "abc"}).startswith(
        "contact_id: Input should be a valid integer")
    assert error("POST", "/api/jobs/1/send", json={"draft_version": 0, "seq": "next"}).startswith("seq: ")
    assert error("POST", "/api/jobs/1/send", json={"confirm": "guessed"}).startswith("confirm: ")
    assert error("POST", "/api/jobs/1/stage", json={}) == "stage: Field required"
    assert error("POST", "/api/jobs/1/stage", json=["saved"]).startswith("body: ")
    assert error("PUT", "/api/jobs/1/cv-text", json={"text": None}).startswith("text: ")
    assert error("POST", "/api/jobs/1/stage", content="{stage", headers={"Content-Type": "application/json"}) == \
        "The request body is not valid JSON"
    assert error("PATCH", "/api/jobs/1/application", json={"applied": True, "applied_at": "soon"}) == \
        "applied_at: not a date: soon"
    assert client.get("/api/jobs?days=week").json()["error"].startswith("days: ")
    assert client.get("/api/jobs/one").status_code == 400
    # Keys a route does not use are ignored, as before.
    assert client.post("/api/jobs/1/stage", json={"stage": "saved", "from": "board"}, headers=AUTH).status_code == 200


def test_editing_the_application_changes_only_the_keys_sent(client):
    def patch(**body):
        return client.patch("/api/jobs/1/application", json=body, headers=AUTH).json()["application"]

    applied = "2026-09-20T10:00:00+00:00"
    patch(applied=True, applied_at="2026-09-20T10:00:00Z")
    patch(subject="Python role", body="Hi,\n\nI build APIs.")
    app = patch(notes="Referred by Sam")
    assert (app["applied_at"], app["subject"], app["notes"]) == (applied, "Python role", "Referred by Sam")
    app = patch(subject="Backend role")
    assert (app["subject"], app["body"], app["applied_at"]) == ("Backend role", "Hi,\n\nI build APIs.", applied)
    assert patch(applied=False)["applied_at"] is None


def test_manual_contact_must_be_an_email(client):
    r = client.put("/api/jobs/1/contact", json={"full_name": "Ana", "email": "not-an-email"}, headers=AUTH)
    assert r.status_code == 400 and "not an email" in r.json()["error"]


def test_marking_a_job_board(client):
    r = client.post("/api/jobs/1/company", json={"is_job_board": True}, headers=AUTH)
    assert r.json()["company"]["is_job_board"] == 1
    assert client.get("/api/jobs?view=shortlisted").json()["jobs"][0]["contact"] is None


def test_lookups_without_keys_say_why(client):
    r = client.post("/api/jobs/1/find-contact", json={}, headers=AUTH)
    assert r.status_code == 400 and "no keys" in r.json()["error"]


def test_today_stats_and_status(client):
    client.post("/api/jobs/1/stage", json={"stage": "closed", "reason": "skipped"}, headers=AUTH)
    assert client.get("/api/stats").json()["closed"] == {"skipped": 1}
    today = client.get("/api/today").json()
    assert [j["id"] for j in today["new_jobs"]] == [2]
    status = client.get("/api/status").json()
    assert status["gmail"] and not status["hunter"] and status["caps"]["total"] == 15


def test_the_visa_list_is_its_own_view(client, home, filters):
    from datetime import timedelta

    from jobhunter.models import ONSITE

    from .conftest import NOW

    store = JobStore(home / "data" / "jobs.sqlite")
    store_job(store, filters, source_job_id="3", company="Wheely", remote_status=ONSITE, allowed_locations=["London"],
              description="Python.\nUK visa sponsorship is available.")
    store_job(store, filters, source_job_id="4", company="Oldvisa", remote_status=ONSITE, allowed_locations=["London"],
              description="Python.\nUK visa sponsorship is available.", posted_at=NOW - timedelta(days=6))
    store.commit()
    store.close()
    visa = {j["company"]: j for j in client.get("/api/jobs?view=visa_list").json()["jobs"]}
    assert set(visa) == {"Wheely", "Oldvisa"} and visa["Wheely"]["status"] == "visa_list"
    # The pipeline's To apply column adds the ones posted today or yesterday (stage new) to the shortlist.
    fresh = client.get("/api/jobs?view=visa_list&days=2").json()["jobs"]
    assert [j["company"] for j in fresh] == ["Wheely"] and fresh[0]["stage"] == "new"
    # Still not in the shortlist view (the daily CV, letter and contact steps take shortlisted jobs only).
    assert "Wheely" not in {j["company"] for j in client.get("/api/jobs?view=shortlisted").json()["jobs"]}
    today = client.get("/api/today").json()
    # The Today card is what was found this week, however old the posting.
    assert {j["company"] for j in today["new_visa_jobs"]} == {"Wheely", "Oldvisa"}
    assert "Wheely" not in {j["company"] for j in today["new_jobs"]}


def test_filter_by_years_asked_and_date_posted(client, home, filters):
    from datetime import timedelta

    from .conftest import NOW

    store = JobStore(home / "data" / "jobs.sqlite")
    store_job(store, filters, source_job_id="3", company="Twoyears", required_yoe=2)
    store_job(store, filters, source_job_id="4", company="Threeyears", required_yoe=3)
    store_job(store, filters, source_job_id="5", company="Fouryears", required_yoe=4)
    store_job(store, filters, source_job_id="6", company="Fiveyears", required_yoe=5,
              posted_at=NOW - timedelta(days=6))  # found today, but posted 6 days ago
    store.commit()
    store.close()

    def companies(query):
        return {j["company"] for j in client.get(f"/api/jobs?view=shortlisted&{query}").json()["jobs"]}

    unstated = {"Acme", "Talentuch"}
    everyone = unstated | {"Twoyears", "Threeyears", "Fouryears", "Fiveyears"}
    assert companies("") == everyone
    # Brackets that don't overlap; a job that doesn't say how many years is only under "not mentioned".
    assert companies("yoe=lt3") == {"Twoyears"}
    assert companies("yoe=3-4") == {"Threeyears"}
    assert companies("yoe=4-5") == {"Fouryears"}
    assert companies("yoe=5%2B") == {"Fiveyears"}
    assert companies("yoe=none") == unstated
    # The date the row shows: when it was posted, not when it was found.
    assert companies("days=1") == everyone - {"Fiveyears"}
    assert companies("days=7") == everyone
    assert companies("yoe=5%2B&days=3") == set()
    rows = {j["company"]: j for j in client.get("/api/jobs?view=shortlisted").json()["jobs"]}
    assert rows["Twoyears"]["required_yoe"] == 2 and rows["Acme"]["required_yoe"] is None
    assert client.get("/api/jobs?yoe=3").status_code == 400
    assert client.get("/api/jobs?days=-1").status_code == 400


def test_skip_with_a_reason_for_the_fit_grade(client):
    assert client.get("/api/status").json()["skip_reasons"]["too_senior"] == "Too senior"
    body = {"stage": "closed", "reason": "skipped", "skip_reason": "wrong_stack", "skip_note": "mostly Go"}
    detail = client.post("/api/jobs/1/stage", json=body, headers=AUTH).json()
    assert (detail["application"]["skip_reason"], detail["application"]["skip_note"]) == ("wrong_stack", "mostly Go")
    assert client.post("/api/jobs/1/stage", json={**body, "skip_reason": "nope"}, headers=AUTH).status_code == 400
    closed = client.get("/api/jobs?view=closed").json()["jobs"]
    assert [(j["id"], j["skip_reason"]) for j in closed] == [(1, "wrong_stack")]


def test_lists_carry_the_fit_grade_and_put_the_best_first(client, home):
    store = JobStore(home / "data" / "jobs.sqlite")
    store.save_fit_grade(2, {"grade": 5, "reason": "Python backend, 3+ years.", "model": "m", "at": "x"})
    store.save_fit_grade(1, {"grade": 2, "reason": "Asks for 7+ years.", "model": "m", "at": "x"})
    store.close()
    jobs = client.get("/api/jobs?view=shortlisted").json()["jobs"]
    assert [(j["id"], j["fit_grade"]["grade"]) for j in jobs] == [(2, 5), (1, 2)]
    assert client.get("/api/jobs/2").json()["job"]["fit_grade"]["reason"] == "Python backend, 3+ years."


def seed_contacts(home, filters, extra_jobs=0):
    """Jobs at companies with contacts: a small one (CEO before CTO), a big one (head of engineering before the
    recruiter), one with a contact you added by hand, one never looked up, and a job whose contact you picked."""
    from jobhunter.store.companies import add_company, update_company

    store = JobStore(home / "data" / "jobs.sqlite")
    for key, name in (("acme", "Acme"), ("globex", "Globex"), ("umbrella", "Umbrella")):
        add_company(store, key, name)
    update_company(store, "globex", size_range="201-500")
    people = {}
    for key, full_name, position, source in (
            ("acme", "Cleo Tran", "CTO", "hunter"), ("acme", "Ana Ruiz", "CEO", "hunter"),
            ("globex", "Rita Moss", "Technical Recruiter", "hunter"), ("globex", "Ed Park", "VP Engineering", "hunter"),
            ("umbrella", "Uma Bell", "Chief Executive Officer", "hunter"), ("umbrella", "Ola Hart", "", "manual")):
        people[full_name] = save_contact(store, key, NOW, full_name=full_name, position=position or None,
                                         email=f"{full_name.split()[0].lower()}@{key}.io", email_status="found",
                                         confidence=90, source=source)
    ids = {"Acme 2": store_job(store, filters, source_job_id="3", company="Acme", title="Backend Engineer"),
           "Globex": store_job(store, filters, source_job_id="4", company="Globex"),
           "Umbrella": store_job(store, filters, source_job_id="5", company="Umbrella https://umbrella.io"),
           "Initech": store_job(store, filters, source_job_id="6", company="Initech")}
    for n in range(extra_jobs):
        store_job(store, filters, source_job_id=f"x{n}", company=("Acme", "Globex", "Umbrella", "Hooli")[n % 4],
                  title=f"Python Engineer {n}")
    tracking.ensure_application(store, ids["Acme 2"], NOW)
    store.conn.execute("UPDATE applications SET contact_id = ? WHERE job_id = ?", (people["Cleo Tran"], ids["Acme 2"]))
    store.commit()
    store.close()
    return ids


def test_the_job_list_shows_each_job_s_contact(client, home, filters):
    ids = seed_contacts(home, filters)
    jobs = {j["id"]: j for j in client.get("/api/jobs?view=shortlisted").json()["jobs"]}
    contact = {job_id: j["contact"] for job_id, j in jobs.items()}
    assert contact[1] == {"name": "Ana Ruiz", "role": "CEO", "email_status": "found"}  # small: the CEO first
    assert contact[ids["Acme 2"]] == {"name": "Cleo Tran", "role": "CTO", "email_status": "found"}  # picked by you
    assert contact[ids["Globex"]] == {"name": "Ed Park", "role": "Head of engineering", "email_status": "found"}
    assert contact[ids["Umbrella"]] == {"name": "Ola Hart", "role": "Other", "email_status": "found"}  # yours first
    assert contact[ids["Initech"]] is None and contact[2] is None  # never looked up; a job board
    # The job's page picks the same person.
    for job_id in (1, ids["Acme 2"], ids["Globex"], ids["Umbrella"], ids["Initech"]):
        detail = client.get(f"/api/jobs/{job_id}").json()["contact"]
        assert (detail or {}).get("full_name") == (contact[job_id] or {}).get("name")


def test_reading_a_job_writes_nothing(client, home):
    def companies():
        store = JobStore(home / "data" / "jobs.sqlite")
        try:
            return store.conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        finally:
            store.close()

    detail = client.get("/api/jobs/1").json()  # Acme has no companies row yet
    assert companies() == 0
    assert detail["company"] | {"targets": None, "why": None, "suggested_domain": None} == {
        "key": "acme", "name": "Acme", "domain": None, "domain_source": None, "size_range": None, "size_count": None,
        "is_job_board": 0, "email_pattern": None, "accept_all": None, "lookup_state": None, "lookup_started_at": None,
        "looked_up_at": None, "note": None, "credits": 0.0, "cost_usd": 0.0, "targets": None, "why": None,
        "skip_listed": False, "suggested_domain": None}
    client.get("/api/jobs")
    assert companies() == 0
    # The actions that need the row make it.
    changed = client.post("/api/jobs/1/company", json={"domain": "acme.io"}, headers=AUTH).json()
    assert changed["company"]["domain"] == "acme.io"
    assert companies() == 1


def test_the_job_list_costs_the_same_few_queries_however_many_jobs(client, home, filters, monkeypatch):
    statements: list[str] = []

    class CountingStore(JobStore):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.conn.set_trace_callback(statements.append)

    monkeypatch.setattr("jobhunter.web.app.JobStore", CountingStore)

    def queries():
        statements.clear()
        jobs = client.get("/api/jobs?view=shortlisted").json()["jobs"]
        return len(jobs), len(statements)

    seed_contacts(home, filters)
    few, few_queries = queries()
    store = JobStore(home / "data" / "jobs.sqlite")
    for n in range(40):
        store_job(store, filters, source_job_id=f"y{n}", company=("Acme", "Globex", "Umbrella", "Hooli")[n % 4],
                  title=f"Backend Engineer {n}")
    store.close()
    many, many_queries = queries()
    # The list, the picked contacts, those contacts, the companies, their people: not one query per job.
    assert many == few + 40 and many_queries == few_queries == 5
