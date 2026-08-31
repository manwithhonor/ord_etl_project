# LiveDune -> Yandex ORD ETL

Draft ETL for monthly self-promotion statistics.

## Core idea

LiveDune post views/impressions are treated as a cumulative counter. The script stores the cumulative snapshot used for each reporting month in SQLite and sends only the difference from the prior monthly snapshot. The same `statistics_id` is deterministic for `(month, creative, platform)`.

This avoids relying on downloading historical statistics from Yandex ORD. Current public Swagger exposes POST `/statistics` but does not show a historical statistics GET/list endpoint.

## First setup

1. `python -m venv .venv`
2. Activate it and run `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env`, add tokens.
4. Export LiveDune to `data/livedune_input.xlsx` or switch `livedune.mode` to `api` after verifying your LiveDune API route/field names.
5. Copy `data/creative_mapping.example.csv` to `data/creative_mapping.csv` and map each post to Yandex ORD `creative_id` and `platform_id`.
6. If creatives existed before the first automated month, prepare `data/state_bootstrap.csv` from previous reporting. `source_cumulative` must be the cumulative number of impressions already accounted for before the new month.
7. Run safe preview: `python main.py --report-month 2026-08`.
8. Check `output/ord_statistics_preview.csv`.
9. Verify the current v8 POST `/statistics` schema. Update `yandex.statistics_payload.field_map`, set `schema_verified: true`.
10. Real send: `python main.py --report-month 2026-08 --live`.

## Important unknowns to verify

- Exact current LiveDune endpoint and response field containing post views for your social network/account.
- Exact current Yandex ORD v8 statistics payload, especially VAT fields.
- Whether your ORD statistics endpoint needs the client-created `creative_id` or can accept only a token/erid. Older API examples use `creativeId`.
- A stable mapping LiveDune post -> ORD creative + ORD platform.

## Tests

`pytest -q`
