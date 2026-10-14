"""
Private dashboard (2026-10-14): a read-only website for the family, at /app.

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
import os
import re
import secrets
import time
from collections import defaultdict

import jinja2
import requests
from flask import Blueprint, Response, abort, redirect, request, session
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
    resp.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'")
    return resp


# --------------------------------------------------------------------------- rendering

ENV = jinja2.Environment(loader=jinja2.DictLoader({}), autoescape=True)


def render(name, me, **ctx):
    lang = me["lang"] if me else request.args.get("lang", "en")
    ENV.loader = jinja2.DictLoader(TEMPLATES)
    tpl = ENV.get_template(name)
    return tpl.render(me=me, lang=lang, nav=NAV, page=ctx.pop("page", ""), csrf=csrf_token(),
                      t=lambda k, **kw: X.t(k, lang, **kw), money=lambda v, **kw: X.money(v, lang, **kw),
                      pct=lambda v, **kw: X.pct(v, lang, **kw), date=lambda v: X.date(v, lang),
                      tag=lambda k: X.TAGS.get(k, (k, k))[1 if lang == "de" else 0], **ctx)


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
        return default, "need_sheet"
    v, err = safe(fn, default)
    return v, ("sheet_error" if err else None)


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
            risks.append({"name": r.get("risk", ""), "level": str(r.get("level", "")).lower(),
                          "text": r.get("evidence") or r.get("why") or r.get("summary") or "",
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
                   chart=D.chart(p["series"]), rows=rows[:5], n_held=len(rows),
                   cash_pct=float(p["account"]["cash"]) / eq * 100 if eq else 0,
                   in_hold=sum(1 for r in rows if r["day"] < 182),
                   first_free=min([r["tax_free"] for r in rows if r["tax_free"]] or [None]))
    ctx["week"] = week_items(tr or [], lang)
    ctx["basket_n"] = len(wl or []) or 20
    ctx["risk"] = risk_model(run, wl or [], dn) if run else None
    return render("overview.html", me, page="overview", **ctx)


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


@dashboard_bp.route("/risk")
@need_login
def risk(me):
    run, rerr = sheet_part(D.latest_run, {})
    wl, werr = sheet_part(D.watchlist, [])
    m = risk_model(run, wl or [], desk_names()) if run else None
    return render("risk.html", me, page="risk", m=m, serr=rerr or werr, run_date=(run or {}).get("run_date", ""))


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
                items.append({"tag": tag, "title": title, "why": o.get("reason", ""),
                              "amount": o.get("amount_usd") if o.get("status") != "skipped" else None})
        for d in row["decisions"]:
            if isinstance(d, dict) and d.get("symbol") and d.get("action") not in (None, ""):
                tag, title = X.explain_decision(d, lang)
                items.append({"tag": tag, "title": title, "why": d.get("why", ""), "amount": None})
        want = {"buys": "BUY", "sells": "SELL", "waits": "WAIT", "checks": "CHECK"}.get(f)
        items = [i for i in items if not want or i["tag"] == want]
        if items:
            days.append({"at": row["at"], "test": row["mode"] != "executed", "mode": row["mode"], "entries": items})
    return render("activity.html", me, page="activity", days=days, f=f, serr=serr)


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
