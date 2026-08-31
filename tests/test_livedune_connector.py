from livedune_connector import LiveDuneConnector


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
            return FakeResponse({"response": [{"id": "1", "url": "https://x/1", "created": "2026-08-01", "views": 10}], "after": "next"})
        return FakeResponse({"response": [{"id": "2", "url": "https://x/2", "created": "2026-08-02", "views": 20}], "after": None})


def test_get_posts_paginates_and_adds_auth():
    cfg = {
        "base_url": "https://api.test",
        "posts_endpoint": "/accounts/{account_id}/posts",
        "auth": {"style": "query", "token_param": "access_token"},
        "pagination": {"items_field": "response", "cursor_response_field": "after", "cursor_param": "after"},
        "column_aliases": {
            "source_post_id": ["id"],
            "post_url": ["url"],
            "published_at": ["created"],
            "impressions_total": ["views"],
            "account_id": ["account_id"],
        },
    }
    session = FakeSession()
    c = LiveDuneConnector(cfg, api_token="secret", session=session)
    df = c.extract_posts_api(["acc"])
    assert list(df["impressions_total"]) == [10, 20]
    assert session.calls[0][2]["access_token"] == "secret"
    assert session.calls[1][2]["after"] == "next"
