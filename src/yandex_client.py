import datetime
import json
import os
import time
import requests


class YandexClient:
    def __init__(self, config):
        self.token = os.environ[config['token']]
        self.base_url = config['base_url']

    def _save_run(func):
        def wrapper(self, *args, **kwargs):
            count_error = 0
            return_value = None
            while True:
                try:
                    return_value = func(self, *args, **kwargs)
                    break
                except (TimeoutError, AssertionError, ConnectionError, TypeError):
                    print(f"{datetime.datetime.now().time().strftime('%H:%M:%S')} Connection to wb may be lost. Waiting for 30 second and reconnecting.")
                    return_value = None
                    count_error += 1
                    assert count_error != 3, "ERROR: wb connection failed 3 times"
                    time.sleep(10)
            return return_value
        return wrapper

    def _request(self, method, url, params=None, data=None):
        """Универсальный метод для всех типов запросов"""
        response = requests.request(
            method=method,
            url=url,
            headers={
                'Authorization': f"Bearer {self.token}",
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            },
            params=params,
            data=json.dumps(data) if data is not None else None
        )
        if response.status_code != 200:
            print(f"URL: {url}")
            print(f"Status: {response.status_code}")
            print(f"Response: {response.text}")
        assert response.status_code == 200, f"Request failed with status {response.status_code}"
        return response

    @_save_run
    def send_get_request(self, url, params=None, data=None):
        return self._request('GET', url, params, data)

    @_save_run
    def send_post_request(self, url, params=None, data=None):
        return self._request('POST', url, params, data)

    def get_status(self, request_id):
        print("Get status")
        params = {"reqid": request_id}
        response = self.send_get_request(self.base_url + "/status", params=params)
        return response.json()["status"]

    def send_statistics(self, payload):
        print("Send statistics")
        response = self.send_post_request(self.base_url + "/statistics", data=payload)
        return response
