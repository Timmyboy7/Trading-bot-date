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
                        ONE_OFF_TOLERANCE, TAX_RATE, _date, _rows, balance_sheet_shares, cover_shares,
                        diluted_shares, extract)

# banks (e.g. JPM) stopped tagging "Revenues" years ago and report net revenue instead
REVENUE_TAGS = tuple(REVENUE_CONCEPTS) + ("RevenuesNetOfInterestExpense",)
STALE_DAYS = 200
MIN_BASE_MARGIN = 0.02      # earnings growth only from a year-ago net margin of at least 2%            # newest quarter older than this -> tags not recognised, report no data

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
_INVENTORY = {}  # sym -> recent tags (for /valuation?debug=1)


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
    # same end, different start: 6M YTD - Q2 = Q1 (filers whose older 10-Qs are missing)
    by_end = {}
    for (s, e), v in per.items():
        by_end.setdefault(e, []).append((s, v))
    for e, lst in by_end.items():
        lst.sort()
        for (s1, v1), (s2, v2) in zip(lst, lst[1:]):
            qe = s2 - datetime.timedelta(days=1)
            if lo <= (qe - s1).days <= hi and not any(abs((d - qe).days) < 30 for d in q):
                q[qe] = v1 - v2
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


# Fallbacks when a company files under tags the fixed lists don't know (2026-10-12:
# BNY, APA had no revenue since 2018/2021; NUE, DE, PSX no operating-income line;
# PSX no capex tag). Candidates are discovered from the filing itself.
REV_EXCLUDE = ("Remaining", "Deferred", "Receivable", "Unbilled", "PerformanceObligation", "Cost",
               "Percentage", "Increase", "Decrease", "Recognized", "Allowance", "Reserve")
COSTS_CONCEPTS = ("CostsAndExpenses", "OperatingCostsAndExpenses", "BenefitsLossesAndExpenses")
PRETAX_CONCEPTS = ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                   "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
                   "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic")


def _concepts(facts):
    return list(((facts.get("facts") or {}).get("us-gaap") or {}).keys())


def _is_revenue_name(n):
    ok = (n.startswith("Revenue") or "Revenues" in n or n.endswith("Revenue")
          or n in ("InterestAndNoninterestIncome", "SalesRevenueNet", "SalesRevenueGoodsNet"))
    return ok and not any(x in n for x in REV_EXCLUDE)


def _is_capex_name(n):
    if n.startswith("PaymentsToAcquire"):
        return any(x in n for x in ("PropertyPlantAndEquipment", "ProductiveAssets", "OilAndGas"))
    return n.startswith("PaymentsToExploreAndDevelop") or n in ("PaymentsForCapitalImprovements",
                                                                "CapitalExpendituresAndInvestments")


def _gaps(vals, k=4):
    """True if any of the latest k values is missing."""
    return any(v is None for v in vals[-k:])


def _fill(vals, alt):
    """keep known values, fill the missing ones from alt"""
    return [v if v is not None else a for v, a in zip(vals, alt)]


def tag_inventory(facts, days=400):
    """Debug: every us-gaap USD concept with a period ending in the last `days` days,
    latest value first. Shows which tags a company really uses."""
    today = datetime.date.today()
    out = []
    for n in _concepts(facts):
        rows = [r for r in _rows(facts, n) if r.get("end") and r.get("val") is not None]
        if not rows:
            continue
        r = max(rows, key=lambda r: (r["end"], r.get("filed", "")))
        if (today - _date(r["end"])).days <= days:
            out.append({"tag": n, "start": r.get("start"), "end": r["end"], "val": r["val"], "form": r.get("form")})
    out.sort(key=lambda x: -abs(float(x["val"])))
    return out


def best_recent(facts, names):
    """(series, name) of the concept with the most recent quarter; ties -> larger latest value
    (a total is at least as big as any of its parts)."""
    best, best_name = [], None
    for n in names:
        q = quarterly(facts, (n,))
        if len(q) < 2:
            continue
        key = (q[-1][0], q[-1][1])
        if not best or key > (best[-1][0], best[-1][1]):
            best, best_name = q, n
    return best, best_name


def summarize(facts, today=None):
    """Everything /valuation needs from one companyfacts document (no price yet).
    `today` = reference date for staleness (backtests pass the formation date)."""
    ref = today or datetime.date.today()
    rev = quarterly(facts, REVENUE_TAGS)
    tags = []
    if len(rev) < 2 or (ref - rev[-1][0]).days > STALE_DAYS:
        alt, name = best_recent(facts, [n for n in _concepts(facts) if _is_revenue_name(n)])
        if alt and (not rev or alt[-1][0] > rev[-1][0]):
            rev = alt
            tags = [f"revenue tag {name}"]
    if len(rev) < 2 or (ref - rev[-1][0]).days > STALE_DAYS:
        # banks: revenue = net interest income + non-interest income
        nii = quarterly(facts, ("InterestIncomeExpenseNet", "InterestIncomeExpenseAfterProvisionForLoanLoss"))
        fees = dict(quarterly(facts, ("NoninterestIncome",)))
        bank = [(e, v + fees[e]) for e, v in nii if e in fees]
        if len(bank) >= 2 and (not rev or bank[-1][0] > rev[-1][0]):
            rev = bank
            tags = ["revenue = net interest income + non-interest income"]
    if len(rev) < 2 or (ref - rev[-1][0]).days > STALE_DAYS:
        # no revenue line in standard tags (e.g. APA files it under its own tag):
        # pre-tax income = revenue - total costs and expenses  ->  revenue = pre-tax + costs
        pre = dict(quarterly(facts, PRETAX_CONCEPTS))
        costs = quarterly(facts, ("CostsAndExpenses",))
        derived = [(e, c + pre[e]) for e, c in costs if e in pre and c + pre[e] > 0]
        if len(derived) >= 2 and (not rev or derived[-1][0] > rev[-1][0]):
            rev = derived
            tags = ["revenue = pre-tax income + total costs (no revenue tag filed)"]
    if len(rev) < 2:
        return None, "fewer than 2 quarters of revenue in SEC filings (insurer layout, foreign filer or new listing)"
    if (ref - rev[-1][0]).days > STALE_DAYS:
        return None, f"newest revenue figure in SEC filings is from {rev[-1][0].isoformat()} - revenue tag not recognised"
    ends = [e for e, _ in rev]
    gross = _align(quarterly(facts, GROSS_CONCEPTS), ends)
    if all(v is None for v in gross):
        cost = _align(quarterly(facts, COST_CONCEPTS), ends)
        gross = [(r - c) if c is not None else None for (_, r), c in zip(rev, cost)]
    op = _align(quarterly(facts, OPINC_CONCEPTS), ends)
    if _gaps(op):   # missing in recent quarters (older filings may still have the line)
        costs = _align(quarterly(facts, COSTS_CONCEPTS), ends)
        alt = [(r - c) if c is not None else None for (_, r), c in zip(rev, costs)]
        how = "revenue - total costs"
        if _gaps(alt):
            alt = _fill(alt, _align(quarterly(facts, PRETAX_CONCEPTS), ends))
            how = "revenue - total costs / pre-tax income"
        if not _gaps(_fill(op, alt)) or sum(v is not None for v in _fill(op, alt)[-4:]) > sum(v is not None for v in op[-4:]):
            op = _fill(op, alt)
            tags.append(f"operating income = {how} where not reported")
    capex = _align(quarterly(facts, CAPEX_CONCEPTS), ends)
    if _gaps(capex):
        cands = [n for n in _concepts(facts) if _is_capex_name(n) and n not in CAPEX_CONCEPTS]
        alt, name = best_recent(facts, cands)
        if alt:
            filled = _fill(capex, _align(alt, ends))
            if sum(v is not None for v in filled[-4:]) > sum(v is not None for v in capex[-4:]):
                capex = filled
                tags.append(f"capex tag {name}")
    ocf = _align(quarterly(facts, OCF_CONCEPTS), ends)
    out = {
        "tags": tags,
        "ends": ends,
        "revenue": [v for _, v in rev],
        "gross": gross,
        "op_inc": op,
        "net_inc": _align(quarterly(facts, NI_CONCEPTS), ends),
        "ocf": ocf,
        "capex": capex,
        "eps": _align(quarterly(facts, EPS_CONCEPTS, unit="USD/shares"), ends),
        "debt_to_equity": latest_debt_to_equity(facts),
    }
    out["shares"] = shares_now(facts)
    # fallback TTM (last FY + YTD - prior YTD, one-off capped) for filers with gaps in their quarters
    try:
        ex = extract(facts)
        out["ttm_fallback"] = {"rev": ex.get("rev_ttm"), "ni": ex.get("ni_ttm"), "op": ex.get("op_ttm"),
                               "fcf": ex.get("fcf_ttm")}
    except Exception:
        out["ttm_fallback"] = {}
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


def _consecutive(ends):
    """True when the last 4 quarters are back to back (~9 months between first and last end)."""
    return len(ends) >= 4 and 250 <= (ends[-1] - ends[-4]).days <= 300


def _ttm(vals, ends):
    last = vals[-4:]
    if not _consecutive(ends) or any(v is None for v in last):
        return None
    return sum(last)


def _yoy_dated(vals, ends):
    """Latest quarter vs the quarter ending ~1 year earlier."""
    if not vals or vals[-1] is None:
        return None
    for v, e in zip(vals, ends):
        if 340 <= (ends[-1] - e).days <= 390 and v not in (None, 0):
            return (vals[-1] - v) / abs(v)
    return None


def _earnings_growth(ni, rev, ends):
    """Year-on-year profit growth, but only when last year's quarter was a real profit
    (net margin >= MIN_BASE_MARGIN). From a near-zero or loss base the percentage
    explodes (SNDK +29,000%) and means nothing, so it is left out (null)."""
    if not ni or ni[-1] is None:
        return None
    for v, r, e in zip(ni, rev, ends):
        if 340 <= (ends[-1] - e).days <= 390:
            if v is None or r in (None, 0) or v <= 0 or v / r < MIN_BASE_MARGIN:
                return None
            return (ni[-1] - v) / v
    return None


def _cap_one_offs(ni, op):
    """Net profit above after-tax operating profit (+20%) is a one-off gain (e.g. investment
    gains at Alphabet/NVIDIA) - cap it, same rule as fair_value."""
    out, capped = [], False
    for n, o in zip(ni, op):
        lim = o * (1 - TAX_RATE) * ONE_OFF_TOLERANCE if (o is not None and o > 0) else None
        if n is not None and lim is not None and n > lim:
            out.append(lim)
            capped = True
        else:
            out.append(n)
    return out, capped


def _ratio(a, b):
    return None if a is None or not b else a / b


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
    ends = s["ends"]
    rev, gross, op = s["revenue"], s["gross"], s["op_inc"]
    ni, capped = _cap_one_offs(s["net_inc"], op)
    fcf = [(o - c) if o is not None and c is not None else None for o, c in zip(s["ocf"], s["capex"])]
    rev_ttm, ni_ttm, op_ttm = _ttm(rev, ends), _ttm(ni, ends), _ttm(op, ends)
    gross_ttm, fcf_ttm = _ttm(gross, ends), _ttm(fcf, ends)
    fb = s.get("ttm_fallback") or {}
    used_fallback = False
    if rev_ttm is None and fb.get("rev"):
        used_fallback = True
        rev_ttm, gross_ttm = fb["rev"], None
        ni_ttm = ni_ttm if ni_ttm is not None else fb.get("ni")
        op_ttm = op_ttm if op_ttm is not None else fb.get("op")
        fcf_ttm = fcf_ttm if fcf_ttm is not None else fb.get("fcf")
    shares = s.get("shares")
    if shares and ni_ttm is not None:
        eps_ttm = ni_ttm / shares
    else:
        eps_ttm = None if capped else _ttm(s["eps"], ends)
    note = "; one-off gains capped" if capped else ""
    if s.get("tags"):
        note += "; " + "; ".join(s["tags"])
    note += "; TTM from annual + year-to-date figures (quarters incomplete)" if used_fallback else ""
    data = {
        "pe_ratio": (price / eps_ttm) if (price and eps_ttm and eps_ttm > 0) else None,
        "forward_pe": None,
        "peg_ratio": None,
        "revenue_growth_yoy": _yoy_dated(rev, ends),
        "earnings_growth_yoy": _earnings_growth(ni, rev, ends),
        "gross_margin": _ratio(gross_ttm, rev_ttm),
        "operating_margin": _ratio(op_ttm, rev_ttm),
        "profit_margin": _ratio(ni_ttm, rev_ttm),
        "debt_to_equity": s.get("debt_to_equity"),
        "free_cash_flow": fcf_ttm,
        "market_cap": (price * shares) if (price and shares) else None,
        "last_price": price,
        "snapshot_source": f"SEC filings (latest quarter {ends[-1].isoformat()}) + Alpaca price; "
                           f"no forward P/E or PEG{note}",
    }
    # trend: last TREND_QUARTERS quarters, oldest -> newest (one extra for the first q/q growth)
    k = TREND_QUARTERS
    tends = ends[-k:]
    r, g, o, n, f = rev[-k:], gross[-k:], op[-k:], ni[-k:], fcf[-k:]
    gm = [_ratio(a, b) for a, b in zip(g, r)]
    om = [_ratio(a, b) for a, b in zip(o, r)]
    nm = [_ratio(a, b) for a, b in zip(n, r)]
    qoq = [((b - a) / abs(a)) if (a and b is not None) else None for a, b in zip(r, r[1:])]
    data.update({
        "trend_period": " -> ".join(e.strftime("%b'%y") for e in tends),
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
            _INVENTORY[sym] = tag_inventory(facts)[:60]
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
