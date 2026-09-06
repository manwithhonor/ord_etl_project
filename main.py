from __future__ import annotations
from datetime import datetime
# import argparse
# import logging
from pathlib import Path
import pandas as pd
import yaml
from dotenv import load_dotenv
from nest_asyncio import apply
from plotly.graph_objs.indicator.gauge import axis
from src.yandex_client import YandexClient

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

    def calculate_date_start(pub_date):
        pub = pd.to_datetime(pub_date)
        now = pd.to_datetime("2026-08-31")
        # now = datetime.now()
        current_month_start = datetime(now.year, now.month, 1)

        # Если месяц публикации = текущий месяц
        if pub.year == now.year and pub.month == now.month:
            return pub.strftime('%Y-%m-%d')
        else:
            return current_month_start.strftime('%Y-%m-%d')

    platform_dict = {"ВК" : "c2dEzzKA3ZjtSewXRvQ5Ao",
                     "МАХ": "qG9XK9A9nxLdrqgEumzNLy",
                     "Телеграм": "MbbgH4gydcfc5gf647uoFP"}

    df = pd.read_excel("data/data_in.xlsx")
    print("Преобразуем данные")

    df['creativeId'] = df["creativeId"].str.replace("c-FV0R-", "")
    df['platformId'] = df["platform"].apply(lambda x: platform_dict[x])
    df.drop("platform", axis=1, inplace=True)
    df['amountPerUnit'] = "0.00000"
    df['type'] = "other"
    df['dateStartFact'] =  df['dateStartFact'].apply(calculate_date_start)
    df['dateStartPlan'] = df['dateStartFact']
    df['dateEndFact'] = "2026-08-31"
    df['dateEndPlan'] = "2026-08-31"
    df['impsPlan'] = df['impsFact']

    datetime_cols = ['dateStartFact', 'dateStartPlan', 'dateEndFact', 'dateEndPlan']
    for col in datetime_cols:
        df[col] = pd.to_datetime(df[col]) # 1. Конвертируем в datetime
        df[col] = df[col].dt.strftime('%Y-%m-%d') # 2. Конвертируем обратно в строку в нужном формате

    records = df.to_dict('records')

    for row in records:
        row['amount'] = {
            "excludingVat": "0",
            "includingVat": "0",
            "vat": "0",
            "vatRate": "0",
        }

    yandex_client = YandexClient(config["yandex"])
    payload = {"statistics": records}
    response = yandex_client.send_statistics(payload)
    response = yandex_client.get_status(response.json()['request_id'])
    print(response)

if __name__ == "__main__":
    main()
