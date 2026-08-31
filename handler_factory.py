from __future__ import annotations

import hashlib
import logging
import os
from calendar import monthrange
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pandas as pd

from exceptions import ConfigurationError, SourceDataError
from livedune_connector import LiveDuneConnector
from state_store import StateStore
from yandex_connector import YandexORDConnector

logger = logging.getLogger(__name__)


class ETLHandler:
    def __init__(
        self,
        config: dict[str, Any],
        livedune: LiveDuneConnector,
        yandex: YandexORDConnector,
        state: StateStore,
    ):
        self.config = config
        self.livedune = livedune
        self.yandex = yandex
        self.state = state

    def run(self) -> pd.DataFrame:
        report_month = self.config["app"]["report_month"]
        dry_run = bool(self.config["app"].get("dry_run", True))

        bootstrap_csv = self.config.get("state", {}).get("bootstrap_csv")
        if bootstrap_csv:
            loaded = self.state.bootstrap_from_csv(bootstrap_csv)
            if loaded:
                logger.info("Bootstrapped %s state rows", loaded)

        source = self.extract()
        transformed = self.transform(source, report_month)
        preview_path = Path(self.config["app"].get("preview_csv", "output/ord_statistics_preview.csv"))
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        transformed.to_csv(preview_path, index=False, encoding="utf-8-sig")
        logger.info("Preview saved to %s (%s rows)", preview_path, len(transformed))

        if not dry_run:
            self.load(transformed, report_month)
        return transformed

    def extract(self) -> pd.DataFrame:
        ld_cfg = self.config["livedune"]
        mode = ld_cfg.get("mode", "excel")
        if mode == "api":
            account_ids = ld_cfg.get("account_ids", [])
            if not account_ids:
                raise ConfigurationError("livedune.account_ids must be set in API mode")
            df = self.livedune.extract_posts_api(account_ids)
        elif mode == "excel":
            df = self.livedune.extract_posts_excel()
        else:
            raise ConfigurationError(f"Unknown livedune.mode={mode!r}")

        if df.empty:
            raise SourceDataError("LiveDune returned no posts")
        return df

    def transform(self, source: pd.DataFrame, report_month: str) -> pd.DataFrame:
        mapping_cfg = self.config.get("mapping", {})
        mapping_path = Path(mapping_cfg.get("path", "data/creative_mapping.csv"))
        if not mapping_path.exists():
            raise SourceDataError(
                f"Mapping file not found: {mapping_path}. It must link LiveDune posts to ORD creative/platform IDs."
            )
        mapping = pd.read_csv(mapping_path, dtype=str).fillna("")
        key = mapping_cfg.get("key", "post_url")
        required = {key, "creative_id", "platform_id"}
        missing = required - set(mapping.columns)
        if missing:
            raise SourceDataError(f"Mapping file is missing columns: {sorted(missing)}")

        left = source.copy()
        if key == "post_url":
            left[key] = left[key].map(self._canonical_url)
            mapping[key] = mapping[key].map(self._canonical_url)
        merged = left.merge(mapping, on=key, how="left", validate="many_to_one")
        no_map = merged[merged["creative_id"].isna() | (merged["creative_id"] == "")]
        if not no_map.empty:
            examples = no_map[key].head(5).tolist()
            raise SourceDataError(f"No ORD mapping for {len(no_map)} posts. Examples: {examples}")

        start, end = self._month_bounds(report_month)
        merged = merged[merged["published_at"].dt.date <= end].copy()
        rows: list[dict[str, Any]] = []
        state_cfg = self.config.get("state", {})
        initial_policy = state_cfg.get("initial_state_policy", "require_bootstrap")
        require_prev_month = bool(state_cfg.get("require_previous_month_snapshot", True))
        previous_month = (pd.Period(report_month, freq="M") - 1).strftime("%Y-%m")

        for row in merged.to_dict("records"):
            creative_id = str(row["creative_id"])
            platform_id = str(row["platform_id"])
            business_key = f"{creative_id}|{platform_id}"
            existing = self.state.get_snapshot(business_key, report_month)
            if existing and not self.config["app"].get("force_recalculate", False):
                logger.info("Skip already reported %s for %s", business_key, report_month)
                continue

            published = pd.Timestamp(row["published_at"]).date()
            current_total = int(row["impressions_total"])
            prev = self.state.get_latest_before(business_key, report_month)

            if published >= start:
                baseline = 0
            elif prev:
                if require_prev_month and prev.report_month != previous_month:
                    raise SourceDataError(
                        f"Gap in snapshots for {business_key}: expected {previous_month}, got {prev.report_month}. "
                        "Process missed months sequentially or bootstrap the missing month."
                    )
                baseline = prev.source_cumulative
            elif initial_policy == "assume_zero":
                baseline = 0
            else:
                raise SourceDataError(
                    f"No previous snapshot for old creative {business_key}. "
                    "Bootstrap state from prior ORD reports before the first production run."
                )

            delta = current_total - int(baseline)
            if delta < 0:
                policy = state_cfg.get("negative_delta_policy", "error")
                if policy == "clamp_zero":
                    delta = 0
                else:
                    raise SourceDataError(
                        f"LiveDune cumulative impressions decreased for {business_key}: "
                        f"current={current_total}, baseline={baseline}"
                    )

            if delta == 0 and self.config["app"].get("skip_zero_impressions", True):
                continue

            fact_start = published if start <= published <= end else start
            statistics_id = self._statistics_id(report_month, creative_id, platform_id)
            normalized = {
                "statistics_id": statistics_id,
                "business_key": business_key,
                "report_month": report_month,
                "post_url": row.get("post_url", ""),
                "creative_token": row.get("creative_token", ""),
                "creative_id": creative_id,
                "platform_id": platform_id,
                "campaign_type": self.config.get("transform", {}).get("campaign_type_value", "Иное"),
                "impsFact": int(delta),
                "impsPlan": int(delta),
                "dateStartFact": fact_start.isoformat(),
                "dateStartPlan": fact_start.isoformat(),
                "dateEndFact": end.isoformat(),
                "dateEndPlan": end.isoformat(),
                # Business-level zero values for self-promotion. The exact v8 API
                # names can be mapped later through config.yaml.
                "amount_without_vat": 0.0,
                "amount_with_vat": 0.0,
                "vat_rate": 0.0,
                "vat_amount": 0.0,
                "unit_cost_with_vat": 0.0,
                # Backward-compatible fields from older ORD statistics schemas.
                "amount": 0.0,
                "amountPerUnit": 0.0,
                "isVat": False,
                "source_cumulative": current_total,
                "source_baseline": int(baseline),
            }
            for field in self.config.get("yandex", {}).get("statistics_payload", {}).get("extra_zero_fields", []):
                normalized[field] = 0
            rows.append(normalized)

        return pd.DataFrame(rows)

    def load(self, transformed: pd.DataFrame, report_month: str) -> None:
        ycfg = self.config["yandex"]
        payload_cfg = ycfg.get("statistics_payload", {})
        if ycfg.get("require_schema_verified", True) and not payload_cfg.get("schema_verified", False):
            raise ConfigurationError(
                "Real Yandex load is blocked because yandex.statistics_payload.schema_verified=false. "
                "Compare the field_map with the current POST /statistics Swagger schema, then set it to true."
            )

        for row in transformed.to_dict("records"):
            payload = self._build_yandex_payload(row)
            response = self.yandex.send_statistics(payload)
            request_id = self.yandex.extract_request_id(response)
            status = "HTTP 200"
            if request_id:
                status_response = self.yandex.poll_status(request_id)
                status = self.yandex._extract_status(status_response) or status

            self.state.upsert_snapshot(
                business_key=row["business_key"],
                report_month=report_month,
                source_cumulative=int(row["source_cumulative"]),
                month_impressions=int(row["impsFact"]),
                statistics_id=row["statistics_id"],
                request_id=request_id,
                status=status,
                payload=payload,
            )

    def _build_yandex_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        cfg = self.config["yandex"].get("statistics_payload", {})
        field_map: dict[str, str] = cfg.get("field_map", {})
        if not field_map:
            raise ConfigurationError("yandex.statistics_payload.field_map is empty")
        payload: dict[str, Any] = {}
        for api_field, logical_field in field_map.items():
            if logical_field not in row:
                raise ConfigurationError(f"Payload mapping references unknown field {logical_field!r}")
            payload[api_field] = row[logical_field]
        return payload

    @staticmethod
    def _statistics_id(report_month: str, creative_id: str, platform_id: str) -> str:
        raw = f"{report_month}|{creative_id}|{platform_id}".encode("utf-8")
        digest = hashlib.sha1(raw).hexdigest()[:12]
        return f"stat-{report_month.replace('-', '')}-{digest}"

    @staticmethod
    def _month_bounds(report_month: str) -> tuple[date, date]:
        period = pd.Period(report_month, freq="M")
        year, month = period.year, period.month
        return date(year, month, 1), date(year, month, monthrange(year, month)[1])

    @staticmethod
    def _canonical_url(value: Any) -> str:
        value = str(value).strip()
        if not value:
            return value
        parts = urlsplit(value)
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


class HandlerFactory:
    @staticmethod
    def create(config: dict[str, Any]) -> ETLHandler:
        ld_cfg = config["livedune"]
        ya_cfg = config["yandex"]
        ld_token = os.getenv(ld_cfg.get("api_token_env", "LIVEDUNE_API_TOKEN"), "")
        ya_token = os.getenv(ya_cfg.get("oauth_token_env", "YANDEX_ORD_OAUTH_TOKEN"), "")

        livedune = LiveDuneConnector(ld_cfg, api_token=ld_token)
        yandex = YandexORDConnector(ya_cfg, oauth_token=ya_token)
        state = StateStore(config.get("state", {}).get("sqlite_path", "state/etl_state.sqlite3"))
        return ETLHandler(config, livedune, yandex, state)
