# Backtest round 4: hold, exit and refill rules (2026-10-12)

Script: `research/round4_hold_rules.py` (runs locally in seconds on `backtest_round3_panel.csv`).
It replays the live system month by month on point-in-time S&P 500 members: 33 start months
(2021-07 .. 2024-03), each run to 2026-03; 20 equal slots, 12-1 rank, max 5 per sector, 6-month
hold, after-tax (gains on sales inside 6 months taxed at 40%, netted per year; later sales tax-free).

| Variant | after-tax CAGR | vs SPY (pts/yr) | worst drawdown | beats live in |
|---|---|---|---|---|
| A live system (trend exit, slot waits in cash for buy-back) | 17.9% | +4.2 | −25.4% | – |
| A without trend exit | 19.0% | +5.3 | −22.7% | 64% |
| B = A + refill trend-exit slot at once | 18.2% | +4.5 | −25.0% | 64% |
| **C = B + tax-aware sale of fading names** | **21.1%** | **+7.4** | **−22.1%** | **79%** |
| C without trend exit | 19.0% | +5.3 | −22.3% | 64% |
| D 6-month cohorts (buy top 20, replace all after 6 months) | 19.9% | +6.2 | −24.8% | 64% |
| D + tax-aware sale | 21.1% | +7.4 | −22.1% | 76% |

Tax-aware sale (C): inside the hold, sell when the name ranks below 35 (or left the index), is
below its ~7-month average and the gain is at most +2%. By start year (pts/yr vs SPY, C vs A):
2021 +9.3 vs +6.4; 2022 +5.1 vs +1.9; 2023 +9.0 vs +4.7; 2024 +5.9 vs +7.1 (only 3 short
2-year windows) - better in 3 of 4. Thresholds were set before the test; sensitivity (rank 25/30/35/50 x gain 0/2/5/10%):
+5.0 to +7.7 pts/yr, all above A (+4.2) and B (+4.5). Realistic expectation: +1 to +3 pts/yr.
Why it works: it sells losers early (no tax, losses even offset gains) and refreshes the slot
with a current leader - momentum's own logic - while winners keep the tax protection.

Trend exit: mixed (hurts in A, helps in C) - roughly neutral in this sample, which had a bear
market (2022) but no bubble burst. Kept as crash insurance (dot-com case study), as decided.
Caveat: checked monthly here; live it runs daily, which changes its behaviour.

Overlapping cohorts: not needed. In the continuous system names past the hold only leave when
their rank falls below 24, so the first expiry month had 15 of 20 swaps in A but only 8 in C.

Caveats: one AI-driven period, monthly checks, equal slots (live 3:1), price only, no trading
costs (C trades about once more per month), start months overlap.

Decision proposed: implement C (refill after trend exit + tax-aware sale) in the live system.
