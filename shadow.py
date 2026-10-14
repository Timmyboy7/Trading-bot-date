"""
Low-AI shadow portfolio: a pure simulation (no orders, no account). Information only.

Question it answers: would the same strategy with far less AI exposure have done better or worse?
Both shadows (the current basket and its Low-AI variant) are run through the SAME simple simulator, so the
only difference between them is the AI exposure:
  - each weekly basket (from the Runs log) is bought at its target weights on the first trading day on/after
    the run date (95% invested, 5% cash floor), selling names that left it;
  - deposits (same schedule as the real account) wait as cash until the next weekly run;
  - no daily trend exits, no three-tranche build-up, no costs. So they differ from the real account on purpose.

Low-AI rule: names whose AI sensitivity (beta to semis-minus-S&P, from stress_test) is above SHADOW_AI_CUT are
replaced, one for one with the same weight, by the best-ranked candidate whose AI sensitivity is at most
SHADOW_AI_FILL_MAX. Without enough replacements the name is dropped and the rest scaled up.
"""
import datetime
import os

AI_CUT = float(os.environ.get("SHADOW_AI_CUT", 0.5))
AI_FILL_MAX = float(os.environ.get("SHADOW_AI_FILL_MAX", 0.25))
CASH_FLOOR = 0.05


def ai_exposure(weights, ai_beta):
    tot = sum(weights.values()) or 1.0
    return sum(w * ai_beta.get(s, 0.0) for s, w in weights.items()) / tot


def low_ai_basket(weights, ranking, ai_beta):
    """-> (weights of the Low-AI basket, [(out, in or None)])"""
    b = dict(weights)
    swaps = []
    fill = [s for s in ranking if s not in weights and ai_beta.get(s) is not None and ai_beta[s] <= AI_FILL_MAX]
    for s in sorted(weights, key=lambda x: -ai_beta.get(x, 0.0)):
        if ai_beta.get(s, 0.0) <= AI_CUT:
            break
        if fill:
            new = fill.pop(0)
            b[new] = b.pop(s)
            swaps.append((s, new))
        else:
            b.pop(s)
            swaps.append((s, None))
    tot = sum(b.values())
    if tot > 0:
        b = {s: w / tot for s, w in b.items()}
    return b, swaps


def _px(closes, sym, day, last):
    v = closes.get(sym, {}).get(day)
    if v is not None:
        last[sym] = v
    return last.get(sym)


def simulate(baskets, closes, deposits, days):
    """baskets [(run_date_iso, {sym: weight})] ascending; closes {sym: {date: close}};
    deposits [(date, amount)]; days = sorted trading days (iso). -> [(day, value)]"""
    cash, shares, last, out = 0.0, {}, {}, []
    dep = sorted((d.isoformat() if hasattr(d, "isoformat") else d, a) for d, a in deposits)
    di, bi, target = 0, 0, None
    for day in days:
        while di < len(dep) and dep[di][0] <= day:
            cash += dep[di][1]
            di += 1
        fresh = None
        while bi < len(baskets) and baskets[bi][0] <= day:
            fresh = baskets[bi][1]
            bi += 1
        if fresh is not None:
            held = {s: _px(closes, s, day, last) for s in set(shares) | set(fresh)}
            eq = cash + sum(shares.get(s, 0.0) * (p or 0.0) for s, p in held.items())
            new = {}
            spent = 0.0
            for s, w in fresh.items():
                p = held.get(s)
                if p:
                    amt = eq * (1 - CASH_FLOOR) * w
                    new[s] = amt / p
                    spent += amt
            shares, cash = new, eq - spent
        value = cash + sum(n * (_px(closes, s, day, last) or 0.0) for s, n in shares.items())
        out.append((day, round(value, 2)))
    return out


def spy_curve(spy, deposits, days):
    """Same deposits straight into SPY on their dates."""
    dep = sorted((d.isoformat() if hasattr(d, "isoformat") else d, a) for d, a in deposits)
    units, di, last, out = 0.0, 0, None, []
    for day in days:
        px = spy.get(day, last)
        last = px
        while di < len(dep) and dep[di][0] <= day:
            if px:
                units += dep[di][1] / px
            di += 1
        out.append((day, round(units * (px or 0.0), 2)))
    return out
