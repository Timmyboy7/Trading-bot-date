# Research results

Saved outputs of research runs, so later decisions (e.g. how to weight positions instead of equal weight) can build on them without re-running.

## backtest_2026-10-11 (`backtest.py`, PR #7)

Point-in-time backtest of the code signals across the S&P 500, monthly formation dates 2021-01 .. 2026-03 (63 dates), 20-name baskets (max 5 per sector, equal weight), forward 3- and 6-month price returns vs SPY.

- `backtest_2026-10-11_summary.json`: headline results, results by regime, and the five baskets formed at end of March 2026 with each stock's next-6-month return.
- `backtest_2026-10-11_per_date.jsonl`: one row per formation month, with every basket's 3m/6m return, SPY, and the information coefficients.

Headline (6-month excess vs SPY): momentum +12.7% (beat SPY 86% of dates), combo +3.2%, value_rising +0.5%, value_any −1.0%, value −1.7%.

Caveats:
- survivorship bias (today's constituents), which inflates momentum most
- price-only returns
- overlapping 6-month windows (effective t-stats about √6 lower)
- one strong momentum regime (2023–2026 AI boom)
- no costs or taxes

Not saved this time: per-stock signals and returns for every date. That dataset is needed for allocation research (signal-weighted vs equal weight, volatility-scaled sizing), so backtest round 2 should export it.
