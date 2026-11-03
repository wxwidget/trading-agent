# trading-agent

ETF momentum allocation research and monthly planning tools.

This repository contains the versioned strategy implementation used for monthly ETF target-weight calculations. It does not connect to a brokerage or place orders. Outputs are model targets, not evidence of account holdings or fills.

## Strategy

- Universe: 510300, 159915, 510880, 518880, 159920 and an explicit cash slot.
- Monthly cross-sectional momentum from trailing 3, 6 and 12 month total returns.
- Eligibility requires positive momentum and price above the 10-month moving average.
- Selects at most one mainland equity ETF and at most two asset categories.
- Portfolio forecast volatility constrained to 10% on both 21 and 126 trading-day windows.
- Nominal allocation caps: 50% for one eligible category, 100% for two; residual allocation stays in cash.
- Frozen production strategy: `etf-momentum-solver-v1.0.0`. Decision-tree and mean-reversion research variants are disabled.

A volatility forecast budget is not a guarantee of maximum drawdown. Historical results do not promise future returns.

## Run

See `docs/strategy.md` and `docs/data-contract.md`. Python dependencies are in `requirements.txt`.

The published repository intentionally excludes private sheet and Drive identifiers, live run logs, account information and the private dated price snapshot. Supply destination settings locally through your own adapter.
