"""
Round 4 (2026-10-12): hold / exit / refill rules of the live system, replayed month by month.

Input: research/backtest_round3_panel.csv (point-in-time S&P 500 members, monthly
2021-01..2026-03, 12-1 momentum, fwd_1m returns, SPY row). Prices are rebuilt by
chaining fwd_1m (plus 3/6-month back returns for the first months of a name).

Common mechanics (all variants): 20 equal slots, 12-1 rank, max 5 per sector, buy
the top 20 at the start; a slot's money stays with the slot when names change.
6-month hold: inside it a name is only sold by an exit rule. After it: dropped
when the rank falls below 24 (live: drop_rank_above 24), replaced by the best
ranked name not held. Trend exit (live rule, checked monthly here): price <= 75%
of the highest month-end since purchase AND below the ~7-month average (~150 days).
Buy-back: above the average and within 3% of the 3-month high.

Variants:
  A  current live system: after a trend exit the slot waits in cash for the
     buy-back signal (released once the name ranks below 24 / leaves the index)
  B  as A, but the trend-exited slot is refilled at once with the best name (option b)
  C  B + tax-aware sale inside the hold: rank below 35 (or out of the index) AND
     below the average AND gain <= +2% -> sold and refilled (owner's case: winner fading)
  D  cohort benchmark: buy the top 20, hold 6 months, replace all (round 2's
     "realistic 6-month rebalance")
Tax model (Luxembourg proxy): gains on positions sold within 6 months taxed at 40%,
netted per calendar year (losses offset gains); tax paid at year end out of the
portfolio. Positions held >= 6 months: tax-free. Unrealised gains at the end untaxed.

Caveats: monthly checks (the live trend exit is daily), equal slots (live: 3:1),
price-only, no costs, one AI-driven period, start months overlap.
"""
import csv
import math
import os
import statistics
import sys
from collections import defaultdict

PANEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_round3_panel.csv")
N, CAP, HOLD, DROP_RANK, TAX_RANK = 20, 5, 6, 24, 35
TREND_DD, REBUY_NEAR, TAX_RATE, TAX_GAIN_MAX = 0.25, 0.03, 0.40, 0.02


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load(path=PANEL):
    rows = list(csv.DictReader(open(path)))
    months = sorted({r["month"] for r in rows})
    idx = {m: i for i, m in enumerate(months)}
    by_m = defaultdict(dict)
    for r in rows:
        by_m[r["month"]][r["symbol"]] = r
    # price index per symbol: chain fwd_1m; seed earlier points from back returns
    price = defaultdict(dict)
    for m in months:
        i = idx[m]
        for s, r in by_m[m].items():
            if i not in price[s]:
                price[s][i] = 1.0
                for k, col in ((3, "ret_3m_back"), (6, "ret_6m_back")):
                    b = fnum(r.get(col))
                    if b is not None and b > -0.99:
                        price[s].setdefault(i - k, 1.0 / (1 + b))
            f = fnum(r.get("fwd_1m"))
            if f is not None and i + 1 not in price[s]:
                price[s][i + 1] = price[s][i] * (1 + f)
    return months, by_m, price


def sma(p, i, n=7):
    pts = [p[j] for j in range(i - n + 1, i + 1) if j in p]
    return sum(pts) / len(pts) if len(pts) >= 3 else None


def ranking(rows):
    """[(symbol, sector)] by 12-1 momentum, best first (index members only)."""
    xs = [(fnum(r["ret_12_1_back"]), s, r["sector"]) for s, r in rows.items()
          if r["sector"] != "benchmark" and fnum(r["ret_12_1_back"]) is not None]
    xs.sort(key=lambda x: -x[0])
    return [(s, sec) for _, s, sec in xs]


def simulate(months, by_m, price, start, variant, end=None, trend=True):
    end = end if end is not None else len(months) - 1
    slots = [None] * N            # {sym, sector, value, cost, buy, wait(sym)}
    taxable = defaultdict(float)  # year -> realised short-term gain
    wealth = [(start, float(N))]  # each slot starts with 1.0
    swaps = defaultdict(int)
    sells = defaultdict(int)
    cohort_next = start

    def held_secs():
        c = defaultdict(int)
        for x in slots:
            if x and x.get("sym"):
                c[x["sector"]] += 1
        return c

    for i in range(start, end):
        m = months[i]
        rows = by_m[m]
        rk = ranking(rows)
        rank_of = {s: k + 1 for k, (s, _) in enumerate(rk)}
        sector_of = dict(rk)

        def sell(j, why):
            x = slots[j]
            if x["buy"] is not None and i - x["buy"] < HOLD:
                taxable[m[:4]] += x["value"] - x["cost"]
            sells[why] += 1
            slots[j] = {"sym": None, "value": x["value"], "wait": x["sym"] if why == "trend" and variant == "A" else None}

        # 1. exits / drops on held names
        for j, x in enumerate(slots):
            if not x or not x.get("sym"):
                continue
            s, p = x["sym"], price[x["sym"]]
            if s not in rows or i not in p:
                sell(j, "left_index")
                continue
            x["high"] = max(x["high"], p[i])
            age = i - x["buy"]
            avg = sma(p, i)
            r = rank_of.get(s, 999)
            if variant == "D" and not (trend == "tax" and age < HOLD and r > TAX_RANK and avg and p[i] < avg
                                       and x["value"] / x["cost"] - 1 <= TAX_GAIN_MAX):
                continue
            if variant == "D":
                sell(j, "tax_aware")
                continue
            if trend and avg and p[i] <= x["high"] * (1 - TREND_DD) and p[i] < avg:
                sell(j, "trend")
            elif age >= HOLD and r > DROP_RANK:
                sell(j, "regular")
            elif variant == "C" and age < HOLD and r > TAX_RANK and avg and p[i] < avg \
                    and x["value"] / x["cost"] - 1 <= TAX_GAIN_MAX:
                sell(j, "tax_aware")
        if variant == "D" and i == cohort_next:
            for j, x in enumerate(slots):
                if x and x.get("sym"):
                    sell(j, "cohort")
            cohort_next = i + HOLD

        # 2. waiting slots (variant A)
        for j, x in enumerate(slots):
            if x and not x.get("sym") and x.get("wait"):
                w, p = x["wait"], price[x["wait"]]
                if w not in rows or rank_of.get(w, 999) > DROP_RANK or i not in p:
                    x["wait"] = None
                    continue
                avg = sma(p, i)
                hi3 = max(p[k] for k in range(i - 2, i + 1) if k in p)
                if avg and p[i] > avg and p[i] >= hi3 * (1 - REBUY_NEAR):
                    slots[j] = {"sym": w, "sector": sector_of[w], "value": x["value"], "cost": x["value"],
                                "buy": i, "high": p[i]}
                    swaps[i] += 1

        # 3. refill free slots with the best names not held (sector cap 5)
        held = {x["sym"] for x in slots if x and x.get("sym")} | {x["wait"] for x in slots if x and x.get("wait")}
        secs = held_secs()
        free = [j for j, x in enumerate(slots) if x is None or (not x.get("sym") and not x.get("wait"))]
        for s, sec in rk:
            if not free:
                break
            if s in held or secs[sec] >= CAP or i not in price[s] or rank_of[s] > N + 5:
                continue
            j = free.pop(0)
            v = slots[j]["value"] if slots[j] else 1.0
            slots[j] = {"sym": s, "sector": sec, "value": v, "cost": v, "buy": i, "high": price[s][i]}
            held.add(s)
            secs[sec] += 1
            if i > start:
                swaps[i] += 1

        # 4. one month of returns
        for x in slots:
            if x and x.get("sym"):
                p = price[x["sym"]]
                if i + 1 in p and i in p:
                    x["value"] *= p[i + 1] / p[i]
        # 5. tax at year end (or at the end of the run)
        if months[i + 1][:4] != m[:4] or i + 1 == end:
            due = TAX_RATE * max(taxable.get(m[:4], 0.0), 0.0)
            tot = sum(x["value"] for x in slots if x)
            if due > 0 and tot > 0:
                for x in slots:
                    if x:
                        x["value"] *= 1 - due / tot
                        if x.get("cost"):
                            x["cost"] *= 1 - due / tot
        wealth.append((i + 1, sum(x["value"] for x in slots if x)))
    return wealth, dict(sells), swaps, dict(taxable)


def spy_path(months, by_m, start, end):
    w = [1.0]
    for i in range(start, end):
        f = fnum(by_m[months[i]].get("SPY", {}).get("fwd_1m"))
        w.append(w[-1] * (1 + (f or 0.0)))
    return w


def stats(wealth, spy):
    v = [x / wealth[0][1] for _, x in wealth]
    yrs = (len(v) - 1) / 12
    cagr = v[-1] ** (1 / yrs) - 1
    spy_cagr = spy[-1] ** (1 / yrs) - 1
    peak, mdd = v[0], 0.0
    for x in v:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1)
    return cagr, spy_cagr, mdd


def main(out=sys.stdout):
    months, by_m, price = load()
    last = len(months) - 1     # fwd_1m of the last month exists -> path ends at last
    starts = list(range(6, last - 23))   # >= 2-year windows, 2021-07 .. 2024-03
    res = defaultdict(list)
    detail = {}
    for st in starts:
        spy = spy_path(months, by_m, st, last)
        for v in "ABCD":
            w, sells, swaps, tax = simulate(months, by_m, price, st, v, last)
            cagr, scagr, mdd = stats(w, spy)
            res[v].append((cagr, scagr, mdd, sells, swaps))
            if st == starts[0]:
                detail[v] = (w, sells, swaps, tax, spy)
    print(f"start months {months[starts[0]]}..{months[starts[-1]]} ({len(starts)} runs, each to {months[last]})", file=out)
    base = [r[0] for r in res["A"]]
    for v, name in (("A", "live system (cash waits for buy-back)"), ("B", "+ refill trend-exit slot"),
                    ("C", "+ tax-aware sale of fading names"), ("D", "6-month cohorts")):
        c = [r[0] for r in res[v]]
        ex = [r[0] - r[1] for r in res[v]]
        md = [r[2] for r in res[v]]
        beat = sum(1 for a, b in zip(c, base) if a > b + 1e-9) / len(c)
        sells = defaultdict(int)
        for r in res[v]:
            for k, n in r[3].items():
                sells[k] += n
        print(f"{v} {name:42s} after-tax CAGR {statistics.mean(c)*100:5.1f}%  vs SPY {statistics.mean(ex)*100:+5.1f} pts/yr"
              f"  worst drawdown avg {statistics.mean(md)*100:5.1f}% (worst {min(md)*100:5.1f}%)"
              f"  beats A in {beat:4.0%} of starts  sells/run " +
              ", ".join(f"{k} {n/len(res[v]):.1f}" for k, n in sorted(sells.items())), file=out)
    # first-run detail: clustering of swaps and taxes
    for v in "ABCD":
        w, sells, swaps, tax, spy = detail[v]
        mx = max(swaps.values()) if swaps else 0
        print(f"  {v} start {months[starts[0]]}: end wealth x{w[-1][1]/w[0][1]:.2f} (SPY x{spy[-1]:.2f}); "
              f"max swaps in one month {mx} (month {months[max(swaps, key=swaps.get)] if swaps else '-'}), "
              f"taxable short-term gains/slot by year " + ", ".join(f"{y} {g/N:+.2f}" for y, g in sorted(tax.items())), file=out)


if __name__ == "__main__":
    main()
