# Data contract

## Required local seed files

`assets/seed/` must contain compressed CSVs for `open`, `close`, `div`, `tradable`, and `volume`. Rows are trading dates; columns are the five ETF codes in `scripts/core.py`. The public repository omits the dated seed snapshot.

## Refresh and validation

`python scripts/run.py --signal-date YYYY-MM-DD --out PATH` reads the local seed, refreshes Sina/AKShare market data and checks for the requested date, positive prices and volume, and price agreement with the seed over the overlapping history. Shanghai funds are cross-checked against Tencent additive-adjusted data to identify distributions. New Shenzhen distributions or any split/adjustment anomaly require verified corporate-action data or must block publication.

The command emits a target plan and an audit. It does not determine the exchange month-end or execution date, perform macro/sector/company research, know the user's holdings, or write to Google Sheets. Those belong to the surrounding workflow and must be checked independently. A run against a date already contained in the seed is a historical replay, not a fresh market-data update.

Do not treat a successful calculation as proof of current data, completed review, actual holdings, or executed trades.
