import json
import os
import datetime
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

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
    return jsonify({"status": "ok"})


@app.route("/market-data")
def market_data():
    symbols_param = request.args.get("symbols", "")
    symbols = [s.strip().upper() for s in symbols_param.split(",") if s.strip()]
    if not symbols:
        return jsonify({"error": "Missing required 'symbols' query parameter, e.g. ?symbols=AAPL,MSFT"}), 400

    days_back = int(request.args.get("days", 45))
    news_limit = int(request.args.get("news_limit", 10))
    start_date = (datetime.date.today() - datetime.timedelta(days=days_back)).isoformat()
    symbols_csv = ",".join(symbols)

    result = {"account": None, "positions": {}, "bars": {}, "news": {}, "errors": []}

    # Account balance
    try:
        r = requests.get(f"{TRADING_BASE}/v2/account", headers=HEADERS, timeout=20)
        r.raise_for_status()
        acct = r.json()
        result["account"] = {"cash": acct.get("cash"), "equity": acct.get("equity")}
    except Exception as e:
        result["errors"].append(f"account: {e}")

    # Current positions (all of them, then filter down to our symbols)
    try:
        r = requests.get(f"{TRADING_BASE}/v2/positions", headers=HEADERS, timeout=20)
        r.raise_for_status()
        positions_list = r.json()
        held = {p["symbol"]: float(p["qty"]) for p in positions_list}
    except Exception as e:
        held = {}
        result["errors"].append(f"positions: {e}")
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

    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
