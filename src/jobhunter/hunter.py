"""Hunter.io API v2 (hunter.io/api-documentation/v2): the parts contacts.py uses.

The key goes in the X-API-KEY header, never in the URL, so it cannot end up in
a log line or an error message.

What each call costs (free plan: 50 credits a month, reset on your signup day):
  account, domain-finder, email-count      free
  companies/find (size)                    charged only when data comes back
  domain-search (people + emails)          1 credit per 1-10 emails returned
  email-finder                             1 credit, only when it finds one
  email-verifier                           0.5 credit (only ever on a click)
contacts.py measures what a lookup really spent from `account` before and
after, instead of trusting these numbers.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

BASE = "https://api.hunter.io/v2"
# Free plan: limit + offset must stay at or under 10.
MAX_RESULTS = 10


class HunterError(RuntimeError):
    def __init__(self, status: int, error_id: str, details: str):
        super().__init__(f"Hunter {status} {error_id}: {details}")
        self.status = status
        self.error_id = error_id

    @property
    def fatal(self) -> bool:
        """Every later call would fail the same way: bad key, no access, out of credits or rate limited."""
        return self.status in (401, 403, 429)


@dataclass
class Account:
    remaining: float | None
    available: float | None
    reset_date: str | None
    plan: str | None


class Hunter:
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=30, follow_redirects=True)
        self._headers = {"X-API-KEY": api_key, "Accept": "application/json"}

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, **params) -> dict | None:
        """The JSON body, or None for a 404 (Hunter's "nothing found" on some endpoints)."""
        params = {k: v for k, v in params.items() if v is not None}
        try:
            response = self._client.get(f"{BASE}/{path}", params=params, headers=self._headers)
        except httpx.RequestError as exc:
            raise HunterError(0, "network", type(exc).__name__) from None
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            try:
                error = (response.json().get("errors") or [{}])[0]
            except ValueError:
                error = {}
            raise HunterError(response.status_code, str(error.get("id") or "error"), str(error.get("details") or ""))
        return response.json()

    def account(self) -> Account:
        data = (self._get("account") or {}).get("data") or {}
        requests = data.get("requests") or {}
        # "credits" only exists on the unified credits plans; older plans count searches.
        bucket = requests.get("credits") or requests.get("searches") or {}
        remaining = bucket.get("remaining")
        if remaining is None and bucket.get("available") is not None:
            remaining = bucket["available"] - (bucket.get("used") or 0)
        return Account(
            remaining=float(remaining) if remaining is not None else None,
            available=float(bucket["available"]) if bucket.get("available") is not None else None,
            reset_date=str(data["reset_date"]) if data.get("reset_date") else None,
            plan=data.get("plan_name"),
        )

    def domain_finder(self, company: str) -> list[dict]:
        body = self._get("domain-finder", company=company, limit=5) or {}
        return body.get("data") or []

    def email_count(self, domain: str) -> dict:
        return (self._get("email-count", domain=domain) or {}).get("data") or {}

    def company(self, domain: str) -> dict | None:
        body = self._get("companies/find", domain=domain)
        return (body or {}).get("data") or None

    def domain_search(self, domain: str, seniority: str | None = None, department: str | None = None) -> dict:
        body = self._get("domain-search", domain=domain, seniority=seniority, department=department,
                         type="personal", limit=MAX_RESULTS) or {}
        return body.get("data") or {}

    def email_finder(self, domain: str, first_name: str, last_name: str) -> dict | None:
        body = self._get("email-finder", domain=domain, first_name=first_name, last_name=last_name)
        data = (body or {}).get("data") or {}
        return data if data.get("email") else None

    def email_verifier(self, email: str) -> dict:
        return (self._get("email-verifier", email=email) or {}).get("data") or {}
