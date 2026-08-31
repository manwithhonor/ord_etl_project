from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class Snapshot:
    business_key: str
    report_month: str
    source_cumulative: int
    month_impressions: int
    statistics_id: str
    request_id: str | None
    status: str | None


class StateStore:
    """Local ledger of monthly LiveDune snapshots already reported to ORD.

    Why this exists: the public Yandex ORD Swagger currently exposes POST /statistics,
    but no list/read endpoint for historical statistics. Therefore a local ledger is the
    safest source of truth for calculating monthly deltas from LiveDune cumulative views.
    """

    def __init__(self, sqlite_path: str | Path):
        self.path = Path(sqlite_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    business_key TEXT NOT NULL,
                    report_month TEXT NOT NULL,
                    source_cumulative INTEGER NOT NULL,
                    month_impressions INTEGER NOT NULL,
                    statistics_id TEXT NOT NULL,
                    request_id TEXT,
                    status TEXT,
                    payload_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (business_key, report_month)
                )
                """
            )

    def get_snapshot(self, business_key: str, report_month: str) -> Snapshot | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE business_key=? AND report_month=?",
                (business_key, report_month),
            ).fetchone()
        return self._row_to_snapshot(row) if row else None

    def get_latest_before(self, business_key: str, report_month: str) -> Snapshot | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM snapshots
                WHERE business_key=? AND report_month < ?
                ORDER BY report_month DESC
                LIMIT 1
                """,
                (business_key, report_month),
            ).fetchone()
        return self._row_to_snapshot(row) if row else None

    def upsert_snapshot(
        self,
        *,
        business_key: str,
        report_month: str,
        source_cumulative: int,
        month_impressions: int,
        statistics_id: str,
        request_id: str | None,
        status: str | None,
        payload: dict[str, Any] | None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True) if payload else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO snapshots (
                    business_key, report_month, source_cumulative, month_impressions,
                    statistics_id, request_id, status, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(business_key, report_month) DO UPDATE SET
                    source_cumulative=excluded.source_cumulative,
                    month_impressions=excluded.month_impressions,
                    statistics_id=excluded.statistics_id,
                    request_id=excluded.request_id,
                    status=excluded.status,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    business_key,
                    report_month,
                    int(source_cumulative),
                    int(month_impressions),
                    statistics_id,
                    request_id,
                    status,
                    payload_json,
                    now,
                    now,
                ),
            )

    def bootstrap_from_csv(self, csv_path: str | Path) -> int:
        """Load a one-time baseline exported/prepared from old reporting.

        Required columns:
        business_key, report_month, source_cumulative

        month_impressions may be omitted; it is stored as 0 because this row is a baseline.
        """
        path = Path(csv_path)
        if not path.exists():
            return 0
        df = pd.read_csv(path)
        required = {"business_key", "report_month", "source_cumulative"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Bootstrap CSV is missing columns: {sorted(missing)}")
        count = 0
        for row in df.to_dict("records"):
            if self.get_snapshot(str(row["business_key"]), str(row["report_month"])):
                continue
            self.upsert_snapshot(
                business_key=str(row["business_key"]),
                report_month=str(row["report_month"]),
                source_cumulative=int(row["source_cumulative"]),
                month_impressions=int(row.get("month_impressions", 0) or 0),
                statistics_id=str(row.get("statistics_id", "bootstrap")),
                request_id=None,
                status="bootstrap",
                payload=None,
            )
            count += 1
        return count

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> Snapshot:
        return Snapshot(
            business_key=row["business_key"],
            report_month=row["report_month"],
            source_cumulative=int(row["source_cumulative"]),
            month_impressions=int(row["month_impressions"]),
            statistics_id=row["statistics_id"],
            request_id=row["request_id"],
            status=row["status"],
        )
