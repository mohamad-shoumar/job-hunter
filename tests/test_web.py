"""The web app through FastAPI's TestClient, on a temp project folder, with fake outside services."""

import re
import shutil

import pytest
from fastapi.testclient import TestClient

from jobhunter.config import OutreachConfig, Paths
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
