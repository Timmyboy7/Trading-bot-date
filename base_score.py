"""
Base score — the deterministic half of Micro (added 2026-10-09).

Design decision (project doc "Weekly pipeline & LLM roles"): answers that live
in numbers are computed by code, answers that live in text are the LLM's job.
This endpoint turns the hard facts into the same four rubric pillars Micro used
to guess (quality, valuation, trend confirmation, risk; 1-5 each) with FIXED
thresholds, so the same inputs always give the same score. Micro then only adds
a bounded overlay (max +/-0.5) for things numbers can't show (news, one-offs,
data errors, cluster bets) — see the Micro prompt and select_basket.py.

It also scores the CURRENT HOLDINGS, not only the screener's candidates, so
every name in the basket is re-checked every week.

Pipeline position (weekly Discovery scenario):
    /screen -> /valuation -> Search Rows + Aggregate (current Watchlist)
            -> THIS -> signals warm-up -> Macro -> Micro x3 -> signals -> select -> reconcile

Endpoint:
    POST /base-score
    Body (each value may be a real JSON value or a JSON string, Make style):
      {
        "candidates":   [...],   // /screen candidates (2.data.candidates)
        "current":      [...],   // current Watchlist rows (36.json)
        "fundamentals": {...}    // /valuation fundamentals for the candidates (30.data.fundamentals)
      }

Response:
    {
      "as_of": "...",
      "symbols_csv": "AAA,BBB,...",      // candidates + holdings, for /signals
      "base_json": "[...]",              // per symbol: base_score, pillars, components, flags, facts
      "micro_input_json": "[...]",       // compact pack for the Micro overlay prompt (facts + headlines)
      "summary": {...}, "summary_json": "...", "errors": [...]
    }

Everything the endpoint fetches itself (price history for all names, fundamentals
for holdings that aren't candidates, recent headlines) is best effort inside a
time budget (BASE_BUDGET_SEC, default 30 s) because Render's proxy cuts requests
at ~40 s. Anything not ready in time is scored from what is there and flagged
"data_gap" — never a crash, never a silent zero.

The thresholds below are deliberately simple and written down so they can be
reviewed and tuned (later by the reviewer agent, via pull request).
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

base_bp = Blueprint("base_score", __name__)

BUDGET_SEC = float(os.environ.get("BASE_BUDGET_SEC", 30))
NEWS_DAYS = int(os.environ.get("BASE_NEWS_DAYS", 30))
NEWS_PER_SYMBOL = int(os.environ.get("BASE_NEWS_PER_SYMBOL", 5))
CACHE_TTL_SEC = 12 * 3600

WEIGHTS = {"quality": 0.35, "valuation": 0.20, "trend": 0.25, "risk": 0.20}

# Rough "typical" levels per GICS sector, used only to make margins and P/E
# sector-relative (a 10% operating margin is good for a retailer, weak for
# software). Approximate, deliberately round numbers — reviewable config.
SECTOR_TYPICAL = {
    #                          op margin, trailing P/E
    "Information Technology": (0.25, 30),
    "Communication Services": (0.22, 22),
    "Health Care":            (0.15, 22),
    "Financials":             (0.25, 16),
    "Industrials":            (0.15, 24),
    "Consumer Discretionary": (0.10, 24),
    "Consumer Staples":       (0.10, 22),
    "Energy":                 (0.12, 14),
    "Materials":              (0.15, 20),
    "Utilities":              (0.20, 18),
    "Real Estate":            (0.30, 35),
}
DEFAULT_TYPICAL = (0.15, 22)
# Leverage and FCF mean something different for banks/insurers (and leverage
# for REITs), so those components are skipped there instead of mis-scored.
NO_DEBT_SCORE = {"Financials", "Real Estate"}
NO_FCF_SCORE = {"Financials"}
NO_PE_SCORE = {"Real Estate"}   # REITs: P/E is distorted by depreciation; FCF yield is used


# ---------- small helpers ----------

def _load(v):
    if v is None or v == "":
        return None
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("```"):
            s = s.strip("`").strip()
            if s.lower().startswith("json"):
                s = s[4:].strip()
        return json.loads(s)
    return v


def _norm(k):
    return "".join(ch for ch in str(k).lower() if ch.isalnum())


def _get(row, *names, default=None):
    lookup = {_norm(k): v for k, v in row.items()}
    for n in names:
        v = lookup.get(_norm(n))
        if v is not None and v != "":
            return v
    return default


def _f(v):
    try:
        x = float(v)
        return None if math.isnan(x) or math.isinf(x) else x
    except (TypeError, ValueError):
        return None


def _sym(row):
    return str(_get(row, "symbol", default="") or "").strip().upper()


def band(x, cuts, scores=(5, 4, 3, 2, 1)):
    """cuts descending: x >= cuts[0] -> scores[0], >= cuts[1] -> scores[1], ..., else last."""
    if x is None:
        return None
    for c, s in zip(cuts, scores):
        if x >= c:
            return s
    return scores[len(cuts)]


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


# ---------- fetching (best effort, cached) ----------

_CACHE = {}


def _cached(kind, sym, fn):
    key = (kind, sym)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL_SEC:
        return hit[1]
    val = fn(sym)
    if val is not None:
        _CACHE[key] = (time.time(), val)
    return val


def _fetch_fundamentals(sym):
    from valuation import _fetch_one   # same code path as /valuation
    _, data, _errs = _fetch_one(sym)
    return data


def _fetch_news(sym):
    from screener import DATA_BASE, HEADERS
    start = (datetime.datetime.utcnow() - datetime.timedelta(days=NEWS_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = requests.get(f"{DATA_BASE}/v1beta1/news", headers=HEADERS, timeout=10,
                     params={"symbols": sym, "start": start, "limit": NEWS_PER_SYMBOL, "sort": "desc"})
    if r.status_code != 200:
        return None
    out = []
    for a in r.json().get("news", [])[:NEWS_PER_SYMBOL]:
        head = str(a.get("headline") or "").strip()
        if head:
            out.append({"date": str(a.get("created_at") or "")[:10], "headline": head[:160]})
    return out


def _volatility(closes, days=63):
    if not closes or len(closes) < days + 1:
        return None
    rets = [closes[i] / closes[i - 1] - 1 for i in range(len(closes) - days, len(closes)) if closes[i - 1]]
    if len(rets) < 20:
        return None
    return statistics.pstdev(rets) * math.sqrt(252)


# ---------- the deterministic rubric ----------

def score_symbol(sym, sector, f, p):
    """f = fundamentals dict (may be {}), p = price factors dict (may be {}).
    Returns (pillars, components, flags)."""
    op_typ, pe_typ = SECTOR_TYPICAL.get(sector, DEFAULT_TYPICAL)
    comp, flags = {}, []

    rev_g = _f(f.get("revenue_growth_yoy"))
    earn_g = _f(f.get("earnings_growth_yoy"))
    op_m = _f(f.get("operating_margin"))
    prof_m = _f(f.get("profit_margin"))
    pe = _f(f.get("pe_ratio"))
    fcf = _f(f.get("free_cash_flow"))
    mcap = _f(f.get("market_cap"))
    de = _f(f.get("debt_to_equity"))
    q_fcf = [x for x in (f.get("q_fcf") or []) if _f(x) is not None]
    q_om = [_f(x) for x in (f.get("q_operating_margin") or [])]
    q_rev = [_f(x) for x in (f.get("q_revenue") or [])]

    # data sanity: a quarter-over-quarter revenue swing above 100% is usually a
    # data error or a one-off — score it, but flag it for the LLM to check.
    for a, b in zip(q_rev, q_rev[1:]):
        if a and b is not None and abs(b - a) / abs(a) > 1.0:
            flags.append("revenue_swing_over_100pct_qoq")
            break
    if pe is not None and pe > 150:
        flags.append("pe_above_150_earnings_near_zero")

    # QUALITY: growth, sector-relative margin, FCF consistency, margin trend
    comp["q_revenue_growth"] = band(rev_g, (0.20, 0.10, 0.03, 0.0))
    if op_m is not None:
        comp["q_margin_vs_sector"] = 1 if op_m <= 0 else band(op_m / op_typ, (1.5, 1.1, 0.8, 0.4))
    if sector not in NO_FCF_SCORE and len(q_fcf) >= 3:
        pos = sum(1 for x in q_fcf if float(x) > 0) / len(q_fcf)
        comp["q_fcf_consistency"] = band(pos, (1.0, 0.75, 0.5, 0.01))
    om_known = [x for x in q_om if x is not None]
    if len(om_known) >= 3:
        delta_pp = (om_known[-1] - om_known[0]) * 100
        comp["q_margin_trend"] = band(delta_pp, (3, 1, -1, -3))

    # VALUATION: sector-relative P/E (growth-adjusted) and FCF yield
    if sector not in NO_PE_SCORE:
        if prof_m is not None and prof_m < 0:
            comp["v_pe_vs_sector"] = 1          # loss-making: no earnings support
        elif pe is not None and pe > 0:
            s = band(-(pe / pe_typ), (-0.6, -0.85, -1.15, -1.6))   # lower relative P/E = better
            if earn_g is not None and earn_g > 0.25 and s <= 3:
                s += 1                           # fast earnings growth earns a higher multiple
            comp["v_pe_vs_sector"] = s
    if fcf is not None and mcap:
        comp["v_fcf_yield"] = band(fcf / mcap, (0.06, 0.04, 0.02, 0.0))

    # TREND CONFIRMATION: price trend, RSI health, do fundamentals back the price?
    r3, r6 = _f(p.get("ret_3m")), _f(p.get("ret_6m"))
    mom = _mean([r3, r6])
    comp["t_momentum"] = band(mom, (0.25, 0.10, 0.0, -0.10))
    rsi = _f(p.get("rsi14"))
    if rsi is not None:
        comp["t_rsi_health"] = (2 if rsi > 78 else 3 if rsi > 70 else 5 if rsi >= 50
                                else 4 if rsi >= 40 else 3 if rsi >= 30 else 2)
    if mom is not None and rev_g is not None:
        if mom > 0:
            comp["t_fundamentals_confirm"] = 5 if rev_g > 0.05 else 4 if rev_g >= 0 else 1
        else:
            comp["t_fundamentals_confirm"] = 3 if rev_g > 0.10 else 2 if rev_g >= 0 else 1

    # RISK (5 = low risk): leverage, volatility, drawdown
    if sector not in NO_DEBT_SCORE and de is not None:
        comp["r_debt_to_equity"] = 5 if de < 50 else 4 if de < 100 else 3 if de < 200 else 2 if de < 400 else 1
    vol = _f(p.get("volatility_63d"))
    if vol is not None:
        comp["r_volatility"] = 5 if vol < 0.20 else 4 if vol < 0.30 else 3 if vol < 0.40 else 2 if vol < 0.55 else 1
    comp["r_drawdown"] = band(_f(p.get("drawdown_from_52w_high")), (-0.10, -0.20, -0.35, -0.50))

    comp = {k: v for k, v in comp.items() if v is not None}
    pillars = {}
    for name, prefix in (("quality", "q_"), ("valuation", "v_"), ("trend", "t_"), ("risk", "r_")):
        m = _mean([v for k, v in comp.items() if k.startswith(prefix)])
        if m is None:
            flags.append(f"data_gap_{name}")
            m = 3.0
        pillars[name] = round(m, 2)
    return pillars, comp, flags


def compute(candidates, current, fundamentals, fetch=True, budget=BUDGET_SEC):
    t0 = time.time()
    errors = []
    cand_sym = {}
    for c in candidates:
        s = _sym(c)
        if s:
            cand_sym[s] = c
    hold_sym = {}
    for r in current:
        s = _sym(r)
        if s:
            hold_sym[s] = r
    symbols = list(cand_sym) + [s for s in hold_sym if s not in cand_sym]

    def sector_of(s):
        row = cand_sym.get(s) or hold_sym.get(s) or {}
        return str(_get(row, "sector", default="Unknown"))

    fund = {k.upper(): v for k, v in (fundamentals or {}).items() if isinstance(v, dict)}
    price = {}
    news = {}

    if fetch:
        # 1) price history for every name (one or two Alpaca batch calls): identical
        #    factors for candidates and holdings, plus volatility.
        try:
            from screener import fetch_bars, compute_raw_factors
            bars = fetch_bars(symbols)
            for s, closes in bars.items():
                fac = compute_raw_factors(closes) or {}
                fac["volatility_63d"] = _volatility(closes)
                fac["last_price"] = closes[-1] if closes else None
                price[s] = fac
        except Exception as e:
            errors.append(f"bars: {e}")

        # 2) fundamentals for holdings that weren't candidates + 3) headlines for all,
        #    in parallel, inside the remaining time budget.
        need_fund = [s for s in symbols if s not in fund]
        pool = ThreadPoolExecutor(max_workers=6)
        futs = {}
        for s in need_fund:
            futs[pool.submit(_cached, "fund", s, _fetch_fundamentals)] = ("fund", s)
        for s in symbols:
            futs[pool.submit(_cached, "news", s, _fetch_news)] = ("news", s)
        remaining = max(budget - (time.time() - t0), 1)
        done, not_done = wait(futs, timeout=remaining)
        for fu in done:
            kind, s = futs[fu]
            try:
                val = fu.result()
            except Exception as e:
                errors.append(f"{kind} {s}: {e}")
                continue
            if val is None:
                continue
            (fund if kind == "fund" else news)[s] = val
        for fu in not_done:
            kind, s = futs[fu]
            errors.append(f"{kind} {s}: not finished within {budget:.0f}s budget (cached for the next call)")
        pool.shutdown(wait=False)   # unfinished fetches keep warming the cache

    rows = []
    for s in symbols:
        sector = sector_of(s)
        f = fund.get(s) or {}
        p = dict(price.get(s) or {})
        c = cand_sym.get(s)
        if c:   # fall back to the screener's own factors if bars were unavailable
            for k in ("ret_3m", "ret_6m", "drawdown_from_52w_high", "rsi14"):
                if p.get(k) is None and _f(_get(c, k)) is not None:
                    p[k] = _f(_get(c, k))
        pillars, comp, flags = score_symbol(s, sector, f, p)
        if not f:
            flags.append("no_fundamentals")
        total = sum(WEIGHTS[k] * pillars[k] for k in WEIGHTS)
        facts = {
            "pe": _f(f.get("pe_ratio")), "rev_growth_yoy": _f(f.get("revenue_growth_yoy")),
            "op_margin": _f(f.get("operating_margin")), "net_margin": _f(f.get("profit_margin")),
            "debt_to_equity_pct": _f(f.get("debt_to_equity")),
            "fcf_yield": (round(_f(f.get("free_cash_flow")) / _f(f.get("market_cap")), 4)
                          if _f(f.get("free_cash_flow")) is not None and _f(f.get("market_cap")) else None),
            "last_price": _f(f.get("last_price")) or p.get("last_price"),
            "ret_3m": p.get("ret_3m"), "ret_6m": p.get("ret_6m"), "drawdown": p.get("drawdown_from_52w_high"),
            "rsi14": p.get("rsi14"), "vol_63d": p.get("volatility_63d"),
            "trend_revenue": f.get("trend_revenue"), "trend_operating_margin": f.get("trend_operating_margin"),
            "trend_fcf": f.get("trend_fcf"),
        }
        facts = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in facts.items() if v not in (None, "n/a")}
        rows.append({
            "symbol": s, "sector": sector,
            "is_holding": s in hold_sym, "in_candidates": s in cand_sym,
            "base_score": round(total, 3), "pillars": pillars, "components": comp,
            "flags": sorted(set(flags)), "facts": facts, "headlines": news.get(s, []),
        })

    micro_input = [{
        "symbol": r["symbol"], "sector": r["sector"], "holding": r["is_holding"],
        "base_score": r["base_score"], "pillars": r["pillars"], "flags": r["flags"],
        "facts": r["facts"], "headlines": r["headlines"],
    } for r in rows]

    summary = {
        "symbols": len(rows), "candidates": len(cand_sym), "holdings": len(hold_sym),
        "holdings_not_in_candidates": len([s for s in hold_sym if s not in cand_sym]),
        "with_fundamentals": sum(1 for r in rows if "no_fundamentals" not in r["flags"]),
        "with_headlines": sum(1 for r in rows if r["headlines"]),
        "with_data_gaps": sum(1 for r in rows if any(fl.startswith("data_gap") for fl in r["flags"])),
        "seconds": round(time.time() - t0, 1),
    }
    return {
        "as_of": datetime.date.today().isoformat(),
        "symbols_csv": ",".join(symbols),
        "base": rows,
        "base_json": json.dumps(rows),
        "micro_input_json": json.dumps(micro_input, separators=(",", ":")),
        "summary": summary,
        "summary_json": json.dumps(summary),
        "errors": errors[:50],
    }


@base_bp.route("/base-score", methods=["POST"])
def base_score():
    body = request.get_json(force=True, silent=True) or {}
    try:
        candidates = _load(body.get("candidates")) or []
        current = _load(body.get("current")) or []
        fundamentals = _load(body.get("fundamentals")) or {}
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"could not parse input: {e}"}), 400
    if isinstance(candidates, dict):
        candidates = candidates.get("candidates", [])
    if not candidates:
        return jsonify({"error": "candidates list is empty — refusing to score"}), 400
    candidates = [c for c in candidates if isinstance(c, dict)]
    current = [r for r in current if isinstance(r, dict)] if isinstance(current, list) else []
    return jsonify(compute(candidates, current, fundamentals))
