"""
sec_fundamentals.py - the /valuation fundamentals from SEC EDGAR instead of Yahoo.

2026-10-11: Yahoo blocks Render's IP completely (401 "Invalid Crumb" / "User is
unable to access this feature"), so every Yahoo-based field came back empty and
the calls jammed the server. SEC companyfacts (the XBRL data behind every
10-Q/10-K) has the same statement figures, free and without blocking; the
price comes from Alpaca. Output keeps the exact field names of the old
Yahoo version so Make modules and /base-score need no change.

    company figures   -> SEC companyfacts (same rate limiter + User-Agent as signals.py)
    price             -> Alpaca latest daily close
    pe_ratio          = price / diluted EPS of the last 4 quarters
    market_cap        = price x latest share count (cover page / diluted / balance sheet)
    forward_pe, peg   -> null (analyst forecasts; SEC has none)

Quarter values: 10-Qs report 3-month figures for income items but year-to-date
figures for cash flow, and there is no Q4 filing. Every quarter is therefore
built from whatever the filings give: a reported ~3-month period directly,
otherwise the difference of two periods with the same start (6M - 3M, 9M - 6M,
FY - 9M).
"""

import datetime
import time

import requests

from fair_value import (CAPEX_CONCEPTS, NI_CONCEPTS, OCF_CONCEPTS, OPINC_CONCEPTS, REVENUE_CONCEPTS,
                        _date, _rows, balance_sheet_shares, cover_shares, diluted_shares)

TREND_QUARTERS = 4          # quarters shown in the trend strings / q_* lists (oldest -> newest)
HISTORY_QUARTERS = 8        # quarters kept so year-on-year growth can be computed
CACHE_TTL_SEC = 12 * 3600
QUARTER_DAYS = (75, 105)    # what counts as "one quarter" in days

GROSS_CONCEPTS = ("GrossProfit",)
COST_CONCEPTS = ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold")
EPS_CONCEPTS = ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic")
EQUITY_CONCEPTS = ("StockholdersEquity",
                   "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")
# total debt = long-term debt (incl. current part) + short-term borrowings; first match per group
DEBT_GROUPS = (
    ("LongTermDebt", "LongTermDebtNoncurrent+LongTermDebtCurrent", "LongTermDebtNoncurrent",
     "LongTermDebtAndCapitalLeaseObligations"),
    ("ShortTermBorrowings", "CommercialPaper", "DebtCurrent"),
)

_CACHE = {}  # sym -> (ts, (facts_summary, error))


# --------------------------------------------------------------------------- pure parsing

def _periods(facts, concepts, unit="USD"):
    """{(start, end): value} over the concepts in priority order; within a concept the
    latest filing wins (restatements replace originals)."""
    out = {}
    for c in concepts:
        best = {}
        for r in _rows(facts, c, unit):
            if not r.get("start") or not r.get("end") or r.get("val") is None:
                continue
            if not str(r.get("form", "")).startswith(("10-Q", "10-K")):
                continue
            k = (_date(r["start"]), _date(r["end"]))
            if k not in best or str(r.get("filed", "")) >= best[k][0]:
                best[k] = (str(r.get("filed", "")), float(r["val"]))
        for k, (_, v) in best.items():
            out.setdefault(k, v)   # higher-priority concept keeps the period
    return out


def quarterly(facts, concepts, unit="USD", n=HISTORY_QUARTERS):
    """[(quarter_end, value)] oldest -> newest, last n quarters."""
    per = _periods(facts, concepts, unit)
    lo, hi = QUARTER_DAYS
    q = {}
    for (s, e), v in per.items():
        if lo <= (e - s).days <= hi:
            q[e] = v
    by_start = {}
    for (s, e), v in per.items():
        by_start.setdefault(s, []).append((e, v))
    for s, lst in by_start.items():
        lst.sort()
        for (e1, v1), (e2, v2) in zip(lst, lst[1:]):
            if e2 not in q and lo <= (e2 - e1).days <= hi:
                q[e2] = v2 - v1
    # Q4 when only 3-month quarters + the full year exist: FY - (Q1 + Q2 + Q3)
    for (s, e), v in per.items():
        if 350 <= (e - s).days <= 380 and e not in q:
            inside = [d for d in q if s < d < e - datetime.timedelta(days=30)]
            if len(inside) == 3:
                q[e] = v - sum(q[d] for d in inside)
    # merge quarter ends a few days apart (52/53-week fiscal years) - keep the later one
    ends = sorted(q)
    keep = []
    for e in ends:
        if keep and (e - keep[-1]).days < 30:
            keep[-1] = e
        else:
            keep.append(e)
    return [(e, q[e]) for e in keep][-n:]


def _instant(facts, concept, unit="USD"):
    """{end: value} for balance-sheet (point in time) items, latest filing wins."""
    best = {}
    for r in _rows(facts, concept, unit):
        if r.get("start") or not r.get("end") or r.get("val") is None:
            continue
        if not str(r.get("form", "")).startswith(("10-Q", "10-K")):
            continue
        e = _date(r["end"])
        if e not in best or str(r.get("filed", "")) >= best[e][0]:
            best[e] = (str(r.get("filed", "")), float(r["val"]))
    return {e: v for e, (_, v) in best.items()}


def latest_debt_to_equity(facts):
    """Yahoo-style debt/equity in percent at the latest balance-sheet date."""
    eq = {}
    for c in EQUITY_CONCEPTS:
        for e, v in _instant(facts, c).items():
            eq.setdefault(e, v)
    if not eq:
        return None
    day = max(eq)
    total, found = 0.0, False
    for group in DEBT_GROUPS:
        for name in group:
            parts = name.split("+")
            vals = [_instant(facts, p).get(day) for p in parts]
            if all(v is not None for v in vals):
                total += sum(vals)
                found = True
                break
    if not found or not eq[day]:
        return 0.0 if eq.get(day) else None   # no debt tagged at all -> treat as debt-free
    return total / eq[day] * 100


def _align(series, ends):
    m = dict(series)
    out = []
    for e in ends:
        v = m.get(e)
        if v is None:   # tolerate a few days of difference between concepts
            v = next((val for d, val in series if abs((d - e).days) <= 10), None)
        out.append(v)
    return out


def summarize(facts):
    """Everything /valuation needs from one companyfacts document (no price yet)."""
    rev = quarterly(facts, REVENUE_CONCEPTS)
    if len(rev) < 2:
        return None, "fewer than 2 quarters of revenue in SEC filings (bank/insurer layout, foreign filer or new listing)"
    ends = [e for e, _ in rev]
    gross = _align(quarterly(facts, GROSS_CONCEPTS), ends)
    if all(v is None for v in gross):
        cost = _align(quarterly(facts, COST_CONCEPTS), ends)
        gross = [(r - c) if c is not None else None for (_, r), c in zip(rev, cost)]
    out = {
        "ends": ends,
        "revenue": [v for _, v in rev],
        "gross": gross,
        "op_inc": _align(quarterly(facts, OPINC_CONCEPTS), ends),
        "net_inc": _align(quarterly(facts, NI_CONCEPTS), ends),
        "ocf": _align(quarterly(facts, OCF_CONCEPTS), ends),
        "capex": _align(quarterly(facts, CAPEX_CONCEPTS), ends),
        "eps": _align(quarterly(facts, EPS_CONCEPTS, unit="USD/shares"), ends),
        "debt_to_equity": latest_debt_to_equity(facts),
    }
    out["shares"] = shares_now(facts)
    return out, None


def shares_now(facts):
    """Today's share count: the most recent of cover page / diluted weighted / balance sheet
    (same rule as fair_value.extract)."""
    latest = []
    for fn in (cover_shares, diluted_shares, balance_sheet_shares):
        try:
            lst = fn(facts)
        except Exception:
            continue
        if lst:
            latest.append((lst[-1][0], lst[-1][1]))
    return max(latest)[1] if latest else None


def _ttm(vals):
    last = vals[-4:]
    if len(last) < 4 or any(v is None for v in last):
        return None
    return sum(last)


def _ratio(a, b):
    return None if a is None or not b else a / b


def _yoy(vals):
    if len(vals) >= 5 and vals[-1] is not None and vals[-5] not in (None, 0):
        return (vals[-1] - vals[-5]) / abs(vals[-5])
    return None


def _money(v):
    if v is None:
        return "n/a"
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1e9:
        return f"{sign}${v / 1e9:.1f}B"
    if v >= 1e6:
        return f"{sign}${v / 1e6:.1f}M"
    return f"{sign}${v:.0f}"


def _pct(v, signed=False):
    if v is None:
        return "n/a"
    return f"{v * 100:+.0f}%" if signed else f"{v * 100:.0f}%"


def _r(v, nd):
    return None if v is None else round(v, nd)


def build(s, price):
    """Turns a summary + price into the /valuation field set (same names as the Yahoo version)."""
    rev, gross, op, ni = s["revenue"], s["gross"], s["op_inc"], s["net_inc"]
    fcf = [(o - c) if o is not None and c is not None else None for o, c in zip(s["ocf"], s["capex"])]
    eps_ttm = _ttm(s["eps"])
    rev_ttm, ni_ttm, op_ttm, gross_ttm, fcf_ttm = _ttm(rev), _ttm(ni), _ttm(op), _ttm(gross), _ttm(fcf)
    shares = s.get("shares")
    if eps_ttm is None and ni_ttm is not None and shares:
        eps_ttm = ni_ttm / shares
    data = {
        "pe_ratio": (price / eps_ttm) if (price and eps_ttm and eps_ttm > 0) else None,
        "forward_pe": None,
        "peg_ratio": None,
        "revenue_growth_yoy": _yoy(rev),
        "earnings_growth_yoy": _yoy(ni),
        "gross_margin": _ratio(gross_ttm, rev_ttm),
        "operating_margin": _ratio(op_ttm, rev_ttm),
        "profit_margin": _ratio(ni_ttm, rev_ttm),
        "debt_to_equity": s.get("debt_to_equity"),
        "free_cash_flow": fcf_ttm,
        "market_cap": (price * shares) if (price and shares) else None,
        "last_price": price,
        "snapshot_source": f"SEC filings (last 4 quarters to {s['ends'][-1].isoformat()}) + Alpaca price; "
                           "no forward P/E or PEG",
    }
    # trend: last TREND_QUARTERS quarters, oldest -> newest (one extra for the first q/q growth)
    k = TREND_QUARTERS
    ends = s["ends"][-k:]
    r, g, o, n, f = rev[-k:], gross[-k:], op[-k:], ni[-k:], fcf[-k:]
    gm = [_ratio(a, b) for a, b in zip(g, r)]
    om = [_ratio(a, b) for a, b in zip(o, r)]
    nm = [_ratio(a, b) for a, b in zip(n, r)]
    qoq = [((b - a) / abs(a)) if (a and b is not None) else None for a, b in zip(r, r[1:])]
    data.update({
        "trend_period": " -> ".join(e.strftime("%b'%y") for e in ends),
        "trend_revenue": " -> ".join(_money(v) for v in r),
        "trend_revenue_growth_qoq": " -> ".join(_pct(v, signed=True) for v in qoq),
        "trend_gross_margin": " -> ".join(_pct(v) for v in gm),
        "trend_operating_margin": " -> ".join(_pct(v) for v in om),
        "trend_net_margin": " -> ".join(_pct(v) for v in nm),
        "trend_fcf": " -> ".join(_money(v) for v in f),
        "q_revenue": [_r(v, 0) for v in r],
        "q_operating_margin": [_r(v, 4) for v in om],
        "q_net_margin": [_r(v, 4) for v in nm],
        "q_fcf": [_r(v, 0) for v in f],
    })
    return data


# --------------------------------------------------------------------------- I/O

def summary_for(sym):
    """(summary, error), cached 12h - filings change at most once a quarter."""
    hit = _CACHE.get(sym)
    if hit and time.time() - hit[0] < CACHE_TTL_SEC:
        return hit[1]
    from signals import _cik_for, _get   # same SEC User-Agent + rate limiter
    try:
        cik = _cik_for(sym)
        if not cik:
            res = (None, "no SEC filer found for this symbol (foreign listing or ETF)")
        else:
            facts = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json", as_json=True)
            res = summarize(facts)
    except Exception as e:   # network errors are not cached for long
        res = (None, f"SEC fetch failed: {e}")
        _CACHE[sym] = (time.time() - CACHE_TTL_SEC + 300, res)
        return res
    _CACHE[sym] = (time.time(), res)
    return res


def latest_prices(symbols):
    """{sym: last daily close} from Alpaca (one call for all symbols)."""
    from screener import DATA_BASE, HEADERS
    start = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
    out = {}
    for feed in ("iex", "sip"):
        try:
            r = requests.get(f"{DATA_BASE}/v2/stocks/bars", headers=HEADERS, timeout=15,
                             params={"symbols": ",".join(symbols), "timeframe": "1Day", "start": start,
                                     "feed": feed, "limit": 10000})
            if r.status_code != 200:
                continue
            for s, bars in (r.json().get("bars") or {}).items():
                if bars:
                    out[s] = float(bars[-1]["c"])
        except Exception:
            continue
        if len(out) >= len(symbols):
            break
    return out
