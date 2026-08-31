from yandex_connector import YandexORDConnector


class FakeResponse:
    def __init__(self, data):
        self.data = data
        self.text = str(data)

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, headers=None, timeout=None, **kwargs):
        self.calls.append((method, url, headers, kwargs))
        if method == "POST":
            return FakeResponse({"request_id": "req-1"})
        return FakeResponse({"status": "ERIR success"})


def test_send_statistics_and_status():
    cfg = {
        "base_url": "https://ord.test",
        "api_version": "v8",
        "status_poll": {"enabled": False},
    }
    session = FakeSession()
    c = YandexORDConnector(cfg, oauth_token="oauth", session=session)
    resp = c.send_statistics({"id": "s1"})
    assert resp["request_id"] == "req-1"
    method, url, headers, kwargs = session.calls[0]
    assert method == "POST"
    assert url.endswith("/api/v8/statistics")
    assert headers["Authorization"] == "Bearer oauth"
    assert kwargs["json"] == {"id": "s1"}
