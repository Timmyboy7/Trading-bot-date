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

OVERLAY MODE (added 2026-10-09, the Micro rebuild). If the body carries "base"
(/base-score's base_json) the rubric is no longer scored by the LLM at all:
    new score = deterministic base score (code)
              + median of the LLM overlay readings (each -0.5..+0.5, one per Micro run)
              + insider-buying bonus (code)
then blended with last week's score as before. Extra body fields:
    "base":      [...]                          // /base-score base_json
    "overlay_1", "overlay_2", "overlay_3": "..."  // raw text of each Micro run (or "overlays": [..])
Per name the ranking also reports: base_score, overlay, overlay_readings,
uncertain (readings disagree by >= UNCERTAIN_SPREAD -> reconcile takes no
score-based action on it this week), red_flag (a majority of runs reported a
thesis-breaking event -> reconcile may exit it / never adds it), flags, evidence.
"""
import json
import os
import statistics

from flask import Blueprint, jsonify, request

select_bp = Blueprint("select_basket", __name__)

BASKET_SIZE = int(os.environ.get("RECON_BASKET_SIZE", 20))
MAX_PER_SECTOR = int(os.environ.get("RECON_MAX_PER_SECTOR", 5))
DEFAULT_BLEND = float(os.environ.get("SELECT_BLEND", 0.5))
HIGH_AT = float(os.environ.get("SELECT_HIGH_AT", 4.0))
MEDIUM_AT = float(os.environ.get("SELECT_MEDIUM_AT", 3.2))

OVERLAY_MAX = 0.5
UNCERTAIN_SPREAD = float(os.environ.get("SELECT_UNCERTAIN_SPREAD", 0.75))

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


def _parse_text(text):
    """JSON from LLM text: plain, ```json fenced, or wrapped in extra prose /
    <think>...</think> reasoning (some open models do that) — then the outermost
    [...] (or {...}) block is used. Raises ValueError if nothing parses."""
    s = text.strip()
    if "</think>" in s:
        s = s.split("</think>")[-1].strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        if s.lower().startswith("json"):
            s = s[4:].strip()
    try:
        return json.loads(s)
    except ValueError:
        pass
    for open_c, close_c in (("[", "]"), ("{", "}")):
        i, j = s.find(open_c), s.rfind(close_c)
        if 0 <= i < j:
            try:
                return json.loads(s[i:j + 1])
            except ValueError:
                continue
    raise ValueError("no JSON array/object found in text")


def _load(v):
    """Array, JSON string (optionally fenced), or list of lists -> flat list of dicts."""
    if v is None or v == "":
        return []
    if isinstance(v, str):
        v = _parse_text(v)
    if isinstance(v, dict):
        for key in ("scores", "basket", "candidates", "rows", "items", "signals", "overlays", "results", "base"):
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


def _snap(v):
    """Clamp to +/-OVERLAY_MAX and snap to the 0.25 grid the prompt asks for."""
    v = min(max(v, -OVERLAY_MAX), OVERLAY_MAX)
    return round(v * 4) / 4


def _truthy(v):
    return v is True or str(v).strip().lower() in ("true", "yes", "1")


def select_overlay(base, overlay_runs, previous, candidates, blend=DEFAULT_BLEND, signals=None, sparse=()):
    """sparse: run ids whose model was asked to list only stocks with something to
    report (faster for slow open models) — a stock missing from such a run counts
    as an explicit 0 reading with no flags."""
    blend = min(max(blend, 0.0), 1.0)
    sig = {}
    for r in signals or []:
        s_ = _sym(r)
        adj = _to_float(_get(r, "adjustment"))
        if s_ and adj:
            sig[s_] = (min(max(adj, 0.0), 0.20), str(_get(r, "reason", default="") or ""))
    cand_rank = {}
    for i, c in enumerate(candidates):
        s = _sym(c)
        if s:
            cand_rank[s] = i + 1
    prev = {}
    for r in previous:
        s = _sym(r)
        if s:
            prev[s] = _to_float(_get(r, "score"))

    # collect each run's reading per symbol
    readings = {}
    for run_no, run in overlay_runs:
        seen = set()
        for r in run:
            s = _sym(r)
            o = _to_float(_get(r, "overlay"))
            if not s or o is None or s in seen:
                continue
            seen.add(s)
            readings.setdefault(s, []).append({
                "run": run_no,
                "overlay": _snap(o),
                "thesis_break": _truthy(_get(r, "thesis_break", default=False)),
                "data_anomaly": _truthy(_get(r, "data_anomaly", default=False)),
                "cluster": str(_get(r, "cluster", default="") or "").strip(),
                "evidence": str(_get(r, "evidence", default="") or "").strip(),
                "thesis": str(_get(r, "thesis_summary", default="") or "").strip(),
                "target": _to_float(_get(r, "target_price")),
            })
    n_runs = len(overlay_runs)
    all_syms = [_sym(b) for b in base if _sym(b)]
    for run_no, run in overlay_runs:
        if run_no not in sparse:
            continue
        listed = {_sym(r) for r in run}
        for s in all_syms:
            if s not in listed and not any(x["run"] == run_no for x in readings.get(s, [])):
                readings.setdefault(s, []).append({"run": run_no, "overlay": 0.0, "thesis_break": False,
                                                   "data_anomaly": False, "cluster": "", "evidence": "",
                                                   "thesis": "", "target": None})

    ranking = []
    for b in base:
        s = _sym(b)
        if not s:
            continue
        base_score = _to_float(_get(b, "base_score"))
        if base_score is None:
            continue
        rd = readings.get(s, [])
        vals = sorted(x["overlay"] for x in rd)
        overlay = statistics.median(vals) if vals else 0.0
        spread = (vals[-1] - vals[0]) if len(vals) >= 2 else 0.0
        uncertain = len(vals) >= 2 and spread >= UNCERTAIN_SPREAD
        breaks = sum(1 for x in rd if x["thesis_break"])
        red_flag = bool(rd) and breaks * 2 > len(rd)
        anomaly = bool(rd) and sum(1 for x in rd if x["data_anomaly"]) * 2 > len(rd)
        clusters = [x["cluster"].lower() for x in rd if x["cluster"]]
        # a cluster label only counts if at least two readings agree on it (one reading
        # is enough only when there is a single run) — labels differ between models
        need = 2 if len(rd) >= 2 else 1
        top = max(set(clusters), key=lambda c: (clusters.count(c), c)) if clusters else ""
        cluster = top if top and clusters.count(top) >= need else ""
        # thesis/evidence from the reading closest to the median
        pick = min(rd, key=lambda x: abs(x["overlay"] - overlay)) if rd else None
        adj, adj_reason = sig.get(s, (0.0, ""))
        new = min(max(base_score + overlay + adj, 1.0), 5.0)
        old = prev.get(s)
        blended = new if old is None else blend * new + (1 - blend) * old
        flags = list(_get(b, "flags", default=[]) or [])
        if not rd:
            flags.append("no_llm_review")
        if anomaly:
            flags.append("llm_data_anomaly")
        # thesis text from the closest reading that has one (sparse runs carry none)
        with_thesis = [x for x in rd if x["thesis"]]
        thesis = min(with_thesis, key=lambda x: abs(x["overlay"] - overlay))["thesis"] if with_thesis else ""
        if pick and pick["evidence"] and overlay != 0:
            thesis += f" [Overlay {overlay:+.2f}: {pick['evidence']}]"
        if adj_reason:
            thesis += f" [Signal: {adj_reason}]"
        targets = [x["target"] for x in rd if x["target"]]
        ranking.append({
            "symbol": s,
            "sector": str(_get(b, "sector", default="Unknown")),
            "is_holding": bool(_get(b, "is_holding", default=False)),
            "thesis_summary": thesis.strip(),
            "target_price": round(statistics.median(targets), 2) if targets else None,
            "score": round(blended, 3),
            "new_score": round(new, 3),
            "base_score": round(base_score, 3),
            "overlay": overlay,
            "overlay_readings": vals,
            # per Micro module (overlay_1/2/3), to compare models over time
            "overlay_by_run": {str(x["run"]): x["overlay"] for x in rd},
            "signal_adj": adj,
            "prev_score": None if old is None else round(old, 3),
            "runs": len(vals),
            "uncertain": uncertain,
            "red_flag": red_flag,
            "cluster": cluster,
            "flags": sorted(set(flags)),
            "pillars": _get(b, "pillars", default={}),
            "conviction": conviction_for(blended),
        })

    ranking.sort(key=lambda r: (-r["score"], cand_rank.get(r["symbol"], 10**6), r["symbol"]))
    proposed, counts = [], {}
    for r in ranking:
        if len(proposed) >= BASKET_SIZE:
            break
        if r["red_flag"] or counts.get(r["sector"], 0) >= MAX_PER_SECTOR:
            continue
        counts[r["sector"]] = counts.get(r["sector"], 0) + 1
        proposed.append(r)

    summary = {
        "mode": "overlay",
        "scored_symbols": len(ranking),
        "proposed": len(proposed),
        "blend": blend,
        "overlay_runs": n_runs,
        "reviewed_by_llm": sum(1 for r in ranking if r["runs"]),
        "uncertain": sorted(r["symbol"] for r in ranking if r["uncertain"]),
        "red_flags": sorted(r["symbol"] for r in ranking if r["red_flag"]),
        "overlay_nonzero": sorted(f"{r['symbol']} {r['overlay']:+.2f}" for r in ranking if r["overlay"]),
        "sector_counts": counts,
    }
    return {
        "proposed": proposed,
        "proposed_json": json.dumps(proposed),
        "ranking": ranking,
        "ranking_json": json.dumps(ranking),
        "summary": summary,
        "summary_json": json.dumps(summary),
    }


@select_bp.route("/select-basket", methods=["POST"])
def select_basket():
    body = request.get_json(force=True, silent=True) or {}
    if body.get("base"):
        return _select_overlay_endpoint(body)
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


def _select_overlay_endpoint(body):
    try:
        base = _load(body.get("base"))
        previous = _load(body.get("previous"))
        candidates = _load(body.get("candidates"))
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"could not parse input: {e}"}), 400
    if not base:
        return jsonify({"error": "base scores are empty — refusing to select (/base-score failed?)"}), 400
    raw_runs = [(f"x{i + 1}", r) for i, r in enumerate(body.get("overlays") or [])]
    raw_runs += [(k[-1], body.get(k)) for k in ("overlay_1", "overlay_2", "overlay_3") if body.get(k)]
    runs, bad, bad_names = [], 0, []
    for name, raw in raw_runs:
        try:
            run = _load(raw)
        except (ValueError, TypeError):
            bad += 1   # one unparseable Micro run must not block the basket; the others still count
            bad_names.append(name)
            continue
        if run:
            runs.append((name, run))
    try:
        signals = _load(body.get("signals"))
    except (ValueError, TypeError):
        signals = []
    blend = _to_float(body.get("blend"))
    sparse = {x.strip() for x in str(body.get("sparse") or "").split(",") if x.strip()}
    result = select_overlay(base, runs, previous, candidates, DEFAULT_BLEND if blend is None else blend, signals, sparse)
    result["summary"]["unparseable_runs"] = bad
    result["summary"]["unparseable_run_ids"] = bad_names
    result["summary"]["usable_run_ids"] = [n for n, _ in runs]
    result["summary"]["sparse_run_ids"] = sorted(sparse)
    result["summary_json"] = json.dumps(result["summary"])
    if not runs:
        return jsonify({"error": "no usable Micro overlay run — refusing to select", "summary": result["summary"]}), 400
    if len(result["proposed"]) < BASKET_SIZE // 2:
        return jsonify({"error": "too few usable scores — refusing to propose a basket", "summary": result["summary"]}), 400
    return jsonify(result)
