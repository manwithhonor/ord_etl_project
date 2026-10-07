from datetime import datetime
import json
import os
import time
import pandas as pd
import requests


class LiveDuneClient:
    def __init__(self, config):
        self.config = config
        self.token = os.environ[config['token']]
        self.base_url = config['base_url']
        self.account_dict = config['account_dict']

    def _save_run(func):
        def wrapper(self, *args, **kwargs):
            count_error = 0
            return_value = None
            while True:
                try:
                    return_value = func(self, *args, **kwargs)
                    break
                except (TimeoutError, AssertionError, ConnectionError, TypeError):
                    print(f"{datetime.now().time().strftime('%H:%M:%S')} Connection to livedune may be lost. Waiting for 10 second and reconnecting.")
                    return_value = None
                    count_error += 1
                    assert count_error != 3, "ERROR: livedune connection failed 3 times"
                    time.sleep(10)
            return return_value
        return wrapper

    def _request(self, method, url, params=None, data=None):
        params = params.copy() if params else {}
        params["access_token"] = self.token

        response = requests.request(
            method=method,
            url=url,
            headers={
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
        return response.json()

    @_save_run
    def send_post_request(self, url, params=None, data=None):
        return self._request('POST', url, params=params, data=data)

    @_save_run
    def send_get_request(self, url, params=None):
        return self._request('GET', url, params=params)


    def get_with_pages(self, url, params=None):
        params = params.copy() if params else {}
        all_items = []
        after = None
        max_pages = 1000
        page = 0

        while True:
            # Добавляем 'after' начиная со второй страницы
            if after not in (None, 0):
                params["after"] = after

            data = self.send_get_request(url, params=params)
            all_items.extend(data.get("response", []))
            count = data.get("count", 0)
            after = data.get("after")
            page += 1

            # Условие остановки: меньше 100 элементов или after пустой/ноль
            if count < 100 or after in (None, 0):
                break

            if page >= max_pages:
                print(f"Достигнут лимит страниц ({max_pages}), пагинация остановлена.")
                break
        return all_items

    def get_data(self):
        print("Скачиваем данные с livedune")
        livedune_df = pd.DataFrame()
        for platform in self.account_dict:
            params = {"date_from": "2026-01-01",
                      "date_to": datetime.now().date().strftime('%Y-%m-%d')}
            posts = self.get_with_pages(f"{self.config['base_url']}/{self.account_dict[platform]}/posts", params)
            df = pd.DataFrame(posts)
            df['current_views'] = df['impressions'].apply(lambda x: x['total'])
            df['platform'] = platform
            df = df.rename(columns={'url': 'platform_url'})
            livedune_df = pd.concat([livedune_df, df[['platform', 'platform_url', 'current_views']]], ignore_index=True)
        return livedune_df
