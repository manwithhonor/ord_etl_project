import pandas as pd
from src.transform_handler import TransformHandler
from src.livedune_client import LiveDuneClient
from src.google_client import GoogleClient
from src.yandex_client import YandexClient


class HandlerFactory:
    def __init__(self, config):
        self.config = config
        self.google_client = GoogleClient(self.config["google"])

    def _extract(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        livedune_client = LiveDuneClient(self.config["livedune"])
        livedune_df = livedune_client.get_data()

        google_df = self.google_client.get_data()
        return livedune_df, google_df

    def _transform(self, livedune_df, google_df):
        transform_handler = TransformHandler(self.config)
        to_google_df, to_yandex_df = transform_handler.transform_exracted_data(livedune_df, google_df)
        payload = transform_handler.transform_to_yandex_data(to_yandex_df)
        return to_google_df, payload

    def _load(self, to_google_df, payload) -> None:
        yandex_client = YandexClient(self.config["yandex"])
        request_id = yandex_client.send_statistics(payload)
        response = yandex_client.get_status(request_id)

        self.google_client.send_data(to_google_df)

    def run(self):
        livedune_df, google_df = self._extract()
        to_google_df, payload = self._transform(livedune_df, google_df)
        self._load(to_google_df, payload)
        print("Готово")
