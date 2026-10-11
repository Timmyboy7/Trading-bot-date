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

Known biases: today's constituent list (survivorship), price-only returns (no
dividends, also for SPY), overlapping 6-month windows (statistics look more
certain than they are), no costs or taxes.

Endpoints (GET, so they can be opened in a browser):
  /backtest/start[?from=2021-01&to=2026-03]   starts the background job (~15-20 min)
  /backtest/status                            progress, and the results when done
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

backtest_bp = Blueprint("backtest", __name__)

BASKET_SIZE = 20
MAX_PER_SECTOR = 5
KEEP = {"start", "end", "val", "form", "accn", "filed", "fp"}
GAAP_NEEDED = set(fv.NI_CONCEPTS + fv.OCF_CONCEPTS + fv.CAPEX_CONCEPTS + fv.REVENUE_CONCEPTS + fv.OPINC_CONCEPTS
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


def run(month_from, month_to):
    from screener import load_constituents
    from signals import _cik_for, _get

    stop = threading.Event()
    threading.Thread(target=_keepalive, args=(stop,), daemon=True).start()
    try:
        t0 = time.time()
        sector_of = dict(load_constituents())
        universe = sorted(sector_of)
        months = _months(month_from, month_to)
        STATE.update(status="loading prices", universe=len(universe), months=len(months))
        adj = monthly_closes(universe + ["SPY"], "split")
        raw = monthly_closes(universe, "raw")
        raw_lists = {s: sorted((datetime.date.fromisoformat(m + "-01"), c) for m, c in d.items()) for s, d in raw.items()}
        _log("PROGRESS", {"step": "prices", "adj": len(adj), "raw": len(raw), "sec": round(time.time() - t0)})

        # fair value per (month, symbol): (upside_pct, confidence)
        fvres = {m: {} for m in months}
        failed = []
        for i, s in enumerate(universe):
            STATE.update(status="fair value", done=i, of=len(universe), elapsed_min=round((time.time() - t0) / 60, 1))
            try:
                cik = _cik_for(s)
                if not cik or s not in raw:
                    failed.append(s)
                    continue
                red = reduce_facts(_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json", as_json=True))
                gc.collect()
                for m in months:
                    price = raw[s].get(m)
                    if not price:
                        continue
                    ex = fv.extract(point_in_time(red, _month_start_after(m)))
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
        per_date, detail = [], None
        for m in months:
            def ret(s, k):
                a, b = adj.get(s, {}).get(m), adj.get(s, {}).get(_shift(m, k))
                return (b / a - 1) if a and b else None

            # momentum score: within-sector z-scores of the 3m and 6m returns up to T, 50/50 (screener logic)
            mom, by_sec = {}, {}
            for s in universe:
                r3, r6 = ret_back(adj, s, m, 3), ret_back(adj, s, m, 6)
                if r3 is not None and r6 is not None:
                    by_sec.setdefault(sector_of[s], []).append((s, r3, r6))
            for sec, rows in by_sec.items():
                if len(rows) < 3:
                    continue
                for idx in (1, 2):
                    xs = [r[idx] for r in rows]
                    mu, sd = statistics.mean(xs), statistics.pstdev(xs) or 1.0
                    for r in rows:
                        mom[r[0]] = mom.get(r[0], 0.0) + 0.5 * (r[idx] - mu) / sd

            vals = fvres[m]
            med = statistics.median([u for u, _ in vals.values()]) if vals else 0.0
            rel = {s: u - med for s, (u, c) in vals.items()}
            conf_ok = {s for s, (u, c) in vals.items() if c in ("high", "medium")}

            mom_pct = dict(zip(mom, [x / max(len(mom) - 1, 1) for x in _ranks(list(mom.values()))])) if mom else {}
            val_pct = dict(zip(rel, [x / max(len(rel) - 1, 1) for x in _ranks(list(rel.values()))])) if rel else {}

            baskets = {
                "momentum": pick(list(mom), lambda s: mom[s], sector_of),
                "value": pick([s for s in rel if s in conf_ok], lambda s: rel[s], sector_of),
                "value_any": pick(list(rel), lambda s: rel[s], sector_of),
                "combo": pick([s for s in rel if s in mom_pct], lambda s: (mom_pct[s] + val_pct[s]) / 2, sector_of),
                "value_rising": pick([s for s in rel if mom.get(s, -1) > 0], lambda s: rel[s], sector_of),
            }
            row = {"month": m, "n_valued": len(vals), "n_mom": len(mom),
                   "spy_3m": ret("SPY", 3), "spy_6m": ret("SPY", 6)}
            for name, b in baskets.items():
                row[name + "_3m"] = _mean([ret(s, 3) for s in b])
                row[name + "_6m"] = _mean([ret(s, 6) for s in b])
            fwd6 = {s: ret(s, 6) for s in universe}
            pv = [(rel[s], fwd6[s]) for s in rel if fwd6.get(s) is not None]
            pm = [(mom[s], fwd6[s]) for s in mom if fwd6.get(s) is not None]
            row["ic_value_6m"] = spearman([a for a, _ in pv], [b for _, b in pv])
            row["ic_mom_6m"] = spearman([a for a, _ in pm], [b for _, b in pm])
            per_date.append(row)
            if m == month_to:
                detail = {name: [{"symbol": s, "sector": sector_of[s],
                                  "rel_upside": round(rel[s], 1) if s in rel else None,
                                  "confidence": vals[s][1] if s in vals else None,
                                  "momentum": round(mom[s], 2) if s in mom else None,
                                  "ret_6m_pct": round(ret(s, 6) * 100, 1) if ret(s, 6) is not None else None}
                                 for s in b] for name, b in baskets.items()}
                detail["spy_6m_pct"] = round(ret("SPY", 6) * 100, 1) if ret("SPY", 6) is not None else None

        summary = summarise(per_date)
        result = {"summary": summary, "per_date": per_date, "latest_baskets": detail,
                  "failed_symbols": len(failed), "minutes": round((time.time() - t0) / 60, 1)}
        STATE.update(status="done", result=result)
        _log("RESULT", {"summary": summary, "failed": len(failed), "minutes": result["minutes"]})
        for name, rows in (detail or {}).items():
            _log("RESULT_BASKET", {"basket": name, "rows": rows})
        for row in per_date:
            _log("RESULT_DATE", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items()})
    except Exception as e:
        STATE.update(status="error", error=str(e), trace=traceback.format_exc()[-1500:])
        _log("ERROR", {"error": str(e), "trace": traceback.format_exc()[-800:]})
    finally:
        stop.set()


def ret_back(adj, s, m, k):
    """P(T)/P(T-k) - 1 from split-adjusted month-end closes."""
    a, b = adj.get(s, {}).get(_shift(m, -k)), adj.get(s, {}).get(m)
    return (b / a - 1) if a and b else None


def summarise(per_date):
    names = ["momentum", "value", "value_any", "combo", "value_rising"]
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
    ics_v = [r["ic_value_6m"] for r in per_date if r.get("ic_value_6m") is not None]
    ics_m = [r["ic_mom_6m"] for r in per_date if r.get("ic_mom_6m") is not None]
    out["ic_6m"] = {"value_mean": round(_mean(ics_v), 3) if ics_v else None,
                    "value_positive_share": round(sum(1 for x in ics_v if x > 0) / len(ics_v), 2) if ics_v else None,
                    "momentum_mean": round(_mean(ics_m), 3) if ics_m else None,
                    "momentum_positive_share": round(sum(1 for x in ics_m if x > 0) / len(ics_m), 2) if ics_m else None}
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
    with _LOCK:
        if STATE.get("status") not in ("idle", "done", "error"):
            return jsonify({"message": "already running", "state": {k: v for k, v in STATE.items() if k != "result"}})
        STATE.clear()
        STATE.update(status="starting", started=datetime.datetime.utcnow().isoformat(timespec="seconds"), range=[a, b])
        threading.Thread(target=run, args=(a, b), daemon=True).start()
    return jsonify({"message": "started - check /backtest/status in ~15-20 minutes", "range": [a, b]})


@backtest_bp.route("/backtest/status", methods=["GET"])
def backtest_status():
    full = request.args.get("full") in ("1", "true")
    st = {k: v for k, v in STATE.items() if k != "result"}
    if STATE.get("status") == "done":
        res = STATE["result"]
        st["result"] = res if full else {k: v for k, v in res.items() if k != "per_date"}
    return jsonify(st)
