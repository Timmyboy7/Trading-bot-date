"""
Valuation / fundamentals fetch — Layer 2's "hard financial data" step.

Sits between Macro Analyst and Micro Analyst in the weekly Discovery scenario:

    Screen -> Macro Analyst -> THIS -> Micro Analyst -> Watchlist

Pure data retrieval, no judgment — deliberately NOT an LLM call, same
principle used for the screener and Risk Guardrails: facts are code,
judgment is the LLM. This endpoint hands Micro Analyst real fundamentals so
it can judge "is this growth genuine and is the price reasonable," instead
of picking on price momentum alone. Micro Analyst is the one that turns
these raw numbers into an actual thesis (target price, conviction,
reasoning) — this endpoint only supplies the facts.

Drop next to app.py, then in app.py add:

    from valuation import valuation_bp
    app.register_blueprint(valuation_bp)

Needs `yfinance` added to requirements.txt and redeployed on Render — it is
NOT one of the libraries app.py/screener.py already use, so without this the
import will fail on Render the same way `flask`/`screener` failed locally
earlier until installed.

Endpoint:
    GET /valuation?symbols=AAPL,MSFT,...

    Call this with the screener's candidate list (the ~35 names from
    /screen), not the full S&P 500 — fundamentals only need to be pulled for
    stocks that already passed the price-based filter, keeping this cheap
    and fast.

Response:
    {
      "as_of": "2026-10-04",
      "fundamentals": "{\"AAPL\": {\"pe_ratio\": 34.2, ...}, ...}",
      "errors": []
    }

Fields per symbol: pe_ratio, forward_pe, peg_ratio, revenue_growth_yoy,
earnings_growth_yoy, gross_margin, operating_margin, profit_margin,
debt_to_equity, free_cash_flow, market_cap.

A null value for any field means Yahoo Finance didn't have that data point
for that company (common for recent IPOs, foreign issuers, or
less-covered names) — not a bug, just a real data gap; Micro Analyst's
prompt should be told to treat a missing field as "unknown," not as zero
or bad.

`fundamentals` is pre-stringified via json.dumps(), same convention as
`bars`/`news`/`positions` elsewhere in this project, so Make's
escapeJSON() works on it directly without the `[object Object]` bug.

Timing note: fetching ~35 symbols one at a time typically takes well under
a minute, but give the Make HTTP module a generous timeout (120s, same as
used for /screen) to be safe — same Render free-tier cold-start
consideration as the other endpoints.
"""
import datetime
import json
import time

import yfinance as yf
from flask import Blueprint, jsonify, request

valuation_bp = Blueprint("valuation", __name__)

REQUEST_PAUSE_SEC = 0.2  # be polite between per-symbol lookups

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


def _safe_get(info, *keys):
    for k in keys:
        v = info.get(k)
        if v is not None:
            return v
    return None


def fetch_fundamentals(symbol):
    """Returns (data_dict, error_string). Exactly one of the two is set."""
    try:
        info = yf.Ticker(symbol).info
    except Exception as e:
        return None, str(e)

    if not info or (info.get("regularMarketPrice") is None and info.get("currentPrice") is None):
        # yfinance often returns a near-empty dict rather than raising for an
        # invalid/delisted symbol — treat that as a soft failure, not a crash.
        return None, "no data returned (invalid symbol or no Yahoo Finance coverage)"

    data = {
        "pe_ratio": _safe_get(info, "trailingPE"),
        "forward_pe": _safe_get(info, "forwardPE"),
        "peg_ratio": _safe_get(info, "pegRatio", "trailingPegRatio"),
        "revenue_growth_yoy": _safe_get(info, "revenueGrowth"),
        "earnings_growth_yoy": _safe_get(info, "earningsGrowth"),
        "gross_margin": _safe_get(info, "grossMargins"),
        "operating_margin": _safe_get(info, "operatingMargins"),
        "profit_margin": _safe_get(info, "profitMargins"),
        "debt_to_equity": _safe_get(info, "debtToEquity"),
        "free_cash_flow": _safe_get(info, "freeCashflow"),
        "market_cap": _safe_get(info, "marketCap"),
    }
    return data, None


@valuation_bp.route("/valuation", methods=["GET"])
def valuation():
    symbols_param = request.args.get("symbols", "")
    symbols = [s.strip().upper() for s in symbols_param.split(",") if s.strip()]
    if not symbols:
        return jsonify({"error": "Missing required 'symbols' query parameter, e.g. ?symbols=AAPL,MSFT"}), 400

    fundamentals = {}
    errors = []

    for sym in symbols:
        data, err = fetch_fundamentals(sym)
        if data:
            fundamentals[sym] = data
        else:
            fundamentals[sym] = {k: None for k in FIELDS}
            errors.append(f"{sym}: {err}")
        time.sleep(REQUEST_PAUSE_SEC)

    return jsonify(
        {
            "as_of": datetime.date.today().isoformat(),
            "fundamentals": json.dumps(fundamentals),
            "errors": errors,
        }
    )
