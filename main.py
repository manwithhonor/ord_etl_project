from pathlib import Path
import yaml
from dotenv import load_dotenv
from src.handler_factory import HandlerFactory


def load_config(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


if __name__ == "__main__":
    load_dotenv(".env", override=True)
    config = load_config("config.yaml")

    handler = HandlerFactory(config)
    handler.run()
