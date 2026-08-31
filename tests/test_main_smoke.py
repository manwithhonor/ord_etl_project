import subprocess
import sys
from pathlib import Path

import pandas as pd
import yaml


def test_main_cli_dry_run(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    input_xlsx = tmp_path / "input.xlsx"
    mapping_csv = tmp_path / "mapping.csv"
    bootstrap_csv = tmp_path / "bootstrap.csv"
    preview_csv = tmp_path / "preview.csv"
    state_db = tmp_path / "state.sqlite3"
    cfg_path = tmp_path / "config.yaml"

    pd.DataFrame([
        {"url": "https://t.me/demo/1", "created": "2026-07-01", "views": 250}
    ]).to_excel(input_xlsx, index=False)
    pd.DataFrame([
        {"post_url": "https://t.me/demo/1", "creative_id": "c1", "platform_id": "p1", "creative_token": "erid"}
    ]).to_csv(mapping_csv, index=False)
    pd.DataFrame([
        {"business_key": "c1|p1", "report_month": "2026-07", "source_cumulative": 200}
    ]).to_csv(bootstrap_csv, index=False)

    cfg = {
        "app": {"report_month": "2026-08", "dry_run": True, "preview_csv": str(preview_csv), "skip_zero_impressions": True},
        "livedune": {
            "mode": "excel",
            "excel": {"path": str(input_xlsx), "sheet_name": 0},
            "column_aliases": {
                "source_post_id": ["id"],
                "post_url": ["url"],
                "published_at": ["created"],
                "impressions_total": ["views"],
                "account_id": ["account_id"],
            },
        },
        "mapping": {"path": str(mapping_csv), "key": "post_url"},
        "state": {
            "sqlite_path": str(state_db),
            "bootstrap_csv": str(bootstrap_csv),
            "initial_state_policy": "require_bootstrap",
            "require_previous_month_snapshot": True,
            "negative_delta_policy": "error",
        },
        "transform": {"campaign_type_value": "Иное"},
        "yandex": {
            "api_version": "v8",
            "require_schema_verified": True,
            "statistics_payload": {"schema_verified": False, "field_map": {"id": "statistics_id"}},
        },
    }
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(project_root / "main.py"), "--config", str(cfg_path)],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert preview_csv.exists()
    preview = pd.read_csv(preview_csv)
    assert int(preview.iloc[0]["impsFact"]) == 50
