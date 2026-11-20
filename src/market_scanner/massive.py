from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any, Callable

import requests


class MassiveError(RuntimeError):
    """A sanitized Massive request failure."""


class MassiveClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.massive.com",
        timeout_seconds: int = 10,
        retries: int = 1,
        session=None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not api_key:
            raise ValueError("api_key is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._retries = retries
        self._session = session or requests.Session()
        self._sleep = sleep

    def _url(self, path: str) -> str:
        if path.startswith("https://") or path.startswith("http://"):
            return path
        return f"{self._base_url}/{path.lstrip('/')}"

    def _request(self, url: str, params: Mapping[str, object] | None) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                response = self._session.get(
                    url,
                    params=dict(params) if params is not None else None,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=self._timeout_seconds,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                if attempt < self._retries:
                    self._sleep(2**attempt)
                    continue
                raise MassiveError("Massive request failed: network error") from exc

            if response.status_code == 200:
                try:
                    payload = response.json()
                except Exception as exc:
                    raise MassiveError("Massive request failed: invalid JSON") from exc
                if not isinstance(payload, dict):
                    raise MassiveError("Massive request failed: invalid payload")
                return payload

            last_error = MassiveError(f"Massive request failed: HTTP {response.status_code}")
            transient = response.status_code == 429 or response.status_code >= 500
            if transient and attempt < self._retries:
                self._sleep(2**attempt)
                continue
            raise last_error

        raise MassiveError("Massive request failed") from last_error

    def get(
        self,
        path: str,
        params: Mapping[str, object] | None = None,
        *,
        paginate: bool = False,
    ) -> tuple[dict[str, Any], ...] | dict[str, Any]:
        url = self._url(path)
        if not paginate:
            return self._request(url, params)

        results: list[dict[str, Any]] = []
        next_params = params
        while url:
            payload = self._request(url, next_params)
            page = payload.get("results")
            if not isinstance(page, list):
                raise MassiveError("Massive request failed: invalid results")
            if not all(isinstance(item, dict) for item in page):
                raise MassiveError("Massive request failed: invalid result item")
            results.extend(page)
            next_url = payload.get("next_url")
            if next_url is not None and not isinstance(next_url, str):
                raise MassiveError("Massive request failed: invalid next page")
            url = self._url(next_url) if next_url else ""
            next_params = None
        return tuple(results)
