"""
Data layer for the private dashboard (dashboard.py). Read-only: nothing here places orders
or writes anywhere.

Sources
  - Alpaca (same keys as /rebalance): account, positions, fills, daily closes, portfolio
    history. Shown through the savings-plan lens of rebalance.py (hidden reserve removed,
    SPY shadow with the same deposits).
  - Google Sheet (optional, read-only service account): Watchlist, Runs (weekly), Trades
    (daily). Env GOOGLE_SA_JSON = the service account's JSON key, DASH_SHEET_ID = the
    spreadsheet id. Without them the pages that need the sheet say so.
  - research/desk/latest.json (in the repo): thesis, sell triggers, earnings dates, themes.

Everything is cached in memory for a few minutes (Render's free plan sleeps anyway).
"""
import calendar
import csv
import datetime
import io
import json
import os
import re
import time
from urllib.parse import quote

import requests

import deep_dive as dd
import rebalance as rb

SHEET_ID = os.environ.get("DASH_SHEET_ID", "")
GITHUB_REPO = os.environ.get("DASH_GITHUB_REPO", "Timmyboy7/Trading-bot-date")
CACHE_SEC = int(os.environ.get("DASH_CACHE_SEC", 300))

_C = {}


def cached(key, ttl, fn):
    hit = _C.get(key)
    now = time.time()
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _C[key] = (now, val)
    return val


def clear_cache():
    _C.clear()


def jparse(v, default=None):
    """JSON from a sheet cell or an LLM answer (code fences, prose around it)."""
    if isinstance(v, (dict, list)):
        return v
    if not v or not isinstance(v, str):
        return default
    t = v.strip()
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t.lower().startswith("json"):
            t = t[4:].strip()
    try:
        return json.loads(t)
    except ValueError:
        for a, b in (("{", "}"), ("[", "]")):
            i, j = t.find(a), t.rfind(b)
            if 0 <= i < j:
                try:
                    return json.loads(t[i:j + 1])
                except ValueError:
                    pass
    return default


def fnum(v):
    try:
        return float(str(v).replace(",", "").replace("%", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- Google Sheet

_TOKEN = {"v": None, "exp": 0.0}


def sheets_configured():
    return bool(os.environ.get("GOOGLE_SA_JSON") and SHEET_ID)


def sheets_problem():
    """Plain-words reason why the sheet connection is not usable (names/shape only, never values)."""
    out = []
    raw = os.environ.get("GOOGLE_SA_JSON")
    if not raw:
        out.append("GOOGLE_SA_JSON is empty or missing")
    else:
        try:
            info = json.loads(raw)
            if not isinstance(info, dict) or not info.get("private_key") or not info.get("client_email"):
                out.append("GOOGLE_SA_JSON is JSON but lacks client_email/private_key")
        except ValueError:
            out.append(f"GOOGLE_SA_JSON is not valid JSON (it starts with '{raw.strip()[:1]}', "
                       f"{len(raw)} characters; the whole file must be pasted, starting with '{{')")
    if not SHEET_ID:
        out.append("DASH_SHEET_ID is empty or missing")
    if out:
        odd = sorted(k for k in os.environ
                     if k not in ("GOOGLE_SA_JSON", "DASH_SHEET_ID")
                     and (k.upper().startswith(("GOOG", "GOGG", "DASH_SH")) or "SA_JSON" in k.upper()
                          or "SHEET" in k.upper()))
        if odd:
            out.append("similar names found on the server: " + ", ".join(odd))
    return "; ".join(out)


def _sheets_token():
    if _TOKEN["v"] and time.time() < _TOKEN["exp"] - 60:
        return _TOKEN["v"]
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account
    info = json.loads(os.environ["GOOGLE_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    creds.refresh(Request())
    _TOKEN["v"] = creds.token
    _TOKEN["exp"] = calendar.timegm(creds.expiry.utctimetuple()) if creds.expiry else time.time() + 3000
    return creds.token


def sheet_values(rng):
    r = requests.get(f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{quote(rng)}",
                     headers={"Authorization": f"Bearer {_sheets_token()}"},
                     params={"valueRenderOption": "FORMATTED_VALUE"}, timeout=20)
    r.raise_for_status()
    return r.json().get("values") or []


def last_rows(tab, last_col, n):
    count = len(sheet_values(f"{tab}!A:A"))
    if count < 2:
        return []
    start = max(2, count - n + 1)
    return sheet_values(f"{tab}!A{start}:{last_col}{count}")


def _cell(row, i):
    return row[i] if i < len(row) else ""


def watchlist():
    def load():
        rows = sheet_values("Watchlist!A2:K200")
        out = []
        for r in rows:
            s = _cell(r, 0).strip().upper()
            if not s:
                continue
            out.append({"symbol": s, "added_on": _cell(r, 1), "sector": _cell(r, 2), "reasoning": _cell(r, 3),
                        "target_price": fnum(_cell(r, 4)), "conviction": _cell(r, 5).strip(),
                        "score": fnum(_cell(r, 8)), "watch": _cell(r, 9).strip(),
                        "risk_exposure": _cell(r, 10).strip()})
        return out
    return cached("watchlist", CACHE_SEC, load)


def latest_run():
    def load():
        rows = last_rows("Runs", "J", 1)
        if not rows:
            return {}
        r = rows[-1]
        return {"run_date": _cell(r, 0), "basket_symbols": _cell(r, 1),
                "actions": jparse(_cell(r, 2), []) or [], "reconcile": jparse(_cell(r, 3), {}) or {},
                "select": jparse(_cell(r, 4), {}) or {}, "macro": jparse(_cell(r, 6), {}) or {},
                "ranking": jparse(_cell(r, 7), []) or [], "stress": jparse(_cell(r, 8), {}) or {},
                "risk_view": jparse(_cell(r, 9), {}) or {}}
    return cached("latest_run", CACHE_SEC, load)


def trades(n=80):
    def load():
        out = []
        for r in last_rows("Trades", "I", n):
            out.append({"at": _cell(r, 0), "mode": _cell(r, 1).strip(), "equity": fnum(_cell(r, 2)),
                        "cash": fnum(_cell(r, 3)), "excess_pct": fnum(_cell(r, 4)),
                        "summary": jparse(_cell(r, 5), {}) or {}, "orders": jparse(_cell(r, 6), []) or [],
                        "errors": _cell(r, 7).strip(), "decisions": jparse(_cell(r, 8), []) or []})
        return out
    return cached(f"trades{n}", CACHE_SEC, load)


# --------------------------------------------------------------------------- Alpaca

def _history():
    try:
        h = rb._get("/v2/account/portfolio/history", period="1A", timeframe="1D")
    except requests.RequestException:
        return []
    ts, eq = h.get("timestamp") or [], h.get("equity") or []
    return [(datetime.datetime.fromtimestamp(t, datetime.timezone.utc).date().isoformat(), float(e))
            for t, e in zip(ts, eq) if e is not None]


def portfolio():
    """Everything the Overview / Holdings pages need, in the bot's own (savings-plan) view."""
    def load():
        errors = []
        acct = rb._get("/v2/account")
        positions = rb._get("/v2/positions")
        try:
            fills = rb.fetch_fills()
        except requests.RequestException as e:
            fills, _ = [], errors.append(f"fills: {e}")
        since = rb.holdings_since(fills, positions)
        first = str(fills[0].get("transaction_time") or "")[:10] if fills else None
        start = rb.START_DATE or first
        today = datetime.date.today()
        deposits = rb.deposit_schedule(start, today) if start else [(today, rb.START_EQUITY)]
        vacct, reserve = rb.virtual_account(acct, deposits)
        held = {p["symbol"] for p in positions}
        try:
            closes = rb.daily_closes(held | {"SPY"})
        except requests.RequestException as e:
            closes, _ = {}, errors.append(f"bars: {e}")
        ind = {s: rb.indicators(closes.get(s), since.get(s)) for s in held if closes.get(s)}
        shadow = rb.spy_shadow(vacct["equity"], closes.get("SPY"), deposits, bool(start))
        paid_in = sum(a for _, a in deposits)
        series = build_series(_history(), closes.get("SPY") or [], deposits, start) if start else []
        return {"account": vacct, "reserve": reserve, "positions": positions, "since": since,
                "ind": ind, "shadow": shadow, "paid_in": paid_in, "deposits": deposits,
                "start": start, "series": series, "errors": errors,
                "market_open": None}
    return cached("portfolio", 120, load)


def build_series(history, spy, deposits, start):
    """[(date, basket, spy_shadow, paid_in)] from the start date, in the bot's view."""
    if not start:
        return []
    paper = float(rb.PAPER_BALANCE) if rb.PAPER_BALANCE else None
    spy_px = dict(spy)
    out, units, di, paid = [], 0.0, 0, 0.0
    days = sorted({d for d, _ in history if d >= start} | {d for d, _ in spy if d >= start})
    eq = dict(history)
    last_eq = None
    for d in days:
        while di < len(deposits) and deposits[di][0].isoformat() <= d:
            px = spy_px.get(d) or next((c for x, c in spy if x >= d), None)
            if px:
                units += deposits[di][1] / px
            paid += deposits[di][1]
            di += 1
        if d in eq:
            last_eq = eq[d]
        if last_eq is None or d not in spy_px:
            continue
        basket = last_eq - (paper - paid) if paper else last_eq
        out.append((d, round(basket, 2), round(units * spy_px[d], 2), round(paid, 2)))
    return out


def chart(series, w=760, h=220):
    """SVG polyline points for basket / spy / paid-in, plus axis labels."""
    if len(series) < 2:
        return None
    vals = [v for _, a, b, c in series for v in (a, b, c)]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.08 or 10
    lo, hi = lo - pad, hi + pad
    n = len(series) - 1

    def pts(i):
        return " ".join(f"{k * w / n:.1f},{h - (row[i] - lo) / (hi - lo) * h:.1f}" for k, row in enumerate(series))
    grid = [(round(h - (v - lo) / (hi - lo) * h, 1), v) for v in
            (lo + (hi - lo) * f for f in (0.1, 0.5, 0.9))]
    return {"basket": pts(1), "spy": pts(2), "paid": pts(3), "w": w, "h": h, "grid": grid,
            "first": series[0][0], "last": series[-1][0],
            "end": (round(w, 1), round(h - (series[-1][1] - lo) / (hi - lo) * h, 1))}


def desk():
    return cached("desk", 600, dd.load_desk)


# --------------------------------------------------------------------------- company names

_LEGAL = re.compile(r"[,\s]+(Inc\.?|Incorporated|Corp\.?|Corporation|Co\.?|Company|Ltd\.?|Limited|PLC|plc|N\.V\.|S\.A\.|LLC|L\.P\.)$")
_SHARES = re.compile(r"\s+(Common Stock|Ordinary Shares?|Common Shares?|Class [A-C]( Common Stock| Ordinary Shares?| Shares?)?|"
                     r"Depositary Shares?.*|American Depositary.*|Registered Shares?|Capital Stock|Shares of Beneficial Interest)$", re.I)


def clean_name(n):
    """'Micron Technology, Inc. Common Stock' -> 'Micron Technology'."""
    n = (n or "").strip()
    for _ in range(4):
        m = _SHARES.sub("", n)
        m = _LEGAL.sub("", m)
        if m == n:
            break
        n = m
    return re.sub(r"\s+(and|&)$", "", n.strip(" ,.")).strip()


def company_names():
    """{symbol: short company name} from Alpaca's asset list (cached a day); {} if unavailable."""
    def load():
        try:
            assets = rb._get("/v2/assets", status="active", asset_class="us_equity")
        except (requests.RequestException, ValueError):
            return {}
        return {a["symbol"].upper(): clean_name(a.get("name")) for a in assets
                if isinstance(a, dict) and a.get("symbol") and a.get("name")}
    names = cached("names", 86400, load)
    if not names:
        _C.pop("names", None)   # do not keep a failure for a day
    return names


# --------------------------------------------------------------------------- risk of what we actually hold

def holdings_risk():
    """The same crash scenarios as the weekly basket check, but on the real positions and their real weights
    (cash counts as 0%). {'empty': True} until something is bought. Cached 30 min: it downloads a year of prices."""
    def load():
        import stress_test as st
        import reconcile_basket as rc
        p = portfolio()
        pos = [x for x in p["positions"] if float(x.get("market_value") or 0) > 0]
        eq = float(p["account"]["equity"]) or 0.0
        if not pos or eq <= 0:
            return {"empty": True}
        mv = {x["symbol"]: float(x["market_value"]) for x in pos}
        invested = min(sum(mv.values()) / eq, 1.0)
        res = st.compute(sorted(mv), weights={s: v / eq for s, v in mv.items()}, news={})
        if "error" in res:
            return {"error": res["error"], "errors": res.get("errors", [])}
        scen = []
        for sc in res["scenarios"]:
            port = sc["basket_pct"] * invested          # cash earns 0
            spy = sc["spy_pct"]
            lim = spy * rc.RISK_MULT[0] if spy <= -0.5 else rc.RISK_ABS_FLOOR[0]
            scen.append({"key": sc["name"], "basket": round(port, 1), "spy": spy, "limit": round(lim, 1),
                         "names": ", ".join(x["symbol"] for x in sc["worst"])})
        return {"empty": False, "scen": scen, "n": len(mv), "invested_pct": invested * 100,
                "cash_pct": (1 - invested) * 100, "beta": round(res["exposures"]["beta_spy_simple"] * invested, 2),
                "skipped": res.get("summary", {}).get("skipped") or [], "errors": res.get("errors", [])}
    return cached("holdings_risk", 1800, load)


# --------------------------------------------------------------------------- downloads

def audit_log_csv():
    """Every change on main, from the public GitHub history (cached 1 h)."""
    def load():
        rows, page = [], 1
        while page <= 5:
            r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/commits",
                             params={"sha": "main", "per_page": 100, "page": page}, timeout=20,
                             headers={"Accept": "application/vnd.github+json"})
            if r.status_code != 200:
                break
            batch = r.json()
            for c in batch:
                msg = (c.get("commit") or {}).get("message", "").split("\n")[0]
                m = re.search(r"\(#(\d+)\)\s*$", msg)
                rows.append([(c.get("commit") or {}).get("committer", {}).get("date", "")[:16].replace("T", " "),
                             m.group(1) if m else "", c.get("sha", "")[:7],
                             re.sub(r"\s*\(#\d+\)\s*$", "", msg)])
            if len(batch) < 100:
                break
            page += 1
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["date (UTC)", "PR", "commit", "change"])
        w.writerows(rows)
        return buf.getvalue()
    return cached("audit", 3600, load)


def trades_csv():
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["run (Luxembourg time)", "mode", "symbol", "side", "kind", "amount_usd", "status", "reason"])
    for t in trades(400):
        for o in t["orders"]:
            if isinstance(o, dict):
                w.writerow([t["at"], t["mode"], o.get("symbol", ""), o.get("side", ""), o.get("kind", ""),
                            o.get("amount_usd", ""), o.get("status", ""), o.get("reason", "")])
    return buf.getvalue()


def latest_run_json():
    t = trades(1)
    return json.dumps({"note": "Latest daily run (Trades sheet) and latest weekly run (Runs sheet). "
                               "No passwords or keys are included.",
                       "daily": t[-1] if t else None, "weekly": latest_run() or None},
                      indent=2, ensure_ascii=False)


def backtests_md():
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research")
    parts = []
    for name in ("ROUND2.md", "ROUND3.md", "ROUND4.md"):
        try:
            with open(os.path.join(base, name), encoding="utf-8") as f:
                parts.append(f.read())
        except OSError:
            pass
    return "\n\n---\n\n".join(parts) or "No backtest reports found."
