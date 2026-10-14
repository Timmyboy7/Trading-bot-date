"""
Wunschik Capital — private family dashboard (2026-10-14): a read-only website for the family, at /app.

  - Logins from env: DASH_USERS = "tim:owner:Tim:en,mama:viewer:Mama:de" (user:role:name:lang)
    and one DASH_PW_<USER> per user (plain text or a werkzeug hash), e.g. DASH_PW_MAMA.
    DASH_SECRET signs the session cookie (set it, or everyone is logged out on each restart).
  - Everyone sees everything; nobody can change anything (no page places orders). The owner
    also sees a system-status box. Name, language (EN/DE) and text size are per browser.
  - No JavaScript; all charts are server-side SVG. Data: dashboard_data.py.

Pages: /app/ (overview), /app/holdings, /app/basket, /app/risk, /app/activity, /app/reports,
/app/how, /app/profile, /app/login, /app/logout, /app/download/<file>.
"""
import datetime
import hmac
import json
import os
import re
import secrets
import time
from collections import defaultdict

import jinja2
import requests
from flask import Blueprint, Response, abort, g, redirect, request, session
from werkzeug.security import check_password_hash

import dashboard_data as D
import dashboard_text as X
import rebalance as rb

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/app")

NAV = [("overview", "/app/"), ("holdings", "/app/holdings"), ("basket", "/app/basket"), ("risk", "/app/risk"),
       ("activity", "/app/activity"), ("reports", "/app/reports")]


# --------------------------------------------------------------------------- users

def users():
    out = {}
    for part in os.environ.get("DASH_USERS", "").split(","):
        f = [x.strip() for x in part.split(":")]
        if not f or not f[0]:
            continue
        u = f[0].lower()
        out[u] = {"role": f[1] if len(f) > 1 and f[1] in ("owner", "viewer") else "viewer",
                  "name": f[2] if len(f) > 2 and f[2] else u.title(),
                  "lang": f[3] if len(f) > 3 and f[3] in ("en", "de") else "en"}
    return out


def password_ok(user, pw):
    stored = os.environ.get("DASH_PW_" + re.sub(r"[^A-Z0-9]", "_", user.upper()))
    if not stored or not pw:
        return False
    if stored.startswith(("pbkdf2:", "scrypt:")):
        return check_password_hash(stored, pw)
    return hmac.compare_digest(stored.encode(), pw.encode())


_FAILS = defaultdict(list)


def _throttled(ip):
    now = time.time()
    _FAILS[ip] = [x for x in _FAILS[ip] if now - x < 900]
    return len(_FAILS[ip]) >= 8


def current():
    u = session.get("user")
    info = users().get(u) if u else None
    if not info:
        return None
    prefs = session.get("prefs") or {}
    return {"user": u, "role": info["role"], "owner": info["role"] == "owner",
            "name": prefs.get("name") or info["name"], "lang": prefs.get("lang") or info["lang"],
            "large": bool(prefs.get("large"))}


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]


def csrf_ok():
    return hmac.compare_digest(str(session.get("csrf", "")), str(request.form.get("csrf", "")))


@dashboard_bp.after_request
def _headers(resp):
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    nonce = getattr(g, "csp_nonce", None)      # set only when a page renders its own small script
    resp.headers["Content-Security-Policy"] = (
        "default-src 'none'; " + (f"script-src 'nonce-{nonce}'; connect-src 'self'; " if nonce else "") + "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'")
    return resp


# --------------------------------------------------------------------------- rendering

ENV = jinja2.Environment(loader=jinja2.DictLoader({}), autoescape=True)


def _names():
    v, _ = safe(D.company_names, {})
    return v or {}


def _nonce():
    if not getattr(g, "csp_nonce", None):
        g.csp_nonce = secrets.token_urlsafe(16)
    return g.csp_nonce


def render(name, me, **ctx):
    lang = me["lang"] if me else request.args.get("lang", "en")
    ENV.loader = jinja2.DictLoader(TEMPLATES)
    tpl = ENV.get_template(name)
    return tpl.render(me=me, lang=lang, nav=NAV, page=ctx.pop("page", ""), csrf=csrf_token(),
                      t=lambda k, **kw: X.t(k, lang, **kw), money=lambda v, **kw: X.money(v, lang, **kw),
                      pct=lambda v, **kw: X.pct(v, lang, **kw), date=lambda v: X.date(v, lang),
                      tag=lambda k: X.TAGS.get(k, (k, k))[1 if lang == "de" else 0],
                      nm=lambda sym: _names().get(str(sym).upper(), ""), nonce=_nonce,
                      plain=lambda v, trig=False: X.plain_risk(v, lang, trig),
                      rname=lambda v: X.risk_name(v, lang), rlevel=lambda v: X.risk_level(v, lang), **ctx)


def need_login(fn):
    def wrap(*a, **kw):
        me = current()
        if not me:
            return redirect("/app/login")
        return fn(me, *a, **kw)
    wrap.__name__ = fn.__name__
    return wrap


def safe(fn, default=None):
    """(value, error) - pages render with whatever loaded."""
    try:
        return fn(), None
    except Exception as e:  # noqa: BLE001 - any data failure is shown, never a 500
        return default, f"{type(e).__name__}: {str(e)[:160]}"


def sheet_part(fn, default):
    if not D.sheets_configured():
        return default, "need_sheet:" + D.sheets_problem()
    v, err = safe(fn, default)
    return v, (f"sheet_error:{err}" if err else None)


# --------------------------------------------------------------------------- view models

def holding_rows(p, desk_names, wl):
    eq = float(p["account"]["equity"]) or 1.0
    thesis = {w["symbol"]: w["reasoning"] for w in wl}
    today = datetime.date.today()
    rows = []
    for x in sorted(p["positions"], key=lambda x: -float(x["market_value"])):
        s, i = x["symbol"], p["ind"].get(x["symbol"])
        since = p["since"].get(s)
        day = (today - datetime.date.fromisoformat(since)).days if since else 0
        dd = i["dd_from_high"] * 100 if i else None
        above = bool(i and i["sma"] and i["close"] >= i["sma"])
        state = "healthy" if above and (dd is None or dd > -15) else ("near_rule" if dd is not None and dd <= -20 and not above else "watch")
        n = desk_names.get(s) or {}
        rows.append({"symbol": s, "value": float(x["market_value"]), "share": float(x["market_value"]) / eq * 100,
                     "gain": float(x.get("unrealized_plpc") or 0) * 100, "since": since, "day": min(day, 182),
                     "price": float(x.get("current_price") or 0), "today": float(x.get("change_today") or 0) * 100,
                     "hold_pct": min(100, round(day / 182 * 100)), "state": state, "above": above, "dd": dd,
                     "next": n.get("next_earnings"), "thesis": n.get("thesis_short") or thesis.get(s, ""),
                     "kill": n.get("kill_criteria") or [], "cluster": n.get("cluster", ""),
                     "tax_free": (datetime.date.fromisoformat(since) + datetime.timedelta(days=182)).isoformat() if since else None,
                     "catalysts": [c for c in (n.get("catalysts") or []) if str(c.get("date", "")) >= today.isoformat()][:3]})
    return rows


def week_items(tr, lang, limit=4):
    items = []
    for row in reversed(tr[-6:]):
        for o in row["orders"]:
            if isinstance(o, dict) and o.get("symbol"):
                tag, title = X.explain_order(o, lang)
                items.append({"tag": tag, "title": title, "why": o.get("reason", ""), "at": row["at"],
                              "test": row["mode"] != "executed"})
        if len(items) >= limit:
            break
    order = {"SELL": 0, "BUY": 1, "WAIT": 2}
    return sorted(items, key=lambda x: order.get(x["tag"], 3))[:limit]


def risk_model(run, wl, desk_names):
    rec = run.get("reconcile") or {}
    weights = rec.get("weights") or {}
    scen = []
    labels = {"market_crash": ("Market crash", "Marktcrash"), "ai_bust": ("AI bust", "KI-Blase platzt"),
              "rate_shock": ("Interest rates up", "Zinsen steigen"), "oil_crash": ("Oil price crash", "Ölpreis-Absturz"),
              "oil_spike": ("Oil price jump", "Ölpreis-Sprung"), "momentum_reversal": ("Momentum reversal", "Trendwende der Gewinner")}
    stress = run.get("stress") or {}
    worst = {k: v[2] for k, v in (stress.get("scenarios") or {}).items() if isinstance(v, list) and len(v) > 2}
    for k, v in (rec.get("risk_after") or {}).items():
        b, s, lim = v.get("basket_pct"), v.get("spy_pct"), v.get("limit_pct")
        if b is None or lim is None:
            continue
        status = "over" if b < lim else ("near" if b <= lim * 0.92 else "within")
        names = next((w for n, w in worst.items() if k.replace("_", " ") in n.lower() or n.lower().startswith(k.split("_")[0])), [])
        scen.append({"key": k, "label": labels.get(k, (k, k)), "basket": b, "spy": s, "limit": lim, "status": status,
                     "level": v.get("level", ""), "names": ", ".join(names[:3]) if isinstance(names, list) else ""})
    for x in scen:
        x["hold"], x["h_bar"] = None, 0
    scen.sort(key=lambda x: (x["basket"] - x["limit"]) / (abs(x["limit"]) or 1))   # closest to its limit first
    mx = max([abs(x["basket"]) for x in scen] + [abs(x["limit"]) for x in scen] + [10])
    for x in scen:
        x["b_bar"] = round(abs(x["basket"]) / mx * 100, 1)
        x["s_bar"] = round(abs(x["spy"] or 0) / mx * 100, 1)
        x["l_bar"] = round(abs(x["limit"]) / mx * 100, 1)
    sectors = defaultdict(lambda: [0.0, 0])
    sec_of = {w["symbol"]: w["sector"] or "?" for w in wl}
    for s, w in weights.items():
        sectors[sec_of.get(s, "?")][0] += w * 100
        sectors[sec_of.get(s, "?")][1] += 1
    sec = sorted(({"name": k, "pct": v[0], "n": v[1]} for k, v in sectors.items()), key=lambda x: -x["pct"])
    smax = max([x["pct"] for x in sec] + [1])
    for x in sec:
        x["bar"] = round(x["pct"] / smax * 100)
    themes = defaultdict(lambda: [0.0, []])
    for s, w in weights.items():
        c = (desk_names.get(s) or {}).get("cluster")
        if c:
            themes[c][0] += w * 100
            themes[c][1].append(s)
    th = sorted(({"name": k.replace("_", " "), "pct": v[0], "syms": " · ".join(v[1])} for k, v in themes.items()
                 if len(v[1]) >= 2), key=lambda x: -x["pct"])
    beta = ((stress.get("exposures") or {}).get("beta_spy_simple"))
    maxw = max(list(weights.values()) + [0]) * 100
    top_theme = th[0] if th else None
    checks = [
        ("chk_spread", len(weights) >= 15 and maxw <= 10, f"{len(weights)} · max {maxw:.1f}%"),
        ("chk_limits", all(x["status"] != "over" for x in scen) and bool(scen),
         ", ".join(x["label"][0] for x in scen if x["status"] == "near") or "OK"),
        ("chk_beta", beta is not None and beta <= 1.6, f"beta {beta:.2f}" if beta is not None else "—"),
        ("chk_theme", not top_theme or top_theme["pct"] <= 25,
         f"{top_theme['name']} {top_theme['pct']:.0f}%" if top_theme else "—"),
    ]
    risks = []
    for r in ((run.get("risk_view") or {}).get("risks") or []):
        if isinstance(r, dict):
            raw = r.get("evidence") or r.get("why") or r.get("summary") or ""
            pr, nw, bt = X.split_risk(raw)
            risks.append({"name": r.get("risk", ""), "level": str(r.get("level", "")).lower(),
                          "text": raw, "prices": pr, "news": nw, "bottom": bt,
                          "trigger": r.get("watch_trigger") or r.get("trigger") or r.get("watch") or ""})
    return {"scen": scen, "sectors": sec, "themes": th, "checks": checks, "risks": risks,
            "ok": sum(1 for c in checks if c[1]), "beta": beta}


def basket_model(run, wl, desk_names):
    rec = run.get("reconcile") or {}
    weights = rec.get("weights") or {}
    ranking = [r for r in (run.get("ranking") or []) if isinstance(r, dict) and r.get("symbol")]
    rank_of = {r["symbol"]: i + 1 for i, r in enumerate(ranking)}
    reasons = {a.get("symbol"): a.get("reason", "") for a in (run.get("actions") or []) if isinstance(a, dict)}
    basket = [w["symbol"] for w in wl]
    rows = []
    for w in wl:
        s = w["symbol"]
        n = desk_names.get(s) or {}
        note = w["watch"] or ("Filled a free place" if "below the entry bar" in reasons.get(s, "") else "")
        rows.append({"symbol": s, "rank": rank_of.get(s), "sector": w["sector"], "theme": (n.get("cluster") or "").replace("_", " "),
                     "score": w["score"], "weight": weights.get(s, 0) * 100, "note": note,
                     "reason": reasons.get(s, ""), "thesis": n.get("thesis_short") or w["reasoning"]})
    rows.sort(key=lambda r: (r["rank"] or 999, -(r["score"] or 0)))
    smin = min([r["score"] for r in rows if r["score"]] + [3.0])
    smax = max([r["score"] for r in rows if r["score"]] + [5.0])
    for r in rows:
        r["bar"] = round(((r["score"] or smin) - smin) / ((smax - smin) or 1) * 90 + 10)
    in_theme = defaultdict(int)
    in_sector = defaultdict(int)
    for s in basket:
        c = (desk_names.get(s) or {}).get("cluster")
        if c:
            in_theme[c] += 1
    for w in wl:
        in_sector[w["sector"]] += 1
    contenders = []
    for r in ranking:
        s = r["symbol"]
        if s in basket:
            continue
        c = (desk_names.get(s) or {}).get("cluster")
        if r.get("red_flag"):
            why = "blk_red"
        elif r.get("uncertain"):
            why = "blk_unc"
        elif c and in_theme.get(c, 0) >= 2:
            why = "blk_theme"
        elif in_sector.get(r.get("sector"), 0) >= 5:
            why = "blk_sector"
        else:
            why = "blk_rank"
        contenders.append({"symbol": s, "rank": rank_of[s], "score": r.get("score"), "sector": r.get("sector", ""),
                           "why": why, "thesis": (desk_names.get(s) or {}).get("thesis_short") or r.get("thesis_summary", "")})
        if len(contenders) >= 8:
            break
    drops = sorted(rows, key=lambda r: -(r["rank"] or 999))[:3] + [r for r in rows if r["note"] and r["note"] != "Filled a free place"]
    seen, drop_list = set(), []
    for r in drops:
        if r["symbol"] not in seen:
            seen.add(r["symbol"])
            drop_list.append(r)
    return {"rows": rows, "contenders": contenders, "drops": drop_list[:6], "run_date": run.get("run_date", ""),
            "changes": sum(1 for a in (run.get("actions") or []) if isinstance(a, dict) and a.get("action") in ("added", "dropped", "swapped"))}


def stock_model(sym, run, wl, desk_names, p, lang):
    """Everything we know about one stock: basket row or contender, the Sunday research, ranking facts, own position."""
    m = basket_model(run or {}, wl or [], desk_names) if wl else {"rows": [], "contenders": []}
    row = next((r for r in m["rows"] if r["symbol"] == sym), None)
    con = next((c for c in m["contenders"] if c["symbol"] == sym), None)
    rk = next((r for r in ((run or {}).get("ranking") or []) if isinstance(r, dict) and r.get("symbol") == sym), None)
    n = desk_names.get(sym) or {}
    w = next((x for x in (wl or []) if x["symbol"] == sym), None)
    if not (row or con or rk or n):
        return None
    rank = (row or con or {}).get("rank")
    if rank is None and rk:
        rank = [r.get("symbol") for r in (run.get("ranking") or []) if isinstance(r, dict)].index(sym) + 1
    reasons = {a.get("symbol"): a.get("reason", "") for a in ((run or {}).get("actions") or []) if isinstance(a, dict)}
    today = datetime.date.today().isoformat()
    facts = []
    if rank:
        facts.append(("f_rank", f"#{rank}"))
    score = (row or {}).get("score") or (con or {}).get("score") or (w or {}).get("score")
    if score:
        facts.append(("f_score", f"{float(score):.2f}"))
    if row and row.get("weight"):
        facts.append(("f_weight", X.pct(row["weight"], lang, sign=False)))
    if w and w.get("target_price"):
        facts.append(("f_target", X.money(w["target_price"], lang)))
    if w and w.get("conviction"):
        facts.append(("f_conv", w["conviction"]))
    if w and w.get("added_on"):
        facts.append(("f_added", str(w["added_on"])[:10]))
    if n.get("next_earnings"):
        facts.append(("f_next", X.date(n["next_earnings"], lang)))
    for key, label, frac in (("ret_3m", "f_r3", True), ("ret_6m", "f_r6", True), ("drawdown_from_52w_high", "f_dd", True)):
        v = fnum_safe((rk or {}).get(key))
        if v is not None:
            facts.append((label, X.pct(abs(v) * 100 if key.startswith("draw") else v * 100, lang, sign=not key.startswith("draw"))))
    v = fnum_safe((rk or {}).get("rsi14"))
    if v is not None:
        facts.append(("f_rsi", f"{v:.0f}"))
    if w and w.get("risk_exposure"):
        facts.append(("f_risk", w["risk_exposure"]))
    own = None
    if p:
        own = next((r for r in holding_rows(p, desk_names, wl or []) if r["symbol"] == sym), None)
    sources = []
    for u in (n.get("sources") or [])[:8]:
        if isinstance(u, str) and u.startswith(("https://", "http://")):
            sources.append({"url": u, "host": re.sub(r"^www\.", "", u.split("/")[2])})
    return {"symbol": sym, "in_basket": bool(row), "rank": rank, "sector": (row or con or w or rk or {}).get("sector", ""),
            "cluster": (n.get("cluster") or "").replace("_", " "),
            "blocker": (con or {}).get("why"),
            "thesis": n.get("thesis_short") or (row or con or {}).get("thesis") or (w or {}).get("reasoning") or (rk or {}).get("thesis_summary", ""),
            "reasoning": (w or {}).get("reasoning", ""), "decision": reasons.get(sym, ""), "note": (row or {}).get("note", ""),
            "kill": n.get("kill_criteria") or [], "facts": facts, "own": own, "sources": sources,
            "catalysts": [c for c in (n.get("catalysts") or []) if str(c.get("date", "")) >= today][:5],
            "researched": n.get("researched_on")}


def fnum_safe(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def desk_names():
    v, _ = safe(lambda: (D.desk().get("names") or {}), {})
    return v or {}


# --------------------------------------------------------------------------- routes

@dashboard_bp.route("/login", methods=["GET", "POST"])
def login():
    lang = request.args.get("lang", "en") if request.args.get("lang") in ("en", "de") else "en"
    msg = None
    if request.method == "POST":
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
        if _throttled(ip):
            msg = "login_slow"
        elif not csrf_ok():
            msg = "login_bad"
        else:
            u = (request.form.get("username") or "").strip().lower()
            if u in users() and password_ok(u, request.form.get("password") or ""):
                session.clear()
                session.permanent = True
                session["user"] = u
                return redirect("/app/")
            _FAILS[ip].append(time.time())
            msg = "login_bad"
    ENV.loader = jinja2.DictLoader(TEMPLATES)
    return ENV.get_template("login.html").render(lang=lang, msg=msg, csrf=csrf_token(),
                                                 t=lambda k, **kw: X.t(k, lang, **kw), configured=bool(users()))


@dashboard_bp.route("/logout")
def logout():
    session.clear()
    return redirect("/app/login")


@dashboard_bp.route("/")
@need_login
def overview(me):
    lang = me["lang"]
    p, err = safe(D.portfolio)
    tr, terr = sheet_part(lambda: D.trades(20), [])
    run, rerr = sheet_part(D.latest_run, {})
    wl, _ = sheet_part(D.watchlist, [])
    dn = desk_names()
    try:
        from zoneinfo import ZoneInfo
        hour = datetime.datetime.now(ZoneInfo("Europe/Luxembourg")).hour
    except Exception:  # noqa: BLE001 - no tz database: fall back to summer time
        hour = (datetime.datetime.now(datetime.timezone.utc).hour + 2) % 24
    greet = "morning" if hour < 12 else ("day" if hour < 18 else "evening")
    ctx = {"greet": greet, "err": err}
    if p:
        eq = float(p["account"]["equity"])
        sh = p["shadow"] if isinstance(p["shadow"], dict) else {}
        rows = holding_rows(p, dn, wl or [])
        ctx.update(p=p, eq=eq, gain=eq - p["paid_in"], gain_pct=(eq / p["paid_in"] - 1) * 100 if p["paid_in"] else 0,
                   spy_value=sh.get("spy_value"), excess=(eq - sh["spy_value"]) if sh.get("spy_value") else None,
                   spy_gain=(sh["spy_value"] - p["paid_in"]) if sh.get("spy_value") else None,
                   spy_gain_pct=sh.get("spy_gain_pct"), spy_asof=sh.get("as_of_close"),
                   cash=float(p["account"]["cash"]), stocks_value=eq - float(p["account"]["cash"]),
                   chart=D.chart(p["series"]), rows=rows[:5], n_held=len(rows),
                   cash_pct=float(p["account"]["cash"]) / eq * 100 if eq else 0,
                   in_hold=sum(1 for r in rows if r["day"] < 182),
                   first_free=min([r["tax_free"] for r in rows if r["tax_free"]] or [None]))
    if p:
        try:
            ctx["v"] = money_strings(D.live_numbers(), lang, len(rows))
        except Exception:  # noqa: BLE001 - the page then omits the money block and says so
            ctx["v"] = None
    ctx["week"] = week_items(tr or [], lang)
    ctx["basket_n"] = len(wl or []) or 20
    ctx["risk"] = risk_model(run, wl or [], dn) if run else None
    return render("overview.html", me, page="overview", **ctx)


def money_strings(n, lang, n_held=0):
    """Every money number of the Overview as ready-to-show text, from D.live_numbers(). The page prints it and
    /live.json sends the same dict, so both always agree. Invested money (stocks) and cash are kept apart: the
    S&P 500 comparison uses the same purchases in the S&P 500 (cash is not part of it)."""
    m, pc = (lambda v, **kw: X.money(v, lang, **kw)), (lambda v, **kw: X.pct(v, lang, **kw))
    eq, cash, paid = n["eq"], n["cash"], n["paid_in"]
    stocks = eq - cash
    cash_pct = cash / eq * 100 if eq else 0.0
    gain = eq - paid
    tw = n.get("twin")
    px = n.get("spy_px")
    v = {"stocks": m(stocks), "stocks_pct": pc(100 - cash_pct, sign=False), "cash_amt": m(cash), "cash_pct": pc(cash_pct, sign=False),
         "cash2_amt": m(cash), "cash2_pct": pc(cash_pct, sign=False), "eq": m(eq), "stocks2": m(stocks),
         "gain_line": f"{m(gain, sign=True)} ({pc((eq / paid - 1) * 100 if paid else 0.0)})",
         "w_inv": f"{max(100 - cash_pct, 0):.1f}%", "w_cash": f"{max(cash_pct, 0):.1f}%", "open": n["open"],
         "has_twin": False, "cls": {"gain_line": "pos" if gain >= 0 else "neg"}}
    if tw and tw["buys"] > 0 and px:
        net_in = tw["buys"] - tw["sells"]
        twin_value = tw["units"] * px
        g, tg = stocks - net_in, twin_value - net_in
        ex = stocks - twin_value
        v.update(has_twin=True, put_a=m(net_in), put_b=m(net_in), st_worth=m(stocks), tw_worth=m(twin_value),
                 st_growth=f"{m(g, sign=True)} ({pc(g / tw['buys'] * 100, dec=2)})",
                 tw_growth=f"{m(tg, sign=True)} ({pc(tg / tw['buys'] * 100, dec=2)})",
                 inv_growth=f"{m(g, sign=True)} ({pc(g / tw['buys'] * 100, dec=2)})", inv_on=m(net_in),
                 excess=f"{X.t('ahead' if ex >= 0 else 'behind', lang)} {m(abs(ex), dec=2)}")
        v["cls"].update(st_growth="pos" if g >= 0 else "neg", tw_growth="pos" if tg >= 0 else "neg",
                        inv_growth="pos" if g >= 0 else "neg")
    sv = n.get("spy_value")
    if sv:
        v.update(whole_a=m(eq), whole_b=m(sv))
    try:
        from zoneinfo import ZoneInfo
        now = datetime.datetime.now(ZoneInfo("Europe/Luxembourg"))
    except Exception:  # noqa: BLE001
        now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)
    v["badge"] = X.t("live_open" if n["open"] else "live_closed", lang, t=now.strftime("%H:%M:%S"))
    return v


@dashboard_bp.route("/live.json")
@need_login
def live_json(me):
    """Overview numbers as ready-to-show text (the page script only copies them in)."""
    try:
        v = money_strings(D.live_numbers(), me["lang"])
    except Exception:  # noqa: BLE001 - the page keeps what it shows
        return Response('{"error": 1}', status=503, mimetype="application/json")
    return Response(json.dumps(v), mimetype="application/json")


@dashboard_bp.route("/holdings-live.json")
@need_login
def holdings_live(me):
    """Price, today's move, value, share and gain per held stock as ready-to-show text (the page script copies them in)."""
    lang = me["lang"]
    try:
        lp = D.live_positions()
    except Exception:  # noqa: BLE001 - the page keeps what it shows
        return Response('{"error": 1}', status=503, mimetype="application/json")
    eq = lp["eq"] or 1.0
    rows = {}
    for sym, x in lp["rows"].items():
        rows[sym] = {"price": X.money(x["price"], lang), "today": X.pct(x["today"], lang, dec=2),
                     "value": X.money(x["value"], lang), "share": X.pct(x["value"] / eq * 100, lang, sign=False),
                     "gain": X.pct(x["gain"], lang), "now": X.pct(x["gain"], lang),
                     "cls": {"gain": "pos" if x["gain"] >= 0 else "neg", "today": "pos" if x["today"] >= 0 else "neg"}}
    try:
        from zoneinfo import ZoneInfo
        now = datetime.datetime.now(ZoneInfo("Europe/Luxembourg"))
    except Exception:  # noqa: BLE001
        now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)
    out = {"rows": rows, "cash": X.money(lp["cash"], lang), "open": lp["open"],
           "badge": X.t("live_open" if lp["open"] else "live_closed", lang, t=now.strftime("%H:%M:%S"))}
    return Response(json.dumps(out), mimetype="application/json")


@dashboard_bp.route("/holdings")
@need_login
def holdings(me):
    p, err = safe(D.portfolio)
    wl, _ = sheet_part(D.watchlist, [])
    rows = holding_rows(p, desk_names(), wl or []) if p else []
    pick = request.args.get("s", "").upper()
    sel = next((r for r in rows if r["symbol"] == pick), rows[0] if rows else None)
    return render("holdings.html", me, page="holdings", rows=rows, sel=sel, err=err, p=p)


@dashboard_bp.route("/basket")
@need_login
def basket(me):
    run, rerr = sheet_part(D.latest_run, {})
    wl, werr = sheet_part(D.watchlist, [])
    m = basket_model(run or {}, wl or [], desk_names()) if wl else None
    return render("basket.html", me, page="basket", m=m, serr=werr or rerr)


@dashboard_bp.route("/stock/<sym>")
@need_login
def stock(me, sym):
    sym = sym.upper()
    if not re.fullmatch(r"[A-Z][A-Z.\-]{0,5}", sym):
        sym = ""
    run, rerr = sheet_part(D.latest_run, {})
    wl, werr = sheet_part(D.watchlist, [])
    p, _ = safe(D.portfolio)
    st = stock_model(sym, run or {}, wl or [], desk_names(), p, me["lang"]) if sym else None
    px, perr, pxc = None, None, None
    if sym:
        px, perr = safe(lambda: D.price_history(sym))
        if px:
            pxc = D.chart_px(px, (st or {}).get("own", {}) and st["own"].get("since"))
            rows = px["rows"]
            pxj = json.dumps({"lang": me["lang"], "w": pxc["w"], "h": pxc["h"], "lo": pxc["lo"], "hi": pxc["hi"],
                              "d": [r[0] for r in rows], "a": [round(r[1], 2) for r in rows],
                              "b": [round(r[2], 2) for r in rows], "t": [X.t(k, me["lang"]) for k in ("px_tip_stock", "px_tip_spy")]})
            pxc["json"] = pxj
    return render("stock.html", me, page="basket", st=st, sym=sym, px=px, pxc=pxc, perr=perr)


@dashboard_bp.route("/risk")
@need_login
def risk(me):
    run, rerr = sheet_part(D.latest_run, {})
    wl, werr = sheet_part(D.watchlist, [])
    m = risk_model(run, wl or [], desk_names()) if run else None
    hold, herr = safe(D.holdings_risk, {})
    hold = hold or {}
    if m and hold.get("scen"):
        by = {x["key"]: x["basket"] for x in hold["scen"]}
        mx = max([abs(x["basket"]) for x in m["scen"]] + [abs(x["limit"]) for x in m["scen"]] + [10])
        for x in m["scen"]:
            x["hold"] = by.get(x["key"])
            x["h_bar"] = round(abs(x["hold"]) / mx * 100, 1) if x["hold"] is not None else 0
    sev = None
    if m:
        sb, _ = safe(D.severe_basket)
        sh = hold.get("severe") if hold.get("scen") else None
        if sb is not None:
            mx = max(abs(sb), abs(sh or 0), 25)
            sev = {"basket": sb, "hold": sh, "spy": -25.0, "b_bar": round(abs(sb) / mx * 100, 1),
                   "h_bar": round(abs(sh or 0) / mx * 100, 1), "s_bar": round(25 / mx * 100, 1)}
    cors = []
    for key, fn in (("corr_basket", D.basket_correlation), ("corr_hold", D.holdings_correlation)):
        c, cerr = safe(fn)
        if c:
            c["level"] = "well" if c["avg"] < 0.3 else ("mod" if c["avg"] < 0.5 else "one")
            c["bar"] = round(min(max(c["avg"], 0), 1) * 100, 1)
        cors.append({"title": key, "c": c, "err": bool(cerr), "empty_key": "corr_hold_none" if key == "corr_hold" else "corr_err"})
    shd, shd_err = safe(D.shadow_low_ai)
    shc = D.chart3(shd["series"]) if shd and shd.get("series") else None
    return render("risk.html", me, page="risk", m=m, serr=rerr or werr, run_date=(run or {}).get("run_date", ""),
                  hold=hold, herr=herr, sev=sev, cors=cors, shd=shd, shd_err=shd_err, shc=shc)


@dashboard_bp.route("/activity")
@need_login
def activity(me):
    lang = me["lang"]
    tr, serr = sheet_part(lambda: D.trades(80), [])
    f = request.args.get("f", "all")
    days = []
    for row in reversed(tr or []):
        items = []
        for o in row["orders"]:
            if isinstance(o, dict) and o.get("symbol"):
                tag, title = X.explain_order(o, lang)
                items.append({"tag": tag, "title": title, "why": o.get("reason", ""), "checks": o.get("checks", ""),
                              "amount": o.get("amount_usd") if o.get("status") != "skipped" else None})
        for d in row["decisions"]:
            if isinstance(d, dict) and d.get("symbol") and d.get("action") not in (None, ""):
                tag, title = X.explain_decision(d, lang)
                items.append({"tag": tag, "title": title, "why": d.get("why", ""), "amount": None})
        want = {"buys": "BUY", "sells": "SELL", "waits": "WAIT", "checks": "CHECK"}.get(f)
        items = [i for i in items if not want or i["tag"] == want]
        if items:
            days.append({"at": row["at"], "test": row["mode"] != "executed", "mode": row["mode"], "entries": items})
    sc, _ = safe(D.wait_scorecard)
    lang = me["lang"]
    score = None
    if sc and sc.get("total"):
        rules = [{"label": X.t("wr_" + k, lang), "n": r["n"], "bought": r["bought"], "helped": r["helped"],
                  "avg": X.pct(r["avg"], lang) if r["avg"] is not None else "–",
                  "usd": X.money(r["usd"], lang, sign=True) if r["bought"] else "–",
                  "good": (r["usd"] > 0) if r["bought"] else None}
                 for k, r in sc["summary"].items()]
        cs = [{"symbol": c["symbol"], "label": X.t("wr_" + c["rule"], lang), "day": c["day"], "price": X.money(c["price"], lang),
               "bought": c["bought"], "buy_price": X.money(c["buy_price"], lang) if c["bought"] else "",
               "buy_day": c.get("buy_day", ""), "diff": X.pct(c["diff"], lang) if c["bought"] else "",
               "good": (c["diff"] > 0) if c["bought"] else None} for c in sc["cases"]]
        score = {"rules": rules, "cases": cs, "total": sc["total"]}
    return render("activity.html", me, page="activity", days=days, f=f, serr=serr, score=score)


@dashboard_bp.route("/reports")
@need_login
def reports(me):
    status = None
    if me["owner"]:
        tr, _ = sheet_part(lambda: D.trades(1), [])
        run, _ = sheet_part(D.latest_run, {})
        status = {"daily": tr[-1] if tr else None, "weekly": (run or {}).get("run_date"),
                  "desk": D.desk().get("as_of"), "sheet": D.sheets_configured()}
    return render("reports.html", me, page="reports", status=status)


@dashboard_bp.route("/how")
@need_login
def how(me):
    return render("how.html", me, page="reports")


@dashboard_bp.route("/profile", methods=["GET", "POST"])
@need_login
def profile(me):
    saved = False
    if request.method == "POST" and csrf_ok():
        name = (request.form.get("name") or "").strip()[:30]
        lang = request.form.get("lang") if request.form.get("lang") in ("en", "de") else me["lang"]
        session["prefs"] = {"name": name or None, "lang": lang, "large": request.form.get("size") == "large"}
        me, saved = current(), True
    return render("profile.html", me, page="profile", saved=saved)


DOWNLOADS = {
    "latest-run.json": ("application/json", D.latest_run_json),
    "trades.csv": ("text/csv; charset=utf-8", lambda: "﻿" + D.trades_csv()),
    "audit-log.csv": ("text/csv; charset=utf-8", lambda: "﻿" + D.audit_log_csv()),
    "backtests.md": ("text/markdown; charset=utf-8", D.backtests_md),
}


@dashboard_bp.route("/download/<name>")
@need_login
def download(me, name):
    if name not in DOWNLOADS:
        abort(404)
    mime, fn = DOWNLOADS[name]
    if name in ("latest-run.json", "trades.csv") and not D.sheets_configured():
        return Response(X.t("need_sheet", me["lang"]), mimetype="text/plain", status=503)
    try:
        body = fn()
    except (requests.RequestException, KeyError, ValueError) as e:
        return Response(f"Could not build the file right now: {type(e).__name__}", mimetype="text/plain", status=503)
    return Response(body, mimetype=mime.split(";")[0],
                    headers={"Content-Disposition": f'attachment; filename="{name}"',
                             "Content-Type": mime})


from dashboard_templates import TEMPLATES  # noqa: E402  (kept apart: it is long)
