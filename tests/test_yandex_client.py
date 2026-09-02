from src.yandex_client import YandexClient
from unittest import TestCase
from dotenv import load_dotenv
import yaml


class TestYandexClient(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open('config.yaml', 'r') as file:
            config = yaml.safe_load(file)
        load_dotenv(".env", override=True)
        cls.config = config
        cls.yandex_client = YandexClient(config["yandex"])

    def test_send_stat(self):
        item_1 = {
            "amount": {
                "excludingVat": "0",
                "includingVat": "0",
                "vat": "0",
                "vatRate": "0",
            },
            "amountPerUnit": "0.00000",
            "creativeId": "D3RnUjVBnerGbAsQzASgey",
            "dateEndFact": "2026-08-31",
            "dateEndPlan": "2026-08-31",
            "dateStartFact": "2026-08-01",
            "dateStartPlan": "2026-08-01",
            "impsFact": 12,
            "impsPlan": 12,
            "platformId": "qG9XK9A9nxLdrqgEumzNLy",
            "type": "other",
        }
        item_2 = {
            "amount": {
                "excludingVat": "0",
                "includingVat": "0",
                "vat": "0",
                "vatRate": "0",
            },
            "amountPerUnit": "0.00000",
            "creativeId": "BPSwhEdNgMhjEoC3KBbxb6",
            "dateEndFact": "2026-08-31",
            "dateEndPlan": "2026-08-31",
            "dateStartFact": "2026-08-01",
            "dateStartPlan": "2026-08-01",
            "impsFact": 13,
            "impsPlan": 13,
            "platformId": "MbbgH4gydcfc5gf647uoFP",
            "type": "other",
        }
        payload = {"statistics": [item_1, item_2]}
        response = self.yandex_client.send_statistics(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual()
        response = self.yandex_client.get_status(response['request_id'])
        self.assertEqual(response, "ERIR sync success")
        print(response)
