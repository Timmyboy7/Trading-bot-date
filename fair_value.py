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
  - Trailing 12 months are computed from the latest 10-Q (last fiscal year +
    year-to-date - same period a year earlier). This week's facts from
    /base-score (TTM P/E, FCF yield, revenue growth) take precedence when given.
  Analyst consensus is NOT used: Yahoo blocks that endpoint from Render
  (see valuation.py, 2026-10-07).

One-off gains: net profit is capped at after-tax operating profit (+20%) per
year and for the trailing 12 months, so e.g. Alphabet's investment gains do not
inflate its value (flag one_off_gains_capped). Financials are untouched.

Methods (all computed on totals, i.e. in market-cap space, then divided by
today's share count; split-safe):
  1. earnings     = profit basis x fair P/E (sector level x growth adjustment)
  2. cash_flow    = FCF basis / fair FCF yield (sector level, same growth adjustment)
  3. own_history  = profit basis x the company's own median P/E over its last
                    5 annual reports (market cap at each 10-K cover / that year's profit)
  Profit/FCF basis = trailing value; for CYCLICAL sectors the average of trailing
  and the median of the profitable years among the last 5 (loss years such as
  COVID are skipped), so a peak year (e.g. refiners in an oil spike) is not
  capitalised as if it were permanent. Fewer than 3 profitable years: trailing
  value, flagged short_profit_history.
  Skips: Real Estate uses cash flow only (P/E is distorted by depreciation);
  Financials skip cash flow (FCF is not meaningful for banks/insurers);
  negative profit or FCF skips that method.

Result per symbol
  fair_value      median of the available methods (per share)
  upside_pct      fair value vs current price (absolute; long-run sector levels)
  relative_upside_pct  upside minus the median upside of all names valued in the same call
                  (cheap vs the others; use THIS for selection - absolute upside mostly
                  says whether the whole market is expensive)
  status          ok | not_valuable (e.g. GAAP profit depressed by acquisition write-offs)
                  | no_data
  confidence      high (methods within 25% of each other), medium (within 50%),
                  low (wider, or only one method)
  methods         each method's value, so the reasoning is visible
  flags           e.g. cyclical_normalised, earnings_above_5y_avg, outlier_dropped

Endpoint
  GET  /fair-value?symbols=AAA,BBB   (quick check in a browser; add &debug=1 to see the raw filing figures)
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
REVENUE_CONCEPTS = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
                    "RevenueFromContractWithCustomerIncludingAssessedTax")
OPINC_CONCEPTS = ("OperatingIncomeLoss",)
TAX_RATE = 0.21                    # used only to turn operating profit into an after-tax ceiling for net profit
ONE_OFF_TOLERANCE = 1.20           # net profit may exceed after-tax operating profit by 20% (low-tax firms, interest income)
MIN_PROFIT_YEARS = 3               # profitable years (of the last 5) needed to define "normal" profit


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

def _rows(facts, concept, unit="USD"):
    return ((((facts.get("facts") or {}).get("us-gaap") or {}).get(concept) or {}).get("units") or {}).get(unit) or []


def _days(r):
    return (_date(r["end"]) - _date(r["start"])).days


def annual_by_report(facts, concepts, unit="USD", used=None):
    """[(period_end, value, accn)] - one value per 10-K: the full fiscal year that report is about.
    Merged across the alternative concept names (companies switch XBRL tags over the years);
    earlier names in `concepts` win for the same period. `used` (a set) collects the names found."""
    merged = {}
    for c in reversed(concepts):            # later names first, so earlier names overwrite them
        best = {}
        for r in _rows(facts, c, unit):
            if not str(r.get("form", "")).startswith("10-K") or not r.get("start") or not r.get("end"):
                continue
            if not 330 <= _days(r) <= 400:
                continue
            accn = r.get("accn")
            if accn not in best or r["end"] > best[accn]["end"]:
                best[accn] = r
        if best and used is not None:
            used.add(c)
        # a restated year can appear in several reports: the latest report per period end wins
        for a, r in sorted(best.items(), key=lambda kv: kv[1].get("filed", "")):
            merged[_date(r["end"])] = (_date(r["end"]), float(r["val"]), a)
    return [merged[k] for k in sorted(merged)]


def trailing_12m(facts, concepts, annual):
    """(ttm_value, ytd_growth, as_of) from the latest 10-Q: last fiscal year + year-to-date - same period a year
    earlier (both YTD figures are in the same 10-Q). Falls back to the last fiscal year when the latest report
    is a 10-K or the quarter data does not line up."""
    fy_end, fy_val = (annual[-1][0], annual[-1][1]) if annual else (None, None)
    for c in concepts:
        q = [r for r in _rows(facts, c) if str(r.get("form", "")).startswith("10-Q") and r.get("start") and r.get("end")]
        if not q:
            continue
        latest_accn = max(q, key=lambda r: (r["end"], r.get("filed", "")))["accn"]
        rows = [r for r in q if r["accn"] == latest_accn and 80 <= _days(r) <= 300]
        if not rows:
            continue
        ytd = max(rows, key=lambda r: (r["end"], _days(r)))
        if fy_end is not None and (_date(ytd["end"]) <= fy_end or abs((_date(ytd["start"]) - fy_end).days - 1) > 10):
            continue
        target = _date(ytd["end"]) - datetime.timedelta(days=365)
        prior = [r for r in rows if abs((_date(r["end"]) - target).days) <= 10 and abs(_days(r) - _days(ytd)) <= 10]
        if not prior and fy_val is not None:
            continue
        if not prior:
            prior = [{"val": 0}]   # growth unknown, value still usable for annualising
        cur, prev = float(ytd["val"]), float(prior[0]["val"])
        growth = (cur / prev - 1) if prev > 0 else None
        if fy_val is None:
            # no annual report under this registration (e.g. XOM after a reorganisation): annualise the
            # year-to-date figure. Rough (ignores seasonality), so callers mark the result low confidence.
            return cur * 365.0 / max(_days(ytd), 1), growth, ytd["end"] + " (annualised YTD)"
        return fy_val + cur - prev, growth, ytd["end"]
    return fy_val, None, (fy_end.isoformat() if fy_end else None)


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


def balance_sheet_shares(facts):
    """[(date, shares)] us-gaap CommonStockSharesOutstanding (instant), last resort for today's share count."""
    rows = ((((facts.get("facts") or {}).get("us-gaap") or {}).get("CommonStockSharesOutstanding") or {})
            .get("units") or {}).get("shares") or []
    out = {}
    for r in rows:
        if r.get("end") and r.get("val"):
            out[r["end"]] = (_date(r["end"]), float(r["val"]))
    return [out[k] for k in sorted(out)]


def extract(facts):
    """Everything the methods need from one companyfacts document."""
    used = set()
    ni = annual_by_report(facts, NI_CONCEPTS, used=used)
    ocf_a = annual_by_report(facts, OCF_CONCEPTS, used=used)
    capex_a = annual_by_report(facts, CAPEX_CONCEPTS, used=used)
    rev_a = annual_by_report(facts, REVENUE_CONCEPTS, used=used)
    op_a = annual_by_report(facts, OPINC_CONCEPTS, used=used)
    ocf = {e: v for e, v, _ in ocf_a}
    capex = {e: v for e, v, _ in capex_a}
    fcf = [(e, ocf[e] - capex.get(e, 0.0)) for e in sorted(ocf) if e in capex]
    revenue = [(e, v) for e, v, _ in rev_a]

    ni_ttm, _, ttm_as_of = trailing_12m(facts, NI_CONCEPTS, ni)
    ocf_ttm, _, _ = trailing_12m(facts, OCF_CONCEPTS, ocf_a)
    capex_ttm, _, _ = trailing_12m(facts, CAPEX_CONCEPTS, capex_a)
    rev_ttm, rev_ytd_growth, _ = trailing_12m(facts, REVENUE_CONCEPTS, rev_a)
    op_ttm, _, _ = trailing_12m(facts, OPINC_CONCEPTS, op_a)

    # one-off gains (e.g. investment gains at Alphabet) inflate GAAP net profit: cap each year's net profit
    # at after-tax operating profit (+20%). Banks/insurers have no operating-income line, so they are untouched.
    op_by_end = {e: v for e, v, _ in op_a}
    capped_years = 0
    ni_capped = []
    for e, v, a in ni:
        op = op_by_end.get(e)
        if op is not None and op > 0 and v > op * (1 - TAX_RATE) * ONE_OFF_TOLERANCE:
            v = op * (1 - TAX_RATE) * ONE_OFF_TOLERANCE
            capped_years += 1
        ni_capped.append((e, v, a))
    ni = ni_capped
    ni_ttm_capped = False
    if ni_ttm is not None and op_ttm is not None and op_ttm > 0 and ni_ttm > op_ttm * (1 - TAX_RATE) * ONE_OFF_TOLERANCE:
        ni_ttm, ni_ttm_capped = op_ttm * (1 - TAX_RATE) * ONE_OFF_TOLERANCE, True

    # small raw sample of how profit is tagged, for debugging companies that do not parse (debug=1)
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    raw_sample = {}
    for c in ("NetIncomeLoss", "ProfitLoss", "Revenues"):
        rows = ((gaap.get(c) or {}).get("units") or {}).get("USD") or []
        if rows:
            forms = {}
            for r in rows:
                forms[r.get("form", "?")] = forms.get(r.get("form", "?"), 0) + 1
            raw_sample[c] = {"forms": forms, "last": [{k: r.get(k) for k in ("form", "fp", "fy", "start", "end", "val")}
                                                     for r in sorted(rows, key=lambda r: r.get("end", ""))[-4:]]}
    fcf_ttm = (ocf_ttm - capex_ttm) if ocf_ttm is not None and capex_ttm is not None else None
    covers, diluted, balance = cover_shares(facts), diluted_shares(facts), balance_sheet_shares(facts)
    ni_by_accn = {a: (e, v) for e, v, a in ni}

    # today's share count: the most recent of the three sources (each is as reported, so current)
    latest = [(x[0], x[1], src) for src, lst in (("cover", covers), ("diluted_weighted", diluted),
                                                  ("balance_sheet", balance)) if lst for x in lst[-1:]]
    now_date, now_shares, now_src = max(latest, key=lambda t: t[0]) if latest else (None, None, None)

    # history for the own-P/E method: cover shares if they cover >= 3 reports, else diluted weighted shares
    k_covers = [(d, s, a) for d, s, a, form in covers if str(form).startswith("10-K") and a in ni_by_accn]
    hist_src = "cover"
    if len(k_covers) < 3:
        k_covers = [(d, s, a) for d, s, a, form in diluted if str(form).startswith("10-K") and a in ni_by_accn]
        hist_src = "diluted_weighted"
    history = [{"cover": d, "shares": s, "fy_end": ni_by_accn[a][0], "net_income": ni_by_accn[a][1]} for d, s, a in k_covers]
    return {
        "shares_source": now_src, "history_shares_source": hist_src,
        "net_income": [(e, v) for e, v, _ in ni],
        "fcf": fcf,
        "revenue": revenue,
        "ni_ttm": ni_ttm, "fcf_ttm": fcf_ttm, "rev_ttm": rev_ttm, "rev_ytd_growth": rev_ytd_growth,
        "ttm_as_of": ttm_as_of, "concepts_found": sorted(used),
        "op_ttm": op_ttm, "ni_capped_years": capped_years, "ni_ttm_capped": ni_ttm_capped,
        "raw_sample": raw_sample, "units_found": sorted(set(u for c in gaap.values() for u in (c.get("units") or {})))[:10],
        "shares_now": now_shares,
        "shares_date": now_date,
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
        return {"symbol": sym, "sector": sector, "status": "no_data",
                "error": "no price" if not price else "no share count in SEC filings"}
    rev = ex.get("revenue") or []
    if rev_growth is None and ex.get("rev_ytd_growth") is not None:
        rev_growth = ex["rev_ytd_growth"]               # this year to date vs same period last year (10-Q)
        flags.append("revenue_growth_ytd_from_filings")
    elif rev_growth is None and len(rev) >= 2 and rev[-2][1] > 0:
        rev_growth = rev[-1][1] / rev[-2][1] - 1      # last fiscal year
        flags.append("revenue_growth_fy_from_filings")
    mcap = price * shares
    fair_pe, fair_yield = SECTOR_FAIR.get(sector, DEFAULT_FAIR)
    ni_series, fcf_series = ex["net_income"], ex["fcf"]

    # trailing 12 months: this week's facts if given, else computed from the 10-Q filings, else last fiscal year
    if ttm_pe and ttm_pe > 0:
        ni_ttm = mcap / ttm_pe
        op = ex.get("op_ttm")
        if op is not None and op > 0 and ni_ttm > op * (1 - TAX_RATE) * ONE_OFF_TOLERANCE:
            ni_ttm = op * (1 - TAX_RATE) * ONE_OFF_TOLERANCE
            flags.append("one_off_gains_capped")
    else:
        ni_ttm = ex.get("ni_ttm") if ex.get("ni_ttm") is not None else (ni_series[-1][1] if ni_series else None)
    if fcf_yield is not None:
        fcf_ttm = mcap * fcf_yield
    else:
        fcf_ttm = ex.get("fcf_ttm") if ex.get("fcf_ttm") is not None else (fcf_series[-1][1] if fcf_series else None)
    if ex.get("ni_ttm_capped") or ex.get("ni_capped_years"):
        flags.append("one_off_gains_capped")
    if not ni_series and not fcf_series and ni_ttm is None:
        return {"symbol": sym, "sector": sector, "price": round(price, 2), "status": "no_data",
                "error": "no profit or cash-flow data found under the expected XBRL names",
                "concepts_found": ex.get("concepts_found")}

    def basis(ttm, series, label):
        """Trailing value; for cyclicals blended 50/50 with the median of the PROFITABLE years among the
        last 5 (loss years such as COVID are skipped, so they cannot drag 'normal' profit toward zero)."""
        if ttm is None:
            return None
        positive = [v for _, v in series[-5:] if v > 0]
        if len(positive) < MIN_PROFIT_YEARS:
            if sector in CYCLICAL:
                flags.append(f"{label}_short_profit_history")
            return ttm
        normal = statistics.median(positive)
        if ttm > 1.5 * normal:
            flags.append(f"{label}_above_normal")
        if sector in CYCLICAL:
            flags.append(f"{label}_cyclical_normalised")
            return (ttm + normal) / 2
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
        why = ("profit and cash flow are far below what the price implies (e.g. GAAP profit depressed by "
               "acquisition write-offs, or a turnaround) - this method cannot value it" if methods
               else "negative profit and cash flow - no earnings-based value")
        return {"symbol": sym, "sector": sector, "price": round(price, 2), "status": "not_valuable",
                "flags": flags, "methods": {k: round(v, 2) for k, v in methods.items()}, "error": why}

    annualised = "annualised" in str(ex.get("ttm_as_of") or "")
    if annualised:
        flags.append("annualised_ytd_no_annual_reports")
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
    if annualised:
        conf = "low"
    return {
        "symbol": sym, "sector": sector, "price": round(price, 2), "status": "ok",
        "fair_value": round(fv, 2), "upside_pct": round((fv / price - 1) * 100, 1),
        "confidence": conf, "spread_pct": round(spread * 100) if spread is not None else None,
        "methods": {k: round(v, 2) for k, v in methods.items()},
        "growth_used_pct": round(g * 100, 1), "growth_adj": round(g_adj, 2),
        "ttm_as_of": ex.get("ttm_as_of"),
        "flags": list(dict.fromkeys(flags)),
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


def _debug_view(ex):
    def tail(series, n=6):
        return [[str(e), round(v / 1e6, 1)] for e, v in series[-n:]]
    return {
        "concepts_found": ex.get("concepts_found"), "shares_source": ex.get("shares_source"),
        "shares_now_m": round(ex["shares_now"] / 1e6, 1) if ex.get("shares_now") else None,
        "net_income_fy_musd": tail(ex.get("net_income", [])), "fcf_fy_musd": tail(ex.get("fcf", [])),
        "revenue_fy_musd": tail(ex.get("revenue", [])),
        "ni_ttm_musd": round(ex["ni_ttm"] / 1e6, 1) if ex.get("ni_ttm") is not None else None,
        "fcf_ttm_musd": round(ex["fcf_ttm"] / 1e6, 1) if ex.get("fcf_ttm") is not None else None,
        "rev_ytd_growth": ex.get("rev_ytd_growth"), "ttm_as_of": ex.get("ttm_as_of"),
        "pe_history_points": len(ex.get("pe_history", [])),
        "op_ttm_musd": round(ex["op_ttm"] / 1e6, 1) if ex.get("op_ttm") is not None else None,
        "ni_capped_years": ex.get("ni_capped_years"), "ni_ttm_capped": ex.get("ni_ttm_capped"),
        "raw_sample": ex.get("raw_sample"), "units_found": ex.get("units_found"),
    }


def compute(items, budget=None, debug=False):
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
            res = value_symbol(s, sector, facts[s], price, m,
                               ttm_pe=_f(i.get("pe")), fcf_yield=_f(i.get("fcf_yield")),
                               rev_growth=_f(i.get("rev_growth")))
            if debug:
                res["debug"] = _debug_view(facts[s])
            results.append(res)
        except Exception as e:
            errors.append(f"{s}: valuation failed ({str(e)[:120]})")

    ok = [r for r in results if r.get("status") == "ok"]
    # Relative upside: vs the median of everything valued in this call. The sector "fair" levels are long-run
    # averages, so in an expensive market nearly everything shows negative absolute upside; for PICKING stocks
    # what matters is cheap vs the others. Absolute upside stays visible (market-level question for Macro).
    med = statistics.median([r["upside_pct"] for r in ok]) if ok else None
    for r in ok:
        r["relative_upside_pct"] = round(r["upside_pct"] - med, 1) if len(ok) >= 8 else None
    summary = {
        "symbols": len(syms), "valued": len(ok), "pending": pending, "price_feed": feed,
        "confidence": {c: sum(1 for r in ok if r["confidence"] == c) for c in ("high", "medium", "low")},
        "median_upside_pct": round(med, 1) if med is not None else None,
        "relative_basis": f"median of {len(ok)} valued names" if len(ok) >= 8 else "too few names for relative upside (need 8)",
        "not_valuable": [r["symbol"] for r in results if r.get("status") == "not_valuable"],
        "no_data": [r["symbol"] for r in results if r.get("status") == "no_data"],
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


@fair_bp.route("/fair-value", methods=["GET", "POST"])
def fair_value():
    # GET /fair-value?symbols=AAA,BBB for quick checks in a browser; POST for the pipeline
    body = dict(request.args) if request.method == "GET" else (request.get_json(force=True, silent=True) or {})
    try:
        items = _items_from_body(body)
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"could not parse input: {e}"}), 400
    if not items:
        return jsonify({"error": "no symbols given (send base or symbols)"}), 400
    if len(items) > 60:
        return jsonify({"error": f"{len(items)} symbols - max 60 per call"}), 400
    return jsonify(compute(items, debug=str(body.get("debug", "")).lower() in ("1", "true", "yes")))
