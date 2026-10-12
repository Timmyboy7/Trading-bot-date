"""
Basket reconcile — deterministic stability layer for the weekly Watchlist.

Sits between Micro Analyst and the Google Sheets write in the weekly
Discovery scenario:

    Screen -> Macro -> Valuation -> Micro -> THIS -> Watchlist (Sheets)

Principle (same as Risk Guardrails): the LLM proposes, code decides what
actually changes. Micro stays blind to the current basket and gives its
honest "best 20 right now"; this step decides which of those changes are
worth acting on, so the basket doesn't churn on noise but can still react to
a real regime change. No LLM, no network calls — pure logic on three inputs.

Drop next to app.py, then in app.py add:

    from reconcile_basket import reconcile_bp
    app.register_blueprint(reconcile_bp)

Endpoint:
    POST /reconcile-basket
    Body (JSON). Each of the three lists may be a real JSON array OR a JSON
    string of one (Make's json.dumps convention), and rows may use sheet-style
    keys ("Added On", "Symbol", ...) or snake_case:
      {
        "proposed":   [ {symbol, sector, thesis_summary, target_price, conviction}, ... ],  // Micro's basket
        "current":    [ {symbol, added_on, sector, thesis_summary, target_price,
                         conviction, weeks_below_cutoff, last_reviewed}, ... ],              // rows now in the Watchlist ([] on first run)
        "candidates": [ {symbol, sector, combined_score, ...}, ... ],                        // this week's /screen candidates
        "today":      "2026-10-07"                                                           // optional, for testing
      }

Response:
    {
      "as_of": "...",
      "basket":  [ {symbol, added_on, sector, thesis_summary, target_price, conviction,
                    weeks_below_cutoff, last_reviewed, status}, ... ],   // native array: Make's Iterator can read it directly
      "actions": [ {symbol, action, reason, ...}, ... ],                // kept/dropped/added/blocked + why (audit log)
      "actions_json": "...",                                           // same, pre-stringified for Make/escapeJSON
      "summary": {...}
    }

Safety: if `proposed` or `candidates` is empty the endpoint returns HTTP 400
instead of a basket, so a failed upstream step makes Make error out rather
than quietly wiping the Watchlist. Put this call BEFORE the "Clear a Row"
step in the scenario.

Rules (all overridable via env vars; defaults confirmed 2026-10-07):
  - Basket is fixed at BASKET_SIZE (20) names, at most MAX_PER_SECTOR (5) per sector.
  - Persistence: an incumbent missing from the screener candidates is dropped
    only after PERSISTENCE_WEEKS (2) consecutive weeks.
  - Minimum hold: no regular drop before MIN_HOLD_DAYS (28) days.
  - Turnover cap: at most MAX_SWAPS (4) regular swaps per run.
  - Re-run guard: weeks_below_cutoff only advances if the row's last_reviewed
    is at least MIN_REVIEW_GAP_DAYS (5) days old, so test runs and retries
    can't fast-forward the persistence clock.
  - Rank bar (thirds of this week's candidates): an incumbent Micro left out
    is only dropped if it sits in the bottom third by combined_score AND the
    replacement is in the top third.
  - Low-conviction override: if Micro keeps an incumbent but tags it "low"
    and it is in the bottom third (or gone from candidates), it may be dropped.
  - Sector stress: a sector is "stressed" if the median stock in it fell
    >= 10% over 1 month or >= 6% over 1 week (from /screen's `sector_returns`,
    optional input), or if the caller lists it in `stressed_sectors`
    (e.g. Macro "avoid" or a future Crisis Watchdog). In a stressed sector,
    Micro omitting an incumbent (or tagging it low conviction) is enough to
    exit it: persistence, minimum hold and the swap cap are waived, and the
    sector gets no new entries this run. Exits speed up; entries don't. Names
    Micro still likes stay — hard price stops are Risk Guardrails' job.

Score mode (added 2026-10-09). If the body also carries "ranking" (select-basket's
ranking_json: every name Micro scored this run, with its blended score), the
rank-third rules are replaced by a score buffer band:
  - Weak drop: a scored incumbent below STAY_MIN (2.8) is replaced by the best
    challenger scoring >= ENTER_MIN (3.0) and >= its own score + WEAK_MARGIN (0.3).
  - Upgrade: a healthy incumbent is replaced only if a challenger beats it by
    UPGRADE_MARGIN (0.6) — wider than run-to-run LLM noise. Weakest first.
  - Entrants are picked by score (not screener rank) and must clear ENTER_MIN.
  - Kept incumbents take this run's score/conviction/thesis, so no stale scores.
  - Incumbents Micro did not score (not in candidates) follow persistence only.
  Minimum hold, swap cap, sector cap and sector stress still apply.
  Env: RECON_ENTER_MIN, RECON_STAY_MIN, RECON_WEAK_MARGIN, RECON_UPGRADE_MARGIN.

Risk, macro and data flags (added 2026-10-11). Optional body fields:
  - "scenario_moves": /stress-test's scenario_moves_json (per-stock % move in
    each scenario for the current basket + every scored candidate, and SPY's).
  - "risk_view": the Risk Analyst's JSON ({"risks": [{risk, level, direction}...]}).
  - "macro_view": the Macro Analyst's JSON ({"sector_view": [{sector, stance}...]}).
  Rules:
  - Risk limits (needs scenario_moves). This is the owner's fixed risk appetite,
    not a forecast: after the normal swaps, in every scenario the basket (equal
    weight) may lose at most 1.5x what SPY loses. "Elevated" from the Risk
    Analyst only gets logged. The limit tightens (1.2x) only when the Risk
    Analyst says "high" AND the market confirms it (stress test's `confirmed`,
    e.g. semis -10% in a month); headlines alone never tighten it. Scenarios
    where SPY itself barely moves (momentum reversal) use absolute floors
    (-5% / -5% / -3%). On a breach, the stock that loses most in that scenario
    is swapped for the best-scoring candidate (entry bar applies) that lowers the
    loss without breaching another limit — among the 5 most exposed names, the one
    with the LOWEST score whose single swap cures the breach goes first (keeps the
    strongest momentum names); if no single swap cures it, the most exposed name
    goes first. At most MAX_RISK_SWAPS (2) per run;
    like stress exits they ignore minimum hold and the swap cap.
    Timing (when to get out of a still-trending name) is the daily deep dive's
    job, not this weekly step: each basket row carries `risk_exposure` (the
    scenarios where the stock alone loses far more than SPY) for it.
    Decided 2026-10-11 after a case study: selling winners on "elevated" only
    pays if a burst is near-certain; a fixed limit + daily trend exit keeps the
    upside of a running trend and cuts the crash path.
  - Macro "avoid": new entries in that sector need MACRO_AVOID_BAR (0.3) more
    score. Nothing is sold because of macro (its sector calls have no tested edge).
  - Data flag (select's data_flag: most LLM runs said the code's metrics don't fit
    the stock): new entries need DATA_FLAG_BAR (0.3) more score; flagged holdings
    are listed in summary.review for a human look, not sold.

Extra optional body fields: "sector_returns" (array or JSON string of
{sector, median_ret_1m, median_ret_1w}) and "stressed_sectors" (array or
comma-separated string).
"""
import datetime
import json
import math
import os

from flask import Blueprint, jsonify, request

reconcile_bp = Blueprint("reconcile", __name__)

BASKET_SIZE = int(os.environ.get("RECON_BASKET_SIZE", 20))
MAX_PER_SECTOR = int(os.environ.get("RECON_MAX_PER_SECTOR", 5))
PERSISTENCE_WEEKS = int(os.environ.get("RECON_PERSISTENCE_WEEKS", 2))
MIN_HOLD_DAYS = int(os.environ.get("RECON_MIN_HOLD_DAYS", 28))
MAX_SWAPS = int(os.environ.get("RECON_MAX_SWAPS", 4))
MIN_REVIEW_GAP_DAYS = int(os.environ.get("RECON_MIN_REVIEW_GAP_DAYS", 5))
# A sector counts as "stressed" when the median stock in it (across the whole
# scored S&P 500 universe, from /screen's sector_returns) is down at least
# this much over 1 month or over 1 week. Absolute thresholds, deliberately simple.
SECTOR_CRASH_1M = float(os.environ.get("RECON_SECTOR_CRASH_1M", -0.10))
SECTOR_CRASH_1W = float(os.environ.get("RECON_SECTOR_CRASH_1W", -0.06))

# Score buffer band (used when select-basket's full `ranking` is passed in).
# Two different bars on purpose, so a name wobbling around one line doesn't
# flip in and out: a new name needs ENTER_MIN to come in, an incumbent is only
# "weak" (droppable) below STAY_MIN. A healthy incumbent is only replaced by a
# challenger that beats it by UPGRADE_MARGIN — wider than run-to-run noise.
ENTER_MIN = float(os.environ.get("RECON_ENTER_MIN", 3.0))
STAY_MIN = float(os.environ.get("RECON_STAY_MIN", 2.8))
WEAK_MARGIN = float(os.environ.get("RECON_WEAK_MARGIN", 0.3))
UPGRADE_MARGIN = float(os.environ.get("RECON_UPGRADE_MARGIN", 0.6))
# Cluster cap: at most this many names that are "the same bet" (same business,
# e.g. three oil refiners), as labelled by Micro's `cluster` field. Sectors are
# broad boxes; clusters catch concentration inside them. 0 disables.
MAX_PER_CLUSTER = int(os.environ.get("RECON_MAX_PER_CLUSTER", 2))

# Risk limits (scenario loss vs SPY) per Risk Analyst level: 0 = low/none, 1 = elevated, 2 = high
RISK_MULT = (float(os.environ.get("RECON_RISK_MULT_BASE", 1.5)),
             float(os.environ.get("RECON_RISK_MULT_ELEVATED", 1.5)),   # elevated = watch, no tightening
             float(os.environ.get("RECON_RISK_MULT_HIGH", 1.2)))       # only if market-confirmed
RISK_ABS_FLOOR = (-5.0, -5.0, -3.0)    # % loss floors for scenarios where SPY moves < 0.5%
MAX_RISK_SWAPS = int(os.environ.get("RECON_MAX_RISK_SWAPS", 2))
EXPOSURE_NOTE_MULT = 2.0               # risk_exposure lists scenarios where a stock loses > 2x SPY
MACRO_AVOID_BAR = float(os.environ.get("RECON_MACRO_AVOID_BAR", 0.3))
DATA_FLAG_BAR = float(os.environ.get("RECON_DATA_FLAG_BAR", 0.3))
LEVELS = {"none": 0, "low": 0, "moderate": 1, "medium": 1, "elevated": 1,
          "high": 2, "severe": 2, "acute": 2, "extreme": 2, "critical": 2}

UNRANKED = 10**6


# ---------- input helpers ----------

def _norm(k):
    return "".join(ch for ch in str(k).lower() if ch.isalnum())


def _get(row, *names, default=None):
    """Case/format-insensitive field lookup, so 'Added On', 'added_on' and
    'addedOn' all match."""
    lookup = {_norm(k): v for k, v in row.items()}
    for n in names:
        v = lookup.get(_norm(n))
        if v is not None and v != "":
            return v
    return default


def _as_list(v):
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
        for key in ("basket", "candidates", "rows", "items"):
            if key in v:
                return _as_list(v[key])
        return []
    return [r for r in v if isinstance(r, dict)]


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_date(v):
    """Accepts ISO strings or Google Sheets serial numbers (e.g. 46294)."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip().replace(".", "", 1).isdigit()):
        try:
            return datetime.date(1899, 12, 30) + datetime.timedelta(days=int(float(v)))
        except (ValueError, OverflowError):
            return None
    try:
        return datetime.date.fromisoformat(str(v).strip()[:10])
    except ValueError:
        return None


def _as_obj(v):
    """dict from a dict or a JSON string (code fences tolerated); {} if unusable."""
    if isinstance(v, dict):
        return v
    if not v or not isinstance(v, str):
        return {}
    t = v.strip()
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t.lower().startswith("json"):
            t = t[4:].strip()
    try:
        out = json.loads(t)
    except ValueError:
        a, b = t.find("{"), t.rfind("}")
        if a < 0 or b <= a:
            return {}
        try:
            out = json.loads(t[a:b + 1])
        except ValueError:
            return {}
    return out if isinstance(out, dict) else {}


def risk_levels(risk_view):
    """{scenario: level 0/1/2} from the Risk Analyst's output."""
    out = {}
    for r in (_as_obj(risk_view).get("risks") or []):
        if not isinstance(r, dict):
            continue
        name = str(r.get("risk", "")).lower()
        lvl = LEVELS.get(str(r.get("level", "")).strip().lower(), 0)
        d = str(r.get("direction", "")).lower()
        if "oil" in name or "energy" in name:
            scen = ["oil_spike"] if d == "up" else ["oil_crash"] if d == "down" else ["oil_spike", "oil_crash"]
        elif name in ("ai", "semis", "semiconductors") or "ai" in name.split():
            scen = ["ai_bust"]
        elif "rate" in name or "yield" in name:
            scen = [] if d == "down" else ["rate_shock"]
        elif "momentum" in name:
            scen = ["momentum_reversal"]
        elif "market" in name or "recession" in name or "equity" in name:
            scen = ["market_crash"]
        else:
            scen = []
        for x in scen:
            out[x] = max(out.get(x, 0), lvl)
    return out


def macro_avoid(macro_view):
    rows = _as_obj(macro_view).get("sector_view") or []
    return sorted({str(r.get("sector")) for r in rows
                   if isinstance(r, dict) and str(r.get("stance", "")).lower() == "avoid"})


def _sym(row):
    return str(_get(row, "symbol", default="") or "").strip().upper()


# ---------- core logic ----------

def reconcile(proposed, current, candidates, today=None, sector_returns=None, stressed_extra=None,
              ranking=None, scenario_moves=None, risk_view=None, macro_view=None):
    today = today or datetime.date.today()
    actions = []

    def log(symbol, action, reason, **extra):
        actions.append({"symbol": symbol, "action": action, "reason": reason, **extra})

    # --- rank this week's candidates by combined_score (fallback: given order)
    cand_rows = [(_sym(c), c) for c in candidates if _sym(c)]
    scores = [_to_float(_get(c, "combined_score")) for _, c in cand_rows]
    if cand_rows and all(s is not None for s in scores):
        order = sorted(range(len(cand_rows)), key=lambda i: -scores[i])
        cand_rows = [cand_rows[i] for i in order]
    rank = {s: i + 1 for i, (s, _) in enumerate(cand_rows)}
    cand_sector = {s: str(_get(c, "sector", default="Unknown")) for s, c in cand_rows}
    n = len(cand_rows)
    drop_rank_min = math.ceil(n * 2 / 3)   # rank above this = bottom third
    entry_rank_max = math.ceil(n / 3)      # rank at/below this = top third

    def rank_of(s):
        return rank.get(s, UNRANKED)

    # --- normalise Micro's proposal
    prop = {}
    for r in proposed:
        s = _sym(r)
        if not s:
            continue
        prop[s] = {
            "symbol": s,
            "sector": str(_get(r, "sector", default=cand_sector.get(s, "Unknown"))),
            "thesis_summary": _get(r, "thesis_summary", "reasoning", default=""),
            "target_price": _to_float(_get(r, "target_price")),
            "conviction": str(_get(r, "conviction", default="")).lower(),
            "score": _to_float(_get(r, "score")),
        }

    # --- select-basket's full ranking (every name Micro scored this run).
    # When present the reconcile runs in SCORE MODE: drops, entries and upgrades
    # are decided on the blended score with a buffer band instead of screener
    # rank thirds. Without it the older rank-based rules below apply unchanged.
    scored = {}
    for r in ranking or []:
        s = _sym(r)
        sc = _to_float(_get(r, "score"))
        if not s or sc is None:
            continue
        scored[s] = {
            "symbol": s,
            "sector": str(_get(r, "sector", default=cand_sector.get(s, "Unknown"))),
            "thesis_summary": _get(r, "thesis_summary", "reasoning", default=""),
            "target_price": _to_float(_get(r, "target_price")),
            "conviction": str(_get(r, "conviction", default="")).lower(),
            "score": sc,
            # from select-basket's overlay mode (Micro rebuild): LLM runs disagreed /
            # a majority reported a thesis-breaking event
            "uncertain": _get(r, "uncertain", default=False) is True,
            "red_flag": _get(r, "red_flag", default=False) is True,
            "cluster": str(_get(r, "cluster", default="") or "").strip().lower(),
            "data_flag": (_get(r, "data_flag", default=False) is True
                          or "llm_data_anomaly" in (_get(r, "flags", default=[]) or [])),
        }
    score_mode = bool(scored)
    avoid = set(macro_avoid(macro_view))
    levels = risk_levels(risk_view)
    mv = _as_obj(scenario_moves)
    moves = {str(k).upper(): v for k, v in (mv.get("symbols") or {}).items() if isinstance(v, dict)}
    spy_moves = {k: float(v) for k, v in (mv.get("spy") or {}).items()}
    confirmed = {k: bool(v) for k, v in (mv.get("confirmed") or {}).items()}
    raw_levels = dict(levels)
    # "high" without market confirmation counts as elevated (= watch only)
    levels = {k: (1 if v == 2 and not confirmed.get(k) else v) for k, v in levels.items()}

    def extra_bar(s, sector):
        """extra score a NEW entry needs: macro 'avoid' sector and/or LLM data flag"""
        x = MACRO_AVOID_BAR if sector in avoid else 0.0
        if s in scored and scored[s]["data_flag"]:
            x += DATA_FLAG_BAR
        return x

    def score_of(s):
        return scored[s]["score"] if s in scored else None

    # --- normalise current Watchlist
    cur = {}
    for r in current:
        s = _sym(r)
        if not s:
            continue
        cur[s] = {
            "symbol": s,
            "sector": str(_get(r, "sector", default=cand_sector.get(s, "Unknown"))),
            "thesis_summary": _get(r, "thesis_summary", "reasoning", default=""),
            "target_price": _to_float(_get(r, "target_price")),
            "conviction": str(_get(r, "conviction", default="")).lower(),
            "added_on": _parse_date(_get(r, "added_on", "date_added", "addedon")),
            "prev_weeks": int(_to_float(_get(r, "weeks_below_cutoff", default=0)) or 0),
            "last_reviewed": _parse_date(_get(r, "last_reviewed", "lastreviewed")),
            "score": _to_float(_get(r, "score")),
        }

    final = {}      # symbol -> output row (without 'status' yet decided)
    status = {}

    def mk_row(base, added_on, weeks, st):
        return {
            "symbol": base["symbol"],
            "added_on": added_on.isoformat() if added_on else today.isoformat(),
            "sector": base["sector"],
            "thesis_summary": base["thesis_summary"],
            "target_price": base["target_price"],
            "conviction": base["conviction"],
            "weeks_below_cutoff": weeks,
            "last_reviewed": today.isoformat(),
            "score": base.get("score"),
            "status": st,
        }

    # --- step A: carry every incumbent forward, refreshing from Micro when it still picks them
    info = {}
    for s, c in cur.items():
        in_cands = s in rank
        # The counter counts WEEKS, not runs: if this row was already reviewed
        # within the last MIN_REVIEW_GAP_DAYS (a test run, a manual re-run, a
        # retry after an error), don't advance it a second time.
        reviewed_recently = (
            c["last_reviewed"] is not None and (today - c["last_reviewed"]).days < MIN_REVIEW_GAP_DAYS
        )
        if in_cands:
            weeks = 0
        elif reviewed_recently:
            weeks = c["prev_weeks"]
        else:
            weeks = c["prev_weeks"] + 1
        age = (today - c["added_on"]).days if c["added_on"] else None
        in_prop = s in prop
        base = dict(c)
        src = prop.get(s) or (scored.get(s) if score_mode else None)
        if src is not None:
            # Refresh from this run (Micro's pick, or — in score mode — any name it
            # scored), so kept names never carry last week's score forward.
            p = dict(src)
            if s in scored:
                p["score"] = scored[s]["score"]
                p["conviction"] = scored[s]["conviction"] or p["conviction"]
            base["thesis_summary"] = p["thesis_summary"] or c["thesis_summary"]
            base["target_price"] = p["target_price"] if p["target_price"] is not None else c["target_price"]
            base["conviction"] = p["conviction"] or c["conviction"]
            if p.get("score") is not None:
                base["score"] = p["score"]
        info[s] = {"in_cands": in_cands, "weeks": weeks, "age": age, "in_prop": in_prop,
                   "conv": base["conviction"] if src is not None else c["conviction"]}
        final[s] = mk_row(base, c["added_on"], weeks, "kept" if in_prop else "kept_by_stability_rule")

    # --- step B: sector-stress detection (price-based, from /screen's sector_returns,
    # plus any sectors the caller flags explicitly — e.g. Macro "avoid" or a future Crisis Watchdog)
    stressed = set(stressed_extra or [])
    for sr in sector_returns or []:
        sector = str(_get(sr, "sector", default=""))
        r1m = _to_float(_get(sr, "median_ret_1m"))
        r1w = _to_float(_get(sr, "median_ret_1w"))
        if (r1m is not None and r1m <= SECTOR_CRASH_1M) or (r1w is not None and r1w <= SECTOR_CRASH_1W):
            stressed.add(sector)
            log("*", "sector_stress", f"{sector}: median stock 1m {r1m if r1m is None else round(r1m * 100, 1)}%, "
                f"1w {r1w if r1w is None else round(r1w * 100, 1)}% — exits fast-tracked, no new entries this run",
                sector=sector)
    for sector in stressed_extra or []:
        log("*", "sector_stress", f"{sector}: flagged by caller — exits fast-tracked, no new entries this run", sector=sector)

    # --- candidate pool for new entries: Micro's proposals first (by rank), then raw screener ranking
    def pool_rows():
        if score_mode:
            # Best score first; only names Micro actually scored this run.
            for s in sorted((s for s in scored if s not in cur), key=lambda s: (-scored[s]["score"], rank_of(s))):
                yield dict(scored[s]), s in prop
            return
        proposed_new = sorted((s for s in prop if s not in cur), key=rank_of)
        for s in proposed_new:
            yield dict(prop[s]), True
        for s, _ in cand_rows:
            if s not in cur and s not in prop:
                yield {"symbol": s, "sector": cand_sector[s], "thesis_summary":
                       "Added from screener ranking (not proposed by Micro) — no thesis yet",
                       "target_price": None, "conviction": "n/a"}, False

    def sector_counts():
        out = {}
        for r in final.values():
            out[r["sector"]] = out.get(r["sector"], 0) + 1
        return out

    def cluster_of(s):
        return scored[s]["cluster"] if s in scored else ""

    def cluster_counts():
        out = {}
        for x in final:
            c = cluster_of(x)
            if c:
                out[c] = out.get(c, 0) + 1
        return out

    def find_challenger(entry_bar, min_score=None, freed_sector=None, freed_cluster=None, risk_ok=None):
        counts = sector_counts()
        ccounts = cluster_counts()
        for base, from_micro in pool_rows():
            s = base["symbol"]
            if s in final:
                continue
            if base["sector"] in stressed:
                continue
            # freed_sector: the slot being vacated still sits in `final` when an
            # upgrade is evaluated, so don't count it against its own sector.
            used = counts.get(base["sector"], 0) - (1 if base["sector"] == freed_sector else 0)
            if used >= MAX_PER_SECTOR:
                continue
            c = cluster_of(s)
            if MAX_PER_CLUSTER and c and ccounts.get(c, 0) - (1 if c == freed_cluster else 0) >= MAX_PER_CLUSTER:
                continue   # would make one business bet too big
            if score_mode:
                sc = score_of(s)
                if s in scored and (scored[s]["red_flag"] or scored[s]["uncertain"]):
                    continue   # never add a name with a red flag or disagreeing LLM readings
                bar = max(ENTER_MIN if entry_bar else 0.0, min_score or 0.0)
                if entry_bar or min_score is not None:
                    bar += extra_bar(s, base["sector"])
                    if sc is None or sc < bar:
                        continue
            elif entry_bar and rank_of(s) > entry_rank_max:
                continue
            if risk_ok is not None and not risk_ok(s):
                continue
            return base, from_micro
        return None

    def describe(base, from_micro):
        s = base["symbol"]
        if score_mode:
            return (f"score {score_of(s):.2f} (entry bar {ENTER_MIN:.1f})" +
                    ("" if from_micro else ", outside Micro's top 20") + f", screener rank {rank.get(s)}/{n}")
        return ("Micro pick" if from_micro else "from screener ranking") + f", rank {rank.get(s)}/{n}"

    def add_entry(base, why):
        s = base["symbol"]
        final[s] = mk_row(base, today, 0, "added")
        log(s, "added", why, rank=rank.get(s), score=score_of(s))

    # --- step C0: cluster cap — if the basket holds more than MAX_PER_CLUSTER names
    # of the same business, the weakest ones beyond the cap become drop candidates.
    over_cluster = set()
    if score_mode and MAX_PER_CLUSTER:
        groups = {}
        for x in final:
            if x in cur and cluster_of(x):
                groups.setdefault(cluster_of(x), []).append(x)
        for c, xs in groups.items():
            if len(xs) > MAX_PER_CLUSTER:
                xs.sort(key=lambda x: -(score_of(x) or 0))
                over_cluster.update(xs[MAX_PER_CLUSTER:])

    # --- step C: regular (non-stress) drop candidates
    regular = []
    stress_exits = []
    for s in list(final):
        if s not in cur:
            continue
        i = info[s]
        kind = None
        if cur[s]["sector"] in stressed and (
            not i["in_prop"]
            or (i["conv"] == "low" and (not i["in_cands"] or rank_of(s) > drop_rank_min))
        ):
            # In a stressed sector Micro's omission (or a low-conviction tag) is enough:
            # persistence, minimum hold and the swap cap are all waived.
            stress_exits.append(s)
            continue
        if score_mode and s in scored:
            sc = scored[s]["score"]
            if scored[s]["red_flag"]:
                kind = "red_flag"
            elif s in over_cluster:
                kind = "cluster_cap"
            elif scored[s]["uncertain"]:
                log(s, "kept", f"score {sc:.2f} but the Micro runs disagree on it — no score-based action this week",
                    kind="uncertain")
                continue
            elif sc < STAY_MIN:
                kind = "weak_score"
            else:
                continue   # healthy incumbent; may still face an upgrade swap below
        elif not i["in_prop"]:
            if not i["in_cands"]:
                if i["weeks"] >= PERSISTENCE_WEEKS:
                    kind = "clean"
                else:
                    log(s, "kept", f"missing from candidates {i['weeks']} of {PERSISTENCE_WEEKS} weeks — persistence not met")
                    continue
            elif score_mode:
                continue   # in candidates but unscored (Micro skipped it): no evidence to drop
            elif rank_of(s) > drop_rank_min:
                kind = "rank_bar"
            else:
                log(s, "kept", f"Micro left it out but it is still rank {rank_of(s)}/{n} (upper two-thirds) — omission alone is not enough")
                continue
        else:
            if i["conv"] == "low" and (not i["in_cands"] or rank_of(s) > drop_rank_min):
                kind = "low_conviction"
            else:
                continue
        if i["age"] is not None and i["age"] < MIN_HOLD_DAYS:
            log(s, "kept", f"eligible to drop ({kind}) but held only {i['age']} of {MIN_HOLD_DAYS} minimum days")
            continue
        regular.append((s, kind))

    # Stress exits first: not counted against the swap cap. A replacement is added if one
    # exists outside the stressed sectors; if not, the basket shrinks and the refill step
    # below tries again — a temporary shortfall is acceptable in a crisis.
    for s in stress_exits:
        final.pop(s)
        log(s, "dropped", f"sector stress in {cur[s]['sector']}: Micro omitted it or tagged it low conviction — "
            "persistence, minimum hold and swap cap waived", kind="sector_stress")
        ch = find_challenger(entry_bar=False)
        if ch is not None:
            base, from_micro = ch
            add_entry(base, f"replaces {s}; " + describe(base, from_micro))

    if score_mode:
        # weakest score first, then clean (persistence) drops
        order = {"red_flag": 0, "cluster_cap": 1, "weak_score": 2}
        regular.sort(key=lambda t: (order.get(t[1], 2), score_of(t[0]) or 0, -rank_of(t[0])))
    else:
        regular.sort(key=lambda t: (0 if t[1] == "clean" else 1, -rank_of(t[0])))

    swaps = 0
    for s, kind in regular:
        if swaps >= MAX_SWAPS:
            log(s, "kept", f"eligible to drop ({kind}) but turnover cap of {MAX_SWAPS} swaps reached this run")
            continue
        row = final.pop(s)
        if score_mode:
            inc = score_of(s)
            need = None if kind in ("red_flag", "cluster_cap") or inc is None else inc + WEAK_MARGIN
            # (s is already out of `final` here, so its sector/cluster slot is free)
            ch = find_challenger(entry_bar=True, min_score=need)
        else:
            ch = find_challenger(entry_bar=kind in ("rank_bar", "low_conviction"))
        if ch is None:
            final[s] = row
            log(s, "kept", f"eligible to drop ({kind}) but no replacement cleared the entry bar / sector cap", kind=kind)
            continue
        base, from_micro = ch
        swaps += 1
        log(s, "dropped", {
            "clean": f"missing from candidates {info[s]['weeks']} consecutive weeks",
            "rank_bar": f"Micro omitted it and it sits in the bottom third (rank {rank_of(s)}/{n})",
            "low_conviction": f"Micro conviction low and rank {rank_of(s) if s in rank else 'n/a'}/{n} deteriorated",
            "weak_score": f"score {score_of(s) if score_of(s) is None else round(score_of(s), 2)} below stay bar {STAY_MIN:.1f}",
            "red_flag": "a majority of Micro runs reported a thesis-breaking event (see its thesis/evidence)",
            "cluster_cap": f"more than {MAX_PER_CLUSTER} names in cluster '{cluster_of(s)}' — weakest one makes room",
        }[kind], kind=kind, score=score_of(s))
        add_entry(base, f"replaces {s}; " + describe(base, from_micro))

    # Upgrade swaps (score mode only): a healthy incumbent is replaced only when a
    # challenger beats it by UPGRADE_MARGIN, weakest incumbent first, within the swap cap.
    if score_mode:
        while swaps < MAX_SWAPS:
            pool = [x for x in final if x in cur and x in scored and not scored[x]["uncertain"]
                    and (info[x]["age"] is None or info[x]["age"] >= MIN_HOLD_DAYS)]
            if not pool:
                break
            done = False
            for s in sorted(pool, key=lambda x: scored[x]["score"]):
                inc = scored[s]["score"]
                ch = find_challenger(entry_bar=True, min_score=inc + UPGRADE_MARGIN,
                                     freed_sector=final[s]["sector"], freed_cluster=cluster_of(s))
                if ch is None:
                    continue
                base, from_micro = ch
                final.pop(s)
                swaps += 1
                log(s, "dropped", f"upgrade: score {inc:.2f} vs challenger {base['symbol']} "
                    f"{score_of(base['symbol']):.2f} (gap >= {UPGRADE_MARGIN:.1f})", kind="upgrade", score=inc)
                add_entry(base, f"replaces {s}; " + describe(base, from_micro))
                done = True
                break
            if not done:
                break
        if swaps >= MAX_SWAPS:
            log("*", "note", f"turnover cap of {MAX_SWAPS} swaps reached — further upgrades deferred")

    # --- step D: refill to BASKET_SIZE (cold start, stress exits, or earlier shortfalls)
    while len(final) < BASKET_SIZE:
        ch = find_challenger(entry_bar=False)
        if ch is None:
            break
        base, from_micro = ch
        add_entry(base, describe(base, from_micro) + " (refill)")
    shortfall = max(BASKET_SIZE - len(final), 0)

    # --- step E: risk limits (needs /stress-test's scenario moves). Runs on the
    # finished basket; swaps here ignore minimum hold and the regular swap cap.
    def basket_move(scn, syms):
        vals = [moves[x][scn] for x in syms if x in moves and scn in moves[x]]
        return sum(vals) / len(vals) if vals else None

    def limit_for(scn):
        lvl = levels.get(scn, 0)
        spy = spy_moves.get(scn, 0.0)
        return spy * RISK_MULT[lvl] if spy <= -0.5 else RISK_ABS_FLOOR[lvl]

    def breaches(syms):
        out = []
        for scn in spy_moves:
            bm = basket_move(scn, syms)
            if bm is not None and bm < limit_for(scn):
                out.append((scn, bm, limit_for(scn)))
        return out

    def risk_table(syms):
        return {scn: {"basket_pct": None if basket_move(scn, syms) is None else round(basket_move(scn, syms), 1),
                      "spy_pct": spy_moves[scn], "limit_pct": round(limit_for(scn), 1),
                      "level": ("low", "elevated", "high")[levels.get(scn, 0)]} for scn in spy_moves}

    risk_swaps = 0
    risk_before = risk_table(list(final)) if moves and spy_moves else None
    if moves and spy_moves and score_mode:
        while risk_swaps < MAX_RISK_SWAPS:
            br = breaches(list(final))
            if not br:
                break
            scn, bm, lim = min(br, key=lambda t: t[1] - t[2])     # deepest breach first
            already = {b[0] for b in br}
            done = False
            exposed = sorted((x for x in final if x in moves and scn in moves[x]), key=lambda x: moves[x][scn])[:5]
            # Prefer the WEAKEST of the most exposed names whose swap cures the breach on its own
            # (keeps strong momentum names, e.g. not SNDK when MRVL would do); if no single swap
            # cures it, fall back to the most exposed name first.
            plans = []
            for out in exposed:
                row = final.pop(out)

                def ok(sym, scn=scn, bm=bm, already=already):
                    if sym not in moves:
                        return False
                    test = list(final) + [sym]
                    return basket_move(scn, test) > bm and all(b[0] in already for b in breaches(test))

                ch = find_challenger(entry_bar=True, risk_ok=ok)
                final[out] = row
                if ch is None:
                    continue
                after = basket_move(scn, [x for x in final if x != out] + [ch[0]["symbol"]])
                plans.append((after >= lim, out, ch))
            curing = sorted((p for p in plans if p[0]), key=lambda p: score_of(p[1]) if score_of(p[1]) is not None else 0)
            pick = curing[0] if curing else (plans[0] if plans else None)
            if pick is not None:
                _, out, (base, from_micro) = pick
                final.pop(out)
                risk_swaps += 1
                log(out, "dropped", f"risk limit: {scn} basket {bm:.1f}% vs limit {lim:.1f}% "
                    f"(SPY {spy_moves[scn]:.1f}%, risk level {('low', 'elevated', 'high')[levels.get(scn, 0)]}); "
                    f"{out} alone {moves[out][scn]:.1f}%" + (" — weakest exposed name that cures the breach" if curing else ""),
                    kind="risk_limit", score=score_of(out))
                add_entry(base, f"replaces {out}; " + describe(base, from_micro) +
                          f"; {scn} {moves[base['symbol']][scn]:.1f}%")
                done = True
            if not done:
                log("*", "note", f"risk limit {scn} breached ({bm:.1f}% vs {lim:.1f}%) but no candidate lowers it "
                    "without breaching another limit", kind="risk_limit")
                break

    # --- trim if somehow oversize (e.g. current sheet had extra rows): drop weakest rank, not a swap
    while len(final) > BASKET_SIZE:
        worst = max(final, key=rank_of)
        final.pop(worst)
        log(worst, "dropped", f"basket above {BASKET_SIZE} names — trimmed weakest rank", kind="trim")

    for x, row in final.items():
        notes = []
        for scn, spy in spy_moves.items():
            m = (moves.get(x) or {}).get(scn)
            if m is None:
                continue
            if (spy <= -0.5 and m < spy * EXPOSURE_NOTE_MULT) or (spy > -0.5 and m <= -10):
                notes.append(f"{scn} {m:.0f}% (SPY {spy:.0f}%)")
        row["risk_exposure"] = "; ".join(notes)
    basket = sorted(final.values(), key=lambda r: (r["sector"], rank_of(r["symbol"])))
    summary = {
        "basket_size": len(basket),
        "shortfall": shortfall,
        "regular_swaps": swaps,
        "stressed_sectors": sorted(stressed),
        "candidates": n,
        "drop_rank_above": drop_rank_min,
        "entry_rank_at_most": entry_rank_max,
        "sector_counts": sector_counts(),
        "mode": "score" if score_mode else "rank",
    }
    summary["macro_avoid"] = sorted(avoid)
    summary["review"] = sorted(x for x in final if x in scored and scored[x]["data_flag"])
    if risk_before is not None:
        summary["risk_swaps"] = risk_swaps
        summary["risk_levels"] = {k: ("low", "elevated", "high")[v] +
                                  (" (not market-confirmed: limit not tightened)" if v == 2 and levels.get(k) != 2 else "")
                                  for k, v in raw_levels.items()}
        summary["market_confirmed"] = sorted(k for k, v in confirmed.items() if v)
        summary["risk_before"] = risk_before
        summary["risk_after"] = risk_table(list(final))
        summary["risk_breaches_left"] = [b[0] for b in breaches(list(final))]
    if score_mode:
        summary.update({"max_per_cluster": MAX_PER_CLUSTER,
                        "cluster_counts": {c: n for c, n in cluster_counts().items() if n > 1},
                        "enter_min": ENTER_MIN, "stay_min": STAY_MIN,
                        "weak_margin": WEAK_MARGIN, "upgrade_margin": UPGRADE_MARGIN})
    return {
        "as_of": today.isoformat(),
        "basket": basket,
        "basket_symbols": ",".join(r["symbol"] for r in basket),   # for the Runs log sheet
        "actions": actions,
        "actions_json": json.dumps(actions),
        "summary": summary,
        "summary_json": json.dumps(summary),
    }


@reconcile_bp.route("/reconcile-basket", methods=["POST"])
def reconcile_basket():
    body = request.get_json(force=True, silent=True) or {}
    try:
        proposed = _as_list(body.get("proposed"))
        current = _as_list(body.get("current"))
        candidates = _as_list(body.get("candidates"))
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"could not parse input: {e}"}), 400

    if not proposed:
        return jsonify({"error": "proposed basket is empty — refusing to reconcile (would wipe the Watchlist)"}), 400
    if not candidates:
        return jsonify({"error": "candidates list is empty — refusing to reconcile"}), 400

    try:
        sector_returns = _as_list(body.get("sector_returns"))
        ranking = _as_list(body.get("ranking"))
        stressed_extra = body.get("stressed_sectors") or []
        if isinstance(stressed_extra, str):
            stressed_extra = [s.strip() for s in stressed_extra.split(",") if s.strip()]
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"could not parse input: {e}"}), 400

    today = _parse_date(body.get("today")) or datetime.date.today()
    return jsonify(reconcile(proposed, current, candidates, today, sector_returns, stressed_extra, ranking,
                             scenario_moves=body.get("scenario_moves"), risk_view=body.get("risk_view"),
                             macro_view=body.get("macro_view")))
