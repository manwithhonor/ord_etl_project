from __future__ import annotations

import time
from typing import Any

import requests

from exceptions import ConfigurationError, ConnectorError


class YandexORDConnector:
    """Universal connector for Yandex ORD REST API.

    The attached guide uses API v4. Current public Swagger exposes v7/v8, so the API
    version is configurable and defaults to v8.
    """

    def __init__(self, config: dict[str, Any], oauth_token: str | None, session=None):
        self.config = config
        self.base_url = config.get("base_url", "https://ord.yandex.net").rstrip("/")
        self.api_version = str(config.get("api_version", "v8")).lstrip("/")
        self.oauth_token = oauth_token
        self.session = session or requests.Session()
        self.timeout = int(config.get("timeout_seconds", 30))

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = dict(kwargs.pop("headers", {}) or {})
        if self.oauth_token:
            headers.setdefault("Authorization", f"Bearer {self.oauth_token}")
        headers.setdefault("Accept", "application/json")
        if "json" in kwargs:
            headers.setdefault("Content-Type", "application/json")

        try:
            response = self.session.request(
                method=method,
                url=url,
                headers=headers,
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            body = getattr(getattr(exc, "response", None), "text", "")
            raise ConnectorError(f"Yandex ORD request failed: {method} {url}: {exc}; body={body[:1000]}") from exc

    def endpoint(self, name: str) -> str:
        configured = self.config.get("endpoints", {}).get(name)
        if configured:
            return configured.format(api_version=self.api_version)
        return f"/api/{self.api_version}/{name}"

    def send_statistics(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.oauth_token:
            raise ConfigurationError("YANDEX_ORD_OAUTH_TOKEN is empty")
        return self._request("POST", self.endpoint("statistics"), json=payload)

    def get_status(self, request_id: str) -> dict[str, Any]:
        return self._request("GET", self.endpoint("status"), params={"reqid": request_id})

    def get_object(self, object_name: str, object_id: str) -> dict[str, Any]:
        """Read an object if the current API exposes GET for this object type."""
        return self._request("GET", self.endpoint(object_name), params={"id": object_id})

    def poll_status(self, request_id: str) -> dict[str, Any]:
        poll = self.config.get("status_poll", {})
        if not poll.get("enabled", True):
            return {"status": "not_polled", "request_id": request_id}

        terminal = set(poll.get("terminal_statuses", ["ORD success", "ERIR success", "ORD error", "ERIR error"]))
        error_statuses = set(poll.get("error_statuses", ["ORD error", "ERIR error"]))
        interval = float(poll.get("interval_seconds", 2))
        timeout = float(poll.get("timeout_seconds", 30))
        started = time.monotonic()
        last: dict[str, Any] = {}

        while time.monotonic() - started <= timeout:
            last = self.get_status(request_id)
            status = self._extract_status(last)
            if status in terminal:
                if status in error_statuses:
                    raise ConnectorError(f"Yandex ORD request {request_id} ended with {status}: {last}")
                return last
            time.sleep(interval)
        return last or {"status": "poll_timeout", "request_id": request_id}

    @staticmethod
    def extract_request_id(response: dict[str, Any]) -> str | None:
        for key in ("request_id", "requestId", "reqid"):
            if response.get(key):
                return str(response[key])
        nested = response.get("result")
        if isinstance(nested, dict):
            return YandexORDConnector.extract_request_id(nested)
        return None

    @staticmethod
    def _extract_status(response: dict[str, Any]) -> str | None:
        for key in ("status", "request_status", "requestStatus"):
            if response.get(key):
                return str(response[key])
        result = response.get("result")
        if isinstance(result, dict):
            return YandexORDConnector._extract_status(result)
        return None
