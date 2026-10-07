"""
S&P 500 quant screener.

Scans the S&P 500, computes a sector-relative momentum score ("upcoming
players") and a sector-relative reversal score ("rebounding names"), blends
them, and returns a ranked shortlist as JSON.

Drop this file next to app.py in the Trading-bot-date repo, then in app.py add:

    from screener import screener_bp
    app.register_blueprint(screener_bp)

right after `app = Flask(__name__)`. No new env vars needed — it reuses the
same ALPACA_API_KEY / ALPACA_API_SECRET already read by app.py.

Endpoint:
    GET /screen?top=30&max_per_sector=8&mom_weight=0.5&rebound_weight=0.5

Response:
    {
      "as_of": "2026-09-28",
      "universe_size": 493,
      "scored": 480,
      "candidates": [
        {
          "symbol": "NVDA",
          "sector": "Information Technology",
          "combined_score": 2.14,
          "momentum_score": 1.98,
          "rebound_score": 1.05,
          "ret_3m": 0.31,
          "ret_6m": 0.58,
          "drawdown_from_52w_high": -0.04,
          "rsi14": 61.2
        },
        ...
      ]
    }
"""
import os
import csv
import json
import math
import time
import datetime
from pathlib import Path

import requests
from flask import Blueprint, jsonify, request

screener_bp = Blueprint("screener", __name__)

ALPACA_KEY = os.environ.get("ALPACA_API_KEY")
ALPACA_SECRET = os.environ.get("ALPACA_API_SECRET")
DATA_BASE = "https://data.alpaca.markets"
DATA_FEED = os.environ.get("ALPACA_DATA_FEED", "iex")  # "iex" works on free/paper accounts; use "sip" if you have that entitlement

HEADERS = {
    "APCA-API-KEY-ID": ALPACA_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET,
}

CONSTITUENTS_PATH = Path(__file__).parent / "sp500_constituents.csv"

# Lookback: ~1 trading year of daily bars gives us 52-week high, 6-month and
# 3-month momentum, and enough history for a stable RSI(14).
LOOKBACK_DAYS = 380  # calendar days; trading days will be ~ 260
BATCH_SIZE = 100      # symbols per Alpaca bars request
REQUEST_PAUSE_SEC = 0.3  # be polite to the free-tier rate limit


def load_constituents():
    rows = []
    with open(CONSTITUENTS_PATH, newline="") as f:
        for r in csv.DictReader(f):
            sym = r["symbol"].strip().upper()
            sector = r["sector"].strip()
            if sym and sector:
                rows.append((sym, sector))
    return rows


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def fetch_bars(symbols):
    """Fetch ~1yr daily bars for a list of symbols. Returns {symbol: [close,...]} in chronological order."""
    end = datetime.datetime.utcnow().date()
    start = end - datetime.timedelta(days=LOOKBACK_DAYS)
    out = {}

    for batch in chunked(symbols, BATCH_SIZE):
        page_token = None
        while True:
            params = {
                "symbols": ",".join(batch),
                "timeframe": "1Day",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "adjustment": "split",
                "feed": DATA_FEED,
                "limit": 10000,
            }
            if page_token:
                params["page_token"] = page_token

            resp = requests.get(
                f"{DATA_BASE}/v2/stocks/bars",
                headers=HEADERS,
                params=params,
                timeout=30,
            )
            if resp.status_code != 200:
                # Skip this batch on error rather than failing the whole screen;
                # the batch's symbols just won't be scored.
                break

            data = resp.json()
            bars_by_symbol = data.get("bars", {}) or {}
            for sym, bars in bars_by_symbol.items():
                closes = [b["c"] for b in bars]
                out.setdefault(sym, [])
                if page_token:
                    out[sym].extend(closes)
                else:
                    out[sym] = closes

            page_token = data.get("next_page_token")
            if not page_token:
                break
            time.sleep(REQUEST_PAUSE_SEC)

        time.sleep(REQUEST_PAUSE_SEC)

    return out


def rsi14(closes):
    """Standard 14-period RSI on a list of closes (chronological)."""
    period = 14
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_raw_factors(closes):
    """From a chronological list of daily closes, compute the raw (unstandardized) factors."""
    n = len(closes)
    if n < 130:  # need at least ~6 months of history to trust these numbers
        return None

    last = closes[-1]

    def ret(n_days_back):
        idx = n - 1 - n_days_back
        if idx < 0:
            return None
        base = closes[idx]
        return (last / base - 1.0) if base else None

    ret_1w = ret(5)
    ret_1m = ret(21)
    ret_3m = ret(63)
    ret_6m = ret(126)
    high_52w = max(closes[-252:]) if n >= 20 else max(closes)
    drawdown = (last / high_52w - 1.0) if high_52w else None
    rsi = rsi14(closes[-(period_needed := 100):]) if n >= 100 else rsi14(closes)

    if None in (ret_3m, ret_6m, drawdown) or rsi is None:
        return None

    momentum_raw = 0.5 * ret_3m + 0.5 * ret_6m

    # Reversal/rebound signal: reward names that are meaningfully off their
    # 52-week high (drawdown is negative -> -drawdown is positive "room to
    # recover") AND have started turning up recently (positive 1-month
    # return even though the 6-month trend is still negative or weak).
    turn_up = max(ret_1m, 0.0) if ret_1m is not None else 0.0
    off_high = max(-drawdown, 0.0)
    rebound_raw = off_high * turn_up

    return {
        "ret_1m": ret_1m,
        "ret_1w": ret_1w,
        "ret_3m": ret_3m,
        "ret_6m": ret_6m,
        "drawdown_from_52w_high": drawdown,
        "rsi14": rsi,
        "momentum_raw": momentum_raw,
        "rebound_raw": rebound_raw,
    }


def zscore_within_sector(rows, field):
    """rows: list of dicts with 'sector' and field. Adds field+'_z' in place, grouped by sector."""
    by_sector = {}
    for r in rows:
        by_sector.setdefault(r["sector"], []).append(r)

    for sector, group in by_sector.items():
        vals = [g[field] for g in group]
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        std = math.sqrt(var)
        for g in group:
            g[field + "_z"] = 0.0 if std == 0 else (g[field] - mean) / std


@screener_bp.route("/screen", methods=["GET"])
def screen():
    if not ALPACA_KEY or not ALPACA_SECRET:
        return jsonify({"error": "ALPACA_API_KEY / ALPACA_API_SECRET not configured"}), 500

    top_n = int(request.args.get("top", 30))
    max_per_sector = int(request.args.get("max_per_sector", 8))
    mom_weight = float(request.args.get("mom_weight", 0.5))
    rebound_weight = float(request.args.get("rebound_weight", 0.5))

    constituents = load_constituents()
    symbols = [s for s, _ in constituents]
    sector_by_symbol = dict(constituents)

    bars = fetch_bars(symbols)

    rows = []
    for sym, closes in bars.items():
        sector = sector_by_symbol.get(sym)
        if not sector:
            continue
        factors = compute_raw_factors(closes)
        if not factors:
            continue
        row = {"symbol": sym, "sector": sector}
        row.update(factors)
        rows.append(row)

    if not rows:
        return jsonify({"error": "no symbols scored — check Alpaca data access/entitlement"}), 502

    zscore_within_sector(rows, "momentum_raw")
    zscore_within_sector(rows, "rebound_raw")

    for r in rows:
        r["momentum_score"] = round(r["momentum_raw_z"], 3)
        r["rebound_score"] = round(r["rebound_raw_z"], 3)
        r["combined_score"] = round(
            mom_weight * r["momentum_raw_z"] + rebound_weight * r["rebound_raw_z"], 3
        )

    rows.sort(key=lambda r: r["combined_score"], reverse=True)

    # Diversify across sectors: cap how many names from any one sector make
    # the final cut, so this doesn't turn into an all-tech list.
    picked = []
    per_sector_count = {}
    for r in rows:
        c = per_sector_count.get(r["sector"], 0)
        if c >= max_per_sector:
            continue
        picked.append(r)
        per_sector_count[r["sector"]] = c + 1
        if len(picked) >= top_n:
            break

    candidates = [
        {
            "symbol": r["symbol"],
            "sector": r["sector"],
            "combined_score": r["combined_score"],
            "momentum_score": r["momentum_score"],
            "rebound_score": r["rebound_score"],
            "ret_3m": round(r["ret_3m"], 4),
            "ret_6m": round(r["ret_6m"], 4),
            "drawdown_from_52w_high": round(r["drawdown_from_52w_high"], 4),
            "rsi14": round(r["rsi14"], 1),
        }
        for r in picked
    ]

    # Sector-level aggregates over the *picked* shortlist only — this is what
    # the macro analyst reads to judge "which sectors are strong right now",
    # computed in code so it doesn't have to average 30-40 numbers by hand.
    sector_summary = {}
    for r in picked:
        s = sector_summary.setdefault(
            r["sector"], {"sector": r["sector"], "count": 0, "momentum_sum": 0.0, "rebound_sum": 0.0}
        )
        s["count"] += 1
        s["momentum_sum"] += r["momentum_score"]
        s["rebound_sum"] += r["rebound_score"]

    sector_summary_list = sorted(
        (
            {
                "sector": s["sector"],
                "count": s["count"],
                "avg_momentum_score": round(s["momentum_sum"] / s["count"], 3),
                "avg_rebound_score": round(s["rebound_sum"] / s["count"], 3),
            }
            for s in sector_summary.values()
        ),
        key=lambda x: x["avg_momentum_score"],
        reverse=True,
    )

    # Price-based sector health over ALL scored names (not just the shortlist):
    # median 1-month and 1-week return per sector. /reconcile-basket uses this
    # to detect a sector crisis (e.g. Energy median 1m <= -10%).
    def _median(vals):
        vals = sorted(v for v in vals if v is not None)
        if not vals:
            return None
        m = len(vals) // 2
        return vals[m] if len(vals) % 2 else (vals[m - 1] + vals[m]) / 2

    by_sector_all = {}
    for r in rows:
        by_sector_all.setdefault(r["sector"], []).append(r)
    sector_returns = [
        {
            "sector": sec,
            "n": len(g),
            "median_ret_1m": None if _median([x["ret_1m"] for x in g]) is None else round(_median([x["ret_1m"] for x in g]), 4),
            "median_ret_1w": None if _median([x["ret_1w"] for x in g]) is None else round(_median([x["ret_1w"] for x in g]), 4),
        }
        for sec, g in by_sector_all.items()
    ]

    return jsonify(
        {
            "sector_returns": json.dumps(sector_returns),
            "as_of": datetime.date.today().isoformat(),
            "universe_size": len(symbols),
            "scored": len(rows),
            # Pre-stringified (matching app.py's existing convention for
            # result["bars"] / result["news"]): Make's escapeJSON() expects a
            # string, not a parsed array/collection — feeding it a raw JSON
            # array makes it fall back to "[object Object]" stringification.
            "candidates": json.dumps(candidates),
            "sector_summary": json.dumps(sector_summary_list),
            # 2026-10-04: plain, NOT stringified — this is deliberately a
            # native JSON array of just the symbols (e.g. ["AAPL","MSFT",...]),
            # so Make can do join(2.data.candidate_symbols; ",") directly to
            # build the Valuation call's ?symbols= list, with no Parse JSON
            # module and no map()/parseJSON() needed. Keep this un-stringified
            # even though `candidates` above is stringified — they serve
            # different consumers (this one needs a real array to iterate,
            # `candidates` needs a string to embed in a prompt).
            "candidate_symbols": [c["symbol"] for c in candidates],
        }
    )
