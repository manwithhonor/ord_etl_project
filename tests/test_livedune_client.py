from pathlib import Path

import pandas as pd

from src.livedune_client import LiveDuneClient


class FakeResponse:
    def __init__(self, data):
        self.data = data
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, params=None, headers=None, timeout=None, **kwargs):
        self.calls.append((method, url, params, headers))
        if not params or not params.get("after"):
            return FakeResponse(
                {
                    "response": [
                        {"id": "1", "url": "https://x/1", "created": "2026-08-01", "views": 10}
                    ],
                    "after": "next",
                }
            )
        return FakeResponse(
            {
                "response": [
                    {"id": "2", "url": "https://x/2", "created": "2026-08-02", "views": 20}
                ],
                "after": None,
            }
        )


def base_aliases():
    return {
        "source_post_id": ["id"],
        "post_url": ["url", "Ссылка"],
        "published_at": ["created", "Дата"],
        "impressions_total": ["views", "Просмотров"],
        "account_id": ["account_id"],
    }


def test_get_posts_paginates_and_adds_auth():
    cfg = {
        "base_url": "https://api.test",
        "posts_endpoint": "/accounts/{account_id}/posts",
        "auth": {"style": "query", "token_param": "access_token"},
        "pagination": {"items_field": "response", "cursor_response_field": "after", "cursor_param": "after"},
        "column_aliases": base_aliases(),
    }
    session = FakeSession()
    c = LiveDuneClient(cfg, api_token="secret", session=session)
    df = c.extract_posts_api(["acc"])
    assert list(df["impressions_total"]) == [10, 20]
    assert session.calls[0][2]["access_token"] == "secret"
    assert session.calls[1][2]["after"] == "next"


def test_real_export_shape_posts_sheet_and_total_row(tmp_path: Path):
    path = tmp_path / "livedune.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame([{"foo": 1}]).to_excel(writer, sheet_name="Общее", index=False)
        pd.DataFrame(
            [
                {
                    "Дата": "31.08.2026 13:10:00",
                    "Ссылка": "https://vk.com/demo?w=wall-1_100",
                    "Просмотров": 277,
                    "Лайков": 3,
                },
                {
                    "Дата": "28.08.2026 13:00:01",
                    "Ссылка": "https://vk.com/demo?w=wall-1_99",
                    "Просмотров": 1957,
                    "Лайков": 25,
                },
                {"Дата": "Итого:", "Ссылка": None, "Просмотров": 0, "Лайков": 0},
            ]
        ).to_excel(writer, sheet_name="Посты", index=False)

    cfg = {
        "excel": {"path": str(path), "sheet_name": "Посты", "dayfirst": True},
        "column_aliases": base_aliases(),
    }
    c = LiveDuneClient(cfg)
    df = c.extract_posts_excel()

    assert len(df) == 2
    assert list(df["impressions_total"]) == [277, 1957]
    assert df.iloc[0]["published_at"].strftime("%Y-%m-%d") == "2026-08-31"
    assert df.iloc[0]["post_url"].endswith("wall-1_100")
