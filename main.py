from __future__ import annotations

# import argparse
# import logging
from pathlib import Path

import yaml
from dotenv import load_dotenv
# from urllib3.contrib.emscripten import response


# from src.handler_factory import HandlerFactory


def load_config(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def main() -> None:
    # parser = argparse.ArgumentParser(description="LiveDune -> Yandex ORD ETL")
    # parser.add_argument("--config", default="config.yaml")
    # parser.add_argument("--report-month", help="Override YYYY-MM from config")
    # parser.add_argument("--live", action="store_true", help="Actually POST to Yandex ORD")
    # parser.add_argument("--force-recalculate", action="store_true")
    # args = parser.parse_args()

    load_dotenv(".env", override=True)

    # config = load_config(args.config)
    config = load_config("config.yaml")
    # if args.report_month:
    #     config["app"]["report_month"] = args.report_month
    # if args.live:
    #     config["app"]["dry_run"] = False
    # if args.force_recalculate:
    #     config["app"]["force_recalculate"] = True

    # logging.basicConfig(
    #     level=getattr(logging, config["app"].get("log_level", "INFO").upper()),
    #     format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    # )

    # handler = HandlerFactory.create(config)
    # result = handler.run()
    # print(result.to_string(index=False) if not result.empty else "No rows to report")



if __name__ == "__main__":
    main()
