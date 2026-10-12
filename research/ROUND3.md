# Backtest round 3 (2026-10-12): old vs new selection, early signals, base-score veto

Same setup as round 2: point-in-time S&P 500 membership, monthly formation 2021-01..2026-03 (63 dates),
20 names max 5/sector, price returns vs SPY, 611 symbols (63 without data). Run: `/backtest/start?from=2021-01&to=2026-03&early=1`
(PR #22, 45 min). Panel: `backtest_round3_panel.csv` (adds rev_growth_yoy, rev_accel, earn_reaction, earn_age_days, base_score).

## 1. Selection methods (6-month excess vs SPY)

| Variant | 6m | beat SPY | 2021-22 | 2023-24 | 2025-26 | 3m |
|---|---|---|---|---|---|---|
| Old flow (3/6m screener top 35 -> top 20 by base score) | +1.15 | 49% | -1.4 | -0.1 | +7.3 | -0.2 |
| Hybrid (12-1 top 35 -> top 20 by base score; live 2026-10-11) | +3.97 | 68% | +1.5 | +4.9 | +6.3 | +1.6 |
| New: 12-1 rank, base score < 3.0 vetoed, equal | +3.99 | 65% | +2.0 | +4.1 | +7.1 | +1.8 |
| New, 3:1 rank weights | +5.43 | 63% | +2.1 | +5.1 | +11.2 | +2.7 |
| Pure 12-1, no veto, equal (round 2) | +4.58 | 67% | +1.8 | +5.2 | +8.0 | +2.4 |

## 2. Early signals: do they catch winners before momentum? No.

| Basket | 6m |
|---|---|
| Revenue acceleration top 20 | -2.28 |
| Revenue acceleration, growing only | -2.46 |
| Earnings reaction (3 days around the latest 10-Q/10-K, vs SPY) | -1.19 |
| Top early names outside the momentum top 20 (accel / reaction) | -2.75 / -3.11 |
| 16 momentum + 4 early slots (accel / reaction) | +3.06 / +4.30 (pure momentum +4.58) |

## 3. Base-score veto threshold (12-1 top 35, <=6/sector -> top 20, <=5/sector)

| Veto below | equal 6m | 3:1 6m | worst 6m vs SPY | 3m |
|---|---|---|---|---|
| none | +4.58 | +5.77 | -16.9 | +2.44 |
| 2.0 | +4.52 | +5.72 | -16.9 | +2.42 |
| 2.5 | +4.13 | +5.32 | -19.1 | +2.16 |
| 2.75 | +4.14 | +5.43 | -19.1 | +2.08 |
| 3.0 | +3.99 | +5.43 | -19.1 | +1.83 |
| 3.25 | +4.69 | +6.31 | -19.1 | +2.20 |
| 3.5 | +4.38 | +5.92 | -19.4 | +1.85 |

- Non-monotonic: differences of +-0.6 points are well inside the noise (6m excess sd ~11-14 points, ~10 independent half-years).
- Names vetoed at 3.0 (240 of 2,079 top-35 slots): mean +1.9% vs SPY (median -3.0%); kept: +2.2% (median -1.5%). Same mean, slightly worse median.
- Base-score quintiles inside the 12-1 top 35 (low -> high): -1.0, -0.9, +4.5, +3.7, +4.4. Quality does separate among momentum names, but the swap-in from lower momentum ranks offsets it in the threshold sweep.
- The veto does not reduce the worst half-year (-16.9 without, -19.1 with).

## Conclusions
- Moving from the old flow to 12-1 was the big step (+1.2 -> +4.0..4.6). Rank weights 3:1 add ~+1.2-1.4.
- Early signals do not help: no early slots.
- The base-score veto is neutral within noise; it is a risk-appetite choice (keeps hype rallies like MRNA out), not a return enhancer.
