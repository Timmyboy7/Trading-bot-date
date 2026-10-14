"""
Alarm - a cheap, code-only check that Make calls every 30 minutes while the US market is
open. It costs no AI money. When something serious happens to the portfolio it answers
"fire": true, and Make then starts the daily chain at once instead of waiting for 20:00.

Built 2026-10-14 (roadmap: "Daily Crisis alarm"). It never trades itself: the daily chain
(news analysts, vetoes, /rebalance) decides what to do, with today's live prices.

Fires on (all thresholds are env settings):
  - market:    SPY down ALARM_SPY_DAY_PCT (3%) or more today
  - drop:      a held stock down ALARM_STOCK_DAY_PCT (7%) or more today, or
               ALARM_VS_SPY_PTS (6) points worse than SPY today
  - trend:     a held stock now meets the trend exit (25% below its high since purchase
               AND below the 150-day average), counting today's price
  - stop:      a held stock at the catastrophic stop (-35% from entry)
  - knife:     a basket name not bought yet (pending tranche) down ALARM_STOCK_DAY_PCT today
               (only when Make passes ?basket=..., optional)

Each reason fires once per day (memory of this server; a restart may fire one extra time,
which is harmless because the daily chain is idempotent: it only buys up to the targets).
At most ALARM_MAX_FIRES_PER_DAY (2) fires per day. Never fires while the market is closed.

    GET /alarm[?basket=SNDK,MU,...]
      -> {fire, reasons, new_reasons, market_open, spy_day_pct, checked, fires_today, as_of, errors}
"""
import datetime
import os

import requests
from flask import Blueprint, jsonify, request

import rebalance as rb

alarm_bp = Blueprint("alarm", __name__)

SPY_DAY_PCT = float(os.environ.get("ALARM_SPY_DAY_PCT", 3))
STOCK_DAY_PCT = float(os.environ.get("ALARM_STOCK_DAY_PCT", 7))
VS_SPY_PTS = float(os.environ.get("ALARM_VS_SPY_PTS", 6))
MAX_FIRES = int(os.environ.get("ALARM_MAX_FIRES_PER_DAY", 2))

_FIRED = {}   # date -> {"keys": set(), "fires": int}


def day_pct(x):
    if not x or not x.get("prev_close"):
        return None
    return round((x["price"] / x["prev_close"] - 1) * 100, 2)


def check(positions, live, ind, basket=()):
    """Pure function: -> list of {key, kind, symbol, text}. live: {sym: {price, prev_close}};
    ind: {sym: rebalance.indicators(...)} computed WITH today's live price."""
    out = []
    spy = day_pct(live.get("SPY"))
    if spy is not None and spy <= -SPY_DAY_PCT:
        out.append({"key": "market", "kind": "market", "symbol": "SPY",
                    "text": f"market: SPY {spy:+.1f}% today (alarm at -{SPY_DAY_PCT:g}%)"})
    held = set()
    for p in positions:
        s = p["symbol"]
        held.add(s)
        d = day_pct(live.get(s))
        plpc = float(p.get("unrealized_plpc") or 0)
        if plpc <= rb.STOP_PCT:
            out.append({"key": f"stop:{s}", "kind": "stop", "symbol": s,
                        "text": f"{s}: {plpc:.0%} from entry - at the catastrophic stop ({rb.STOP_PCT:.0%})"})
        elif rb.trend_broken(ind.get(s)):
            i = ind[s]
            out.append({"key": f"trend:{s}", "kind": "trend", "symbol": s,
                        "text": f"{s}: trend exit now met ({abs(i['dd_from_high']):.0%} below its high since purchase, "
                                f"below the {rb.SMA_DAYS}-day average)"})
        if d is not None and (d <= -STOCK_DAY_PCT or (spy is not None and d - spy <= -VS_SPY_PTS)):
            rel = f", {d - spy:+.1f} pts vs SPY" if spy is not None else ""
            out.append({"key": f"drop:{s}", "kind": "drop", "symbol": s,
                        "text": f"{s}: {d:+.1f}% today{rel}"})
    for s in basket:
        if s in held:
            continue
        d = day_pct(live.get(s))
        if d is not None and d <= -STOCK_DAY_PCT:
            out.append({"key": f"knife:{s}", "kind": "knife", "symbol": s,
                        "text": f"{s} (buy pending): {d:+.1f}% today - re-check before buying"})
    return out


def decide(reasons, today, fired=None):
    """Once per reason per day, at most MAX_FIRES per day. Mutates `fired`."""
    fired = _FIRED if fired is None else fired
    for k in [k for k in fired if k != today]:
        del fired[k]
    st = fired.setdefault(today, {"keys": set(), "fires": 0})
    new = [r for r in reasons if r["key"] not in st["keys"]]
    fire = bool(new) and st["fires"] < MAX_FIRES
    if fire:
        st["fires"] += 1
        st["keys"].update(r["key"] for r in new)
    return fire, new, st["fires"]


@alarm_bp.route("/alarm", methods=["GET", "POST"])
def alarm():
    now = datetime.datetime.now(datetime.timezone.utc)
    errors = []
    basket = rb._symbols(request.args.get("basket") or (request.get_json(silent=True) or {}).get("basket") or "")
    try:
        clock = rb._get("/v2/clock")
        positions = rb._get("/v2/positions")
    except requests.RequestException as e:
        return jsonify({"fire": False, "error": f"Alpaca request failed: {e}"}), 502
    base = {"as_of": now.isoformat(timespec="seconds"), "market_open": bool(clock.get("is_open")),
            "checked": len(positions)}
    if not clock.get("is_open"):
        return jsonify({**base, "fire": False, "reasons": [], "new_reasons": [], "text": "market closed", "errors": []})
    held = {p["symbol"] for p in positions}
    syms = held | set(basket) | {"SPY"}
    try:
        live = rb.live_prices(syms)
    except requests.RequestException as e:
        live, _ = {}, errors.append(f"snapshots: {e}")
    ind = {}
    if held:
        try:
            since = rb.holdings_since(rb.fetch_fills(), positions)
            closes = rb.daily_closes(held, live=True)
            ind = {s: rb.indicators(closes.get(s), since.get(s)) for s in held if closes.get(s)}
        except requests.RequestException as e:
            errors.append(f"bars: {e} - trend check off")
    reasons = check(positions, live, ind, basket)
    fire, new, fires = decide(reasons, now.date().isoformat())
    return jsonify({**base, "fire": fire, "reasons": [r["text"] for r in reasons],
                    "new_reasons": [r["text"] for r in new], "fires_today": fires,
                    "spy_day_pct": day_pct(live.get("SPY")),
                    "text": "; ".join(r["text"] for r in new) if fire else "all quiet",
                    "errors": errors})
