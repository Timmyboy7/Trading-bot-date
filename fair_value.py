"""
Fair value — code-based price targets (added 2026-10-11).

Why: the LLM target prices proved anchored to the current price (median upside
about +4% on 2026-10-11; VLO/PSX/MRVL sat above their own targets), so they
cannot carry the "buy well, hold long" strategy. Facts are code: this endpoint
estimates fair value per share from official filings with three independent
methods and reports how well they agree.

Data
  - SEC EDGAR companyfacts (official XBRL from 10-K/10-Q filings; free, no key,
    the same User-Agent and rate limiter as signals.py): annual net income,
    operating cash flow, capex, and shares outstanding from each 10-K cover.
  - Alpaca monthly bars, RAW (not split-adjusted), ~7 years: the price on each
    10-K cover date, so historical market caps are correct across splits.
  - Optional: this week's facts from /base-score (price, TTM P/E, FCF yield,
    revenue growth), which give trailing-12-month values instead of the last
    fiscal year.
  Analyst consensus is NOT used: Yahoo blocks that endpoint from Render
  (see valuation.py, 2026-10-07).

Methods (all computed on totals, i.e. in market-cap space, then divided by
today's share count; split-safe):
  1. earnings     = profit basis x fair P/E (sector level x growth adjustment)
  2. cash_flow    = FCF basis / fair FCF yield (sector level, same growth adjustment)
  3. own_history  = profit basis x the company's own median P/E over its last
                    5 annual reports (market cap at each 10-K cover / that year's profit)
  Profit/FCF basis = trailing value; for CYCLICAL sectors the average of trailing
  and the 5-year average, so a peak year (e.g. refiners in an oil spike) is not
  capitalised as if it were permanent.
  Skips: Real Estate uses cash flow only (P/E is distorted by depreciation);
  Financials skip cash flow (FCF is not meaningful for banks/insurers);
  negative profit or FCF skips that method.

Result per symbol
  fair_value      median of the available methods (per share)
  upside_pct      fair value vs current price
  confidence      high (methods within 25% of each other), medium (within 50%),
                  low (wider, or only one method)
  methods         each method's value, so the reasoning is visible
  flags           e.g. cyclical_normalised, earnings_above_5y_avg, outlier_dropped

Endpoint
  POST /fair-value
  Body: {"base": "<base_json from /base-score>"}       (weekly pipeline), or
        {"symbols": "AAA,BBB", "sectors": {"AAA": "Energy"}}   (ad hoc / daily)
  Response: {"as_of", "results": [...], "results_json", "summary", "summary_json", "errors"}

  Fetching is best effort inside FV_BUDGET_SEC (default 30 s; Render cuts at
  ~40 s). Results are cached for 24 h, so a second call completes anything
  that was still pending (same warm-up pattern as /signals).
"""
import datetime
import json
import math
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, wait

import requests
from flask import Blueprint, jsonify, request

fair_bp = Blueprint("fair_value", __name__)

BUDGET_SEC = float(os.environ.get("FV_BUDGET_SEC", 30))
CACHE_TTL_SEC = 24 * 3600
WORKERS = 4

# Fair levels per sector. Deliberately round, reviewable numbers (the reviewer
# agent may propose changes later). P/E levels match base_score.SECTOR_TYPICAL.
SECTOR_FAIR = {
    #                          fair P/E, fair FCF yield
    "Information Technology": (30, 0.035),
    "Communication Services": (22, 0.045),
    "Health Care":            (22, 0.045),
    "Financials":             (16, None),
    "Industrials":            (24, 0.045),
    "Consumer Discretionary": (24, 0.050),
    "Consumer Staples":       (22, 0.045),
    "Energy":                 (14, 0.070),
    "Materials":              (20, 0.055),
    "Utilities":              (18, None),     # FCF usually negative (capex-heavy)
    "Real Estate":            (None, 0.055),  # cash flow only
}
DEFAULT_FAIR = (22, 0.045)
CYCLICAL = {"Energy", "Materials", "Industrials", "Consumer Discretionary"}

BASE_GROWTH = 0.05                 # growth already "priced into" the sector level
GROWTH_SLOPE = 1.5                 # +1 point growth above base -> +1.5% fair multiple
GROWTH_ADJ_RANGE = (0.8, 1.5)
OWN_PE_RANGE = (5, 60)
SANITY_RANGE = (0.4, 2.5)          # a method's value outside 0.4x-2.5x price is dropped as an outlier
HIGH_SPREAD, MEDIUM_SPREAD = 0.25, 0.50

NI_CONCEPTS = ("NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic")
OCF_CONCEPTS = ("NetCashProvidedByUsedInOperatingActivities",
                "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations")
CAPEX_CONCEPTS = ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets")


# --------------------------------------------------------------------------- small helpers

def _load(v):
    if v is None or v == "":
        return None
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("[") or s.startswith("{"):
            return json.loads(s)
        return [x.strip() for x in s.split(",") if x.strip()]
    return v


def _f(v):
    try:
        x = float(v)
        return None if math.isnan(x) or math.isinf(x) else x
    except (TypeError, ValueError):
        return None


def _date(s):
    return datetime.date.fromisoformat(str(s)[:10])


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


# --------------------------------------------------------------------------- EDGAR parsing (pure)

def annual_by_report(facts, concepts, unit="USD"):
    """[(period_end, value, accn)] — one value per 10-K: the full fiscal year that report is about."""
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    for c in concepts:
        rows = ((gaap.get(c) or {}).get("units") or {}).get(unit) or []
        best = {}
        for r in rows:
            if not str(r.get("form", "")).startswith("10-K") or not r.get("start") or not r.get("end"):
                continue
            days = (_date(r["end"]) - _date(r["start"])).days
            if not 330 <= days <= 400:
                continue
            accn = r.get("accn")
            if accn not in best or r["end"] > best[accn]["end"]:
                best[accn] = r
        if best:
            out = sorted(((_date(r["end"]), float(r["val"]), a) for a, r in best.items()), key=lambda t: t[0])
            # a restated year can appear in several reports: keep the latest report per period end
            dedup = {}
            for end, val, accn in out:
                dedup[end] = (end, val, accn)
            return [dedup[k] for k in sorted(dedup)]
    return []


def cover_shares(facts):
    """[(cover_date, shares, accn, form)] from the dei cover page of each filing (as reported, not split-restated).
    Multi-class companies (e.g. GOOGL) report this per class with a dimension, which companyfacts omits -
    extract() then falls back to diluted weighted shares."""
    rows = ((((facts.get("facts") or {}).get("dei") or {}).get("EntityCommonStockSharesOutstanding") or {})
            .get("units") or {}).get("shares") or []
    out = {}
    for r in rows:
        if r.get("end") and r.get("val"):
            k = (r["end"], r.get("accn"))
            if k not in out or float(r["val"]) > out[k][1]:
                out[k] = (_date(r["end"]), float(r["val"]), r.get("accn"), r.get("form", ""))
    return sorted(out.values(), key=lambda t: t[0])


def diluted_shares(facts):
    """[(period_end, shares, accn, form)] diluted weighted shares, as reported in each filing (current period only)."""
    rows = ((((facts.get("facts") or {}).get("us-gaap") or {}).get("WeightedAverageNumberOfDilutedSharesOutstanding") or {})
            .get("units") or {}).get("shares") or []
    best = {}
    for r in rows:
        if r.get("end") and r.get("val") and (r.get("accn") not in best or r["end"] > best[r["accn"]]["end"]):
            best[r.get("accn")] = r
    return sorted(((_date(r["end"]), float(r["val"]), a, r.get("form", "")) for a, r in best.items()), key=lambda t: t[0])


def extract(facts):
    """Everything the methods need from one companyfacts document."""
    ni = annual_by_report(facts, NI_CONCEPTS)
    ocf = {e: v for e, v, _ in annual_by_report(facts, OCF_CONCEPTS)}
    capex = {e: v for e, v, _ in annual_by_report(facts, CAPEX_CONCEPTS)}
    fcf = [(e, ocf[e] - capex.get(e, 0.0)) for e in sorted(ocf) if e in capex]
    shares = cover_shares(facts)
    shares_source = "cover"
    ni_by_accn = {a: (e, v) for e, v, a in ni}
    k_covers = [(d, s, a) for d, s, a, form in shares if str(form).startswith("10-K") and a in ni_by_accn]
    if len(k_covers) < 3 or not shares:
        # fallback: diluted weighted shares of each report, priced at that period's end
        shares = diluted_shares(facts)
        shares_source = "diluted_weighted"
        k_covers = [(d, s, a) for d, s, a, form in shares if str(form).startswith("10-K") and a in ni_by_accn]
    history = [{"cover": d, "shares": s, "fy_end": ni_by_accn[a][0], "net_income": ni_by_accn[a][1]} for d, s, a in k_covers]
    return {
        "shares_source": shares_source,
        "net_income": [(e, v) for e, v, _ in ni],
        "fcf": fcf,
        "shares_now": shares[-1][1] if shares else None,
        "shares_date": shares[-1][0] if shares else None,
        "pe_history": history,
    }


# --------------------------------------------------------------------------- valuation (pure)

def growth_adjustment(ni_series, rev_growth):
    gs = []
    if len(ni_series) >= 4 and ni_series[-4][1] > 0 and ni_series[-1][1] > 0:
        gs.append((ni_series[-1][1] / ni_series[-4][1]) ** (1 / 3) - 1)
    if rev_growth is not None:
        gs.append(rev_growth)
    g = _clamp(statistics.mean(gs), -0.05, 0.30) if gs else BASE_GROWTH
    return _clamp(1 + GROWTH_SLOPE * (g - BASE_GROWTH), *GROWTH_ADJ_RANGE), g


def own_history_pe(history, monthly_raw):
    """Median of (market cap at 10-K cover / that year's profit) over the last 5 reports."""
    pes = []
    for h in history[-5:]:
        if h["net_income"] <= 0:
            continue
        price = price_at(monthly_raw, h["cover"])
        if price is None:
            continue
        pes.append(price * h["shares"] / h["net_income"])
    if len(pes) < 3:
        return None, len(pes)
    return _clamp(statistics.median(pes), *OWN_PE_RANGE), len(pes)


def price_at(monthly, day):
    """Close of the last monthly bar on or before `day` (monthly = sorted [(date, close)])."""
    best = None
    for d, c in monthly:
        if d <= day:
            best = c
        else:
            break
    return best


def value_symbol(sym, sector, ex, price, monthly_raw, ttm_pe=None, fcf_yield=None, rev_growth=None):
    flags = []
    shares = ex.get("shares_now")
    if not price or not shares:
        return {"symbol": sym, "error": "no price or share count"}
    mcap = price * shares
    fair_pe, fair_yield = SECTOR_FAIR.get(sector, DEFAULT_FAIR)
    ni_series, fcf_series = ex["net_income"], ex["fcf"]

    # trailing values: this week's facts if given, else the last fiscal year
    ni_ttm = mcap / ttm_pe if ttm_pe and ttm_pe > 0 else (ni_series[-1][1] if ni_series else None)
    fcf_ttm = mcap * fcf_yield if fcf_yield is not None else (fcf_series[-1][1] if fcf_series else None)

    def basis(ttm, series, label):
        if ttm is None:
            return None
        last5 = [v for _, v in series[-5:]]
        if len(last5) >= 3:
            avg5 = statistics.mean(last5)
            if avg5 > 0 and ttm > 1.5 * avg5:
                flags.append(f"{label}_above_5y_avg")
            if sector in CYCLICAL:
                flags.append(f"{label}_cyclical_normalised")
                return (ttm + avg5) / 2
        return ttm

    ni_basis = basis(ni_ttm, ni_series, "earnings")
    fcf_basis = basis(fcf_ttm, fcf_series, "fcf")
    g_adj, g = growth_adjustment(ni_series, rev_growth)

    methods = {}
    if fair_pe and ni_basis and ni_basis > 0:
        methods["earnings"] = ni_basis * fair_pe * g_adj / shares
    if fair_yield and fcf_basis and fcf_basis > 0:
        methods["cash_flow"] = fcf_basis / fair_yield * g_adj / shares
    if sector != "Real Estate" and ni_basis and ni_basis > 0:
        own_pe, n = own_history_pe(ex["pe_history"], monthly_raw)
        if own_pe:
            methods["own_history"] = ni_basis * own_pe / shares

    kept = {}
    for k, v in methods.items():
        if SANITY_RANGE[0] * price <= v <= SANITY_RANGE[1] * price:
            kept[k] = v
        else:
            flags.append(f"{k}_outlier_dropped")
    if not kept:
        return {"symbol": sym, "sector": sector, "price": round(price, 2), "flags": flags,
                "methods": {k: round(v, 2) for k, v in methods.items()},
                "error": "no usable method (negative profit/FCF, missing data, or all outliers)"}

    vals = sorted(kept.values())
    fv = statistics.median(vals)
    spread = (vals[-1] - vals[0]) / fv if len(vals) > 1 else None
    if spread is None:
        conf = "low"
    elif spread <= HIGH_SPREAD:
        conf = "high"
    elif spread <= MEDIUM_SPREAD:
        conf = "medium"
    else:
        conf = "low"
    return {
        "symbol": sym, "sector": sector, "price": round(price, 2),
        "fair_value": round(fv, 2), "upside_pct": round((fv / price - 1) * 100, 1),
        "confidence": conf, "spread_pct": round(spread * 100) if spread is not None else None,
        "methods": {k: round(v, 2) for k, v in methods.items()},
        "growth_used_pct": round(g * 100, 1), "growth_adj": round(g_adj, 2),
        "flags": flags,
    }


# --------------------------------------------------------------------------- fetching

_CACHE = {}


def _cached(key, fn):
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL_SEC:
        return hit[1]
    val = fn()
    _CACHE[key] = (time.time(), val)
    return val


def _facts(sym):
    from signals import _cik_for, _get   # same SEC User-Agent + rate limiter
    cik = _cik_for(sym)
    if not cik:
        raise ValueError("no SEC CIK for symbol")
    return extract(_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json", as_json=True))


def _monthly_raw(symbols):
    """{sym: [(date, close)]} raw monthly closes for ~7 years (SIP history, IEX fallback)."""
    from screener import DATA_BASE, HEADERS
    start = (datetime.date.today() - datetime.timedelta(days=7 * 366)).isoformat()
    for feed in ("sip", "iex"):
        out, token, ok = {}, None, True
        for _ in range(30):
            params = {"symbols": ",".join(symbols), "timeframe": "1Month", "start": start,
                      "adjustment": "raw", "feed": feed, "limit": 10000}
            if token:
                params["page_token"] = token
            r = requests.get(f"{DATA_BASE}/v2/stocks/bars", headers=HEADERS, params=params, timeout=20)
            if r.status_code != 200:
                ok = False
                break
            data = r.json()
            for s, bars in (data.get("bars") or {}).items():
                out.setdefault(s, []).extend((_date(b["t"]), float(b["c"])) for b in bars)
            token = data.get("next_page_token")
            if not token:
                break
        if ok and out:
            return {s: sorted(v) for s, v in out.items()}, feed
    return {}, None


def _sector_map():
    try:
        from screener import load_constituents
        rows = load_constituents()
        return dict(rows)
    except Exception:
        return {}


def compute(items, budget=None):
    """items: [{symbol, sector?, price?, pe?, fcf_yield?, rev_growth?}]"""
    budget = BUDGET_SEC if budget is None else budget
    t0 = time.time()
    errors, results = [], []
    syms = [i["symbol"] for i in items]
    sectors = None

    monthly, feed = _cached(("monthly", ",".join(sorted(syms)), datetime.date.today().isoformat()),
                            lambda: _monthly_raw(syms))
    if not monthly:
        errors.append("no monthly price history from Alpaca (own_history method and missing prices unavailable)")

    facts, pending = {}, []
    ex = ThreadPoolExecutor(max_workers=WORKERS)
    futs = {}
    for s in syms:
        hit = _CACHE.get(("facts", s))
        if hit and time.time() - hit[0] < CACHE_TTL_SEC:
            facts[s] = hit[1]
        else:
            futs[ex.submit(_facts, s)] = s
    done, not_done = wait(futs, timeout=max(1.0, budget - (time.time() - t0)))
    for f in done:
        s = futs[f]
        try:
            facts[s] = f.result()
            _CACHE[("facts", s)] = (time.time(), facts[s])
        except Exception as e:
            errors.append(f"{s}: SEC data unavailable ({str(e)[:120]})")
    for f in not_done:
        pending.append(futs[f])

        def _store(fut, s=futs[f]):
            try:
                _CACHE[("facts", s)] = (time.time(), fut.result())
            except Exception:
                pass
        f.add_done_callback(_store)
    ex.shutdown(wait=False)

    for i in items:
        s = i["symbol"]
        if s not in facts:
            continue
        sector = i.get("sector")
        if not sector:
            sectors = sectors if sectors is not None else _sector_map()
            sector = sectors.get(s, "")
        m = monthly.get(s, [])
        price = _f(i.get("price")) or (m[-1][1] if m else None)
        try:
            results.append(value_symbol(s, sector, facts[s], price, m,
                                        ttm_pe=_f(i.get("pe")), fcf_yield=_f(i.get("fcf_yield")),
                                        rev_growth=_f(i.get("rev_growth"))))
        except Exception as e:
            errors.append(f"{s}: valuation failed ({str(e)[:120]})")

    ok = [r for r in results if "fair_value" in r]
    summary = {
        "symbols": len(syms), "valued": len(ok), "pending": pending, "price_feed": feed,
        "confidence": {c: sum(1 for r in ok if r["confidence"] == c) for c in ("high", "medium", "low")},
        "median_upside_pct": round(statistics.median([r["upside_pct"] for r in ok]), 1) if ok else None,
        "seconds": round(time.time() - t0, 1),
    }
    if pending:
        errors.append(f"{len(pending)} symbol(s) still loading from SEC - call again in ~30 s to complete")
    return {
        "as_of": datetime.date.today().isoformat(),
        "results": results, "results_json": json.dumps(results, separators=(",", ":")),
        "summary": summary, "summary_json": json.dumps(summary), "errors": errors[:40],
    }


def _items_from_body(body):
    base = _load(body.get("base"))
    if base:
        items = []
        for r in base if isinstance(base, list) else []:
            f = r.get("facts") or {}
            items.append({"symbol": str(r.get("symbol", "")).upper(), "sector": r.get("sector"),
                          "price": f.get("last_price"), "pe": f.get("pe"),
                          "fcf_yield": f.get("fcf_yield"), "rev_growth": f.get("rev_growth_yoy")})
        return [i for i in items if i["symbol"]]
    syms = _load(body.get("symbols")) or []
    sectors = _load(body.get("sectors")) or {}
    return [{"symbol": str(s).upper(), "sector": sectors.get(str(s).upper())} for s in syms if str(s).strip()]


@fair_bp.route("/fair-value", methods=["POST"])
def fair_value():
    body = request.get_json(force=True, silent=True) or {}
    try:
        items = _items_from_body(body)
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"could not parse input: {e}"}), 400
    if not items:
        return jsonify({"error": "no symbols given (send base or symbols)"}), 400
    if len(items) > 60:
        return jsonify({"error": f"{len(items)} symbols - max 60 per call"}), 400
    return jsonify(compute(items))
