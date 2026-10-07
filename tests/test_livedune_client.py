from src.livedune_client import LiveDuneClient
from unittest import TestCase
from dotenv import load_dotenv
import yaml


class TestLiveDuneClient(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open('config.yaml', 'r') as file:
            config = yaml.safe_load(file)
        load_dotenv(".env", override=True)
        cls.config = config
        cls.yandex_client = LiveDuneClient(config["livedune"])