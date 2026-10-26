"""The shared HTTP client: which answers are tried again, how long it waits, and what it returns.
Requests go to httpx.MockTransport (no network) and the waits are recorded, not slept."""

import json

import httpx
import pytest

from jobhunter import http as http_module
from jobhunter.http import Http, wait_for_network

URL = "https://api.example.com/jobs"
DROPPED = "the connection drops"  # an answer that raises httpx.ConnectError


@pytest.fixture
def sleeps(monkeypatch):
    """The waits between tries, in seconds."""
    waited = []
    monkeypatch.setattr(http_module.time, "sleep", waited.append)
    return waited


def serve(*answers, retries=2):
    """An Http whose requests get `answers` in order, and the list of requests it made."""
    queue, requests = list(answers), []

    def handler(request):
        requests.append(request)
        answer = queue.pop(0)
        if answer == DROPPED:
            raise httpx.ConnectError("connection refused", request=request)
        return answer

    return Http(retries=retries, transport=httpx.MockTransport(handler)), requests


def test_a_busy_server_is_asked_again_after_the_wait_it_names(sleeps):
    client, requests = serve(httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(200, json={"jobs": [1]}))
    assert client.get_json(URL) == {"jobs": [1]}
    assert len(requests) == 2 and sleeps == [2.0]


def test_retry_after_is_capped_at_30_seconds_and_a_date_in_it_is_not_read(sleeps):
    client, requests = serve(
        httpx.Response(429, headers={"Retry-After": "120"}),
        httpx.Response(503, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),  # the usual wait instead
        httpx.Response(200, text="ok"),
    )
    assert client.get_text(URL) == "ok"
    assert len(requests) == 3 and sleeps == [30.0, 3.0]


def test_server_errors_wait_longer_each_time_and_raise_after_the_last_try(sleeps):
    client, requests = serve(httpx.Response(500), httpx.Response(502), httpx.Response(504))
    with pytest.raises(httpx.HTTPStatusError) as error:
        client.get(URL)
    assert error.value.response.status_code == 504
    assert len(requests) == 3 and sleeps == [1.5, 3.0]


def test_a_dropped_connection_is_tried_again(sleeps):
    client, requests = serve(DROPPED, httpx.Response(200, content=b"%PDF"))
    assert client.get_bytes(URL) == b"%PDF"
    assert len(requests) == 2 and sleeps == [1.5]


def test_a_connection_that_keeps_dropping_raises_after_the_last_try(sleeps):
    client, requests = serve(DROPPED, DROPPED, DROPPED)
    with pytest.raises(httpx.ConnectError):
        client.get(URL)
    assert len(requests) == 3 and sleeps == [1.5, 3.0]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410])
def test_other_client_errors_raise_at_once(sleeps, status):
    # Asking again would get the same answer: the request itself is wrong, or the job is gone.
    client, requests = serve(httpx.Response(status))
    with pytest.raises(httpx.HTTPStatusError) as error:
        client.get(URL)
    assert error.value.response.status_code == status
    assert len(requests) == 1 and sleeps == []


def test_no_retries_means_one_try(sleeps):
    client, requests = serve(httpx.Response(503), retries=0)
    with pytest.raises(httpx.HTTPStatusError):
        client.get(URL)
    assert len(requests) == 1 and sleeps == []


def test_get_sends_the_params_and_a_user_agent(sleeps):
    client, requests = serve(httpx.Response(200, json=[]))
    assert client.get_json(URL, {"q": "python", "page": 2}) == []
    assert requests[0].url.params == httpx.QueryParams({"q": "python", "page": "2"})
    assert "jobhunter" in requests[0].headers["User-Agent"]


def test_post_json_sends_the_body_and_returns_the_json_answer(sleeps):
    client, requests = serve(httpx.Response(503), httpx.Response(200, json={"results": ["a"]}))
    answer = client.post_json(URL, {"query": "backend"}, headers={"X-Api-Key": "test"})
    assert answer == {"results": ["a"]} and sleeps == [1.5]  # a POST is retried too
    for request in requests:
        assert request.method == "POST" and request.headers["X-Api-Key"] == "test"
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {"query": "backend"}


def test_post_form_sends_a_form_and_returns_the_json_answer(sleeps):
    client, requests = serve(httpx.Response(200, json={"html": "<li>job</li>"}))
    assert client.post_form(URL, {"action": "load_jobs", "page": "2"}) == {"html": "<li>job</li>"}
    assert requests[0].method == "POST"
    assert requests[0].headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert requests[0].content == b"action=load_jobs&page=2"


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.mark.parametrize("answers_on_try, expected", [(3, 10.0), (None, None)])
def test_waiting_for_the_network(monkeypatch, answers_on_try, expected):
    # After the Mac wakes, Wi-Fi may take a while: try every `step` seconds, give up after `timeout`.
    clock, tries = [0.0], []

    def connect(address, timeout):
        tries.append(address)
        if len(tries) != answers_on_try:
            raise OSError("network is unreachable")
        return _Connection()

    monkeypatch.setattr(http_module.socket, "create_connection", connect)
    monkeypatch.setattr(http_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(http_module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    assert wait_for_network("api.example.com", timeout=12, step=5) == expected
    assert tries[0] == ("api.example.com", 443) and len(tries) == (answers_on_try or 4)
