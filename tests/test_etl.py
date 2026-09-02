from pathlib import Path

import pandas as pd

from src.handler_factory import ETLHandler
from src.livedune_client import LiveDuneClient
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
            "excel": {"path": str(tmp_path / "input.xlsx"), "sheet_name": "Посты", "dayfirst": True},
            "column_aliases": {
                "source_post_id": ["id"],
                "post_url": ["url", "Ссылка"],
                "published_at": ["created", "Дата"],
                "impressions_total": ["views", "Просмотров"],
                "account_id": ["account_id"],
            },
        },
        "mapping": {
            "path": str(tmp_path / "mapping.csv"),
            "key": "post_url",
            "unmapped_policy": "ignore",
            "write_template": True,
            "template_path": str(tmp_path / "mapping_template.csv"),
        },
        "state": {
            "sqlite_path": str(tmp_path / "state.sqlite3"),
            "bootstrap_csv": str(tmp_path / "bootstrap.csv"),
            "initial_state_policy": "require_bootstrap",
            "require_previous_month_snapshot": True,
            "negative_delta_policy": "error",
        },
        "transform": {"campaign_type_value": "other"},
        "yandex": {
            "require_schema_verified": True,
            "statistics_payload": {"schema_verified": True},
        },
    }


def prepare_files(tmp_path: Path):
    with pd.ExcelWriter(tmp_path / "input.xlsx") as writer:
        pd.DataFrame(
            [
                {
                    "Ссылка": "https://vk.com/demo?w=wall-1_100&utm_source=x",
                    "Дата": "10.07.2026 12:00:00",
                    "Просмотров": 150,
                },
                {
                    "Ссылка": "https://vk.com/demo?w=wall-1_101",
                    "Дата": "20.08.2026 12:00:00",
                    "Просмотров": 999,
                },
                {"Ссылка": None, "Дата": "Итого:", "Просмотров": 0},
            ]
        ).to_excel(writer, sheet_name="Посты", index=False)

    # Only the first row is reportable. The second LiveDune post is intentionally unmapped.
    pd.DataFrame(
        [
            {
                "post_url": "https://vk.com/demo?w=wall-1_100",
                "creative_id": "creative-100",
                "creative_token": "token",
                "platform_id": "vk-platform",
                "enabled": "true",
            }
        ]
    ).to_csv(tmp_path / "mapping.csv", index=False)

    pd.DataFrame(
        [
            {
                "creative_id": "creative-100",
                "platform_id": "vk-platform",
                "report_month": "2026-07",
                "source_cumulative": 100,
            }
        ]
    ).to_csv(tmp_path / "bootstrap.csv", index=False)


def test_full_etl_dry_run_calculates_month_delta(tmp_path):
    prepare_files(tmp_path)
    cfg = make_config(tmp_path, dry_run=True)
    ld = LiveDuneClient(cfg["livedune"])
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
    assert row["campaign_type"] == "other"
    assert row["amount_excluding_vat"] == "0"
    assert ya.payloads == []
    assert (tmp_path / "mapping_template.csv").exists()


def test_full_etl_live_sends_exact_v8_envelope_and_saves_snapshot(tmp_path):
    prepare_files(tmp_path)
    cfg = make_config(tmp_path, dry_run=False)
    ld = LiveDuneClient(cfg["livedune"])
    ya = FakeYandex()
    state = StateStore(cfg["state"]["sqlite_path"])
    etl = ETLHandler(cfg, ld, ya, state)

    etl.run()
    assert len(ya.payloads) == 1
    assert ya.payloads[0] == {
        "statistics": [
            {
                "amount": {
                    "excludingVat": "0",
                    "includingVat": "0",
                    "vat": "0",
                    "vatRate": "0",
                },
                "amountPerUnit": "0",
                "creativeId": "creative-100",
                "dateEndFact": "2026-08-31",
                "dateEndPlan": "2026-08-31",
                "dateStartFact": "2026-08-01",
                "dateStartPlan": "2026-08-01",
                "impsFact": 50,
                "impsPlan": 50,
                "platformId": "vk-platform",
                "type": "other",
            }
        ]
    }
    snap = state.get_snapshot("creative-100|vk-platform", "2026-08")
    assert snap is not None
    assert snap.source_cumulative == 150
    assert snap.month_impressions == 50
    assert snap.status == "ERIR success"


def test_vk_query_parameter_is_not_destroyed():
    a = ETLHandler._canonical_url("https://vk.com/psb?w=wall-1_10&utm_source=test")
    b = ETLHandler._canonical_url("https://vk.com/psb?w=wall-1_11&utm_source=test")
    assert a == "https://vk.com/psb?w=wall-1_10"
    assert b == "https://vk.com/psb?w=wall-1_11"
    assert a != b
