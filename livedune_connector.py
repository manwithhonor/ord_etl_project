from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests

from exceptions import ConnectorError, SourceDataError


class LiveDuneConnector:
    """Universal LiveDune reader with API and Excel fallback modes."""

    def __init__(self, config: dict[str, Any], api_token: str | None = None, session=None):
        self.config = config
        self.base_url = config.get("base_url", "https://api.livedune.com").rstrip("/")
        self.api_token = api_token
        self.session = session or requests.Session()
        self.timeout = int(config.get("timeout_seconds", 30))

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        params = dict(kwargs.pop("params", {}) or {})
        headers = dict(kwargs.pop("headers", {}) or {})

        auth = self.config.get("auth", {})
        auth_style = auth.get("style", "query")
        if self.api_token:
            if auth_style == "query":
                params.setdefault(auth.get("token_param", "access_token"), self.api_token)
            elif auth_style == "bearer":
                headers.setdefault("Authorization", f"Bearer {self.api_token}")

        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                headers=headers,
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ConnectorError(f"LiveDune request failed: {method} {url}: {exc}") from exc

    def get_accounts(self) -> list[dict[str, Any]]:
        data = self._request("GET", self.config.get("accounts_endpoint", "/accounts"))
        return self._items(data)

    def get_posts(self, account_id: str) -> list[dict[str, Any]]:
        endpoint = self.config.get("posts_endpoint", "/accounts/{account_id}/posts").format(
            account_id=account_id
        )
        pagination = self.config.get("pagination", {})
        cursor_param = pagination.get("cursor_param", "after")
        cursor_field = pagination.get("cursor_response_field", "after")

        result: list[dict[str, Any]] = []
        cursor = None
        seen_cursors: set[str] = set()
        while True:
            params = {cursor_param: cursor} if cursor else {}
            data = self._request("GET", endpoint, params=params)
            page_items = self._items(data)
            for item in page_items:
                item = dict(item)
                item.setdefault("account_id", account_id)
                result.append(item)

            cursor = data.get(cursor_field)
            if not cursor or not page_items or str(cursor) in seen_cursors:
                break
            seen_cursors.add(str(cursor))
        return result

    def extract_posts_api(self, account_ids: Iterable[str]) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for account_id in account_ids:
            rows.extend(self.get_posts(str(account_id)))
        if not rows:
            return pd.DataFrame()
        return self.normalize_posts(pd.DataFrame(rows))

    def extract_posts_excel(self, path: str | Path | None = None, sheet_name: Any = None) -> pd.DataFrame:
        excel_cfg = self.config.get("excel", {})
        path = Path(path or excel_cfg.get("path", "data/livedune_input.xlsx"))
        sheet_name = excel_cfg.get("sheet_name", 0) if sheet_name is None else sheet_name
        if not path.exists():
            raise SourceDataError(f"LiveDune Excel file not found: {path}")
        df = pd.read_excel(path, sheet_name=sheet_name)
        return self.normalize_posts(df)

    def normalize_posts(self, df: pd.DataFrame) -> pd.DataFrame:
        aliases = self.config.get("column_aliases", {})
        required = ["post_url", "published_at", "impressions_total"]
        optional = ["source_post_id", "account_id"]
        rename: dict[str, str] = {}

        for target in required + optional:
            candidates = aliases.get(target, [target])
            found = next((c for c in candidates if c in df.columns), None)
            if found:
                rename[found] = target
            elif target in required:
                raise SourceDataError(
                    f"Cannot find required LiveDune column '{target}'. Tried: {candidates}. "
                    f"Available: {list(df.columns)}"
                )

        out = df.rename(columns=rename).copy()
        out["post_url"] = out["post_url"].astype(str).str.strip()
        out["published_at"] = pd.to_datetime(out["published_at"], errors="raise")
        out["impressions_total"] = pd.to_numeric(out["impressions_total"], errors="raise").astype("int64")
        if "source_post_id" not in out.columns:
            out["source_post_id"] = out["post_url"]
        if "account_id" not in out.columns:
            out["account_id"] = ""
        return out

    def _items(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        configured = self.config.get("pagination", {}).get("items_field", "response")
        for key in (configured, "response", "data", "items", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return []
