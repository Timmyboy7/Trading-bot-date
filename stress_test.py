"""
Stress test — basket exposures and downside scenarios (added 2026-10-11).

Design rule (project doc "Weekly pipeline & LLM roles"): facts are code. This
endpoint MEASURES the basket's downside; it never changes the basket. Version 1
only logs, so we can sanity-check the numbers for a few weeks before the planned
Crisis/Risk alarm is allowed to act on them.

What it answers, every week:
  1. Exposures: how strongly does the basket move with
       - the market        (SPY)
       - oil               (USO)
       - long-term rates   (TLT; a NEGATIVE TLT move = rates UP)
       - momentum          (MTUM minus SPY = "recent winners vs the market")
       - the AI trade      (SMH minus SPY = semiconductors vs the market;
                            own market+AI model, see AI_SCENARIO)
     measured per stock by regression on ~1 year of daily returns.
  2. Scenarios: estimated basket loss under fixed shocks (market crash, oil
     crash, oil spike, rate shock, momentum reversal, AI bust), compared with SPY, plus
     the names that drive each loss.
  3. History: what this exact basket would actually have done over the last
     year: volatility, max drawdown, worst month, 95% one-month VaR, vs SPY.

Pipeline position (weekly Discovery scenario), since 2026-10-11:
    ... -> select (Render 5) -> THIS -> Risk Analyst -> reconcile (Render 4) -> Watchlist
The basket here is the CURRENT Watchlist (what we hold going into the week);
`universe` adds every name select scored, so reconcile knows how each possible
replacement would behave in every scenario and can enforce risk limits
(scenario_moves_json). Before 2026-10-11 this ran after reconcile and only logged.

Endpoint:
    POST /stress-test
    Body:
      {
        "basket":  "AAA,BBB,..."   // Render 4 basket_symbols (csv or JSON list)
        "weights": {"AAA": 0.05}   // optional; default equal weight
        "universe": "CCC,DDD,..."  // optional: more names (csv, JSON list, or select's ranking_json)
                                   // that only get per-stock scenario moves, for reconcile.
                                   // If basket is empty (first run), the first 20 of universe are used.
      }

Response:
    {
      "as_of", "weights": "equal"|"given", "days": N,
      "exposures": {"market": b, "oil": b, "rates_tlt": b, "momentum": b},
      "scenarios": [{"name", "description", "basket_pct", "spy_pct", "vs_spy_pct", "worst": [...]}],
      "history": {"basket": {...}, "spy": {...}},
      "per_symbol": [...],
      "warnings": [...],
      "market_context": {...},  // recent moves of SPY/USO/TLT/MTUM/SMH (1w/1m/3m, from high, vol)
      "headlines": {...},       // last 7 days per theme: oil, ai, rates_market
      "stress_json": "...",     // compact string for the Runs log (one cell)
      "risk_input_json": "...", // everything the Risk Analyst LLM needs, one mapping
      "summary_json": "...",
      "scenario_moves_json": "...", // {"spy": {scenario: pct}, "symbols": {SYM: {scenario: pct}}}
                                    // for basket + universe -> reconcile's risk limits
      "errors": [...]
    }

Limits worth knowing: the scenario numbers are LINEAR estimates from one year of
history. They show direction and relative size (which names, which risk), not
an exact forecast. Real crashes are usually worse than linear models say because
correlations jump toward 1, so the historical numbers are reported next to them.
"""
import datetime
import json
import math
import os
import statistics

import requests
from flask import Blueprint, jsonify, request

from screener import DATA_BASE, DATA_FEED, HEADERS

stress_bp = Blueprint("stress_test", __name__)

LOOKBACK_DAYS = int(os.environ.get("STRESS_LOOKBACK_DAYS", 380))   # calendar days, ~1 trading year
MIN_DAYS = 120                                                     # fewer aligned days -> name skipped
FACTOR_ETFS = {"SPY": "market", "USO": "oil", "TLT": "rates_tlt", "MTUM": "momentum", "SMH": "ai"}
FACTORS = ["market", "oil", "rates_tlt", "momentum"]

# Fixed scenario shocks, as total moves of the factor ETFs over the episode.
# Deliberately written down so they can be reviewed and tuned. Rough anchors:
# TLT has ~16y duration, so -15% ~ +100bp on long yields; momentum = MTUM - SPY.
SCENARIOS = [
    ("market_crash", "S&P -20%, oil -15%, bonds rally +5%",
     {"market": -0.20, "oil": -0.15, "rates_tlt": 0.05, "momentum": 0.0}),
    ("oil_crash", "Oil -30%, S&P -3%",
     {"market": -0.03, "oil": -0.30, "rates_tlt": 0.02, "momentum": 0.0}),
    ("oil_spike", "Oil +30% (supply shock / war), S&P -5%",
     {"market": -0.05, "oil": 0.30, "rates_tlt": -0.03, "momentum": 0.0}),
    ("rate_shock", "Long rates about +1% (TLT -15%), S&P -5%",
     {"market": -0.05, "oil": 0.0, "rates_tlt": -0.15, "momentum": 0.0}),
    ("momentum_reversal", "Recent winners fall 10% vs the market",
     {"market": 0.0, "oil": 0.0, "rates_tlt": 0.0, "momentum": -0.10}),
]

# AI exposure gets its OWN small model (market + AI), because AI and momentum
# overlap heavily (today's winners ARE the AI names): in one regression the
# split between them would be noise. AI factor = SMH (semiconductors) minus SPY.
# Anchors: 2022 SMH about -45% vs SPY -25%; Jul-Aug 2024 SMH about -25% vs SPY -8%.
AI_SCENARIO = ("ai_bust", "AI trade unwinds: semis about -37% (25 points worse than the market), S&P -12%",
               {"market": -0.12, "ai": -0.25})

# Headlines per risk theme for the Risk Analyst LLM (fetched by code, read by the LLM).
# Alpaca news is tagged by ticker, so each theme uses a few bellwether tickers.
NEWS_THEMES = {
    "oil": "USO,XOM,CVX,COP,OXY",
    "ai": "NVDA,SMH,AVGO,MSFT,AMD",
    "rates_market": "SPY,TLT,QQQ,JPM",
}
NEWS_DAYS = int(os.environ.get("STRESS_NEWS_DAYS", 7))
NEWS_PER_THEME = int(os.environ.get("STRESS_NEWS_PER_THEME", 12))

# Information-only warnings (v1 never acts on them).
WARN_BETA = 1.25          # basket market beta above this
WARN_VS_SPY = 0.05        # scenario loss worse than SPY by more than 5 points
WARN_TOP3_SHARE = 0.5     # top 3 names cause more than half of a scenario loss


# --------------------------------------------------------------------------- input

def _load(v):
    if v is None or v == "":
        return None
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("[") or s.startswith("{"):
            return json.loads(s)
        return [x.strip() for x in s.split(",") if x.strip()]
    return v


def _symbols(v):
    v = _load(v) or []
    out = []
    for x in v:
        s = x.get("symbol") if isinstance(x, dict) else x
        s = str(s or "").strip().upper()
        if s and s not in out:
            out.append(s)
    return out


# --------------------------------------------------------------------------- data

def fetch_dated_closes(symbols):
    """{symbol: {date: close}} for ~1 year, dividend+split adjusted (total return)."""
    end = datetime.datetime.utcnow().date()
    start = end - datetime.timedelta(days=LOOKBACK_DAYS)
    out, errors = {}, []
    page_token = None
    for _ in range(20):
        params = {
            "symbols": ",".join(symbols), "timeframe": "1Day",
            "start": start.isoformat(), "end": end.isoformat(),
            "adjustment": "all", "feed": DATA_FEED, "limit": 10000,
        }
        if page_token:
            params["page_token"] = page_token
        try:
            r = requests.get(f"{DATA_BASE}/v2/stocks/bars", headers=HEADERS, params=params, timeout=25)
        except requests.RequestException as e:
            errors.append(f"bars request failed: {e}")
            break
        if r.status_code != 200:
            errors.append(f"bars HTTP {r.status_code}: {r.text[:200]}")
            break
        data = r.json()
        for sym, bars in (data.get("bars") or {}).items():
            d = out.setdefault(sym, {})
            for b in bars:
                d[str(b["t"])[:10]] = b["c"]
        page_token = data.get("next_page_token")
        if not page_token:
            break
    return out, errors


def _returns(closes_by_date, dates):
    """Daily simple returns on the given (sorted, common) dates."""
    px = [closes_by_date[d] for d in dates]
    return [px[i] / px[i - 1] - 1 for i in range(1, len(px))]


# --------------------------------------------------------------------------- maths

def _solve(a, b):
    """Gaussian elimination with partial pivoting; returns None if singular."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            return None
        m[c], m[p] = m[p], m[c]
        for r in range(c + 1, n):
            f = m[r][c] / m[c][c]
            for k in range(c, n + 1):
                m[r][k] -= f * m[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][k] * x[k] for k in range(r + 1, n))) / m[r][r]
    return x


def ols(y, cols):
    """Regress y on [1] + cols. Returns (betas without intercept, r2) or (None, None)."""
    n = len(y)
    X = [[1.0] + [c[i] for c in cols] for i in range(n)]
    k = len(X[0])
    xtx = [[sum(X[i][a] * X[i][b] for i in range(n)) for b in range(k)] for a in range(k)]
    xty = [sum(X[i][a] * y[i] for i in range(n)) for a in range(k)]
    beta = _solve(xtx, xty)
    if beta is None:
        return None, None
    my = sum(y) / n
    ss_tot = sum((v - my) ** 2 for v in y)
    ss_res = sum((y[i] - sum(beta[j] * X[i][j] for j in range(k))) ** 2 for i in range(n))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return beta[1:], r2


def _history_stats(rets):
    """Volatility, max drawdown, worst 21-day return and 95% 21-day VaR from daily returns."""
    if len(rets) < 30:
        return {}
    vol = statistics.pstdev(rets) * math.sqrt(252)
    level, peak, mdd = 1.0, 1.0, 0.0
    levels = [1.0]
    for r in rets:
        level *= 1 + r
        levels.append(level)
        peak = max(peak, level)
        mdd = min(mdd, level / peak - 1)
    m21 = sorted(levels[i + 21] / levels[i] - 1 for i in range(len(levels) - 21))
    var95 = m21[int(0.05 * len(m21))] if m21 else None
    return {
        "vol_annual_pct": round(vol * 100, 1),
        "max_drawdown_pct": round(mdd * 100, 1),
        "worst_month_pct": round(m21[0] * 100, 1) if m21 else None,
        "var95_month_pct": round(var95 * 100, 1) if var95 is not None else None,
        "return_1y_pct": round((levels[-1] - 1) * 100, 1),
    }


def _cov(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (n - 1)


def _corr(a, b):
    va, vb = _cov(a, a), _cov(b, b)
    return _cov(a, b) / math.sqrt(va * vb) if va > 0 and vb > 0 else None


def _avg_pairwise_corr(series):
    syms = list(series)
    vals = []
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            a, b = series[syms[i]], series[syms[j]]
            c = _corr(a, b)
            if c is not None:
                vals.append(c)
    return round(sum(vals) / len(vals), 2) if vals else None


def fetch_theme_news():
    """{theme: [{date, headline}]} for the last NEWS_DAYS days; best effort, never raises."""
    start = (datetime.datetime.utcnow() - datetime.timedelta(days=NEWS_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out, errors = {}, []
    for theme, syms in NEWS_THEMES.items():
        try:
            r = requests.get(f"{DATA_BASE}/v1beta1/news", headers=HEADERS, timeout=10,
                             params={"symbols": syms, "start": start, "limit": 50, "sort": "desc"})
            if r.status_code != 200:
                errors.append(f"news {theme}: HTTP {r.status_code}")
                continue
            seen, items = set(), []
            for a in r.json().get("news", []):
                head = str(a.get("headline") or "").strip()
                key = head.lower()[:80]
                if head and key not in seen:
                    seen.add(key)
                    items.append({"date": str(a.get("created_at") or "")[:10], "headline": head[:160]})
                if len(items) >= NEWS_PER_THEME:
                    break
            out[theme] = items
        except requests.RequestException as e:
            errors.append(f"news {theme}: {e}")
    return out, errors


def market_context(closes):
    """Recent behaviour of each factor ETF: the hard facts the Risk Analyst must cite."""
    ctx = {}
    for etf, label in FACTOR_ETFS.items():
        series = closes.get(etf) or {}
        dates = sorted(series)
        if len(dates) < 70:
            continue
        px = [series[d] for d in dates]
        rets = [px[i] / px[i - 1] - 1 for i in range(1, len(px))]
        last = px[-1]

        def ago(n):
            return round((last / px[-1 - n] - 1) * 100, 1) if len(px) > n else None

        vol_1m = statistics.pstdev(rets[-21:]) * math.sqrt(252)
        vol_1y = statistics.pstdev(rets[-252:]) * math.sqrt(252)
        ctx[label] = {
            "etf": etf, "as_of": dates[-1],
            "ret_1w_pct": ago(5), "ret_1m_pct": ago(21), "ret_3m_pct": ago(63),
            "from_1y_high_pct": round((last / max(px[-252:]) - 1) * 100, 1),
            "vol_1m_pct": round(vol_1m * 100, 1), "vol_1y_pct": round(vol_1y * 100, 1),
        }
    return ctx


# --------------------------------------------------------------------------- core

def scenario_moves(closes, symbols, factor_dates):
    """Per-stock estimated move (in %) in every scenario, each stock on its OWN
    calendar (so one young listing can't shorten everyone's history)."""
    spy = {n: round(sh["market"] * 100, 2) for n, _, sh in SCENARIOS}
    spy[AI_SCENARIO[0]] = round(AI_SCENARIO[2]["market"] * 100, 2)
    out, skipped = {}, []
    for s in symbols:
        dates = sorted(factor_dates & set(closes.get(s, {})))
        if len(dates) < MIN_DAYS:
            skipped.append(s)
            continue
        r = {x: _returns(closes[x], dates) for x in [s] + list(FACTOR_ETFS)}
        fac = {"market": r["SPY"], "oil": r["USO"], "rates_tlt": r["TLT"],
               "momentum": [m - q for m, q in zip(r["MTUM"], r["SPY"])]}
        b, _ = ols(r[s], [fac[f] for f in FACTORS])
        if b is None:
            skipped.append(s)
            continue
        by = dict(zip(FACTORS, b))
        ab, _ = ols(r[s], [fac["market"], [a - q for a, q in zip(r["SMH"], r["SPY"])]])
        mv = {n: round(sum(by[f] * sh[f] for f in FACTORS) * 100, 2) for n, _, sh in SCENARIOS}
        n, _, sh = AI_SCENARIO
        mv[n] = round(((ab[0] * sh["market"] + ab[1] * sh["ai"]) if ab else 0.0) * 100, 2)
        out[s] = mv
    return {"spy": spy, "symbols": out, "skipped": skipped}


def compute(basket, weights=None, closes=None, news=None, universe=None):
    errors = []
    universe = [u for u in (universe or []) if u not in basket]
    if closes is None:
        closes, errors = fetch_dated_closes(basket + universe + list(FACTOR_ETFS))
    if news is None:
        news, news_errors = fetch_theme_news()
        errors += news_errors

    missing_factors = [e for e in FACTOR_ETFS if len(closes.get(e, {})) < MIN_DAYS]
    if missing_factors:
        return {"error": f"factor data missing for {missing_factors}", "errors": errors}

    factor_dates = set.intersection(*(set(closes[e]) for e in FACTOR_ETFS))
    usable, skipped = [], []
    for s in basket:
        if len(set(closes.get(s, {})) & factor_dates) >= MIN_DAYS:
            usable.append(s)
        else:
            skipped.append(s)
    if skipped:
        errors.append(f"not enough price history, left out: {','.join(skipped)}")
    if not usable:
        return {"error": "no basket symbol has enough price history", "errors": errors}

    # one common calendar for everything -> returns line up day by day
    dates = sorted(factor_dates.intersection(*(set(closes[s]) for s in usable)))
    r = {s: _returns(closes[s], dates) for s in usable + list(FACTOR_ETFS)}
    fac = {
        "market": r["SPY"],
        "oil": r["USO"],
        "rates_tlt": r["TLT"],
        "momentum": [m - s for m, s in zip(r["MTUM"], r["SPY"])],
    }
    ai_fac = [a - s for a, s in zip(r["SMH"], r["SPY"])]
    cols = [fac[f] for f in FACTORS]

    # weights: given (renormalised over usable names) or equal
    if weights:
        w = {s: max(float(weights.get(s, 0) or 0), 0.0) for s in usable}
        tot = sum(w.values()) or 1.0
        w = {s: v / tot for s, v in w.items()}
        wmode = "given"
    else:
        w = {s: 1.0 / len(usable) for s in usable}
        wmode = "equal"

    per = []
    for s in usable:
        b, r2 = ols(r[s], cols)
        if b is None:
            errors.append(f"{s}: regression failed")
            b, r2 = [0.0] * len(FACTORS), 0.0
        ab, _ = ols(r[s], [fac["market"], ai_fac])
        ai_beta = round(ab[1], 2) if ab else 0.0
        ai_mkt = round(ab[0], 2) if ab else 0.0
        vs = _cov(r["SPY"], r["SPY"])
        mbeta = _cov(r[s], r["SPY"]) / vs if vs > 0 else None
        per.append({
            "symbol": s, "weight": round(w[s], 4),
            "beta_spy": round(mbeta, 2) if mbeta is not None else None,   # simple one-factor beta
            **{f: round(v, 2) for f, v in zip(FACTORS, b)},                # multi-factor betas
            "ai": ai_beta, "ai_model_market": ai_mkt,
            "r2": round(r2, 2),
            "vol_annual_pct": round(statistics.pstdev(r[s]) * math.sqrt(252) * 100, 1),
        })
    by = {p["symbol"]: p for p in per}

    exposures = {f: round(sum(w[s] * by[s][f] for s in usable), 2) for f in FACTORS}
    exposures["ai"] = round(sum(w[s] * by[s]["ai"] for s in usable), 2)
    exposures["beta_spy_simple"] = round(sum(w[s] * (by[s]["beta_spy"] or 0) for s in usable), 2)

    scenarios = []
    runs = [(n, d, sh, lambda s, sh=sh: sum(by[s][f] * sh[f] for f in FACTORS)) for n, d, sh in SCENARIOS]
    n, d, sh = AI_SCENARIO
    runs.append((n, d, sh, lambda s, sh=sh: by[s]["ai_model_market"] * sh["market"] + by[s]["ai"] * sh["ai"]))
    for name, desc, shock, move in runs:
        contrib = {s: w[s] * move(s) for s in usable}
        basket_ret = sum(contrib.values())
        spy_ret = shock["market"]   # SPY moves exactly its own shock
        worst = sorted(contrib.items(), key=lambda kv: kv[1])[:3]
        loss_total = sum(v for v in contrib.values() if v < 0)
        top3_share = (sum(v for _, v in worst if v < 0) / loss_total) if loss_total < 0 else 0.0
        scenarios.append({
            "name": name, "description": desc,
            "basket_pct": round(basket_ret * 100, 1),
            "spy_pct": round(spy_ret * 100, 1),
            "vs_spy_pct": round((basket_ret - spy_ret) * 100, 1),
            "worst": [{"symbol": s, "contribution_pct": round(v * 100, 2)} for s, v in worst],
            "top3_share_of_loss": round(top3_share, 2),
        })

    basket_daily = [sum(w[s] * r[s][i] for s in usable) for i in range(len(dates) - 1)]
    history = {"basket": _history_stats(basket_daily), "spy": _history_stats(r["SPY"])}
    history["avg_pairwise_correlation"] = _avg_pairwise_corr({s: r[s] for s in usable})

    warnings = []
    if exposures["beta_spy_simple"] > WARN_BETA:
        warnings.append(f"market beta {exposures['beta_spy_simple']} above {WARN_BETA}")
    for sc in scenarios:
        if sc["vs_spy_pct"] < -WARN_VS_SPY * 100:
            warnings.append(f"{sc['name']}: basket {sc['basket_pct']}% vs SPY {sc['spy_pct']}%")
        if sc["basket_pct"] < 0 and sc["top3_share_of_loss"] > WARN_TOP3_SHARE:
            names = ",".join(x["symbol"] for x in sc["worst"])
            warnings.append(f"{sc['name']}: {names} cause {int(sc['top3_share_of_loss']*100)}% of the loss")
    bh, sh = history["basket"], history["spy"]
    if bh and sh and bh.get("max_drawdown_pct") is not None and bh["max_drawdown_pct"] < sh["max_drawdown_pct"] - 5:
        warnings.append(f"1y max drawdown {bh['max_drawdown_pct']}% vs SPY {sh['max_drawdown_pct']}%")

    ctx = market_context(closes)

    def top(f, n=4, reverse=True):
        # only names with a meaningful sensitivity in that direction (|beta| >= 0.1)
        keep = [p for p in per if (p[f] >= 0.1 if reverse else p[f] <= -0.1)]
        ranked = sorted(keep, key=lambda p: p[f] * w[p["symbol"]], reverse=reverse)
        return [f"{p['symbol']} {p[f]:+.2f}" for p in ranked[:n]]

    # compact, self-contained pack for the Risk Analyst LLM (one Make mapping)
    risk_input = {
        "as_of": datetime.date.today().isoformat(),
        "market_context": ctx,
        "basket_exposures": exposures,
        "scenarios": [{"name": sc["name"], "description": sc["description"],
                       "basket_pct": sc["basket_pct"], "spy_pct": sc["spy_pct"],
                       "main_names": [x["symbol"] for x in sc["worst"]]} for sc in scenarios],
        "most_exposed": {
            "oil_long": top("oil"), "oil_short": top("oil", reverse=False),
            "ai_long": top("ai"), "ai_short": top("ai", reverse=False),
            "rates_hurt_if_up": top("rates_tlt"), "momentum": top("momentum"),
        },
        "history": history,
        "headlines": news,
    }

    compact = {
        "as_of": datetime.date.today().isoformat(),
        "exposures": exposures,
        "scenarios": {sc["name"]: [sc["basket_pct"], sc["spy_pct"], [x["symbol"] for x in sc["worst"]]] for sc in scenarios},
        "history": history,
        "warnings": warnings,
        "per_symbol_cols": ["beta_spy", "oil", "rates_tlt", "momentum", "ai"],
        "per_symbol": {p["symbol"]: [p["beta_spy"], p["oil"], p["rates_tlt"], p["momentum"], p["ai"]] for p in per},
    }
    summary = {
        "symbols": len(usable), "skipped": skipped, "days": len(dates) - 1, "weights": wmode,
        "beta": exposures["beta_spy_simple"],
        "crash_pct": scenarios[0]["basket_pct"],
        "worst_scenario": min(scenarios, key=lambda x: x["basket_pct"])["name"],
        "warnings": len(warnings),
    }
    moves = scenario_moves(closes, basket + universe, factor_dates)
    if moves["skipped"]:
        errors.append(f"no scenario moves (short history): {','.join(moves['skipped'][:15])}")
    return {
        "scenario_moves_json": json.dumps(moves, separators=(",", ":")),
        "as_of": compact["as_of"], "weights": wmode, "days": len(dates) - 1,
        "exposures": exposures, "scenarios": scenarios, "history": history,
        "per_symbol": per, "warnings": warnings,
        "market_context": ctx, "headlines": news,
        "stress_json": json.dumps(compact, separators=(",", ":")),
        "risk_input_json": json.dumps(risk_input, separators=(",", ":")),
        "summary": summary, "summary_json": json.dumps(summary),
        "errors": errors[:20],
    }


@stress_bp.route("/stress-test", methods=["POST"])
def stress_test():
    body = request.get_json(force=True, silent=True) or {}
    try:
        basket = _symbols(body.get("basket"))
        universe = _symbols(body.get("universe"))
        weights = _load(body.get("weights")) if body.get("weights") else None
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"could not parse input: {e}"}), 400
    if not basket:
        basket = universe[:20]   # first run: no Watchlist yet -> stress the top of the ranking
    if not basket:
        return jsonify({"error": "basket is empty"}), 400
    if weights is not None and not isinstance(weights, dict):
        return jsonify({"error": "weights must be an object like {\"AAA\": 0.05}"}), 400
    out = compute(basket, weights, universe=universe)
    return jsonify(out), (200 if "error" not in out else 502)
