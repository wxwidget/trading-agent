# Frozen strategy: etf-momentum-solver-v1.0.0

## Asset pool

- 510300: CSI 300 broad-market ETF
- 159915: ChiNext broad-market ETF
- 510880: dividend-factor broad-market ETF
- 518880: gold ETF
- 159920: Hang Seng broad-market ETF
- CASH: explicit uninvested cash or a separately chosen money-market fund

The cash slot has zero modeled return. No particular money-market fund or yield is assumed.

## Signal and selection

At each monthly signal date, compute total-return momentum over 3, 6, and 12 completed months and average the three returns. An ETF qualifies only when the score is positive and its close is above its 10-month moving average. At most one of the three mainland equity ETFs may be selected; combine that winner with eligible gold or Hang Seng candidates, then retain at most two asset categories by score.

The nominal allocation cap is 50% when one category qualifies and 100% when two qualify. Unallocated weight remains cash. A constrained solver allocates among selected assets subject to nonnegative weights and annualized forecast-volatility limits of 10% on both 21- and 126-trading-day return windows. Solver failure falls back to the documented inverse-volatility allocation and records the fallback.

The operational workflow uses a 5 percentage-point ordinary rebalance threshold and a 20-trading-day waiting condition after full exit. These checks require actual account holdings and cooldown state; absent those inputs, outputs are target weights only. No broker or order interface is included.

## Research variants

Decision-tree prediction, price-volume ranking, and mean-reversion variants are disabled in production. Parameters are frozen; the workflow must not tune them automatically.

## Limits

The 10% forecast-volatility budget is not a maximum-drawdown guarantee. A long-run 10% return target and 10%-15% drawdown preference are goals, not promises. Historical simulation uses idealized fills and depends on source and corporate-action quality.
