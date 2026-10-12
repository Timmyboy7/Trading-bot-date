"""
Rebalance - turns the weekly basket into the actual Alpaca portfolio (step 11).

Facts are code, judgment is LLM. The weekly process decides WHICH names may be
owned (Watchlist). This endpoint decides, deterministically, the ORDERS that make
the account match it. v1 written 2026-10-11 (equal weight, hard stop); v2
2026-10-12 adds everything the "buy well, hold long" plan needs:

  Sizing
  - target weights from the basket: strongest 3x the weakest (rank by the
    Watchlist score; a row's target_weight wins if given; RECON_WEIGHT_RATIO),
    on equity x (1 - cash floor)
  - tranches: a new name is built up in REBAL_TRANCHES (3) steps, one per
    REBAL_TRANCHE_DAYS (7): week 1 a third of target, week 2 two thirds, then full
  - drift: top up below target x (1 - band); trim above target x (1 + band)
    ONLY after the 6-month hold (a partial sale inside the hold is taxed in LU)

  Selling (the only reasons to sell inside the 6-month hold, apart from the basket
  itself dropping a name for a red flag / risk swap)
  - dropped: no longer in the basket -> sold in full
  - trend exit (code, daily): close > REBAL_TREND_DD (25%) below the highest close
    since purchase AND below the REBAL_SMA_DAYS (150) day average -> sold in full
  - catastrophic stop: down REBAL_STOP_PCT (-35%) from entry -> sold in full
  - thesis exit: "exit" input from the daily deep dive (Confirm/Veto) -> sold in
    full, no re-buy until the next weekly run

  Buying back after a trend exit / stop (the bear-market-rally trap of 2000):
  only when the close is above the 150-day average AND within REBAL_REBUY_NEAR_HIGH
  (3%) of its 3-month high. Stateless: read from our own client_order_ids.

  Timing guards on buys (the deep dive adds more in step 12)
  - spike: up >= REBAL_SPIKE_PCT (15%) in 5 days -> wait
  - falling knife: down >= REBAL_KNIFE_PCT (15%) in 10 days -> wait
  - "hold" input from the deep dive -> wait
  Waits only work in the first REBAL_MAX_WAIT_DAYS (3) days after the weekly
  run; after that the buy goes through. Nothing can block a buy for good.

  New money (savings plan, dividends, leftovers): once spare cash above the floor
  exceeds REBAL_DEPLOY_MIN_PCT (2%) of capital, it goes to the names furthest below
  their target (never above it, never past the current tranche) - buying laggards is
  the tax-free way to rebalance.

  Savings-plan simulation (Alpaca paper takes no deposits): reset the paper account to
  a larger balance, set REBAL_PAPER_BALANCE to it and REBAL_MONTHLY_DEPOSIT (e.g. 100).
  The bot sees only REBAL_START_EQUITY plus one deposit per month since the start; the
  rest is a hidden reserve. The SPY shadow buys SPY with the same deposits on the same dates.

  The LLM can never add a name, size a position or block the sale of a dropped name.

Endpoints:
    POST /rebalance
      {
        "basket":  Watchlist rows ([{Symbol, score}, ...], JSON string) or "AAA,BBB" csv,
        "execute": false,          // default = dry run (plan only)
        "hold":    "CCC",          // optional (deep dive): delay these buys
        "exit":    "DDD"           // optional (deep dive): confirmed thesis breaks
      }
      -> {as_of, mode, account, orders, skipped, positions, spy_shadow, summary,
          summary_json, orders_json, errors}
    GET /holdings
      -> {holdings: [{symbol, since}], holdings_json}   // for reconcile-basket's "holdings"

Orders only go out when execute is true AND the market is open. Sells go first;
the endpoint waits for fills, re-reads cash and scales buys down if needed.
Never uses margin.
"""
import datetime
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from flask import Blueprint, jsonify, request

rebalance_bp = Blueprint("rebalance", __name__)

TRADING_BASE = os.environ.get("ALPACA_TRADING_BASE", "https://paper-api.alpaca.markets")
DATA_BASE = "https://data.alpaca.markets"
DATA_FEED = os.environ.get("ALPACA_DATA_FEED", "iex")
HEADERS = {
    "APCA-API-KEY-ID": os.environ.get("ALPACA_API_KEY"),
    "APCA-API-SECRET-KEY": os.environ.get("ALPACA_API_SECRET"),
}


def _env(name, default):
    return float(os.environ.get(name, default))


CASH_FLOOR = _env("RISK_CASH_FLOOR_PCT", 0.05)
BAND = _env("REBAL_BAND", 0.25)                      # relative drift band around target
MIN_ORDER_USD = _env("REBAL_MIN_ORDER_USD", 5.0)     # no dust orders
STOP_PCT = _env("REBAL_STOP_PCT", -0.35)             # catastrophic stop from entry
TREND_DD = _env("REBAL_TREND_DD", 0.25)              # trend exit: below high since purchase by this much...
SMA_DAYS = int(_env("REBAL_SMA_DAYS", 150))          # ...and below this moving average
REBUY_NEAR_HIGH = _env("REBAL_REBUY_NEAR_HIGH", 0.03)
HIGH_3M_DAYS = 63
SPIKE_PCT = _env("REBAL_SPIKE_PCT", 0.15)            # +15% in 5 days
KNIFE_PCT = _env("REBAL_KNIFE_PCT", 0.15)            # -15% in 10 days
TRANCHES = int(_env("REBAL_TRANCHES", 3))
TRANCHE_DAYS = int(_env("REBAL_TRANCHE_DAYS", 7))
HOLD_DAYS = int(_env("RECON_HOLD_DAYS", 182))
WEIGHT_RATIO = _env("RECON_WEIGHT_RATIO", 3.0)
MAX_WAIT_DAYS = int(_env("REBAL_MAX_WAIT_DAYS", 3))
CAPITAL_CAP = os.environ.get("REBAL_CAPITAL_CAP_USD")
START_EQUITY = _env("REBAL_START_EQUITY", 1000.0)    # first deposit (SPY shadow, savings plan)
START_DATE = os.environ.get("REBAL_START_DATE")      # else: first fill
MONTHLY_DEPOSIT = _env("REBAL_MONTHLY_DEPOSIT", 0.0)  # simulated savings plan, e.g. 100
# Alpaca paper accounts take no deposits. To simulate a savings plan, reset the paper
# account to a larger balance (e.g. 5000) and set REBAL_PAPER_BALANCE to it: the money
# not "deposited" yet is held back as a reserve that the bot never sees or spends.
PAPER_BALANCE = os.environ.get("REBAL_PAPER_BALANCE")
DEPLOY_MIN_PCT = _env("REBAL_DEPLOY_MIN_PCT", 0.02)   # spare cash above the floor gets invested once > 2%
WEEKLY_UTC_HOUR = int(_env("REBAL_WEEKLY_UTC_HOUR", 18))
FILL_WAIT_SEC = _env("REBAL_FILL_WAIT_SEC", 12)
REBUY_GATED = ("trend", "stop")                      # re-buy needs the buy-back signal
WEEK_BLOCKED = ("exit",)                             # re-buy waits for the next weekly run
LOOKBACK_DAYS = 420


# --------------------------------------------------------------------------- input

def _parse(v):
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("[") or s.startswith("{"):
            v = json.loads(s)
        else:
            v = [x for x in s.split(",")]
    if isinstance(v, dict):
        v = next((x for x in v.values() if isinstance(x, list)), [])
    return v or []


def _key(d, *names):
    low = {str(k).strip().lower().replace(" ", "_"): val for k, val in d.items()}
    for n in names:
        if low.get(n) not in (None, ""):
            return low[n]
    return None


def _num(x):
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None


def parse_basket(v):
    """[(symbol, score, target_weight)] from Watchlist rows, JSON or csv."""
    out, seen = [], set()
    for x in _parse(v):
        if isinstance(x, dict):
            s, sc, w = _key(x, "symbol"), _num(_key(x, "score")), _num(_key(x, "target_weight"))
        else:
            s, sc, w = x, None, None
        s = str(s or "").strip().upper()
        if s and s not in seen:
            seen.add(s)
            out.append((s, sc, w))
    return out


def _symbols(v):
    return [s for s, _, _ in parse_basket(v)] if v not in (None, "") else []


def _bool(v):
    return v is True or str(v).strip().lower() in ("true", "1", "yes")


def basket_weights(rows, ratio=None):
    """{symbol: weight}, sums to 1. Given target_weights win; else 3:1 by score; else equal."""
    ratio = WEIGHT_RATIO if ratio is None else ratio
    if not rows:
        return {}
    if all(w for _, _, w in rows):
        tot = sum(w for _, _, w in rows)
        return {s: w / tot for s, _, w in rows}
    order = sorted(rows, key=lambda r: -(r[1] if r[1] is not None else -1e9)) \
        if any(sc is not None for _, sc, _ in rows) else rows
    n = len(order)
    raw = [1 + (ratio - 1) * (n - 1 - i) / max(n - 1, 1) for i in range(n)] if any(
        sc is not None for _, sc, _ in rows) else [1.0] * n
    tot = sum(raw)
    return {r[0]: w / tot for r, w in zip(order, raw)}


# --------------------------------------------------------------------------- alpaca

def _get(path, base=TRADING_BASE, **params):
    r = requests.get(f"{base}{path}", headers=HEADERS, params=params or None, timeout=15)
    r.raise_for_status()
    return r.json()


def _post_order(payload):
    r = requests.post(f"{TRADING_BASE}/v2/orders", headers=HEADERS, json=payload, timeout=15)
    if r.status_code >= 300:
        return None, f"HTTP {r.status_code}: {r.text[:200]}"
    return r.json(), None


def last_weekly_run(now=None):
    """Most recent Sunday WEEKLY_UTC_HOUR:00 UTC at or before now."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    days_back = (now.weekday() - 6) % 7
    run = (now - datetime.timedelta(days=days_back)).replace(hour=WEEKLY_UTC_HOUR, minute=0, second=0, microsecond=0)
    if run > now:
        run -= datetime.timedelta(days=7)
    return run


def fetch_fills():
    """All FILL activities, oldest first."""
    out, token = [], None
    for _ in range(20):
        params = {"direction": "asc", "page_size": 100}
        if token:
            params["page_token"] = token
        page = _get("/v2/account/activities/FILL", **params)
        if not page:
            break
        out.extend(page)
        if len(page) < 100:
            break
        token = page[-1].get("id")
    return out


def holdings_since(fills, positions):
    """{symbol: date the current position was opened} (qty went from 0 to > 0 the last time)."""
    qty, since = {}, {}
    for f in fills:
        s = f.get("symbol")
        q = _num(f.get("qty")) or 0.0
        q = q if f.get("side") == "buy" else -q
        before = qty.get(s, 0.0)
        after = before + q
        d = str(f.get("transaction_time") or "")[:10]
        if before <= 1e-9 and after > 1e-9 and d:
            since[s] = d
        qty[s] = after if after > 1e-9 else 0.0
    today = datetime.date.today().isoformat()
    return {p["symbol"]: since.get(p["symbol"], today) for p in positions}


def last_own_orders(days=200):
    """{symbol: (kind, side, created_at)} of our most recent non-cancelled order per symbol."""
    after = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()
    orders = _get("/v2/orders", status="all", after=after, limit=500, direction="desc")
    out = {}
    for o in orders:
        cid = str(o.get("client_order_id") or "")
        if not cid.startswith("tb-") or o.get("status") in ("canceled", "rejected", "expired"):
            continue
        if o["symbol"] not in out:
            out[o["symbol"]] = (cid.split("-")[1], o.get("side"), str(o.get("created_at") or ""))
    return out


def daily_closes(symbols, today=None):
    """{symbol: [(date, close), ...]} split-adjusted, completed days only (today's bar dropped)."""
    today = today or datetime.date.today()
    start = (today - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat()
    out = {}
    syms = sorted(set(symbols))
    for i in range(0, len(syms), 100):
        token = None
        while True:
            params = {"symbols": ",".join(syms[i:i + 100]), "timeframe": "1Day", "start": start,
                      "adjustment": "split", "feed": DATA_FEED, "limit": 10000}
            if token:
                params["page_token"] = token
            r = requests.get(f"{DATA_BASE}/v2/stocks/bars", headers=HEADERS, params=params, timeout=25)
            if r.status_code != 200:
                break
            data = r.json()
            for s, bars in (data.get("bars") or {}).items():
                out.setdefault(s, []).extend((b["t"][:10], float(b["c"])) for b in bars)
            token = data.get("next_page_token")
            if not token:
                break
    iso = today.isoformat()
    return {s: [x for x in v if x[0] < iso] for s, v in out.items()}


# --------------------------------------------------------------------------- indicators

def indicators(series, since=None):
    """Facts the rules need, from [(date, close)] oldest first."""
    if not series:
        return None
    closes = [c for _, c in series]
    last = closes[-1]
    sma = sum(closes[-SMA_DAYS:]) / len(closes[-SMA_DAYS:]) if len(closes) >= min(SMA_DAYS, 60) else None
    hi_since = max([c for d, c in series if since is None or d >= since] or [last])
    hi3m = max(closes[-HIGH_3M_DAYS:])

    def ret(n):
        return last / closes[-1 - n] - 1 if len(closes) > n and closes[-1 - n] else None
    return {"close": last, "date": series[-1][0], "sma": sma, "high_since": hi_since, "high_3m": hi3m,
            "ret5": ret(5), "ret10": ret(10),
            "dd_from_high": last / hi_since - 1 if hi_since else 0.0}


def trend_broken(ind):
    return bool(ind and ind["sma"] and ind["dd_from_high"] <= -TREND_DD and ind["close"] < ind["sma"])


def buyback_ok(ind):
    return bool(ind and ind["sma"] and ind["close"] > ind["sma"]
                and ind["close"] >= ind["high_3m"] * (1 - REBUY_NEAR_HIGH))


def tranche_fraction(since, today):
    """Share of the target a position may have reached by today."""
    if since is None:
        return 1.0 / TRANCHES
    days = (today - datetime.date.fromisoformat(since)).days
    return min(1.0, (1 + days // TRANCHE_DAYS) / TRANCHES)


# --------------------------------------------------------------------------- plan

def plan(basket_rows, account, positions, ind, since, last_orders, hold=(), exits=(),
         weekly_run=None, now=None):
    """Pure function: inputs -> orders. No network, so it is fully testable.

    ind: {symbol: indicators(...)}; since: {symbol: 'YYYY-MM-DD'} for held names;
    last_orders: {symbol: (kind, side, created_at)} of our latest order."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    today = now.date()
    weekly_run = weekly_run or last_weekly_run(now)
    equity, cash = float(account["equity"]), float(account["cash"])
    capital = min(equity, float(CAPITAL_CAP)) if CAPITAL_CAP else equity
    investable = capital * (1 - CASH_FLOOR)
    weights = basket_weights(basket_rows)
    basket = [s for s, _, _ in basket_rows]
    waits_allowed = (now - weekly_run).days < MAX_WAIT_DAYS
    stamp = now.strftime("%Y%m%d%H%M%S")
    pos = {p["symbol"]: p for p in positions}
    sells, buys, skipped, notes = [], [], [], {}
    room = {}   # symbol -> (desired value today, current value), for deploying spare cash

    def held_days(s):
        return (today - datetime.date.fromisoformat(since[s])).days if s in since else 0

    def full_exit(sym, kind, reason):
        p = pos[sym]
        sells.append({"symbol": sym, "side": "sell", "kind": kind, "qty": p["qty"],
                      "amount_usd": round(float(p["market_value"]), 2), "reason": reason,
                      "client_order_id": f"tb-{kind}-{sym}-{stamp}"})

    # 1. full exits
    for sym, p in pos.items():
        plpc = float(p.get("unrealized_plpc") or 0)
        i = ind.get(sym)
        hd = held_days(sym)
        in_hold = f" (inside the 6-month hold, day {hd})" if hd < HOLD_DAYS else ""
        if sym not in basket:
            full_exit(sym, "drop", "no longer in the weekly basket" + in_hold)
        elif sym in exits:
            full_exit(sym, "exit", "thesis break confirmed by the deep dive - no re-buy until the next weekly run" + in_hold)
        elif plpc <= STOP_PCT:
            full_exit(sym, "stop", f"down {plpc:.0%} from entry (catastrophic stop {STOP_PCT:.0%}); "
                                   "re-buy only on the buy-back signal" + in_hold)
        elif trend_broken(i):
            full_exit(sym, "trend", f"trend exit: {abs(i['dd_from_high']):.0%} below the high since purchase and "
                                    f"below the {SMA_DAYS}-day average ({i['close']:.2f} < {i['sma']:.2f}); "
                                    "re-buy only on the buy-back signal" + in_hold)
    sold = {s["symbol"] for s in sells}

    # 2. buys / trims per basket name
    for sym in basket:
        if sym in sold:
            continue
        target = investable * weights.get(sym, 0.0)
        value = float(pos[sym]["market_value"]) if sym in pos else 0.0
        i = ind.get(sym)
        held = sym in pos
        lo = last_orders.get(sym)

        # re-buy gates (only for names we are out of)
        if not held and lo and lo[1] == "sell":
            if lo[0] in WEEK_BLOCKED and lo[2] >= weekly_run.isoformat():
                skipped.append({"symbol": sym, "reason": "thesis exit this week - re-buy waits for the next weekly run"})
                continue
            if lo[0] in REBUY_GATED and not buyback_ok(i):
                why = "no price data" if not i else (
                    f"close {i['close']:.2f} vs {SMA_DAYS}-day average {i['sma']:.2f} and 3-month high {i['high_3m']:.2f}"
                    if i["sma"] else "not enough history")
                skipped.append({"symbol": sym, "reason": f"after a {lo[0]} exit: waiting for the buy-back signal ({why})"})
                continue

        frac = tranche_fraction(since.get(sym) if held else None, today)
        desired = target * frac
        room[sym] = (desired, value)
        if value < desired * (1 - BAND) or not held:
            amount = desired - value
            if amount < MIN_ORDER_USD:
                continue
            wait = None
            if sym in hold:
                wait = "buy delayed by the deep dive (timing)"
            elif i and i["ret5"] is not None and i["ret5"] >= SPIKE_PCT:
                wait = f"spike: up {i['ret5']:.0%} in 5 days"
            elif i and i["ret10"] is not None and i["ret10"] <= -KNIFE_PCT:
                wait = f"falling knife: down {abs(i['ret10']):.0%} in 10 days"
            if wait and waits_allowed:
                skipped.append({"symbol": sym, "reason": wait + f" - waits at most {MAX_WAIT_DAYS} days after the weekly run"})
                continue
            in_buildup = not held or held_days(sym) < TRANCHES * TRANCHE_DAYS
            kind = "new" if not held else ("tranche" if in_buildup else "drift")
            step = min(TRANCHES, int(round(frac * TRANCHES)))
            reason = (f"tranche {step}/{TRANCHES} of target {target:.2f} ({weights.get(sym, 0):.1%} of the basket)"
                      if in_buildup else f"below target ({value:.2f} vs {target:.2f})")
            if wait:
                reason += f" [{wait}, max wait over]"
            buys.append({"symbol": sym, "side": "buy", "kind": kind, "amount_usd": round(amount, 2),
                         "reason": reason, "client_order_id": f"tb-buy-{sym}-{stamp}"})
        elif value > target * (1 + BAND) and frac >= 1:
            amount = value - target
            if amount < MIN_ORDER_USD:
                continue
            if held_days(sym) < HOLD_DAYS:
                notes[sym] = (f"above target ({value:.2f} vs {target:.2f}) but in the 6-month hold "
                              f"(day {held_days(sym)}) - no trim (tax)")
                continue
            sells.append({"symbol": sym, "side": "sell", "kind": "trim", "amount_usd": round(amount, 2),
                          "reason": f"above target ({value:.2f} vs {target:.2f})",
                          "client_order_id": f"tb-trim-{sym}-{stamp}"})

    proceeds = sum(s["amount_usd"] for s in sells)
    deployed = deploy_spare(buys, room, skipped, cash + proceeds, capital, stamp)
    scale = scale_buys(buys, cash + proceeds, capital)
    return {"capital": round(capital, 2), "investable": round(investable, 2), "weights": weights,
            "sells": sells, "buys": buys, "skipped": skipped, "notes": notes, "buy_scale": scale,
            "deployed_spare": deployed}


def deploy_spare(buys, room, skipped, cash_available, capital, stamp):
    """New money (deposits, dividends, leftovers) goes to the names furthest below their
    target, never above it. Buying the laggards is the tax-free way to rebalance.
    Only runs when spare cash above the floor exceeds DEPLOY_MIN_PCT of capital. Mutates buys."""
    planned = {b["symbol"]: b for b in buys}
    spare = cash_available - sum(b["amount_usd"] for b in buys) - CASH_FLOOR * capital
    if spare < max(MIN_ORDER_USD, DEPLOY_MIN_PCT * capital):
        return 0.0
    waiting = {x["symbol"] for x in skipped}
    gaps = {s: d - v - (planned[s]["amount_usd"] if s in planned else 0.0)
            for s, (d, v) in room.items() if s not in waiting}
    gaps = {s: g for s, g in gaps.items() if g > 0.5}
    total = sum(gaps.values())
    if total <= 0:
        return 0.0
    use = min(spare, total)
    done = 0.0
    for s, g in sorted(gaps.items(), key=lambda x: -x[1]):
        amt = round(use * g / total, 2)
        if s in planned:
            planned[s]["amount_usd"] = round(planned[s]["amount_usd"] + amt, 2)
            planned[s]["reason"] += f" (+{amt:.2f} new money)"
            done += amt
        elif amt >= MIN_ORDER_USD:
            buys.append({"symbol": s, "side": "buy", "kind": "deploy", "amount_usd": amt,
                         "reason": f"new money to an underweight name ({room[s][1]:.2f} vs {room[s][0]:.2f})",
                         "client_order_id": f"tb-buy-{s}-{stamp}"})
            done += amt
    return round(done, 2)


def scale_buys(buys, cash_available, capital):
    """Scale all buys down proportionally if they would breach the cash floor. Mutates buys."""
    spendable = max(cash_available - CASH_FLOOR * capital * 0.5, 0.0)   # keep at least half the floor as slack
    need = sum(b["amount_usd"] for b in buys)
    if need <= spendable or need == 0:
        return 1.0
    scale = spendable / need
    for b in buys:
        b["amount_usd"] = round(b["amount_usd"] * scale, 2)
        b["reason"] += f" (scaled to {scale:.0%}: not enough cash)"
    buys[:] = [b for b in buys if b["amount_usd"] >= MIN_ORDER_USD]
    return round(scale, 3)


def deposit_schedule(start_date, today):
    """[(date, amount)]: START_EQUITY on the start date, then MONTHLY_DEPOSIT on the same
    day of each following month (end of month if that day doesn't exist)."""
    start = datetime.date.fromisoformat(start_date) if start_date else today
    out = [(start, START_EQUITY)]
    if MONTHLY_DEPOSIT <= 0:
        return out
    y, m = start.year, start.month
    while True:
        m += 1
        if m > 12:
            y, m = y + 1, 1
        day = min(start.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28,
                              31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
        d = datetime.date(y, m, day)
        if d > today:
            return out
        out.append((d, MONTHLY_DEPOSIT))


def virtual_account(account, deposits):
    """Account as the bot should see it: with REBAL_PAPER_BALANCE set, money not yet
    'deposited' is a hidden reserve (subtracted from equity and cash)."""
    if not PAPER_BALANCE:
        return account, 0.0
    reserve = max(float(PAPER_BALANCE) - sum(a for _, a in deposits), 0.0)
    return {"equity": float(account["equity"]) - reserve, "cash": float(account["cash"]) - reserve}, reserve


def spy_shadow(equity, spy_series, deposits, started):
    """The same deposits, on the same dates, put into SPY instead - vs the account."""
    if not started or not spy_series:
        return {"note": "no trades yet - the shadow starts with the first fill"}
    units = 0.0
    for d, amt in deposits:
        px = next((c for day, c in spy_series if day >= d.isoformat()), spy_series[-1][1])
        units += amt / px
    spy_value = units * spy_series[-1][1]
    paid_in = sum(a for _, a in deposits)
    return {"start": deposits[0][0].isoformat(), "paid_in": round(paid_in, 2), "deposits": len(deposits),
            "spy_value": round(spy_value, 2), "account_value": round(equity, 2),
            "spy_gain_pct": round((spy_value / paid_in - 1) * 100, 2),
            "account_gain_pct": round((equity / paid_in - 1) * 100, 2),
            "excess_usd": round(equity - spy_value, 2),
            "excess_pct": round((equity - spy_value) / paid_in * 100, 2),
            "as_of_close": spy_series[-1][0]}


# --------------------------------------------------------------------------- execute

def _order_payload(o):
    base = {"symbol": o["symbol"], "side": o["side"], "type": "market", "time_in_force": "day",
            "client_order_id": o["client_order_id"]}
    if "qty" in o:
        base["qty"] = str(o["qty"])
    else:
        base["notional"] = f"{o['amount_usd']:.2f}"
    return base


def _submit(orders, errors):
    def one(o):
        res, err = _post_order(_order_payload(o))
        if err:
            o["status"], o["error"] = "failed", err
            errors.append(f"{o['symbol']} {o['side']}: {err}")
        else:
            o["status"], o["order_id"] = res.get("status"), res.get("id")
        return o
    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(one, orders))


def _wait_for_fills(orders):
    ids = [o["order_id"] for o in orders if o.get("order_id")]
    deadline = time.time() + FILL_WAIT_SEC
    while ids and time.time() < deadline:
        time.sleep(1.5)
        still = []
        for oid in ids:
            try:
                st = _get(f"/v2/orders/{oid}").get("status")
            except requests.RequestException:
                st = "unknown"
            if st not in ("filled", "canceled", "rejected", "expired"):
                still.append(oid)
        ids = still
    return ids


def gather(basket_syms):
    """Everything plan() needs from Alpaca. Partial failures are reported, not fatal."""
    errors = []
    account = _get("/v2/account")
    positions = _get("/v2/positions")
    clock = _get("/v2/clock")
    try:
        fills = fetch_fills()
    except requests.RequestException as e:
        fills, _ = [], errors.append(f"fills: {e} - purchase dates unknown (hold/tranches count from today)")
    since = holdings_since(fills, positions)
    try:
        last_orders = last_own_orders()
    except requests.RequestException as e:
        last_orders, _ = {}, errors.append(f"orders: {e} - re-buy gates off")
    syms = set(basket_syms) | {p["symbol"] for p in positions} | {"SPY"}
    try:
        closes = daily_closes(syms)
    except requests.RequestException as e:
        closes, _ = {}, errors.append(f"bars: {e} - trend exit and timing guards off")
    ind = {s: indicators(closes.get(s), since.get(s)) for s in syms if closes.get(s)}
    missing = sorted(s for s in syms if s not in ind)
    if missing:
        errors.append(f"no price history: {', '.join(missing)}")
    first_fill = str(fills[0].get("transaction_time") or "")[:10] if fills else None
    return account, positions, clock, since, last_orders, closes, ind, START_DATE or first_fill, errors


def run(basket_rows, execute=False, hold=(), exits=()):
    now = datetime.datetime.now(datetime.timezone.utc)
    basket = [s for s, _, _ in basket_rows]
    account_real, positions, clock, since, last_orders, closes, ind, start, errors = gather(basket)
    weekly = last_weekly_run(now)
    deposits = deposit_schedule(start, now.date())
    account, reserve = virtual_account(account_real, deposits)
    if account["cash"] < -1:
        errors.append(f"paper balance too small for the simulated deposits (reserve {reserve:.2f}) - check REBAL_PAPER_BALANCE")
    p = plan(basket_rows, account, positions, ind, since, last_orders,
             hold=set(hold), exits=set(exits), weekly_run=weekly, now=now)
    orders = p["sells"] + p["buys"]
    mode = "dry_run"
    if execute and not clock.get("is_open"):
        mode = "market_closed"
        errors.append("market closed - nothing placed (run again during US market hours)")
    elif execute:
        mode = "executed"
        _submit(p["sells"], errors)
        pending = _wait_for_fills(p["sells"])
        if pending:
            errors.append(f"{len(pending)} sell(s) not filled after {FILL_WAIT_SEC:.0f}s - buys sized from current cash")
        fresh = _get("/v2/account")
        p["buy_scale"] = scale_buys(p["buys"], float(fresh["cash"]) - reserve, p["capital"])
        _submit(p["buys"], errors)
        orders = p["sells"] + p["buys"]
    for o in orders:
        o.setdefault("status", "planned")

    equity = float(account["equity"])
    today = now.date()
    pos_view = []
    for x in sorted(positions, key=lambda x: -float(x["market_value"])):
        s, i = x["symbol"], ind.get(x["symbol"])
        d = (today - datetime.date.fromisoformat(since[s])).days if s in since else None
        pos_view.append({
            "symbol": s, "value": round(float(x["market_value"]), 2),
            "weight": round(float(x["market_value"]) / equity, 4) if equity else None,
            "target_weight": round(p["weights"].get(s, 0) * (1 - CASH_FLOOR), 4),
            "pl_pct": round(float(x.get("unrealized_plpc") or 0) * 100, 1),
            "since": since.get(s), "hold": (f"in hold, day {d} of {HOLD_DAYS}" if d is not None and d < HOLD_DAYS
                                            else "past hold"),
            "below_high_pct": round(i["dd_from_high"] * 100, 1) if i else None,
            "vs_sma_pct": round((i["close"] / i["sma"] - 1) * 100, 1) if i and i["sma"] else None,
            "note": p["notes"].get(s, ""),
        })
    shadow = spy_shadow(equity, closes.get("SPY"), deposits, bool(start))
    summary = {
        "mode": mode, "basket": len(basket), "positions_before": len(positions),
        "equity": round(equity, 2), "cash": round(float(account["cash"]), 2),
        "capital": p["capital"], "investable": p["investable"],
        "sells": len(p["sells"]), "buys": len(p["buys"]), "skipped": len(p["skipped"]),
        "sell_usd": round(sum(o["amount_usd"] for o in p["sells"]), 2),
        "buy_usd": round(sum(o["amount_usd"] for o in p["buys"]), 2),
        "buy_scale": p["buy_scale"], "deployed_spare": p["deployed_spare"],
        "paid_in": round(sum(a for _, a in deposits), 2), "hidden_reserve": round(reserve, 2), "failed": sum(1 for o in orders if o.get("status") == "failed"),
        "exits": {k: [o["symbol"] for o in p["sells"] if o["kind"] == k]
                  for k in ("drop", "trend", "stop", "exit", "trim") if any(o["kind"] == k for o in p["sells"])},
        "spy_shadow": shadow, "weekly_run": weekly.isoformat(),
        "settings": {"cash_floor": CASH_FLOOR, "band": BAND, "stop_pct": STOP_PCT, "trend_dd": TREND_DD,
                     "sma_days": SMA_DAYS, "tranches": TRANCHES, "tranche_days": TRANCHE_DAYS,
                     "hold_days": HOLD_DAYS, "weight_ratio": WEIGHT_RATIO,
                     "monthly_deposit": MONTHLY_DEPOSIT, "paper_balance": PAPER_BALANCE, "spike_pct": SPIKE_PCT,
                     "knife_pct": KNIFE_PCT, "max_wait_days": MAX_WAIT_DAYS, "capital_cap": CAPITAL_CAP},
    }
    slim = [{k: o.get(k) for k in ("symbol", "side", "kind", "amount_usd", "qty", "status", "reason", "error")
             if o.get(k) is not None} for o in orders]
    return {
        "as_of": now.isoformat(timespec="seconds"), "mode": mode,
        "account": {"equity": summary["equity"], "cash": summary["cash"], "capital": p["capital"]},
        "orders": orders, "skipped": p["skipped"], "positions": pos_view, "spy_shadow": shadow,
        "summary": summary, "summary_json": json.dumps(summary),
        "orders_json": json.dumps(slim + [{"symbol": s["symbol"], "status": "skipped", "reason": s["reason"]}
                                          for s in p["skipped"]]),
        "errors": errors[:30],
    }


@rebalance_bp.route("/rebalance", methods=["POST"])
def rebalance():
    body = request.get_json(force=True, silent=True) or {}
    try:
        rows = parse_basket(body.get("basket"))
        hold = _symbols(body.get("hold"))
        exits = _symbols(body.get("exit"))
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"could not parse input: {e}"}), 400
    if len(rows) < 5:
        return jsonify({"error": f"basket has {len(rows)} names - refusing to rebalance (expected about 20)"}), 400
    try:
        return jsonify(run(rows, execute=_bool(body.get("execute")), hold=hold, exits=exits))
    except requests.RequestException as e:
        return jsonify({"error": f"Alpaca request failed: {e}"}), 502


@rebalance_bp.route("/holdings", methods=["GET"])
def holdings():
    """Current positions with the date each was opened - feeds reconcile-basket's 6-month hold."""
    try:
        positions = _get("/v2/positions")
        since = holdings_since(fetch_fills(), positions)
    except requests.RequestException as e:
        return jsonify({"error": f"Alpaca request failed: {e}"}), 502
    rows = [{"symbol": s, "since": d} for s, d in sorted(since.items())]
    return jsonify({"holdings": rows, "holdings_json": json.dumps(rows), "count": len(rows)})
