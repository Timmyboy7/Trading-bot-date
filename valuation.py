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

Fields per symbol — two groups:

  1. Point-in-time snapshot (unchanged from the original version):
     pe_ratio, forward_pe, peg_ratio, revenue_growth_yoy,
     earnings_growth_yoy, gross_margin, operating_margin, profit_margin,
     debt_to_equity, free_cash_flow, market_cap.

  2. NEW — quarterly trend (added 2026-10-04, per "does this data show any
     development, or just one point in time?"). The snapshot fields above
     are still just one point in time; revenue_growth_yoy is one YoY
     comparison, not a trajectory. These new fields pull the last 4 reported
     quarters via yfinance's quarterly statements and summarize them as
     compact "oldest -> newest" strings, so Micro Analyst's prompt gets an
     actual trend without being handed raw financial statements:

       trend_period            "Dec'24 -> Mar'25 -> Jun'25 -> Sep'25"
       trend_revenue           "$94.9B -> $90.8B -> $95.4B -> $124.3B"
       trend_revenue_growth_qoq  "-1% -> +5% -> +30%"   (quarter-over-quarter, one fewer value than periods)
       trend_gross_margin      "43% -> 44% -> 46% -> 47%"
       trend_operating_margin  "30% -> 31% -> 29% -> 33%"
       trend_net_margin        "24% -> 25% -> 23% -> 27%"
       trend_fcf               "$20.1B -> $14.2B -> $18.9B -> $29.0B"
       trend_error             only present if the trend pull failed/was
                                unavailable for this symbol (e.g. recent IPO
                                with <4 reported quarters) — snapshot fields
                                are still returned in that case.

     A trend value of "n/a" for one slot means that particular quarter's
     figure wasn't available (e.g. a line item yfinance didn't report that
     period) — same "treat as unknown, not zero" rule as the snapshot nulls.

A null/"n/a" value for any field means Yahoo Finance didn't have that data
point for that company (common for recent IPOs, foreign issuers, or
less-covered names) — not a bug, just a real data gap; Micro Analyst's
prompt should be told to treat a missing field as "unknown," not as zero
or bad.

`fundamentals` is pre-stringified via json.dumps(), same convention as
`bars`/`news`/`positions` elsewhere in this project, so Make's
escapeJSON() works on it directly without the `[object Object]` bug.

Timing note: fetching ~35 symbols one at a time (snapshot + trend both use
yfinance, same underlying request session) typically takes well under a
minute, but give the Make HTTP module a generous timeout (120s, same as
used for /screen) to be safe — same Render free-tier cold-start
consideration as the other endpoints.
"""
import datetime
import json
import math
import time

import yfinance as yf
from flask import Blueprint, jsonify, request

valuation_bp = Blueprint("valuation", __name__)

REQUEST_PAUSE_SEC = 0.5  # be polite between per-symbol lookups
TREND_QUARTERS = 4  # how many reported quarters to summarize, oldest -> newest
SNAPSHOT_RETRIES = 2  # extra attempts for the .info call, which Yahoo rate-limits
# harder than the quarterly-statement endpoints — see 2026-10-04 note below.

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


def _safe_get(info, *keys):
    for k in keys:
        v = info.get(k)
        if v is not None:
            return v
    return None


def fetch_fundamentals(symbol, retries=SNAPSHOT_RETRIES):
    """Returns (data_dict, error_string). Exactly one of the two is set.

    2026-10-04: Yahoo rate-limits the `.info` endpoint ("quoteSummary") more
    aggressively than the quarterly-statement endpoints used by
    fetch_trend() below — this shows up as .info silently returning an
    empty/near-empty dict (not an exception) for valid symbols, especially
    on shared cloud IPs like Render's. A short retry-with-backoff recovers
    some of these; it is a mitigation, not a guaranteed fix — if Yahoo is
    mid-block, every attempt will fail and this correctly falls through to
    an error entry rather than crashing the whole request.
    """
    info = None
    last_err = None
    for attempt in range(retries + 1):
        try:
            info = yf.Ticker(symbol).info
        except Exception as e:
            last_err = str(e)
            info = None
        else:
            if info and (info.get("regularMarketPrice") is not None or info.get("currentPrice") is not None):
                break
            last_err = "no data returned (invalid symbol, no Yahoo Finance coverage, or rate-limited)"
            info = None
        if attempt < retries:
            time.sleep(1.0 * (attempt + 1))  # 1s, then 2s before giving up

    if not info:
        return None, last_err or "no data returned (invalid symbol or no Yahoo Finance coverage)"

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


# --- Trend helpers -----------------------------------------------------

def _is_nan(v):
    try:
        return v is None or (isinstance(v, float) and math.isnan(v))
    except Exception:
        return v is None


def _row(df, *row_names):
    """Returns the first matching row (as a pandas Series) from a yfinance
    statement DataFrame, trying a few possible row-label spellings since
    these can differ slightly by company/filing. None if none match."""
    if df is None or df.empty:
        return None
    for name in row_names:
        if name in df.index:
            return df.loc[name]
    return None


def _fmt_money(v):
    if _is_nan(v):
        return "n/a"
    v = float(v)
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1e9:
        return f"{sign}${v / 1e9:.1f}B"
    if v >= 1e6:
        return f"{sign}${v / 1e6:.1f}M"
    return f"{sign}${v:.0f}"


def _fmt_pct(v, signed=False):
    if _is_nan(v):
        return "n/a"
    pct = v * 100
    if signed:
        return f"{pct:+.0f}%"
    return f"{pct:.0f}%"


def fetch_trend(symbol, quarters=TREND_QUARTERS):
    """Returns (trend_dict, error_string). Exactly one of the two is set.

    Pulls the last `quarters` reported quarters via yfinance's quarterly
    statements and summarizes each metric as a single compact "oldest ->
    newest" string, rather than handing raw statements to the LLM prompt.
    """
    try:
        t = yf.Ticker(symbol)
        fin = t.quarterly_financials
        cf = t.quarterly_cashflow
    except Exception as e:
        return None, str(e)

    if fin is None or fin.empty:
        return None, "no quarterly financials available (recent IPO, foreign issuer, or no coverage)"

    # yfinance returns columns most-recent-quarter-first; take the newest N,
    # then reverse to oldest -> newest for a natural-reading trend.
    cols = list(fin.columns)[:quarters]
    if len(cols) < 2:
        return None, "fewer than 2 reported quarters available — not enough for a trend"
    cols_chrono = list(reversed(cols))

    def series_for(df, *row_names):
        row = _row(df, *row_names)
        if row is None:
            return [None] * len(cols_chrono)
        out = []
        for c in cols_chrono:
            v = row.get(c) if c in row.index else None
            out.append(None if _is_nan(v) else float(v))
        return out

    revenue = series_for(fin, "Total Revenue", "TotalRevenue")
    gross_profit = series_for(fin, "Gross Profit", "GrossProfit")
    operating_income = series_for(fin, "Operating Income", "OperatingIncome")
    net_income = series_for(fin, "Net Income", "NetIncome", "Net Income Common Stockholders")
    op_cash_flow = series_for(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities", "Total Cash From Operating Activities")
    capex = series_for(cf, "Capital Expenditure", "Capital Expenditures")

    def margin(num, den):
        if num is None or den in (None, 0):
            return None
        return num / den

    def qoq_growth(curr, prev):
        if curr is None or prev in (None, 0):
            return None
        return (curr - prev) / abs(prev)

    def fcf(ocf, cpx):
        if ocf is None or cpx is None:
            return None
        return ocf + cpx  # capex is reported negative by yfinance

    gross_margin_seq = [margin(gross_profit[i], revenue[i]) for i in range(len(cols_chrono))]
    operating_margin_seq = [margin(operating_income[i], revenue[i]) for i in range(len(cols_chrono))]
    net_margin_seq = [margin(net_income[i], revenue[i]) for i in range(len(cols_chrono))]
    fcf_seq = [fcf(op_cash_flow[i], capex[i]) for i in range(len(cols_chrono))]
    revenue_growth_qoq_seq = [
        qoq_growth(revenue[i], revenue[i - 1]) for i in range(1, len(cols_chrono))
    ]

    period_labels = [c.strftime("%b'%y") for c in cols_chrono]

    trend = {
        "trend_period": " -> ".join(period_labels),
        "trend_revenue": " -> ".join(_fmt_money(v) for v in revenue),
        "trend_revenue_growth_qoq": " -> ".join(_fmt_pct(v, signed=True) for v in revenue_growth_qoq_seq),
        "trend_gross_margin": " -> ".join(_fmt_pct(v) for v in gross_margin_seq),
        "trend_operating_margin": " -> ".join(_fmt_pct(v) for v in operating_margin_seq),
        "trend_net_margin": " -> ".join(_fmt_pct(v) for v in net_margin_seq),
        "trend_fcf": " -> ".join(_fmt_money(v) for v in fcf_seq),
    }
    return trend, None


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

        trend, trend_err = fetch_trend(sym)
        if trend:
            fundamentals[sym].update(trend)
        else:
            fundamentals[sym].update({k: "n/a" for k in TREND_FIELDS})
            fundamentals[sym]["trend_error"] = trend_err
            errors.append(f"{sym} (trend): {trend_err}")

        time.sleep(REQUEST_PAUSE_SEC)

    return jsonify(
        {
            "as_of": datetime.date.today().isoformat(),
            "fundamentals": json.dumps(fundamentals),
            "errors": errors,
        }
    )
