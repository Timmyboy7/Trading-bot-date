"""
Basket selection from Micro Analyst SCORES — makes the proposal stable.

Why this exists: when Micro Analyst is asked to "pick 20", the choice flips
on near-ties and on run-to-run sampling noise (a name rated "high" one run can
be absent the next). Here Micro instead RATES every candidate on a fixed
rubric, and this code does the selecting. Two things give stability:

  1. Averaging: if Micro was run several times, scores are averaged per symbol.
  2. Memory: a name already in the Watchlist keeps part of last week's score
     (blended = BLEND * new + (1 - BLEND) * previous), so one noisy week can't
     flip it — it takes sustained deterioration to move.

Pipeline position:

    Screen -> Macro -> Valuation -> Micro (scores) -> THIS -> /reconcile-basket -> Watchlist

Endpoint:
    POST /select-basket
    {
      "scores":     [ {symbol, quality, valuation, trend_confirmation, risk,
                       target_price, thesis_summary}, ... ],   // Micro output; array or JSON string;
                                                               // may be several runs concatenated,
                                                               // or a list of lists
      "previous":   [ Watchlist rows incl. a "score" column ],  // [] on first run
      "candidates": [ /screen candidates (symbol, sector, combined_score) ],
      "signals":    [ /signals output (symbol, adjustment, reason) ],   // optional; insider-buying bonus, +0..0.20
      "blend":      0.5                                         // optional, weight of THIS week's score
    }

Response:
    {
      "proposed": [ {symbol, sector, thesis_summary, target_price, conviction, score, new_score, prev_score}, ... ],
      "proposed_json": "...",   // the same list as a string, for Make's escapeJSON()
      "ranking":  [ ...every scored symbol with its blended score, best first... ],
      "summary":  {...}
    }

`proposed` has exactly the shape /reconcile-basket expects, plus `score`.

Rubric (1-5 each, 5 = best; for risk 5 = lowest risk):
    quality 35%, valuation 20%, trend_confirmation 25%, risk 20%
Conviction is derived here, not by the LLM:  score >= 4.0 high, >= 3.2 medium, else low.
"""
import json
import os

from flask import Blueprint, jsonify, request

select_bp = Blueprint("select_basket", __name__)

BASKET_SIZE = int(os.environ.get("RECON_BASKET_SIZE", 20))
MAX_PER_SECTOR = int(os.environ.get("RECON_MAX_PER_SECTOR", 5))
DEFAULT_BLEND = float(os.environ.get("SELECT_BLEND", 0.5))
HIGH_AT = float(os.environ.get("SELECT_HIGH_AT", 4.0))
MEDIUM_AT = float(os.environ.get("SELECT_MEDIUM_AT", 3.2))

WEIGHTS = {"quality": 0.35, "valuation": 0.20, "trend_confirmation": 0.25, "risk": 0.20}


def _norm(k):
    return "".join(ch for ch in str(k).lower() if ch.isalnum())


def _get(row, *names, default=None):
    lookup = {_norm(k): v for k, v in row.items()}
    for n in names:
        v = lookup.get(_norm(n))
        if v is not None and v != "":
            return v
    return default


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _load(v):
    """Array, JSON string (optionally fenced), or list of lists -> flat list of dicts."""
    if v is None or v == "":
        return []
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("```"):
            s = s.strip("`").strip()
            if s.lower().startswith("json"):
                s = s[4:].strip()
        v = json.loads(s)
    if isinstance(v, dict):
        for key in ("scores", "basket", "candidates", "rows", "items", "signals"):
            if key in v:
                return _load(v[key])
        return []
    out = []
    for item in v:
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, (list, str)):
            out.extend(_load(item))
    return out


def _sym(row):
    return str(_get(row, "symbol", default="") or "").strip().upper()


def conviction_for(score):
    if score is None:
        return ""
    if score >= HIGH_AT:
        return "high"
    if score >= MEDIUM_AT:
        return "medium"
    return "low"


def total_score(row):
    """Weighted rubric score, or None if any rubric field is missing/invalid."""
    parts = {}
    for k in WEIGHTS:
        v = _to_float(_get(row, k, "trend" if k == "trend_confirmation" else k))
        if v is None:
            return None
        parts[k] = min(max(v, 1.0), 5.0)
    return sum(WEIGHTS[k] * parts[k] for k in WEIGHTS)


def select(scores, previous, candidates, blend=DEFAULT_BLEND, signals=None):
    blend = min(max(blend, 0.0), 1.0)

    # optional insider-buying bonus from /signals: deterministic, capped at +0.20
    sig = {}
    for r in signals or []:
        s_ = _sym(r)
        adj = _to_float(_get(r, "adjustment"))
        if s_ and adj:
            sig[s_] = (min(max(adj, 0.0), 0.20), str(_get(r, "reason", default="") or ""))

    # sector + screener rank from /screen (sector falls back to the scored row, then the sheet)
    cand_sector, cand_rank = {}, {}
    for i, c in enumerate(candidates):
        s = _sym(c)
        if s:
            cand_sector[s] = str(_get(c, "sector", default="Unknown"))
            cand_rank[s] = i + 1

    prev = {}
    for r in previous:
        s = _sym(r)
        if s:
            prev[s] = {
                "score": _to_float(_get(r, "score")),
                "sector": str(_get(r, "sector", default="Unknown")),
            }

    # average this week's runs per symbol
    agg = {}
    skipped = []
    for r in scores:
        s = _sym(r)
        if not s:
            continue
        t = total_score(r)
        if t is None:
            skipped.append(s)
            continue
        a = agg.setdefault(s, {"scores": [], "targets": [], "thesis": "", "sector": None})
        a["scores"].append(t)
        tp = _to_float(_get(r, "target_price"))
        if tp:
            a["targets"].append(tp)
        th = _get(r, "thesis_summary", "reasoning", default="")
        if th and not a["thesis"]:
            a["thesis"] = th
        sec = _get(r, "sector")
        if sec and not a["sector"]:
            a["sector"] = str(sec)

    ranking = []
    for s, a in agg.items():
        raw = sum(a["scores"]) / len(a["scores"])
        adj, adj_reason = sig.get(s, (0.0, ""))
        new = min(max(raw + adj, 1.0), 5.0)
        old = prev.get(s, {}).get("score")
        blended = new if old is None else blend * new + (1 - blend) * old
        ranking.append({
            "symbol": s,
            "sector": cand_sector.get(s) or a["sector"] or prev.get(s, {}).get("sector") or "Unknown",
            "thesis_summary": (a["thesis"] + (f" [Signal: {adj_reason}]" if adj_reason else "")).strip(),
            "target_price": round(sum(a["targets"]) / len(a["targets"]), 2) if a["targets"] else None,
            "score": round(blended, 3),
            "new_score": round(new, 3),
            "raw_score": round(raw, 3),
            "signal_adj": adj,
            "prev_score": None if old is None else round(old, 3),
            "runs": len(a["scores"]),
            "conviction": conviction_for(blended),
        })

    # best first; ties broken by screener rank (better rank first), then symbol
    ranking.sort(key=lambda r: (-r["score"], cand_rank.get(r["symbol"], 10**6), r["symbol"]))

    proposed, counts = [], {}
    for r in ranking:
        if len(proposed) >= BASKET_SIZE:
            break
        if counts.get(r["sector"], 0) >= MAX_PER_SECTOR:
            continue
        counts[r["sector"]] = counts.get(r["sector"], 0) + 1
        proposed.append(r)

    summary = {
        "scored_symbols": len(ranking),
        "proposed": len(proposed),
        "blend": blend,
        "runs_seen": max((r["runs"] for r in ranking), default=0),
        "skipped_incomplete": sorted(set(skipped)),
        "sector_counts": counts,
    }
    return {
        "proposed": proposed,
        # same list pre-stringified: Make can't put an array of objects into a JSON body
        # directly, but escapeJSON(select.data.proposed_json) works (project convention).
        "proposed_json": json.dumps(proposed),
        "ranking": ranking,
        "ranking_json": json.dumps(ranking),   # for the Runs log sheet
        "summary": summary,
        "summary_json": json.dumps(summary),
    }


@select_bp.route("/select-basket", methods=["POST"])
def select_basket():
    body = request.get_json(force=True, silent=True) or {}
    try:
        scores = _load(body.get("scores"))
        previous = _load(body.get("previous"))
        candidates = _load(body.get("candidates"))
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"could not parse input: {e}"}), 400

    if not scores:
        return jsonify({"error": "scores are empty — refusing to select (Micro step failed?)"}), 400
    try:
        signals = _load(body.get("signals"))
    except (ValueError, TypeError):
        signals = []  # signals are optional: a bad/empty value must never block the basket
    blend = _to_float(body.get("blend"))
    result = select(scores, previous, candidates, DEFAULT_BLEND if blend is None else blend, signals)
    if len(result["proposed"]) < BASKET_SIZE // 2:
        return jsonify({"error": "too few usable scores — refusing to propose a basket", "summary": result["summary"]}), 400
    return jsonify(result)
