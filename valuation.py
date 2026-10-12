"""
Valuation / fundamentals fetch - Layer 2's "hard financial data" step.

    Screen -> Macro Analyst -> THIS -> Micro Analyst -> Watchlist

Pure data retrieval, no judgment (facts are code, judgment is the LLM).

2026-10-11: moved from Yahoo Finance to SEC EDGAR + Alpaca. Yahoo blocks
Render's IP completely (401 on snapshot, statements and prices); requests took
60-70s, Make retried and the single worker jammed the whole server. The SEC
has the same statement figures (official, free, not blocked); prices come from
Alpaca. Field names are unchanged, so Make modules and /base-score keep
working. Differences: forward_pe and peg_ratio are always null (analyst
forecasts), and figures are as of the latest filing (snapshot_source says
which quarter). See sec_fundamentals.py for how quarters are built.

Endpoint:
    GET /valuation?symbols=AAPL,MSFT,...

Returns {"as_of", "fundamentals": "<json string>", "errors": [...]}, where
fundamentals maps each symbol to:
    pe_ratio, forward_pe (null), peg_ratio (null), revenue_growth_yoy,
    earnings_growth_yoy, gross_margin, operating_margin, profit_margin,
    debt_to_equity (percent, Yahoo style), free_cash_flow (TTM), market_cap,
    last_price, snapshot_source,
    trend_period, trend_revenue, trend_revenue_growth_qoq, trend_gross_margin,
    trend_operating_margin, trend_net_margin, trend_fcf (oldest -> newest strings),
    q_revenue, q_operating_margin, q_net_margin, q_fcf (same, as numbers)
One bad symbol never fails the batch: it gets nulls plus an entry in errors.
The whole request answers within REQUEST_BUDGET_SEC (Render's proxy cuts at ~40s);
filings are cached 12h, so repeat calls are near-instant.
"""

import datetime
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout

from flask import Blueprint, jsonify, request

import sec_fundamentals as sec

valuation_bp = Blueprint("valuation", __name__)

MAX_CONCURRENT_SYMBOLS = 5   # SEC rate limit (~8/s) is enforced inside signals._get
REQUEST_BUDGET_SEC = 28

FIELDS = (
    "pe_ratio",
    "forward_pe",
    "peg_ratio",
    "revenue_growth_yoy",
    "earnings_growth_yoy",
    "gross_margin",
    "operating_margin",
    "profit_margin",
    "debt_to_equity",
    "free_cash_flow",
    "market_cap",
)

TREND_FIELDS = (
    "trend_period",
    "trend_revenue",
    "trend_revenue_growth_qoq",
    "trend_gross_margin",
    "trend_operating_margin",
    "trend_net_margin",
    "trend_fcf",
)


def _empty_result(reason):
    result = {k: None for k in FIELDS}
    result.update({k: "n/a" for k in TREND_FIELDS})
    result["trend_error"] = reason
    return result


def _fetch_one(sym, price=None):
    """(sym, data, errors) for one symbol. Never raises. Also used by /base-score."""
    try:
        if price is None:
            price = sec.latest_prices([sym]).get(sym)
        summary, err = sec.summary_for(sym)
        if not summary:
            return sym, _empty_result(err), [f"{sym}: {err}"]
        data = sec.build(summary, price)
        errors = [] if price else [f"{sym}: no Alpaca price - P/E and market cap unavailable"]
        return sym, data, errors
    except Exception as e:
        return sym, _empty_result(f"unexpected error: {e}"), [f"{sym}: unexpected error - {e}"]


@valuation_bp.route("/valuation", methods=["GET"])
def valuation():
    symbols_param = request.args.get("symbols", "")
    symbols = [s.strip().upper() for s in symbols_param.split(",") if s.strip()]
    if not symbols:
        return jsonify({"error": "Missing required 'symbols' query parameter, e.g. ?symbols=AAPL,MSFT"}), 400

    fundamentals, errors = {}, []
    try:
        prices = sec.latest_prices(symbols)
    except Exception as e:
        prices = {}
        errors.append(f"prices: {e}")

    pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_SYMBOLS)
    futures = {pool.submit(_fetch_one, sym, prices.get(sym) or 0.0): sym for sym in symbols}
    try:
        for future in as_completed(futures, timeout=REQUEST_BUDGET_SEC):
            sym, result, sym_errors = future.result()
            fundamentals[sym] = result
            errors.extend(sym_errors)
    except FuturesTimeout:
        for sym in symbols:
            if sym not in fundamentals:
                reason = f"skipped - request time budget ({REQUEST_BUDGET_SEC}s) used up; retry fills it from cache"
                fundamentals[sym] = _empty_result(reason)
                errors.append(f"{sym}: {reason}")
    finally:
        # answer now; stragglers keep running in the background and land in the cache
        pool.shutdown(wait=False)

    out = {
        "as_of": datetime.date.today().isoformat(),
        "fundamentals": json.dumps(fundamentals),
        "errors": errors,
    }
    if request.args.get("debug"):
        # which SEC tags each company actually files (recent periods, largest first)
        for sym in symbols:
            if sym not in sec._INVENTORY:
                sec._CACHE.pop(sym, None)
                sec.summary_for(sym)
        out["tag_inventory"] = {sym: sec._INVENTORY.get(sym) for sym in symbols}
    return jsonify(out)
