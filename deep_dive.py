"""
Deep dive (step 12) - the judgment half of the daily scenario.

    Watchlist -> /deep-dive-input (facts, code) -> News Analyst (LLM)
              -> /deep-dive-cases (code: picks the possible thesis breaks)
              -> Confirm/Veto committee: Claude, GPT, Kimi (LLM, independent)
              -> /deep-dive-decide (code: applies the exit rule) -> /rebalance (hold, exit)

Facts are code, judgment is LLM, decisions are code:
  - The News Analyst only sees news since the last weekly run, per basket name or holding,
    with the thesis and the facts. It answers none / wait / break (with a quoted headline).
  - wait -> "hold": a BUY is delayed (rebalance caps any delay at 3 days after the weekly run).
  - break -> the committee judges it independently. EXIT only if
        2 of 3 say broken AND the market confirms (down >= DD_CONFIRM_DROP_PCT (8%) since the
        news, or >= DD_CONFIRM_VS_SPY_PTS (5) points worse than SPY), or
        3 of 3 say broken (the market may not have caught up yet).
    Otherwise the name is put on hold (no new buying) and logged.
  - With fewer than 3 readable votes an exit always needs the market confirmation and 2 yes.
  - Price-shock trigger (code): a HELD name with news that fell >= DD_SHOCK_5D_PCT (10%) in 5 days
    or >= DD_SHOCK_VS_SPY_PTS (8) points vs SPY since the news also goes to the committee, even if
    the News Analyst missed it - the committee reads the raw news itself. Same exit rule.
  - Missing or failed LLM output never blocks trading: empty hold / exit, code rules still run.

Endpoints (POST, JSON):
  /deep-dive-input   {"basket": "SNDK:5,MU:4.8,...", "notes": "SYM|thesis|risk_exposure\\n..."}
      -> facts_json (all names), llm_input_json (names with news), news_names, news_count
  /deep-dive-cases   {"facts": facts_json, "analyst": <analyst text>}
      -> cases_json (possible breaks, for the committee), cases_count, hold
  /deep-dive-decide  {"facts": facts_json, "analyst": <analyst text>,
                      "vote_claude": <text>, "vote_gpt": <text>, "vote_kimi": <text>}
      -> hold (csv), exit (csv), decisions, decisions_json, summary
"""
import datetime
import json
import os
import re

import requests
from flask import Blueprint, jsonify, request

import rebalance as rb

deep_dive_bp = Blueprint("deep_dive", __name__)

DD_CONFIRM_DROP_PCT = float(os.environ.get("DD_CONFIRM_DROP_PCT", 8.0))
DD_CONFIRM_VS_SPY_PTS = float(os.environ.get("DD_CONFIRM_VS_SPY_PTS", 5.0))
NEWS_PER_NAME = int(os.environ.get("DD_NEWS_PER_NAME", 6))
# Price-shock trigger: a held name with news that fell this much goes to the committee even if
# the News Analyst saw no break (the committee reads the raw news itself).
DD_SHOCK_5D_PCT = float(os.environ.get("DD_SHOCK_5D_PCT", 10.0))
DD_SHOCK_VS_SPY_PTS = float(os.environ.get("DD_SHOCK_VS_SPY_PTS", 8.0))


# --------------------------------------------------------------------------- parsing

def parse_notes(text):
    """{symbol: {thesis, risk_exposure}} from lines 'SYM|thesis|risk_exposure'."""
    out = {}
    for line in re.split(r"[\r\n]+", str(text or "")):
        parts = [p.strip() for p in line.split("|")]
        if parts and re.fullmatch(r"[A-Za-z.\-]{1,6}", parts[0] or ""):
            out[parts[0].upper()] = {"thesis": parts[1] if len(parts) > 1 else "",
                                     "risk_exposure": parts[2] if len(parts) > 2 else ""}
    return out


def llm_json(text, key):
    """List under `key` from an LLM answer (tolerates code fences, prose around the JSON,
    a bare list, or Make's ', '-joined content blocks). None if nothing readable."""
    if text is None:
        return None
    if isinstance(text, (list, dict)):
        obj = text
    else:
        t = str(text).strip()
        if not t:
            return None
        t = re.sub(r"```(?:json)?", "", t)
        obj = None
        pairs = sorted((("{", "}"), ("[", "]")), key=lambda oc: t.find(oc[0]) if t.find(oc[0]) != -1 else 10**9)
        for opener, closer in pairs:
            i, j = t.find(opener), t.rfind(closer)
            if i != -1 and j > i:
                try:
                    obj = json.loads(t[i:j + 1])
                    break
                except ValueError:
                    continue
        if obj is None:
            return None
    if isinstance(obj, dict):
        obj = obj.get(key, [])
    return obj if isinstance(obj, list) else None


def _truthy(v):
    return v is True or str(v).strip().lower() in ("true", "yes", "1", "broken")


def _load(v, default):
    if isinstance(v, str):
        try:
            return json.loads(v) if v.strip() else default
        except ValueError:
            return default
    return v if v is not None else default


# --------------------------------------------------------------------------- input

def fetch_news(symbols, since):
    """{symbol: [{time, headline, summary}]} newest first, since `since` (UTC datetime)."""
    out = {s: [] for s in symbols}
    syms = sorted(symbols)
    for i in range(0, len(syms), 20):
        token = None
        for _ in range(5):
            params = {"symbols": ",".join(syms[i:i + 20]), "start": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "limit": 50, "sort": "desc"}
            if token:
                params["page_token"] = token
            r = requests.get(f"{rb.DATA_BASE}/v1beta1/news", headers=rb.HEADERS, params=params, timeout=15)
            if r.status_code != 200:
                raise requests.RequestException(f"news HTTP {r.status_code}")
            data = r.json()
            for a in data.get("news", []):
                head = str(a.get("headline") or "").strip()
                if not head:
                    continue
                item = {"time": str(a.get("created_at") or "")[:16], "headline": head[:200],
                        "summary": re.sub(r"\s+", " ", str(a.get("summary") or ""))[:300]}
                for s in a.get("symbols") or []:
                    if s in out and len(out[s]) < NEWS_PER_NAME and \
                            all(x["headline"].lower()[:80] != head.lower()[:80] for x in out[s]):
                        out[s].append(item)
            token = data.get("next_page_token")
            if not token:
                break
    return out


def move_since(series, day):
    """% move from the last close BEFORE `day` (YYYY-MM-DD) to the latest close."""
    if not series or not day:
        return None
    before = [c for d, c in series if d < day]
    if not before:
        return None
    return round((series[-1][1] / before[-1] - 1) * 100, 1)


def build_input(basket_rows, notes, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    errors = []
    basket = [s for s, _, _ in basket_rows]
    positions = rb._get("/v2/positions")
    pos = {p["symbol"]: p for p in positions}
    try:
        since = rb.holdings_since(rb.fetch_fills(), positions)
    except requests.RequestException as e:
        since, _ = {}, errors.append(f"fills: {e}")
    syms = list(dict.fromkeys(basket + list(pos)))
    try:
        closes = rb.daily_closes(set(syms) | {"SPY"})
    except requests.RequestException as e:
        closes, _ = {}, errors.append(f"bars: {e}")
    weekly = rb.last_weekly_run(now)
    try:
        news = fetch_news(syms, weekly)
    except requests.RequestException as e:
        news, _ = {s: [] for s in syms}, errors.append(f"news: {e} - no news today, nothing for the LLMs")
    today = now.date()
    facts = []
    for s in syms:
        i = rb.indicators(closes.get(s), since.get(s))
        held = s in pos
        d = (today - datetime.date.fromisoformat(since[s])).days if s in since else None
        if not held:
            status = "not held yet (buy pending)" if s in basket else "held? no"
        elif d is not None and d < rb.TRANCHES * rb.TRANCHE_DAYS:
            status = f"building position (day {d}, tranches of {rb.TRANCHE_DAYS} days)"
        elif d is not None and d < rb.HOLD_DAYS:
            status = f"in 6-month hold, day {d} of {rb.HOLD_DAYS}"
        else:
            status = "held, past the 6-month hold"
        if s not in basket:
            status += " - NOT in this week's basket (being sold)"
        items = news.get(s, [])
        first_day = min((x["time"][:10] for x in items), default=None)
        mv, spy_mv = move_since(closes.get(s), first_day), move_since(closes.get("SPY"), first_day)
        n = notes.get(s, {})
        facts.append({
            "symbol": s, "in_basket": s in basket, "held": held, "status": status,
            "gain_since_purchase_pct": round(float(pos[s].get("unrealized_plpc") or 0) * 100, 1) if held else None,
            "ret_5d_pct": round(i["ret5"] * 100, 1) if i and i["ret5"] is not None else None,
            "ret_10d_pct": round(i["ret10"] * 100, 1) if i and i["ret10"] is not None else None,
            "below_high_since_purchase_pct": round(i["dd_from_high"] * 100, 1) if i and held else None,
            "vs_150d_average_pct": round((i["close"] / i["sma"] - 1) * 100, 1) if i and i["sma"] else None,
            "thesis": n.get("thesis", ""), "risk_exposure": n.get("risk_exposure", ""),
            "news_since": weekly.date().isoformat(), "news": items,
            "move_since_first_news_pct": mv,
            "vs_spy_since_first_news_pts": round(mv - spy_mv, 1) if mv is not None and spy_mv is not None else None,
        })
    with_news = [f for f in facts if f["news"]]
    return {
        "as_of": now.isoformat(timespec="seconds"),
        "facts": facts, "facts_json": json.dumps(facts),
        "llm_input_json": json.dumps(with_news),
        "news_names": ",".join(f["symbol"] for f in with_news),
        "news_count": sum(len(f["news"]) for f in facts),
        "errors": errors,
    }


# --------------------------------------------------------------------------- cases / decide

def analyst_items(text, text2=None):
    """Merged analyst verdicts. With a second analyst (optional): break if EITHER says break
    (the committee filters false alarms), wait if either says wait."""
    a, b = _one_analyst(text), _one_analyst(text2)
    rank = {"none": 0, "wait": 1, "break": 2}
    out = dict(a)
    for s, x in b.items():
        if s not in out or rank[x["verdict"]] > rank[out[s]["verdict"]]:
            out[s] = dict(x, reason=x["reason"] + (" [2nd analyst]" if s in a else " [2nd analyst only]"))
    return out


def _one_analyst(text):
    items = llm_json(text, "items") or []
    out = {}
    for x in items:
        if isinstance(x, dict) and x.get("symbol"):
            v = str(x.get("verdict") or "none").strip().lower()
            out[str(x["symbol"]).upper()] = {"verdict": v if v in ("none", "wait", "break") else "none",
                                             "reason": str(x.get("reason") or "")[:300],
                                             "evidence": str(x.get("evidence") or "")[:300]}
    return out


def cases(facts, analyst_text, analyst_text2=None):
    fx = {f["symbol"]: f for f in facts}
    items = analyst_items(analyst_text, analyst_text2)
    out = []
    flagged = [(s, a["reason"], a["evidence"], "analyst") for s, a in items.items() if a["verdict"] == "break"]
    for f in facts:
        s = f["symbol"]
        if s in items and items[s]["verdict"] == "break" or not f.get("held") or not f.get("news"):
            continue
        r5, rel = f.get("ret_5d_pct"), f.get("vs_spy_since_first_news_pts")
        if (r5 is not None and r5 <= -DD_SHOCK_5D_PCT) or (rel is not None and rel <= -DD_SHOCK_VS_SPY_PTS):
            flagged.append((s, f"price shock ({r5}% in 5 days, {rel} pts vs SPY since the news) - the News Analyst "
                               "saw no break; judge the raw news yourself", "", "price_shock"))
    for s, reason, evidence, source in flagged:
        if s in fx:
            f = fx[s]
            out.append({"symbol": s, "flagged_by": source, "status": f["status"], "thesis": f["thesis"],
                        "risk_exposure": f["risk_exposure"], "news": f["news"],
                        "analyst_reason": reason, "analyst_evidence": evidence,
                        "move_since_first_news_pct": f["move_since_first_news_pct"],
                        "vs_spy_since_first_news_pts": f["vs_spy_since_first_news_pts"],
                        "gain_since_purchase_pct": f["gain_since_purchase_pct"]})
    hold = sorted(s for s, a in items.items() if a["verdict"] == "wait")
    return out, hold, items


def decide(facts, analyst_text, votes, analyst_text2=None):
    """votes: {model: answer text}. Returns hold/exit lists and a log per name."""
    fx = {f["symbol"]: f for f in facts}
    case_list, hold, items = cases(facts, analyst_text, analyst_text2)
    parsed, errors = {}, []
    for model, text in votes.items():
        v = llm_json(text, "verdicts")
        if v is None:
            if text not in (None, ""):
                errors.append(f"{model}: answer not readable - counted as missing")
            continue
        parsed[model] = {str(x.get("symbol", "")).upper(): x for x in v if isinstance(x, dict)}
    exits, extra_hold, decisions = [], [], []
    for c in case_list:
        s = c["symbol"]
        yes = [m for m, v in parsed.items() if s in v and _truthy(v[s].get("broken"))]
        mv, rel = c["move_since_first_news_pct"], c["vs_spy_since_first_news_pts"]
        market = (mv is not None and mv <= -DD_CONFIRM_DROP_PCT) or (rel is not None and rel <= -DD_CONFIRM_VS_SPY_PTS)
        n = len(parsed)
        if len(yes) >= 2 and market:
            action, why = "exit", f"{len(yes)} of {n} committee votes say broken and the market confirms"
        elif len(yes) == 3:
            action, why = "exit", "3 of 3 committee votes say broken (market not yet confirming)"
        elif yes:
            action, why = "hold", (f"{len(yes)} of {n} votes say broken" + ("" if market else ", market not confirming")
                                   + " - no exit; no new buying while the story is open")
        else:
            action, why = "none", f"0 of {n} votes say broken - analyst overruled"
        if action == "exit":
            exits.append(s)
        elif action == "hold":
            extra_hold.append(s)
        decisions.append({
            "symbol": s, "action": action, "why": why, "flagged_by": c["flagged_by"], "analyst_reason": c["analyst_reason"],
            "evidence": c["analyst_evidence"], "move_since_news_pct": mv, "vs_spy_pts": rel,
            "votes": {m: {"broken": _truthy(v.get(s, {}).get("broken")) if s in v else None,
                          "reason": str(v.get(s, {}).get("reason") or "")[:200]} for m, v in parsed.items()},
            "held": fx.get(s, {}).get("held"),
        })
    for s in hold:
        decisions.append({"symbol": s, "action": "wait", "why": "News Analyst: wait (timing)",
                          "analyst_reason": items[s]["reason"], "evidence": items[s]["evidence"]})
    hold_all = sorted(set(hold) | set(extra_hold))
    summary = {"names_with_news": sum(1 for f in facts if f["news"]), "analyst_items": len(items),
               "wait": len(hold), "break_cases": len(case_list), "votes_readable": len(parsed),
               "exits": exits, "hold": hold_all,
               "rule": f"exit = 2 of 3 broken + market (<= -{DD_CONFIRM_DROP_PCT:g}% or <= -{DD_CONFIRM_VS_SPY_PTS:g} pts vs SPY), or 3 of 3"}
    if analyst_text not in (None, "") and llm_json(analyst_text, "items") is None:
        errors.append("analyst answer not readable - no hold/exit from it today")
    return {"hold": ",".join(hold_all), "exit": ",".join(exits), "decisions": decisions,
            "decisions_json": json.dumps(decisions), "summary": summary, "summary_json": json.dumps(summary),
            "errors": errors}


# --------------------------------------------------------------------------- routes

@deep_dive_bp.route("/deep-dive-input", methods=["POST"])
def deep_dive_input():
    body = request.get_json(force=True, silent=True) or {}
    rows = rb.parse_basket(body.get("basket"))
    if len(rows) < 5:
        return jsonify({"error": f"basket has {len(rows)} names - expected about 20"}), 400
    try:
        return jsonify(build_input(rows, parse_notes(body.get("notes"))))
    except requests.RequestException as e:
        return jsonify({"error": f"Alpaca request failed: {e}"}), 502


@deep_dive_bp.route("/deep-dive-cases", methods=["POST"])
def deep_dive_cases():
    body = request.get_json(force=True, silent=True) or {}
    facts = _load(body.get("facts"), [])
    c, hold, items = cases(facts, body.get("analyst"), body.get("analyst_2"))
    return jsonify({"cases_json": json.dumps(c), "cases_count": len(c), "hold": ",".join(hold),
                    "analyst_readable": llm_json(body.get("analyst"), "items") is not None})


@deep_dive_bp.route("/deep-dive-decide", methods=["POST"])
def deep_dive_decide():
    body = request.get_json(force=True, silent=True) or {}
    facts = _load(body.get("facts"), [])
    votes = {m: body.get(f"vote_{m}") for m in ("claude", "gpt", "kimi")}
    return jsonify(decide(facts, body.get("analyst"), votes, body.get("analyst_2")))
