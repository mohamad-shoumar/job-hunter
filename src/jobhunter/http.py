"""One shared HTTP client: timeouts, a user agent, and a couple of polite retries."""

from __future__ import annotations

import time

import httpx

DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; jobhunter/0.1; personal job search)"
_RETRY_STATUSES = {429, 500, 502, 503, 504}


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After", "")
    return min(float(value), 30.0) if value.isdigit() else None


class Http:
    def __init__(self, timeout: float = 30.0, retries: int = 2, user_agent: str = DEFAULT_USER_AGENT):
        self.retries = retries
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json, text/html, application/xml;q=0.9, */*;q=0.8",
            },
        )

    def get(self, url: str, params: dict | None = None) -> httpx.Response:
        for attempt in range(self.retries + 1):
            final = attempt == self.retries
            try:
                response = self._client.get(url, params=params)
            except httpx.TransportError:
                if final:
                    raise
                time.sleep(1.5 * (attempt + 1))
                continue
            if response.status_code in _RETRY_STATUSES and not final:
                time.sleep(_retry_after(response) or 1.5 * (attempt + 1))
                continue
            response.raise_for_status()
            return response
        raise AssertionError("unreachable")

    def get_json(self, url: str, params: dict | None = None):
        return self.get(url, params).json()

    def get_text(self, url: str, params: dict | None = None) -> str:
        return self.get(url, params).text

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Http:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
