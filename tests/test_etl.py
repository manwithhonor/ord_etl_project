from pathlib import Path

import pandas as pd

from handler_factory import ETLHandler
from livedune_connector import LiveDuneConnector
from state_store import StateStore


class FakeYandex:
    def __init__(self):
        self.payloads = []

    def send_statistics(self, payload):
        self.payloads.append(payload)
        return {"request_id": "req-1"}

    def extract_request_id(self, response):
        return response.get("request_id")

    def poll_status(self, request_id):
        return {"status": "ERIR success"}

    def _extract_status(self, response):
        return response.get("status")


def make_config(tmp_path: Path, dry_run: bool):
    return {
        "app": {
            "report_month": "2026-08",
            "dry_run": dry_run,
            "preview_csv": str(tmp_path / "preview.csv"),
            "skip_zero_impressions": True,
            "force_recalculate": False,
        },
        "livedune": {
            "mode": "excel",
            "excel": {"path": str(tmp_path / "input.xlsx"), "sheet_name": 0},
            "column_aliases": {
                "source_post_id": ["id"],
                "post_url": ["url"],
                "published_at": ["created"],
                "impressions_total": ["views"],
                "account_id": ["account_id"],
            },
        },
        "mapping": {"path": str(tmp_path / "mapping.csv"), "key": "post_url"},
        "state": {
            "sqlite_path": str(tmp_path / "state.sqlite3"),
            "bootstrap_csv": str(tmp_path / "bootstrap.csv"),
            "initial_state_policy": "require_bootstrap",
            "require_previous_month_snapshot": True,
            "negative_delta_policy": "error",
        },
        "transform": {"campaign_type_value": "Иное"},
        "yandex": {
            "require_schema_verified": True,
            "statistics_payload": {
                "schema_verified": True,
                "field_map": {
                    "id": "statistics_id",
                    "creativeId": "creative_id",
                    "platformId": "platform_id",
                    "impsFact": "impsFact",
                    "impsPlan": "impsPlan",
                    "dateStartFact": "dateStartFact",
                    "dateStartPlan": "dateStartPlan",
                    "dateEndFact": "dateEndFact",
                    "dateEndPlan": "dateEndPlan",
                    "amount": "amount",
                    "amountPerUnit": "amountPerUnit",
                    "isVat": "isVat",
                },
            },
        },
    }


def prepare_files(tmp_path: Path):
    pd.DataFrame(
        [{"id": "p1", "url": "https://t.me/example/100?utm=x", "created": "2026-07-10", "views": 150}]
    ).to_excel(tmp_path / "input.xlsx", index=False)
    pd.DataFrame(
        [{"post_url": "https://t.me/example/100", "creative_id": "creative-100", "creative_token": "token", "platform_id": "telegram"}]
    ).to_csv(tmp_path / "mapping.csv", index=False)
    pd.DataFrame(
        [{"business_key": "creative-100|telegram", "report_month": "2026-07", "source_cumulative": 100}]
    ).to_csv(tmp_path / "bootstrap.csv", index=False)


def test_full_etl_dry_run_calculates_month_delta(tmp_path):
    prepare_files(tmp_path)
    cfg = make_config(tmp_path, dry_run=True)
    ld = LiveDuneConnector(cfg["livedune"])
    ya = FakeYandex()
    state = StateStore(cfg["state"]["sqlite_path"])
    etl = ETLHandler(cfg, ld, ya, state)

    df = etl.run()
    assert len(df) == 1
    row = df.iloc[0]
    assert row["impsFact"] == 50
    assert row["impsPlan"] == 50
    assert row["dateStartFact"] == "2026-08-01"
    assert row["dateEndFact"] == "2026-08-31"
    assert row["amount"] == 0
    assert ya.payloads == []


def test_full_etl_live_sends_and_saves_snapshot(tmp_path):
    prepare_files(tmp_path)
    cfg = make_config(tmp_path, dry_run=False)
    ld = LiveDuneConnector(cfg["livedune"])
    ya = FakeYandex()
    state = StateStore(cfg["state"]["sqlite_path"])
    etl = ETLHandler(cfg, ld, ya, state)

    df = etl.run()
    assert len(ya.payloads) == 1
    assert ya.payloads[0]["impsFact"] == 50
    snap = state.get_snapshot("creative-100|telegram", "2026-08")
    assert snap is not None
    assert snap.source_cumulative == 150
    assert snap.month_impressions == 50
    assert snap.status == "ERIR success"
