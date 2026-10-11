# Backtest round 2 (2026-10-11): point-in-time membership

Same method as round 1 (`backtest.py`), but a stock is only eligible while it was actually in the S&P 500 (`sp500_membership_monthly.csv`). 611 companies were members 2021-01..2026-03; 64 of them had no SEC or price data. Monthly formation dates, 20-name baskets (max 5 per sector), forward returns vs SPY. Price only, no costs or taxes.

Files:
- `backtest_round2_summary.json`: all headline numbers below
- `backtest_round2_panel.csv`: one row per member and month (31,535 rows): signals (momentum score, 3/6/12-1 month returns, 12m volatility, fair-value upside and confidence) and forward 1/3/6-month returns, plus SPY rows
- `analyze_panel.py`: reproduces the analysis from the panel (`python3 -I analyze_panel.py`)

## Main results (6-month excess vs SPY, average of 63 overlapping windows)

| Basket | Round 1 (today's members) | Round 2 (point-in-time) | Beat SPY |
|---|---|---|---|
| 12-1 momentum | n/a | **+4.6%** | 67% |
| momentum + value guard | n/a | +2.7% | 54% |
| momentum (screener 3/6m) | +12.7% | +2.6% | 54% |
| combo | +3.2% | −0.9% | 46% |
| all members, equal weight | n/a | −2.4% | 27% |
| value | −1.7% | −3.3% | 27% |

- Survivorship bias inflated round 1 by about 10 points.
- 12-1 momentum is the only signal that was positive in all three regimes: 2021–22 +1.8, 2023–24 +5.2, 2025–26 +8.0.
- The value guard and the sector cap made no material difference.

## Allocation (12-1 momentum)

- The edge sits in the top: quintiles 1–4 all lag SPY by about 3%; the top quintile beats it slightly; the top 20 by +4.6% and the top 10 by +8.0%.
- Weighting the top 20 by rank +6.7%, by signal × inverse volatility +5.5%, equal +4.6%, by inverse volatility +3.1%. Excluding the most volatile 20% of stocks removed the edge (+0.3%).
- Realistic simulation (rebalance every 6 months, compounded, averaged over the 6 possible start months): top 20 equal 21.7%/yr vs SPY 12.6%/yr; positive for every start month (+6.7 to +13.0 points/yr). Equal weight of all members: 7.8%/yr.
- Risk per 6 months: top 20 equal sd 13.9% vs SPY 9.3%, worst −18.6% (SPY −20.9%), worst vs SPY −16.9 points. Top 10 sd 21.1%, worst vs SPY −20.7 points.

Caveats:
- one AI-driven period
- about 10 independent 6-month periods only
- 64 former members without data (probably mostly losers)
- no costs or taxes
- the edge in this period came largely from volatile winners
