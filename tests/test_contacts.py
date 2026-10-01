"""Who to contact: plain rules, the Hunter client, the lookup, and the Claude backup (through fakes)."""

from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest

from jobhunter import contacts
from jobhunter.config import OutreachConfig
from jobhunter.contacts import (
    ContactFinder, chosen_contact, domain_from_links, find_contacts, guess_email, role_of, run_budget, size_upper_bound,
    targets_for,
)
from jobhunter.hunter import Account, Hunter, HunterError
from jobhunter.store import JobStore

from .conftest import NOW, fixture_json, store_job

CONFIG = OutreachConfig(skip_companies=["Proxify"])


@pytest.mark.parametrize("position, role", [
    ("Co-founder & CTO", "cto"),
    ("Founder & CEO", "ceo"),
    ("Co-Founder", "founder"),
    ("Managing Director", "ceo"),
    ("Head of Engineering", "eng_lead"),
    ("VP, Software Development", "eng_lead"),
    ("Director of Technology", "eng_lead"),
    ("Engineering Manager", "eng_manager"),
    ("Technical Lead", "eng_manager"),
    ("Senior Technical Recruiter", "recruiter"),
    ("Head of Talent", "recruiter"),
    ("Head of People", "hr"),
    ("HR Business Partner", "hr"),
    ("Product Owner", "other"),
    ("Head of Sales", "other"),
    (None, "other"),
])
def test_positions_map_to_roles(position, role):
    assert role_of(position) == role


def test_size_decides_who_to_target():
    assert size_upper_bound("11-50") == 50 and size_upper_bound("10K+") == 10000 and size_upper_bound(None) is None
    assert size_upper_bound("51-200", 42) == 42  # an exact count wins
    assert targets_for("11-50", None, CONFIG)[0] == ["ceo", "founder", "cto"]
    targets, why = targets_for("51-200", None, CONFIG)
    assert targets[0] == "eng_lead" and targets[-1] == "hr" and "over 50" in why
    targets, why = targets_for(None, None, CONFIG)
    assert targets[0] == "ceo" and why.startswith("Size unknown")


@pytest.mark.parametrize("name, texts, domain", [
    ("Sticker Mule", ["https://weworkremotely.com/remote-jobs/x", "Apply at https://www.stickermule.com/careers"], "stickermule.com"),
    ("Reddit", ["see www.redditinc.com/careers"], "redditinc.com"),
    ("Circle.so", ["https://jobs.ashbyhq.com/circle/1", "https://circleco.notion.site/x https://careers.circle.so/"], "circle.so"),
    ("WorkHero https://workhero.pro", [""], "workhero.pro"),
    ("Toggl", ["https://toggl.com/jobs"], "toggl.com"),
    ("Acme", ["https://himalayas.app/companies/acme/jobs/1", "https://www.linkedin.com/company/acme"], None),
    ("Acme", ["https://unrelated-shop.com/"], None),
])
def test_domain_comes_from_the_company_s_own_links(name, texts, domain):
    assert domain_from_links(name, texts) == domain


def test_email_guesses_follow_the_known_pattern():
    assert guess_email("Jane", "Doe", "acme.com", None, small=True) == "jane@acme.com"
    assert guess_email("Jane", "Doe", "acme.com", None, small=False) == "jane.doe@acme.com"
    assert guess_email("José", "Núñez", "acme.com", "{f}{last}", small=True) == "jnunez@acme.com"
    assert guess_email("Jane", "", "acme.com", "{first}.{last}", small=False) == "jane@acme.com"


# --- the Hunter client -------------------------------------------------------------


def hunter_with(handler) -> Hunter:
    return Hunter("secret-key", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_the_key_travels_in_a_header_never_the_url():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=fixture_json("hunter_account.json"))

    account = hunter_with(handler).account()
    assert account == Account(remaining=9450.0, available=10000.0, reset_date="2026-10-05", plan="Growth")
    assert seen[0].headers["X-API-KEY"] == "secret-key" and "secret-key" not in str(seen[0].url)


def test_hunter_errors_are_readable_and_say_when_to_stop():
    def handler(request):
        return httpx.Response(401, json={"errors": [{"id": "authentication_failed", "code": 401, "details": "No user found"}]})

    with pytest.raises(HunterError) as err:
        hunter_with(handler).email_count("acme.com")
    assert err.value.fatal and "authentication_failed" in str(err.value) and "secret-key" not in str(err.value)


def test_hunter_responses_parse():
    routes = {
        "/v2/companies/find": fixture_json("hunter_companies_find.json"),
        "/v2/domain-search": fixture_json("hunter_domain_search.json"),
        "/v2/email-finder": fixture_json("hunter_email_finder.json"),
        "/v2/domain-finder": fixture_json("hunter_domain_finder.json"),
    }
    hunter = hunter_with(lambda r: httpx.Response(200, json=routes[r.url.path]))
    assert hunter.company("hunter.io")["metrics"]["employees"] == "11-50"
    search = hunter.domain_search("intercom.com", "executive")
    assert search["pattern"] == "{first}" and search["emails"][0]["value"] == "ciaran@intercom.com"
    assert hunter.email_finder("reddit.com", "Alexis", "Ohanian")["email"] == "alexis@reddit.com"
    assert hunter.domain_finder("stripe")[0]["domain"] == "stripe.com"


# --- the lookup, with a fake Hunter ----------------------------------------------------


def person(first, last, position, email, status="valid", confidence=90):
    return {"value": email, "first_name": first, "last_name": last, "position": position, "confidence": confidence,
            "sources": [{"uri": f"https://example.com/team#{first}", "still_on_page": True}],
            "verification": {"status": status}, "linkedin": None}


class FakeHunter:
    def __init__(self, size="11-50", people=None, count=5, remaining=40.0, domains=None):
        self.size, self.count, self.remaining = size, count, remaining
        self.people = people if people is not None else [
            person("Sam", "Lee", "Engineering Manager", "sam@acme.io"),
            person("Ana", "Ruiz", "Co-founder & CEO", "ana@acme.io"),
        ]
        self.domains = domains or []
        self.calls = []

    def account(self):
        self.calls.append(("account",))
        return Account(self.remaining, 50.0, "2026-10-15", "Free")

    def domain_finder(self, company):
        self.calls.append(("domain_finder", company))
        return self.domains

    def email_count(self, domain):
        self.calls.append(("email_count", domain))
        return {"total": self.count, "department": {"executive": self.count, "it": self.count}, "seniority": {"executive": 1}}

    def company(self, domain):
        self.calls.append(("company", domain))
        self.remaining -= 0.2
        return {"metrics": {"employees": self.size, "employeesCount": None}}

    def domain_search(self, domain, seniority=None, department=None):
        self.calls.append(("domain_search", domain, seniority, department))
        self.remaining -= 1
        return {"pattern": "{first}", "accept_all": False, "emails": self.people}

    def email_finder(self, domain, first, last):
        self.calls.append(("email_finder", domain, first, last))
        return None


def acme_job(store, filters, **overrides):
    overrides.setdefault("company", "Acme")
    overrides.setdefault("description", "We build APIs with Python. More at https://acme.io/about")
    return store_job(store, filters, **overrides)


def test_a_small_company_gets_its_ceo_with_proof(filters):
    store = JobStore(":memory:")
    job_id = acme_job(store, filters)
    hunter = FakeHunter()
    result = ContactFinder(CONFIG, hunter).lookup(store, store.get(job_id), NOW)
    assert result.status == "found" and result.credits == pytest.approx(1.2)
    assert ("domain_search", "acme.io", "executive", None) in hunter.calls
    best = chosen_contact(store, store.get(job_id), CONFIG)
    assert (best["full_name"], best["role"], best["email_status"]) == ("Ana Ruiz", "ceo", "verified")
    assert best["evidence_url"].startswith("https://example.com/team") and best["verified"] == 1
    company = store.conn.execute("SELECT * FROM companies").fetchone()
    assert (company["domain"], company["domain_source"], company["size_range"], company["lookup_state"]) == \
        ("acme.io", "links", "11-50", "done")


def test_a_bigger_company_gets_engineering_first(filters):
    store = JobStore(":memory:")
    job_id = acme_job(store, filters)
    hunter = FakeHunter(size="201-500", people=[
        person("Ana", "Ruiz", "CEO", "ana@acme.io"),
        person("Kim", "Ho", "Talent Partner", "kim@acme.io"),
        person("Sam", "Lee", "VP Engineering", "sam@acme.io"),
    ])
    ContactFinder(CONFIG, hunter).lookup(store, store.get(job_id), NOW)
    assert ("domain_search", "acme.io", "senior,executive", "it,hr,management,executive") in hunter.calls
    assert chosen_contact(store, store.get(job_id), CONFIG)["full_name"] == "Sam Lee"


def test_a_second_job_at_the_same_company_costs_nothing(filters):
    store = JobStore(":memory:")
    first = acme_job(store, filters, source_job_id="1")
    second = acme_job(store, filters, source_job_id="2", title="Python Engineer", company="Acme Inc")
    hunter = FakeHunter()
    finder = ContactFinder(CONFIG, hunter)
    finder.lookup(store, store.get(first), NOW)
    calls = len(hunter.calls)
    assert finder.lookup(store, store.get(second), NOW).status == "reused"
    assert len(hunter.calls) == calls
    assert chosen_contact(store, store.get(second), CONFIG)["full_name"] == "Ana Ruiz"


def test_job_boards_are_skipped_without_calls(filters):
    store = JobStore(":memory:")
    job_id = store_job(store, filters, company="Proxify AB")
    hunter = FakeHunter()
    assert ContactFinder(CONFIG, hunter).lookup(store, store.get(job_id), NOW).status == "job_board"
    assert hunter.calls == []


def test_hunter_s_domain_guess_is_used_only_for_the_same_name(filters):
    store = JobStore(":memory:")
    job_id = store_job(store, filters, company="Globex", description="Python APIs.")
    hunter = FakeHunter(domains=[{"domain": "globexcorp.com", "company_name": "Globex Industries"}])
    result = ContactFinder(CONFIG, hunter).lookup(store, store.get(job_id), NOW)
    assert result.status == "no_domain" and "Hunter suggests globexcorp.com" in result.note
    hunter = FakeHunter(domains=[{"domain": "globex.com", "company_name": "Globex"}])
    ContactFinder(CONFIG, hunter).lookup(store, store.get(job_id), NOW, force=True)
    assert store.conn.execute("SELECT domain FROM companies").fetchone()[0] == "globex.com"


def test_low_credits_stop_hunter(filters):
    store = JobStore(":memory:")
    job_id = acme_job(store, filters)
    hunter = FakeHunter(remaining=5.5)
    result = ContactFinder(CONFIG, hunter).lookup(store, store.get(job_id), NOW, use_claude=False)
    assert not any(c[0] == "domain_search" for c in hunter.calls)
    assert "credits low" in result.note


def test_the_budget_spreads_credits_over_the_days_left():
    config = OutreachConfig(max_companies_per_run=10, hunter_reserve_credits=5)
    assert run_budget(Account(45.0, 50.0, "2026-10-15", "Free"), NOW, config) == 1  # 40 left / 1.2 / 20 days
    assert run_budget(Account(45.0, 50.0, "2026-09-27", "Free"), NOW, config) == 10  # resets in 2 days: spend it
    assert run_budget(Account(5.5, 50.0, "2026-10-15", "Free"), NOW, config) == 0
    assert run_budget(None, NOW, config) == 10


def test_find_contacts_keeps_to_the_limit_best_fit_first(filters):
    store = JobStore(":memory:")
    low = acme_job(store, filters, source_job_id="1", company="Low Co", description="Python. https://lowco.com")
    high = acme_job(store, filters, source_job_id="2", company="High Co",
                    description="Python FastAPI PostgreSQL AWS Django. https://highco.com")
    run = find_contacts(store, ContactFinder(CONFIG, FakeHunter()), [store.get(low), store.get(high)], NOW, limit=1,
                        use_claude=False)
    assert run.looked_up == 1 and run.waiting == 1 and run.found_job_ids == [high]


# --- the Claude backup ----------------------------------------------------------------


class FakeClaude:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def web_answer(people, titles, employees=""):
    results = [{"type": "web_search_result", "url": f"https://www.linkedin.com/in/{n}", "title": t}
               for n, t in enumerate(titles)]
    blocks = [
        {"type": "server_tool_use", "id": "srv_1", "name": "web_search", "input": {"query": "acme cto"}},
        {"type": "web_search_tool_result", "tool_use_id": "srv_1", "content": results},
        {"type": "tool_use", "id": "tu_1", "name": "record_people",
         "input": {"domain": "acme.io", "employees": employees, "employees_url": "", "people": people}},
    ]
    usage = {"input_tokens": 8000, "output_tokens": 300, "server_tool_use": {"web_search_requests": 2}}
    return SimpleNamespace(content=blocks, stop_reason="tool_use", usage=usage)


def test_claude_finds_a_person_the_search_results_confirm(filters):
    store = JobStore(":memory:")
    job_id = acme_job(store, filters)
    claude = FakeClaude(web_answer(
        [{"name": "Jane Doe", "title": "CTO", "quote": "Jane Doe - CTO - Acme", "source_url": "https://www.linkedin.com/in/0"},
         {"name": "Bob Stone", "title": "CEO", "quote": "Bob Stone, CEO of Acme", "source_url": "https://acme.io"}],
        ["Jane Doe - CTO - Acme | LinkedIn"],
    ))
    result = ContactFinder(CONFIG, None, claude).lookup(store, store.get(job_id), NOW)
    assert result.status == "found" and result.cost_usd > 0
    assert claude.calls[0]["model"] == "claude-haiku-4-5"
    assert claude.calls[0]["tools"][0]["type"] == "web_search_20250305"
    rows = {r["full_name"]: r for r in store.conn.execute("SELECT * FROM contacts")}
    assert rows["Jane Doe"]["verified"] == 1 and rows["Jane Doe"]["email"] == "jane@acme.io"
    assert rows["Jane Doe"]["email_status"] == "guessed"
    assert rows["Bob Stone"]["verified"] == 0  # the quote is not in any search result: "not confirmed"
    assert rows["Bob Stone"]["email"] is None  # only the best person gets an email guess


def test_an_employee_count_counts_only_when_a_result_shows_it(filters):
    store = JobStore(":memory:")
    job_id = acme_job(store, filters)
    claude = FakeClaude(web_answer([], ["Acme | 11-50 employees | LinkedIn"], employees="11-50 employees"))
    ContactFinder(CONFIG, None, claude).lookup(store, store.get(job_id), NOW)
    assert store.conn.execute("SELECT size_range FROM companies").fetchone()[0] == "11-50"
    store = JobStore(":memory:")
    job_id = acme_job(store, filters)
    claude = FakeClaude(web_answer([], ["Acme | LinkedIn"], employees="11-50 employees"))
    ContactFinder(CONFIG, None, claude).lookup(store, store.get(job_id), NOW)
    assert store.conn.execute("SELECT size_range FROM companies").fetchone()[0] is None


def test_a_running_lookup_is_not_started_twice(filters):
    store = JobStore(":memory:")
    job_id = acme_job(store, filters)
    contacts.job_company(store, store.get(job_id), NOW)
    store.conn.execute("UPDATE companies SET lookup_state = 'running', lookup_started_at = ?", (NOW.isoformat(),))
    hunter = FakeHunter()
    assert ContactFinder(CONFIG, hunter).lookup(store, store.get(job_id), NOW + timedelta(minutes=1)).status == "busy"
    assert ContactFinder(CONFIG, hunter).lookup(store, store.get(job_id), NOW + timedelta(minutes=11)).status == "found"
