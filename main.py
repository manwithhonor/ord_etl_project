from pathlib import Path
import logging
import yaml
from dotenv import load_dotenv
from src.handler_factory import HandlerFactory
from src.logging_config import setup_logging

logger = logging.getLogger(__name__)


def load_config(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


if __name__ == "__main__":
    app_dir = (Path(__file__).resolve().parent)
    setup_logging(app_dir / "logs", console=True)

    load_dotenv(".env", override=True)
    config = load_config("config.yaml")

    handler = HandlerFactory(config)
    handler.run()
