import json
import os
import datetime
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

import traceback

# 2026-10-07: blueprint imports are wrapped so that ONE broken module (e.g. a
# bad paste or a missing package) can't stop the whole service from booting.
# The error text is exposed at GET / under "import_errors", so a failed
# import is visible in the browser instead of only as a crashed deploy.
IMPORT_ERRORS = {}


def _register(module_name, bp_name):
    try:
        module = __import__(module_name)
        app.register_blueprint(getattr(module, bp_name))
    except Exception:
        IMPORT_ERRORS[module_name] = traceback.format_exc()[-1500:]


_register("screener", "screener_bp")
_register("valuation", "valuation_bp")
_register("reconcile_basket", "reconcile_bp")

ALPACA_KEY = os.environ.get("ALPACA_API_KEY")
ALPACA_SECRET = os.environ.get("ALPACA_API_SECRET")

TRADING_BASE = "https://paper-api.alpaca.markets"
DATA_BASE = "https://data.alpaca.markets"

HEADERS = {
    "APCA-API-KEY-ID": ALPACA_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET,
}


@app.route("/")
def health():
    out = {"status": "ok"}
    if IMPORT_ERRORS:
        out["import_errors"] = IMPORT_ERRORS
    return jsonify(out)


@app.route("/market-data")
def market_data():
    symbols_param = request.args.get("symbols", "")
    requested_symbols = [s.strip().upper() for s in symbols_param.split(",") if s.strip()]
    if not requested_symbols:
        return jsonify({"error": "Missing required 'symbols' query parameter, e.g. ?symbols=AAPL,MSFT"}), 400

    days_back = int(request.args.get("days", 45))
    news_limit = int(request.args.get("news_limit", 10))
    start_date = (datetime.date.today() - datetime.timedelta(days=days_back)).isoformat()

    result = {"account": None, "positions": {}, "bars": {}, "news": {}, "errors": []}

    # Account balance
    try:
        r = requests.get(f"{TRADING_BASE}/v2/account", headers=HEADERS, timeout=20)
        r.raise_for_status()
        acct = r.json()
        result["account"] = {"cash": acct.get("cash"), "equity": acct.get("equity")}
    except Exception as e:
        result["errors"].append(f"account: {e}")

    # Current positions (all of them) — fetched first so any held-but-not-
    # requested symbol can be folded into the analysis list below. This is
    # what keeps a stock from disappearing from monitoring the moment it
    # drops out of the Watchlist while you still hold it: it stays in the
    # analyzed set (and gets a sell/hold decision from the daily chain)
    # until you're actually out of the position.
    try:
        r = requests.get(f"{TRADING_BASE}/v2/positions", headers=HEADERS, timeout=20)
        r.raise_for_status()
        positions_list = r.json()
        held = {p["symbol"]: float(p["qty"]) for p in positions_list}
    except Exception as e:
        held = {}
        result["errors"].append(f"positions: {e}")

    held_extra = [sym for sym, qty in held.items() if qty != 0 and sym not in requested_symbols]
    symbols = requested_symbols + held_extra
    symbols_csv = ",".join(symbols)

    for sym in symbols:
        result["positions"][sym] = held.get(sym, 0)

    # Price bars for all symbols in one call
    try:
        r = requests.get(
            f"{DATA_BASE}/v2/stocks/bars",
            headers=HEADERS,
            params={
                "symbols": symbols_csv,
                "timeframe": "1Day",
                "start": start_date,
                "limit": 1000,
                "feed": "iex",
            },
            timeout=20,
        )
        r.raise_for_status()
        bars_data = r.json().get("bars", {})
        for sym in symbols:
            result["bars"][sym] = bars_data.get(sym, [])
    except Exception as e:
        result["errors"].append(f"bars: {e}")
        for sym in symbols:
            result["bars"][sym] = []

    # News for all symbols in one call, then split per symbol
    try:
        r = requests.get(
            f"{DATA_BASE}/v1beta1/news",
            headers=HEADERS,
            params={"symbols": symbols_csv, "limit": min(news_limit * len(symbols), 50)},
            timeout=20,
        )
        r.raise_for_status()
        articles = r.json().get("news", [])
        for sym in symbols:
            result["news"][sym] = [
                {"headline": a.get("headline"), "summary": a.get("summary"), "created_at": a.get("created_at")}
                for a in articles
                if sym in (a.get("symbols") or [])
            ][:news_limit]
    except Exception as e:
        result["errors"].append(f"news: {e}")
        for sym in symbols:
            result["news"][sym] = []

    # effective_symbols is the real list that got analyzed (requested ∪ held) —
    # this is what the Make prompts should read the "stocks" list from, not
    # the raw Watchlist text, so every prompt and this data agree on exactly
    # which symbols are in play.
    result["effective_symbols"] = ",".join(symbols)
    result["bars"] = json.dumps(result["bars"])
    result["news"] = json.dumps(result["news"])
    result["positions"] = json.dumps(result["positions"])

    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
