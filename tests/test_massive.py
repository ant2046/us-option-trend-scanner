from __future__ import annotations

import requests
import pytest

from market_scanner.massive import MassiveClient, MassiveError


class Response:
    def __init__(self, status_code=200, payload=None, *, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class Session:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def client(outcomes, *, retries=1, sleep=lambda _: None):
    return MassiveClient(
        "secret-value",
        base_url="https://api.massive.com",
        timeout_seconds=3,
        retries=retries,
        session=Session(outcomes),
        sleep=sleep,
    )


def test_get_authenticates_with_header_and_returns_json():
    api = client([Response(payload={"status": "OK", "results": [{"ticker": "SPY"}]})])

    result = api.get("/v3/reference/tickers/SPY")

    assert result["results"][0]["ticker"] == "SPY"
    url, kwargs = api._session.calls[0]
    assert url == "https://api.massive.com/v3/reference/tickers/SPY"
    assert kwargs["headers"]["Authorization"] == "Bearer secret-value"
    assert kwargs["timeout"] == 3


def test_paginated_get_combines_all_pages_and_preserves_query():
    api = client(
        [
            Response(payload={"results": [{"t": 1}], "next_url": "https://api.massive.com/page-2"}),
            Response(payload={"results": [{"t": 2}]}),
        ]
    )

    results = api.get("/v2/aggs/ticker/SPY", {"limit": 1}, paginate=True)

    assert results == ({"t": 1}, {"t": 2})
    assert api._session.calls[0][1]["params"] == {"limit": 1}
    assert api._session.calls[1][1]["params"] is None


@pytest.mark.parametrize("status", [401, 403])
def test_authorization_errors_do_not_retry(status):
    api = client([Response(status, {"status": "NOT_AUTHORIZED"})], retries=2)

    with pytest.raises(MassiveError, match=f"HTTP {status}"):
        api.get("/restricted")

    assert len(api._session.calls) == 1


@pytest.mark.parametrize("first", [Response(429, {}), Response(503, {}), requests.Timeout("slow")])
def test_transient_failures_retry(first):
    sleeps = []
    api = client([first, Response(payload={"status": "OK"})], sleep=sleeps.append)

    assert api.get("/retry") == {"status": "OK"}
    assert len(api._session.calls) == 2
    assert sleeps == [1]


def test_malformed_json_is_sanitized_and_does_not_leak_credentials():
    api = client([Response(payload=ValueError("bad apiKey=secret-value"))], retries=0)

    with pytest.raises(MassiveError) as exc_info:
        api.get("/broken?apiKey=secret-value")

    message = str(exc_info.value)
    assert "secret-value" not in message
    assert "apiKey=" not in message


def test_second_page_failure_discards_partial_results():
    api = client(
        [
            Response(payload={"results": [{"t": 1}], "next_url": "https://api.massive.com/page-2"}),
            Response(500, {"error": "broken"}),
        ],
        retries=0,
    )

    with pytest.raises(MassiveError, match="HTTP 500"):
        api.get("/bars", paginate=True)
