"""
Point-in-time backtest of the CODE signals: momentum (today's screener logic) and
fair value (fair_value.py), across the S&P 500, monthly 2021-01 .. 2026-03.
(added 2026-10-11)

Why: before fair value feeds selection, check on history whether the signals
predicted anything, and which combination worked. LLM judgments are NOT
backtested: today's models were trained on data up to mid-2026 and partly
"know" what happened, so any LLM backtest would be contaminated. The LLMs are
tested going forward by the prediction ledger instead.

Point-in-time rules (no look-ahead):
  - fair value at month-end T uses only SEC facts FILED before the first day of
    the following month, and the raw month-end price at T
  - momentum uses split-adjusted month-end closes up to T (3- and 6-month
    returns, z-scored within sector, 50/50 - the screener's momentum leg)
  - forward returns: split-adjusted closes T -> T+3 and T -> T+6 months (price only)

Baskets per date (20 names, max 5 per sector, equal weight):
  momentum       top momentum score
  value          top relative fair-value upside, confidence high/medium
  value_any      top relative upside, any confidence
  combo          average of momentum and value percentile ranks
  value_rising   top relative upside among names with momentum above their sector average
Plus the information coefficient (rank correlation of each signal with the next
6-month return across ALL names) per date.

Round 2 (2026-10-11): point-in-time S&P 500 membership (research/sp500_membership_monthly.csv,
from the fja05680/sp500 dataset) - a stock is only eligible while it was in the index,
which removes most of the survivorship bias of round 1. Extra baskets: momentum_guard
(momentum without names >40% overvalued vs the others at high/medium confidence),
momentum_12_1 (academic 12-month-minus-last-month momentum), momentum_nocap (no sector
cap), equal_all_members (all members equal weight, the "dumb" benchmark). A per-stock
panel (signals, volatility, forward returns) is kept for /backtest/export.csv.

Remaining biases: former members without SEC/Alpaca data drop out, sector unknown for
former members ("Unknown"), price-only returns (no dividends, also for SPY), overlapping
6-month windows (statistics look more certain than they are), no costs or taxes.

Endpoints (GET, so they can be opened in a browser):
  /backtest/start[?from=2021-01&to=2026-03]   starts the background job (~15-20 min)
  /backtest/status                            progress, and the results when done
  /backtest/export.csv                        per-stock panel of the last finished run
  ?membership=current on /backtest/start      round-1 behaviour (today's constituents)
Results are also written to the app log, lines starting with BACKTEST_RESULT.
"""
import datetime
import gc
import json
import math
import os
import statistics
import threading
import time
import traceback

import requests
from flask import Blueprint, jsonify, request

import fair_value as fv
import sec_fundamentals as secf
import base_score as bscore

backtest_bp = Blueprint("backtest", __name__)

BASKET_SIZE = 20
MAX_PER_SECTOR = 5
KEEP = {"start", "end", "val", "form", "accn", "filed", "fp"}
GAAP_NEEDED = set(("RevenuesNetOfInterestExpense",) + fv.NI_CONCEPTS + fv.OCF_CONCEPTS + fv.CAPEX_CONCEPTS + fv.REVENUE_CONCEPTS + fv.OPINC_CONCEPTS
                  + ("WeightedAverageNumberOfDilutedSharesOutstanding", "CommonStockSharesOutstanding"))

STATE = {"status": "idle"}
_LOCK = threading.Lock()


def _log(kind, payload):
    print(f"BACKTEST_{kind} " + json.dumps(payload, separators=(",", ":")), flush=True)


# --------------------------------------------------------------------------- months

def _months(a, b):
    y, m = map(int, a.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= b:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _shift(month, k):
    y, m = map(int, month.split("-"))
    m += k
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def _month_start_after(month):
    return _shift(month, 1) + "-01"


# --------------------------------------------------------------------------- data

def monthly_closes(symbols, adjustment, start="2015-06-01"):
    """{sym: {"YYYY-MM": close}} month-end closes (Alpaca monthly bars; SIP history, IEX fallback)."""
    from screener import DATA_BASE, HEADERS
    out = {}
    for i in range(0, len(symbols), 100):
        batch = symbols[i:i + 100]
        for feed in ("sip", "iex"):
            token, ok, got = None, True, {}
            for _ in range(60):
                params = {"symbols": ",".join(batch), "timeframe": "1Month", "start": start,
                          "adjustment": adjustment, "feed": feed, "limit": 10000}
                if token:
                    params["page_token"] = token
                r = requests.get(f"{DATA_BASE}/v2/stocks/bars", headers=HEADERS, params=params, timeout=30)
                if r.status_code != 200:
                    ok = False
                    break
                data = r.json()
                for s, bars in (data.get("bars") or {}).items():
                    d = got.setdefault(s, {})
                    for b in bars:
                        d[str(b["t"])[:7]] = float(b["c"])
                token = data.get("next_page_token")
                if not token:
                    break
            if ok and got:
                out.update(got)
                break
    return out


def daily_closes(symbol, start="2020-06-01"):
    """[(YYYY-MM-DD, close)] split-adjusted daily closes for one symbol (SIP, IEX fallback)."""
    from screener import DATA_BASE, HEADERS
    for feed in ("sip", "iex"):
        out, token = [], None
        for _ in range(10):
            params = {"symbols": symbol, "timeframe": "1Day", "start": start, "adjustment": "split",
                      "feed": feed, "limit": 10000}
            if token:
                params["page_token"] = token
            try:
                r = requests.get(f"{DATA_BASE}/v2/stocks/bars", headers=HEADERS, params=params, timeout=30)
            except requests.RequestException:
                break
            if r.status_code != 200:
                break
            data = r.json()
            out += [(str(b["t"])[:10], float(b["c"])) for b in (data.get("bars") or {}).get(symbol, [])]
            token = data.get("next_page_token")
            if not token:
                break
        if out:
            return sorted(out)
    return []


def earnings_reactions(filing_dates, daily, spy_daily, after=3):
    """{filed: reaction} = stock return from the last close BEFORE the filing day to `after`
    trading days later, minus SPY over the same days (the market's verdict on the report)."""
    import bisect
    days = [d for d, _ in daily]
    px = dict(daily)
    spy = dict(spy_daily)
    out = {}
    for f in filing_dates:
        i = bisect.bisect_left(days, f) - 1
        if i < 0 or i + after >= len(days):
            continue
        d0, d1 = days[i], days[i + after]
        if d0 in spy and d1 in spy and px[d0] and spy[d0]:
            out[f] = (px[d1] / px[d0] - 1) - (spy[d1] / spy[d0] - 1)
    return out


def early_metrics(pit_facts, cutoff, reactions):
    """(rev_growth_yoy, rev_accel, earn_reaction, earn_age_days) known at `cutoff`.
    rev_accel = YoY growth of the latest quarter minus YoY growth of the quarter before."""
    q = secf.quarterly(pit_facts, secf.REVENUE_TAGS, n=12)
    cut = datetime.date.fromisoformat(cutoff)
    g0 = g1 = None
    if q and (cut - q[-1][0]).days <= 200:
        vals, ends = [v for _, v in q], [e for e, _ in q]
        g0 = secf._yoy_dated(vals, ends)
        if len(vals) > 1:
            g1 = secf._yoy_dated(vals[:-1], ends[:-1])
    accel = (g0 - g1) if g0 is not None and g1 is not None else None
    past = [f for f in reactions if f < cutoff]
    react = age = None
    if past:
        f = max(past)
        age = (cut - datetime.date.fromisoformat(f)).days
        if age <= 95:
            react = reactions[f]
    return g0, accel, react, age


def base_score_at(sym, sector, pitf, cutoff, price, adj, m):
    """The live base-score rubric (base_score.score_symbol) on point-in-time SEC data and
    month-end prices: what the old selection would have scored at formation date m."""
    summ, _ = secf.summarize(pitf, today=datetime.date.fromisoformat(cutoff))
    f = secf.build(summ, price) if summ else {}
    closes = [adj.get(_shift(m, -k)) for k in range(12, -1, -1)]
    p = {"ret_3m": ret_back({sym: adj}, sym, m, 3), "ret_6m": ret_back({sym: adj}, sym, m, 6)}
    known = [c for c in closes if c]
    if closes[-1] and known:
        p["drawdown_from_52w_high"] = closes[-1] / max(known) - 1
    last7 = [c for c in closes[-7:] if c]
    if len(last7) == 7:
        mr = [last7[i + 1] / last7[i] - 1 for i in range(6)]
        p["volatility_63d"] = statistics.pstdev(mr) * math.sqrt(12)   # monthly proxy for the daily 63-day vol
    pillars, _, _ = bscore.score_symbol(sym, sector, f or {}, p)
    return sum(bscore.WEIGHTS[k] * pillars[k] for k in bscore.WEIGHTS)


def reduce_facts(facts):
    """Keep only the concepts/fields fair value needs (10-K/10-Q rows), to keep memory small."""
    f = facts.get("facts") or {}
    gaap = {}
    for c, body in (f.get("us-gaap") or {}).items():
        if c not in GAAP_NEEDED:
            continue
        units = {}
        for u, rows in (body.get("units") or {}).items():
            kept = [{k: r[k] for k in KEEP if k in r} for r in rows
                    if str(r.get("form", "")).startswith(("10-K", "10-Q")) and r.get("filed")]
            if kept:
                units[u] = kept
        if units:
            gaap[c] = {"units": units}
    dei = {}
    body = (f.get("dei") or {}).get("EntityCommonStockSharesOutstanding")
    if body:
        rows = [{k: r[k] for k in KEEP if k in r} for r in (body.get("units") or {}).get("shares", []) if r.get("filed")]
        if rows:
            dei["EntityCommonStockSharesOutstanding"] = {"units": {"shares": rows}}
    return {"us-gaap": gaap, "dei": dei}


def point_in_time(red, cutoff):
    """companyfacts-shaped dict with only the facts filed before `cutoff` (YYYY-MM-DD)."""
    out = {}
    for tax, concepts in red.items():
        d = {}
        for c, body in concepts.items():
            units = {u: [r for r in rows if r["filed"] < cutoff] for u, rows in body["units"].items()}
            units = {u: rows for u, rows in units.items() if rows}
            if units:
                d[c] = {"units": units}
        out[tax] = d
    return {"facts": out}


# --------------------------------------------------------------------------- stats helpers

def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2.0
        i = j + 1
    return r


def spearman(a, b):
    if len(a) < 20:
        return None
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = statistics.mean(ra), statistics.mean(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return cov / (va * vb) if va and vb else None


def pick(cands, key, sector_of, n=BASKET_SIZE):
    """Top n by key (descending) with at most MAX_PER_SECTOR per sector."""
    out, per = [], {}
    for s in sorted(cands, key=key, reverse=True):
        sec = sector_of.get(s, "")
        if per.get(sec, 0) >= MAX_PER_SECTOR:
            continue
        out.append(s)
        per[sec] = per.get(sec, 0) + 1
        if len(out) == n:
            break
    return out


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def _tstat(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 3:
        return None
    sd = statistics.stdev(xs)
    return statistics.mean(xs) / (sd / math.sqrt(len(xs))) if sd else None


# --------------------------------------------------------------------------- job

def _keepalive(stop):
    url = os.environ.get("RENDER_EXTERNAL_URL")
    while url and not stop.is_set():
        try:
            requests.get(url + "/", timeout=10)
        except requests.RequestException:
            pass
        stop.wait(240)


MEMBERSHIP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research", "sp500_membership_monthly.csv")
GUARD_REL_UPSIDE = -40.0      # momentum_guard: drop names this overvalued vs the others (high/medium confidence)


def load_membership():
    """{"YYYY-MM": set(tickers)} point-in-time S&P 500 members at each month-end (fja05680/sp500 dataset)."""
    import csv
    with open(MEMBERSHIP_FILE, newline="") as f:
        return {r["month"]: set(r["tickers"].split(",")) for r in csv.DictReader(f)}


def run(month_from, month_to, pit=True, early=False):
    from screener import load_constituents
    from signals import _cik_for, _get

    stop = threading.Event()
    threading.Thread(target=_keepalive, args=(stop,), daemon=True).start()
    try:
        t0 = time.time()
        sector_of = dict(load_constituents())
        months = _months(month_from, month_to)
        if pit:
            membership = load_membership()
            members_at = {m: membership.get(m, set()) for m in months}
            universe = sorted(set().union(*members_at.values()))
        else:
            universe = sorted(sector_of)
            members_at = {m: set(universe) for m in months}
        for s in universe:
            sector_of.setdefault(s, "Unknown")      # former members: sector not in today's list
        STATE.update(status="loading prices", universe=len(universe), months=len(months), point_in_time=pit)
        adj = monthly_closes(universe + ["SPY"], "split")
        raw = monthly_closes(universe, "raw")
        raw_lists = {s: sorted((datetime.date.fromisoformat(m + "-01"), c) for m, c in d.items()) for s, d in raw.items()}
        _log("PROGRESS", {"step": "prices", "universe": len(universe), "adj": len(adj), "raw": len(raw),
                          "sec": round(time.time() - t0), "point_in_time": pit})

        # fair value per (month, symbol): (upside_pct, confidence) - only while the stock is a member
        fvres = {m: {} for m in months}
        # early signals per (month, symbol): (rev_growth_yoy, rev_accel, earn_reaction, earn_age_days)
        earlyres = {m: {} for m in months}
        bsres = {m: {} for m in months}      # base score per (month, symbol) - old selection
        spy_daily = daily_closes("SPY") if early else []
        failed = []
        for i, s in enumerate(universe):
            STATE.update(status="fair value", done=i, of=len(universe), elapsed_min=round((time.time() - t0) / 60, 1))
            member_months = [m for m in months if s in members_at[m]]
            try:
                cik = _cik_for(s)
                if not cik or s not in raw or not member_months:
                    failed.append(s)
                    continue
                red = reduce_facts(_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json", as_json=True))
                gc.collect()
                reactions = {}
                if early:
                    filed = sorted({r["filed"] for c in red["us-gaap"].values() for rows in c["units"].values()
                                    for r in rows if str(r.get("form", "")).startswith(("10-Q", "10-K"))
                                    and r["filed"] >= "2020-06-01"})
                    reactions = earnings_reactions(filed, daily_closes(s), spy_daily)
                for m in member_months:
                    pitf = point_in_time(red, _month_start_after(m))
                    if early:
                        earlyres[m][s] = early_metrics(pitf, _month_start_after(m), reactions)
                    price = raw[s].get(m)
                    if not price:
                        continue
                    if early and s in adj:
                        try:
                            bsres[m][s] = base_score_at(s, sector_of[s], pitf, _month_start_after(m), price, adj[s], m)
                        except Exception:
                            pass
                    ex = fv.extract(pitf)
                    if not ex.get("shares_now"):
                        continue
                    upto = [x for x in raw_lists[s] if x[0] <= datetime.date.fromisoformat(m + "-01")]
                    r = fv.value_symbol(s, sector_of[s], ex, price, upto)
                    if r.get("status") == "ok":
                        fvres[m][s] = (r["upside_pct"], r["confidence"])
                del red
            except Exception as e:
                failed.append(s)
                if len(failed) <= 15:
                    _log("WARN", {"symbol": s, "error": str(e)[:160]})
            if i % 50 == 0:
                _log("PROGRESS", {"step": "fair value", "done": i, "of": len(universe), "min": round((time.time() - t0) / 60, 1)})

        STATE.update(status="computing")
        per_date, detail, panel = [], None, []
        for m in months:
            def ret(s, k):
                a, b = adj.get(s, {}).get(m), adj.get(s, {}).get(_shift(m, k))
                return (b / a - 1) if a and b else None

            members = [s for s in members_at[m] if s in adj]

            # momentum score: within-sector z-scores of the 3m and 6m returns up to T, 50/50 (screener logic),
            # computed among the members at T only
            mom, by_sec, r3m, r6m, r12_1, vol = {}, {}, {}, {}, {}, {}
            for s in members:
                r3, r6 = ret_back(adj, s, m, 3), ret_back(adj, s, m, 6)
                a, b = adj[s].get(_shift(m, -12)), adj[s].get(_shift(m, -1))
                r12_1[s] = (b / a - 1) if a and b else None
                rets = [adj[s].get(_shift(m, -k)) for k in range(12, -1, -1)]
                if all(rets):
                    mr = [rets[j + 1] / rets[j] - 1 for j in range(12)]
                    vol[s] = statistics.pstdev(mr) * math.sqrt(12)
                if r3 is not None and r6 is not None:
                    r3m[s], r6m[s] = r3, r6
                    by_sec.setdefault(sector_of[s], []).append((s, r3, r6))
            for sec, rows in by_sec.items():
                if len(rows) < 3:
                    continue
                for idx in (1, 2):
                    xs = [r[idx] for r in rows]
                    mu, sd = statistics.mean(xs), statistics.pstdev(xs) or 1.0
                    for r in rows:
                        mom[r[0]] = mom.get(r[0], 0.0) + 0.5 * (r[idx] - mu) / sd

            vals = {s: v for s, v in fvres[m].items() if s in members_at[m]}
            med = statistics.median([u for u, _ in vals.values()]) if vals else 0.0
            rel = {s: u - med for s, (u, c) in vals.items()}
            conf_ok = {s for s, (u, c) in vals.items() if c in ("high", "medium")}
            mom12 = {s: v for s, v in r12_1.items() if v is not None}

            mom_pct = dict(zip(mom, [x / max(len(mom) - 1, 1) for x in _ranks(list(mom.values()))])) if mom else {}
            val_pct = dict(zip(rel, [x / max(len(rel) - 1, 1) for x in _ranks(list(rel.values()))])) if rel else {}
            overvalued = {s for s in rel if s in conf_ok and rel[s] < GUARD_REL_UPSIDE}

            em = earlyres.get(m, {})
            accel = {s: v[1] for s, v in em.items() if v[1] is not None and s in adj}
            react = {s: v[2] for s, v in em.items() if v[2] is not None and s in adj}
            mom_top = set(pick(list(mom12), lambda s: mom12[s], sector_of))

            def early_slots(sig, n_early=4):
                """16 momentum names + the n_early strongest early-signal names NOT already in the momentum top 20"""
                core = pick(list(mom12), lambda s: mom12[s], sector_of, BASKET_SIZE - n_early)
                extra = [s for s in sorted(sig, key=lambda s: sig[s], reverse=True) if s not in mom_top][:n_early]
                return core + extra

            baskets = {
                "momentum": pick(list(mom), lambda s: mom[s], sector_of),
                "momentum_guard": pick([s for s in mom if s not in overvalued], lambda s: mom[s], sector_of),
                "momentum_12_1": pick(list(mom12), lambda s: mom12[s], sector_of),
                "momentum_nocap": sorted(mom, key=lambda s: mom[s], reverse=True)[:BASKET_SIZE],
                "value": pick([s for s in rel if s in conf_ok], lambda s: rel[s], sector_of),
                "value_any": pick(list(rel), lambda s: rel[s], sector_of),
                "combo": pick([s for s in rel if s in mom_pct], lambda s: (mom_pct[s] + val_pct[s]) / 2, sector_of),
                "value_rising": pick([s for s in rel if mom.get(s, -1) > 0], lambda s: rel[s], sector_of),
                "equal_all_members": members,
            }
            if early:
                bs = {x: v for x, v in bsres.get(m, {}).items() if x in adj}

                def screen35(score):
                    out, per = [], {}
                    for x in sorted(score, key=lambda x: score[x], reverse=True):
                        if per.get(sector_of[x], 0) >= 6:
                            continue
                        out.append(x)
                        per[sector_of[x]] = per.get(sector_of[x], 0) + 1
                        if len(out) == 35:
                            break
                    return out
                old35 = screen35(mom)        # old screener: 3m/6m within-sector z, top 35, <=6/sector
                new35 = screen35(mom12)      # live screener since 2026-10-11: 12-1
                vetoed = {x for x, v in bs.items() if v < 3.0}
                baskets.update({
                    # the three ways of picking 20, head to head
                    "old_flow_basescore": pick([x for x in old35 if x in bs], lambda x: bs[x], sector_of),
                    "hybrid_12_1_basescore": pick([x for x in new35 if x in bs], lambda x: bs[x], sector_of),
                    "new_momentum_veto": pick([x for x in new35 if x not in vetoed], lambda x: mom12[x], sector_of),
                    "rev_accel": pick(list(accel), lambda s: accel[s], sector_of),
                    "rev_accel_growing": pick([s for s in accel if (em[s][0] or 0) > 0], lambda s: accel[s], sector_of),
                    "earn_reaction": pick(list(react), lambda s: react[s], sector_of),
                    "mom16_accel4": early_slots(accel),
                    "mom16_react4": early_slots(react),
                    "early_not_in_mom_accel": [s for s in sorted(accel, key=lambda s: accel[s], reverse=True)
                                               if s not in mom_top][:20],
                    "early_not_in_mom_react": [s for s in sorted(react, key=lambda s: react[s], reverse=True)
                                               if s not in mom_top][:20],
                })
            row = {"month": m, "n_members": len(members_at[m]), "n_priced": len(members), "n_valued": len(vals),
                   "n_mom": len(mom), "spy_3m": ret("SPY", 3), "spy_6m": ret("SPY", 6)}
            for name, b in baskets.items():
                row[name + "_3m"] = _mean([ret(s, 3) for s in b])
                row[name + "_6m"] = _mean([ret(s, 6) for s in b])
            if early and baskets.get("new_momentum_veto"):
                # the live weighting: strongest 3x the weakest
                b = baskets["new_momentum_veto"]
                w = [1 + 2 * (len(b) - 1 - i) / max(len(b) - 1, 1) for i in range(len(b))]
                for h in (3, 6):
                    pr = [(wi, ret(s, h)) for wi, s in zip(w, b) if ret(s, h) is not None]
                    row[f"new_momentum_veto_w31_{h}m"] = (sum(a * r for a, r in pr) / sum(a for a, _ in pr)) if pr else None
            fwd6 = {s: ret(s, 6) for s in members}
            pv = [(rel[s], fwd6[s]) for s in rel if fwd6.get(s) is not None]
            pm = [(mom[s], fwd6[s]) for s in mom if fwd6.get(s) is not None]
            p12 = [(mom12[s], fwd6[s]) for s in mom12 if fwd6.get(s) is not None]
            row["ic_value_6m"] = spearman([a for a, _ in pv], [b for _, b in pv])
            row["ic_mom_6m"] = spearman([a for a, _ in pm], [b for _, b in pm])
            row["ic_mom12_6m"] = spearman([a for a, _ in p12], [b for _, b in p12])
            if early:
                pb = [(bs[s], fwd6[s]) for s in bs if fwd6.get(s) is not None]
                row["ic_basescore_6m"] = spearman([a for a, _ in pb], [b for _, b in pb])
                pa = [(accel[s], fwd6[s]) for s in accel if fwd6.get(s) is not None]
                pr = [(react[s], fwd6[s]) for s in react if fwd6.get(s) is not None]
                row["ic_accel_6m"] = spearman([a for a, _ in pa], [b for _, b in pa])
                row["ic_react_6m"] = spearman([a for a, _ in pr], [b for _, b in pr])
            per_date.append(row)

            # per-stock panel for later research (weighting, other baskets) - members only
            for s in members:
                u = vals.get(s)
                panel.append([m, s, sector_of[s], _r(mom.get(s), 3), _r(r3m.get(s), 4), _r(r6m.get(s), 4),
                              _r(r12_1.get(s), 4), _r(vol.get(s), 4), _r(rel.get(s), 1), _r(u[0] if u else None, 1),
                              u[1] if u else "", _r(ret(s, 1), 4), _r(ret(s, 3), 4), _r(ret(s, 6), 4)]
                             + ([_r(x, 4) for x in em.get(s, (None, None, None))[:3]] + [em[s][3] if s in em and em[s][3] is not None else ""]
                                + [_r(bsres[m].get(s), 3)] if early else []))
            panel.append([m, "SPY", "benchmark", "", "", "", "", "", "", "", "", _r(ret("SPY", 1), 4),
                          _r(ret("SPY", 3), 4), _r(ret("SPY", 6), 4)] + (["", "", "", "", ""] if early else []))

            if m == month_to:
                detail = {name: [{"symbol": s, "sector": sector_of[s],
                                  "rel_upside": round(rel[s], 1) if s in rel else None,
                                  "confidence": vals[s][1] if s in vals else None,
                                  "momentum": round(mom[s], 2) if s in mom else None,
                                  "ret_6m_pct": round(ret(s, 6) * 100, 1) if ret(s, 6) is not None else None}
                                 for s in b] for name, b in baskets.items() if name != "equal_all_members"}
                detail["spy_6m_pct"] = round(ret("SPY", 6) * 100, 1) if ret("SPY", 6) is not None else None

        names = [k[:-3] for k in per_date[0] if k.endswith("_6m") and not k.startswith(("spy", "ic_"))]
        summary = summarise(per_date, names)
        result = {"summary": summary, "per_date": per_date, "latest_baskets": detail, "point_in_time": pit,
                  "universe": len(universe), "failed_symbols": len(failed), "minutes": round((time.time() - t0) / 60, 1)}
        STATE.update(status="done", result=result, panel=panel, early=early)
        _log("RESULT", {"summary": summary, "failed": len(failed), "universe": len(universe),
                        "point_in_time": pit, "minutes": result["minutes"], "panel_rows": len(panel)})
        for name, rows in (detail or {}).items():
            _log("RESULT_BASKET", {"basket": name, "rows": rows})
        for row in per_date:
            _log("RESULT_DATE", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items()})
    except Exception as e:
        STATE.update(status="error", error=str(e), trace=traceback.format_exc()[-1500:])
        _log("ERROR", {"error": str(e), "trace": traceback.format_exc()[-800:]})
    finally:
        # keep the free Render instance awake for another hour so the results and the
        # /backtest/export.csv panel can still be fetched before it sleeps and forgets them
        threading.Timer(3600, stop.set).start()


def _r(x, n):
    return "" if x is None else round(x, n)


PANEL_COLUMNS = ["month", "symbol", "sector", "momentum_score", "ret_3m_back", "ret_6m_back", "ret_12_1_back",
                 "vol_12m", "rel_upside_pct", "upside_pct", "fv_confidence", "fwd_1m", "fwd_3m", "fwd_6m"]


EARLY_COLUMNS = ["rev_growth_yoy", "rev_accel", "earn_reaction", "earn_age_days", "base_score"]


def ret_back(adj, s, m, k):
    """P(T)/P(T-k) - 1 from split-adjusted month-end closes."""
    a, b = adj.get(s, {}).get(_shift(m, -k)), adj.get(s, {}).get(m)
    return (b / a - 1) if a and b else None


def summarise(per_date, names=None):
    names = names or ["momentum", "value", "value_any", "combo", "value_rising"]
    out = {}
    for h in ("3m", "6m"):
        block = {}
        for n in names:
            ex = [(r[f"{n}_{h}"] - r[f"spy_{h}"]) for r in per_date
                  if r.get(f"{n}_{h}") is not None and r.get(f"spy_{h}") is not None]
            block[n] = {
                "dates": len(ex),
                "avg_excess_vs_spy_pct": round(_mean(ex) * 100, 2) if ex else None,
                "beat_spy_share": round(sum(1 for x in ex if x > 0) / len(ex), 2) if ex else None,
                "t_stat_overlapping": round(_tstat(ex), 2) if _tstat(ex) is not None else None,
            }
        out[h] = block
    out["ic_6m"] = {}
    for key, label in (("ic_value_6m", "value"), ("ic_mom_6m", "momentum"), ("ic_mom12_6m", "momentum_12_1")):
        xs = [r[key] for r in per_date if r.get(key) is not None]
        if xs:
            out["ic_6m"][label + "_mean"] = round(_mean(xs), 3)
            out["ic_6m"][label + "_positive_share"] = round(sum(1 for x in xs if x > 0) / len(xs), 2)
    # by regime
    regimes = {"2021-2022": ("2021-01", "2022-12"), "2023-2024": ("2023-01", "2024-12"), "2025-2026": ("2025-01", "2026-12")}
    reg = {}
    for label, (a, b) in regimes.items():
        rows = [r for r in per_date if a <= r["month"] <= b]
        reg[label] = {n: (round(_mean([r[f"{n}_6m"] - r["spy_6m"] for r in rows
                                       if r.get(f"{n}_6m") is not None and r.get("spy_6m") is not None]) * 100, 2)
                          if any(r.get(f"{n}_6m") is not None for r in rows) else None) for n in names}
    out["by_regime_6m_excess_pct"] = reg
    return out


@backtest_bp.route("/backtest/start", methods=["GET", "POST"])
def backtest_start():
    a = request.args.get("from", "2021-01")
    b = request.args.get("to", "2026-03")
    pit = request.args.get("membership", "pit") != "current"
    early = request.args.get("early") in ("1", "true")
    with _LOCK:
        if STATE.get("status") not in ("idle", "done", "error"):
            return jsonify({"message": "already running", "state": {k: v for k, v in STATE.items() if k != "result"}})
        STATE.clear()
        STATE.update(status="starting", started=datetime.datetime.utcnow().isoformat(timespec="seconds"), range=[a, b])
        threading.Thread(target=run, args=(a, b, pit, early), daemon=True).start()
    return jsonify({"message": "started - check /backtest/status in ~20-25 minutes", "range": [a, b],
                    "membership": "point-in-time" if pit else "current constituents",
                    "early_signals": early})


@backtest_bp.route("/backtest/status", methods=["GET"])
def backtest_status():
    full = request.args.get("full") in ("1", "true")
    st = {k: v for k, v in STATE.items() if k not in ("result", "panel")}
    if STATE.get("status") == "done":
        res = STATE["result"]
        st["result"] = res if full else {k: v for k, v in res.items() if k != "per_date"}
    return jsonify(st)


@backtest_bp.route("/backtest/export.csv", methods=["GET"])
def backtest_export():
    """Per-stock panel of the last finished run (one row per member and month) as CSV, for offline research."""
    import csv
    import io
    from flask import Response
    panel = STATE.get("panel")
    if not panel:
        return jsonify({"error": "no finished run in memory - start one with /backtest/start"}), 404
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(PANEL_COLUMNS + (EARLY_COLUMNS if STATE.get("early") else []))
    w.writerows(panel)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=backtest_panel.csv"})
