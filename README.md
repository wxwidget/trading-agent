# trading-agent

Version-controlled ETF momentum allocation research and monthly target-planning code.

The code implements `etf-momentum-solver-v1.0.0` for 510300, 159915, 510880, 518880, 159920 and an explicit cash slot. It uses mean 3/6/12-month total-return momentum, a positive-score and 10-month moving-average gate, at most two asset categories, nominal caps of 50%/100%, and 10% forecast-volatility limits at 21 and 126 trading days. Decision-tree, mean-reversion, and price-volume research variants are disabled.

See [strategy](docs/strategy.md), [data contract](docs/data-contract.md), and [Sheets adapter contract](docs/google-sheets-append.md). Install dependencies with `pip install -r requirements.txt`. The dated seed data is intentionally excluded; see `assets/seed/README.md`.

This repository does not place orders or contain account information. A volatility forecast limit does not guarantee a maximum drawdown or target return.
