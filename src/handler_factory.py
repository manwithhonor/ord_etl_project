from __future__ import annotations

import hashlib
import logging
import os
from calendar import monthrange
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd

from exceptions import ConfigurationError, SourceDataError
from src.livedune_client import LiveDuneClient
from state_store import StateStore
from src.yandex_client import YandexORDConnector

logger = logging.getLogger(__name__)


class ETLHandler:
    def __init__(
        self,
        config: dict[str, Any],
        livedune: LiveDuneClient,
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

        bootstrap_csv = self.config.get("../state", {}).get("bootstrap_csv")
        if bootstrap_csv:
            loaded = self.state.bootstrap_from_csv(bootstrap_csv)
            if loaded:
                logger.info("Bootstrapped %s state rows", loaded)

        source = self.extract()
        transformed = self.transform(source, report_month)
        preview_path = Path(self.config["app"].get("preview_csv", "statics/ord_statistics_preview.csv"))
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
        key = mapping_cfg.get("key", "post_url")

        left = source.copy()
        if key == "post_url":
            left[key] = left[key].map(self._canonical_url)

        if mapping_path.exists():
            mapping = pd.read_csv(mapping_path, dtype=str).fillna("")
        else:
            mapping = pd.DataFrame(columns=[key, "creative_id", "creative_token", "platform_id"])

        required = {key, "creative_id", "platform_id"}
        missing = required - set(mapping.columns)
        if missing:
            raise SourceDataError(f"Mapping file is missing columns: {sorted(missing)}")

        if key == "post_url" and not mapping.empty:
            mapping[key] = mapping[key].map(self._canonical_url)

        # Blank rows are allowed in the hand-maintained mapping file. This makes it
        # possible to keep all LiveDune posts there and fill IDs only for reportable ads.
        mapping = mapping[
            mapping["creative_id"].astype(str).str.strip().ne("")
            & mapping["platform_id"].astype(str).str.strip().ne("")
        ].copy()

        if "enabled" in mapping.columns:
            enabled = mapping["enabled"].astype(str).str.strip().str.casefold()
            mapping = mapping[enabled.isin({"1", "true", "yes", "y", "да"})].copy()

        # Always refresh a convenient file that can be used for manual mapping.
        self._write_mapping_template(left, mapping, mapping_cfg, key)

        if mapping.empty:
            raise SourceDataError(
                f"No completed ORD mappings found in {mapping_path}. "
                f"Fill creative_id/platform_id using the generated mapping template."
            )

        merged = left.merge(mapping, on=key, how="left", validate="many_to_one")
        mapped_mask = merged["creative_id"].notna() & merged["creative_id"].astype(str).str.strip().ne("")
        unmapped_count = int((~mapped_mask).sum())
        if unmapped_count:
            policy = mapping_cfg.get("unmapped_policy", "ignore")
            logger.info("Ignoring %s LiveDune posts without ORD mapping", unmapped_count)
            if policy == "error":
                examples = merged.loc[~mapped_mask, key].head(5).tolist()
                raise SourceDataError(f"No ORD mapping for {unmapped_count} posts. Examples: {examples}")

        # Mapping is intentionally the whitelist of posts that belong in ORD.
        merged = merged.loc[mapped_mask].copy()
        if merged.empty:
            raise SourceDataError("No mapped LiveDune posts are available for ORD processing")

        start, end = self._month_bounds(report_month)
        merged = merged[merged["published_at"].dt.date <= end].copy()
        rows: list[dict[str, Any]] = []
        state_cfg = self.config.get("../state", {})
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
                    "Bootstrap state from the amount of cumulative impressions already reported before this month."
                )

            delta = current_total - int(baseline)
            if delta < 0:
                policy = state_cfg.get("negative_delta_policy", "error")
                if policy == "clamp_zero":
                    delta = 0
                else:
                    raise SourceDataError(
                        f"LiveDune cumulative views decreased for {business_key}: "
                        f"current={current_total}, baseline={baseline}"
                    )

            if delta == 0 and self.config["app"].get("skip_zero_impressions", True):
                continue

            fact_start = published if start <= published <= end else start
            statistics_id = self._statistics_id(report_month, creative_id, platform_id)
            normalized = {
                "statistics_id": statistics_id,  # local id only; v8 statistics schema has no id field
                "business_key": business_key,
                "report_month": report_month,
                "post_url": row.get("post_url", ""),
                "creative_token": row.get("creative_token", ""),
                "creative_id": creative_id,
                "platform_id": platform_id,
                "campaign_type": self.config.get("transform", {}).get("campaign_type_value", "other"),
                "impsFact": int(delta),
                "impsPlan": int(delta),
                "dateStartFact": fact_start.isoformat(),
                "dateStartPlan": fact_start.isoformat(),
                "dateEndFact": end.isoformat(),
                "dateEndPlan": end.isoformat(),
                # Self-promotion is zero-value reporting. v8 expects these as strings.
                "amount_excluding_vat": "0",
                "amount_including_vat": "0",
                "vat_amount": "0",
                "vat_rate": "0",
                "amount_per_unit": "0",
                # Local delta audit columns.
                "source_cumulative": current_total,
                "source_baseline": int(baseline),
            }
            rows.append(normalized)

        return pd.DataFrame(rows)

    def load(self, transformed: pd.DataFrame, report_month: str) -> None:
        ycfg = self.config["yandex"]
        payload_cfg = ycfg.get("statistics_payload", {})
        if ycfg.get("require_schema_verified", True) and not payload_cfg.get("schema_verified", False):
            raise ConfigurationError(
                "Real Yandex load is blocked because yandex.statistics_payload.schema_verified=false."
            )

        # User requirement: send statistics one row at a time. v8 still expects an
        # envelope with a statistics array, so every POST contains exactly one item.
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
        """Build exactly the POST /api/v8/statistics shape supplied for the project."""
        item = {
            "amount": {
                "excludingVat": str(row["amount_excluding_vat"]),
                "includingVat": str(row["amount_including_vat"]),
                "vat": str(row["vat_amount"]),
                "vatRate": str(row["vat_rate"]),
            },
            "amountPerUnit": str(row["amount_per_unit"]),
            "creativeId": str(row["creative_id"]),
            "dateEndFact": str(row["dateEndFact"]),
            "dateEndPlan": str(row["dateEndPlan"]),
            "dateStartFact": str(row["dateStartFact"]),
            "dateStartPlan": str(row["dateStartPlan"]),
            "impsFact": int(row["impsFact"]),
            "impsPlan": int(row["impsPlan"]),
            "platformId": str(row["platform_id"]),
            "type": str(row["campaign_type"]),
        }
        return {"statistics": [item]}

    def _write_mapping_template(
        self,
        source: pd.DataFrame,
        mapping: pd.DataFrame,
        mapping_cfg: dict[str, Any],
        key: str,
    ) -> None:
        if not mapping_cfg.get("write_template", True):
            return

        path = Path(mapping_cfg.get("template_path", "statics/creative_mapping_to_fill.csv"))
        path.parent.mkdir(parents=True, exist_ok=True)

        template = source[["published_at", key, "impressions_total"]].copy()
        template["published_at"] = template["published_at"].dt.strftime("%Y-%m-%d %H:%M:%S")

        map_columns = [c for c in [key, "creative_id", "creative_token", "platform_id", "enabled"] if c in mapping.columns]
        if not mapping.empty and map_columns:
            template = template.merge(mapping[map_columns], on=key, how="left")

        for col in ["creative_id", "creative_token", "platform_id", "enabled"]:
            if col not in template.columns:
                template[col] = ""

        template.to_csv(path, index=False, encoding="utf-8-sig")
        logger.info("Mapping helper saved to %s", path)

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
        """Normalize URL without deleting identity-bearing query parameters.

        This matters for the supplied VK export: the post id is in ``?w=wall-...``.
        Only UTM-style tracking parameters are removed; the ``w`` parameter is kept.
        """
        value = str(value).strip()
        if not value:
            return value
        parts = urlsplit(value)
        kept_query = [
            (key, val)
            for key, val in parse_qsl(parts.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_")
        ]
        return urlunsplit(
            (
                parts.scheme.lower(),
                parts.netloc.lower(),
                parts.path.rstrip("/"),
                urlencode(kept_query, doseq=True),
                "",
            )
        )


class HandlerFactory:
    @staticmethod
    def create(config: dict[str, Any]) -> ETLHandler:
        ld_cfg = config["livedune"]
        ya_cfg = config["yandex"]
        ld_token = os.getenv(ld_cfg.get("api_token_env", "LIVEDUNE_API_TOKEN"), "")
        ya_token = os.getenv(ya_cfg.get("oauth_token_env", "YANDEX_ORD_OAUTH_TOKEN"), "")

        livedune = LiveDuneClient(ld_cfg, api_token=ld_token)
        yandex = YandexORDConnector(ya_cfg, oauth_token=ya_token)
        state = StateStore(config.get("../state", {}).get("sqlite_path", "state/etl_state.sqlite3"))
        return ETLHandler(config, livedune, yandex, state)
