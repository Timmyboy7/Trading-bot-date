"""
Insider-buying signals from SEC EDGAR Form 4 filings (code only, no LLM).

Why: the price/fundamentals pipeline is backward-looking. Insiders (officers,
directors, 10% owners) must report their trades to the SEC within two business
days on Form 4, so their OPEN-MARKET PURCHASES are a cheap, official,
forward-looking input that arrives within days, not weeks.

Method (deliberately simple and transparent):
  1. ticker -> CIK from SEC's company_tickers.json (cached 24h).
  2. The company's EDGAR "submissions" feed lists its recent filings; keep the
     Form 4s filed in the last LOOKBACK_DAYS (newest first, at most MAX_FILINGS).
  3. Download each Form 4's raw XML and read the non-derivative transactions.
     Only transaction code "P" (open-market purchase) and "S" (open-market sale)
     are counted. Grants (A), option exercises (M), tax withholding (F), gifts (G)
     etc. are ignored: they are compensation mechanics, not conviction.
  4. Aggregate per symbol: distinct buyers, dollars bought, distinct sellers,
     dollars sold, latest buy.
  5. Turn it into a small, capped, DETERMINISTIC score adjustment (see
     adjustment_for). Purchases earn a bonus; sales earn nothing, because
     insiders sell for many unrelated reasons (taxes, diversification, scheduled
     plans), so sales are shown but not scored.

Endpoint:
    GET /signals?symbols=AAPL,MSFT,...&days=90&max_filings=8&budget=25
    -> {as_of, lookback_days, signals:[...], signals_json:"...", summary:{...}}

Speed/robustness:
  * SEC allows ~10 requests/second and REQUIRES a User-Agent with contact info:
    set SEC_USER_AGENT on Render, e.g.  "Trading-bot-date you@example.com".
  * Render's proxy kills requests at ~40s, so each call has a time budget
    (default 25s). Symbols not finished in time come back as status "pending"
    and keep loading in the background; results are cached 12h, so a second
    call a minute later returns everything.
  * One failing symbol never fails the call (status "error" for that symbol).
"""
import datetime
import json
import os
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, wait

import requests
from flask import Blueprint, jsonify, request

signals_bp = Blueprint("signals", __name__)

SEC_UA = os.environ.get("SEC_USER_AGENT", "Trading-bot-date (set SEC_USER_AGENT env var with contact email)")
LOOKBACK_DAYS = int(os.environ.get("SIGNALS_LOOKBACK_DAYS", 90))
MAX_FILINGS = int(os.environ.get("SIGNALS_MAX_FILINGS", 8))
CACHE_TTL = 12 * 3600
ERROR_TTL = 300
MIN_INTERVAL = 0.125  # ~8 requests/second, under SEC's 10/s limit

# score adjustment rules (on the 1-5 rubric scale; capped at MAX_ADJ)
MAX_ADJ = 0.20

_rl_lock = threading.Lock()
_last_call = [0.0]
_cache_lock = threading.Lock()
_CACHE = {}      # (symbol, lookback) -> (timestamp, ttl, result)
_INFLIGHT = {}   # (symbol, lookback) -> Future
_TICKERS = {"ts": 0.0, "map": {}}
_EXECUTOR = None


# ---------------------------------------------------------------- HTTP helpers
def _throttle():
    with _rl_lock:
        wait_for = _last_call[0] + MIN_INTERVAL - time.monotonic()
        if wait_for > 0:
            time.sleep(wait_for)
        _last_call[0] = time.monotonic()


def _get(url, as_json=False):
    last_exc = None
    for attempt in range(2):
        _throttle()
        r = requests.get(
            url,
            headers={"User-Agent": SEC_UA, "Accept-Encoding": "gzip, deflate"},
            timeout=15,
        )
        if r.status_code in (429, 503) and attempt == 0:
            time.sleep(1.5)
            continue
        try:
            r.raise_for_status()
        except requests.HTTPError as e:
            last_exc = e
            raise
        return r.json() if as_json else r.text
    raise last_exc or RuntimeError("request failed")


def _ticker_map():
    now = time.time()
    if _TICKERS["map"] and now - _TICKERS["ts"] < 24 * 3600:
        return _TICKERS["map"]
    data = _get("https://www.sec.gov/files/company_tickers.json", as_json=True)
    m = {}
    for row in data.values():
        t = str(row.get("ticker", "")).upper()
        if t:
            m[t] = int(row["cik_str"])
    _TICKERS["map"], _TICKERS["ts"] = m, now
    return m


def _cik_for(symbol):
    m = _ticker_map()
    s = symbol.upper()
    return m.get(s) or m.get(s.replace(".", "-"))


# ---------------------------------------------------------------- EDGAR parsing
def recent_form4s(submissions, lookback_days, cap, today=None):
    """From a submissions JSON, the newest Form 4 filings inside the lookback window."""
    today = today or datetime.date.today()
    cutoff = (today - datetime.timedelta(days=lookback_days)).isoformat()
    rec = (submissions.get("filings") or {}).get("recent") or {}
    forms = rec.get("form") or []
    dates = rec.get("filingDate") or []
    accs = rec.get("accessionNumber") or []
    docs = rec.get("primaryDocument") or []
    out = []
    for i, form in enumerate(forms):
        if form != "4":
            continue
        if i >= len(dates) or i >= len(accs) or i >= len(docs):
            continue
        if dates[i] < cutoff:
            continue
        out.append({"filed": dates[i], "accession": accs[i], "doc": docs[i]})
    out.sort(key=lambda f: f["filed"], reverse=True)
    return out[:cap]


def raw_xml_url(cik, filing):
    """primaryDocument is often the XSL-rendered view ('xslF345X05/form4.xml');
    the raw XML sits in the same folder without that prefix."""
    name = filing["doc"].split("/")[-1]
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{filing['accession'].replace('-', '')}/{name}"


def _flag(v):
    return str(v or "").strip().lower() in ("1", "true")


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_form4(xml_text):
    """Form 4 XML -> list of non-derivative transactions with insider info."""
    root = ET.fromstring(xml_text)
    owners = []
    for ro in root.findall("reportingOwner"):
        rel = ro.find("reportingOwnerRelationship")
        officer = rel is not None and _flag(rel.findtext("isOfficer"))
        director = rel is not None and _flag(rel.findtext("isDirector"))
        ten = rel is not None and _flag(rel.findtext("isTenPercentOwner"))
        title = (rel.findtext("officerTitle") or "").strip() if rel is not None else ""
        role = title if (officer and title) else "Officer" if officer else "Director" if director else "10% owner" if ten else "Other"
        owners.append({
            "name": (ro.findtext("reportingOwnerId/rptOwnerName") or "").strip(),
            "role": role,
            "insider_class": officer or director or ten,
        })
    owner = owners[0] if owners else {"name": "", "role": "Other", "insider_class": False}

    txs = []
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = (tx.findtext("transactionCoding/transactionCode") or "").strip().upper()
        shares = _num(tx.findtext("transactionAmounts/transactionShares/value"))
        price = _num(tx.findtext("transactionAmounts/transactionPricePerShare/value"))
        txs.append({
            "date": (tx.findtext("transactionDate/value") or "").strip(),
            "code": code,
            "shares": shares,
            "price": price,
            "insider": owner["name"],
            "role": owner["role"],
            "insider_class": owner["insider_class"],
        })
    return txs


# ---------------------------------------------------------------- scoring
def adjustment_for(buyers, total_usd, any_insider_class):
    """Deterministic, capped bonus for open-market buying. Returns (adj, reason)."""
    if buyers >= 3 and total_usd >= 250_000:
        return 0.20, "cluster buying"
    if buyers >= 2 and total_usd >= 100_000:
        return 0.15, "multiple insiders buying"
    if buyers >= 1 and total_usd >= 100_000 and any_insider_class:
        return 0.10, "sizeable insider purchase"
    if buyers >= 1 and total_usd >= 25_000 and any_insider_class:
        return 0.05, "small insider purchase"
    return 0.0, ""


def summarize(symbol, txs, lookback_days, filings_checked):
    buys = [t for t in txs if t["code"] == "P" and (t["shares"] or 0) > 0 and (t["price"] or 0) > 0]
    sells = [t for t in txs if t["code"] == "S" and (t["shares"] or 0) > 0 and (t["price"] or 0) > 0]
    val = lambda t: t["shares"] * t["price"]
    buy_usd = sum(val(t) for t in buys)
    sell_usd = sum(val(t) for t in sells)
    buyers = {t["insider"] for t in buys}
    sellers = {t["insider"] for t in sells}
    adj, why = adjustment_for(len(buyers), buy_usd, any(t["insider_class"] for t in buys))
    reason = ""
    if adj > 0:
        reason = f"{len(buyers)} insider{'s' if len(buyers) != 1 else ''} bought ${buy_usd:,.0f} on the open market in the last {lookback_days}d ({why})"
    latest = max(buys, key=lambda t: t["date"], default=None)
    return {
        "symbol": symbol,
        "status": "ok",
        "lookback_days": lookback_days,
        "form4_checked": filings_checked,
        "buyers": len(buyers),
        "buy_value_usd": round(buy_usd),
        "sellers": len(sellers),
        "sell_value_usd": round(sell_usd),
        "latest_buy": None if not latest else {
            "date": latest["date"], "insider": latest["insider"], "role": latest["role"],
            "value_usd": round(val(latest)),
        },
        "adjustment": adj,
        "reason": reason,
    }


def compute_symbol(symbol, lookback_days, cap):
    try:
        cik = _cik_for(symbol)
        if not cik:
            return {"symbol": symbol, "status": "error", "error": "ticker not found in SEC list", "adjustment": 0.0}
        subs = _get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", as_json=True)
        filings = recent_form4s(subs, lookback_days, cap)
        txs, failed = [], 0
        for f in filings:
            try:
                txs.extend(parse_form4(_get(raw_xml_url(cik, f))))
            except Exception:
                failed += 1
        res = summarize(symbol, txs, lookback_days, len(filings))
        if failed:
            res["filings_failed"] = failed
        return res
    except Exception as e:
        return {"symbol": symbol, "status": "error", "error": str(e)[:200], "adjustment": 0.0}


# ---------------------------------------------------------------- cache + jobs
def _executor():
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = ThreadPoolExecutor(max_workers=6)
    return _EXECUTOR


def _job(key, symbol, lookback_days, cap):
    res = compute_symbol(symbol, lookback_days, cap)
    ttl = CACHE_TTL if res.get("status") == "ok" else ERROR_TTL
    with _cache_lock:
        _CACHE[key] = (time.time(), ttl, res)
        _INFLIGHT.pop(key, None)
    return res


def _cached(key):
    with _cache_lock:
        hit = _CACHE.get(key)
        if hit and time.time() - hit[0] < hit[1]:
            return hit[2]
    return None


@signals_bp.route("/signals", methods=["GET"])
def signals():
    syms = []
    for s in request.args.get("symbols", "").split(","):
        s = s.strip().upper()
        if s and s not in syms:
            syms.append(s)
    if not syms:
        return jsonify({"error": "Missing required 'symbols' query parameter, e.g. ?symbols=AAPL,MSFT"}), 400
    syms = syms[:80]
    days = int(request.args.get("days", LOOKBACK_DAYS))
    cap = int(request.args.get("max_filings", MAX_FILINGS))
    budget = float(request.args.get("budget", 25))

    futures = {}
    results = {}
    for s in syms:
        key = (s, days)
        hit = _cached(key)
        if hit is not None:
            results[s] = hit
            continue
        with _cache_lock:
            fut = _INFLIGHT.get(key)
            if fut is None:
                fut = _executor().submit(_job, key, s, days, cap)
                _INFLIGHT[key] = fut
        futures[s] = fut

    if futures:
        wait(list(futures.values()), timeout=budget)
        for s, fut in futures.items():
            if fut.done():
                results[s] = fut.result()
            else:
                results[s] = {"symbol": s, "status": "pending", "adjustment": 0.0}

    ordered = [results[s] for s in syms]
    compact = [
        {"symbol": r["symbol"], "status": r["status"], "adjustment": r.get("adjustment", 0.0),
         "reason": r.get("reason", ""), "buyers": r.get("buyers"), "buy_value_usd": r.get("buy_value_usd")}
        for r in ordered
    ]
    summary = {
        "requested": len(syms),
        "ok": sum(1 for r in ordered if r["status"] == "ok"),
        "pending": sum(1 for r in ordered if r["status"] == "pending"),
        "error": sum(1 for r in ordered if r["status"] == "error"),
        "with_buys": sum(1 for r in ordered if r.get("adjustment", 0) > 0),
        "complete": all(r["status"] != "pending" for r in ordered),
    }
    return jsonify({
        "as_of": datetime.date.today().isoformat(),
        "lookback_days": days,
        "signals": ordered,
        "signals_json": json.dumps(compact),
        "summary": summary,
    })
