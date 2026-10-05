"""1-10 deal rating for suggested pairs and live opportunities.

rating = 1 + 9 × confidence × money

- confidence (0-1): how sure we are the two markets are really the same bet (match quality, orientation,
  dates, rule-sensitive market types, implausible price gaps). A shaky match can never rate high,
  however much money it seems to offer — that's where both sides lose.
- money (0-1): how much is on the table after fees. A perfect match with no gap rates ~3-4 ("good pair,
  nothing to grab right now"); 1¢ after fees ~7; 2¢ ~9; 3¢+ rates 10.

10 means every check passes and there's real after-fee profit. Nothing is literally risk-free: the two
exchanges can still settle differently.
"""
from . import arb_engine, matcher

KALSHI_RATE = 0.07
PMUS_RATE = 0.0695

LABELS = [(9, "Excellent"), (7, "Strong"), (5, "Fair"), (3, "Weak"), (1, "Skip")]


def label(rating: int) -> str:
    return next(text for floor, text in LABELS if rating >= floor)


def confidence(d: dict, score: float, est_cost: float | None = None) -> tuple[float, list[str]]:
    """How sure we are the pair is the same bet, with the reasons that moved it."""
    reasons: list[str] = []
    c = min(max((score - 70) / 30, 0.0), 1.0)
    reasons.append(f"Match score {score:.0f}/100")
    if d.get("numbers"):
        c = min(c + 0.1, 1.0)
        reasons.append("Same exact line/number on both (+)")
    o = d.get("orientation")
    if o == "inverse_head_to_head":
        c *= 0.9
        reasons.append("Inverse pair, one more thing to get right (−)")
    elif o == "inverse_flipped_spread":
        c *= 0.8
        reasons.append("Flipped spread market: YES is the opposite of its title (−)")
    gap = d.get("date_gap_days")
    if gap is not None and gap > 1:
        c *= 0.8 if gap <= 3 else 0.6
        reasons.append(f"Dates {gap:.1f} days apart (−)")
    quals = set(d.get("qualifiers") or [])
    if quals & {"draw", "ot", "half", "quarter", "period", "method"}:
        c *= 0.85
        reasons.append("Rule-sensitive market type (ties/overtime/periods often settle differently) (−)")
    if (d.get("event_similarity") or 100) < 90:
        c *= 0.85
        reasons.append("Event names only partly match (−)")
    if est_cost is not None and est_cost < 0.9:
        c *= 0.3
        reasons.append("Price gap is too big for identical markets, likely a mismatch (−−)")
    return max(min(c, 1.0), 0.0), reasons


def money_from_net(net_cents: float | None) -> tuple[float, str]:
    """Map after-fee profit per contract (¢) to 0-1."""
    if net_cents is None:
        return 0.15, "No live prices on one side"
    if net_cents >= 3:
        return 1.0, f"{net_cents:.1f}¢ per contract after fees (+)"
    if net_cents > 0:
        return 0.55 + 0.15 * net_cents, f"{net_cents:.1f}¢ per contract after fees"
    # Well-matched pairs typically sit 3-6¢ from a gap once fees are counted; that's "good pair, nothing yet".
    if net_cents > -6:
        return 0.45 + 0.04 * net_cents, f"No gap right now ({net_cents:.1f}¢ after fees). Worth watching"
    return 0.2, f"Far from a gap ({net_cents:.1f}¢ after fees)"


def best_net_cents(k: dict, p: dict, inverted: bool) -> tuple[float | None, float | None]:
    """(after-fee profit per contract in ¢, before-fee cost) for the cheapest hedge at top of book."""
    if inverted:
        combos = [(k.get("yes_ask"), p.get("yes_ask")), (k.get("no_ask"), p.get("no_ask"))]
    else:
        combos = [(k.get("yes_ask"), p.get("no_ask")), (k.get("no_ask"), p.get("yes_ask"))]
    mult = float(k.get("fee_multiplier") or 1)
    best = None
    for a, b in combos:
        if not (a and b and 0 < a < 1 and 0 < b < 1):
            continue
        net = 1 - a - b - KALSHI_RATE * mult * a * (1 - a) - PMUS_RATE * b * (1 - b)
        if best is None or net > best[0]:
            best = (net, a + b)
    return (round(best[0] * 100, 2), round(best[1], 4)) if best else (None, None)


def _finish(conf: float, money: float, reasons: list[str]) -> dict:
    rating = max(1, min(10, round(1 + 9 * conf * money)))
    return {"rating": rating, "rating_label": label(rating), "confidence": round(conf, 3),
            "rating_reasons": reasons}


def rate_candidate(k: dict, p: dict, score: float, inverted: bool) -> dict:
    d = matcher.match_details(k, p)
    net, cost = best_net_cents(k, p, inverted)
    conf, reasons = confidence(d, score, cost)
    money, why = money_from_net(net)
    out = _finish(conf, money, reasons + [why])
    closes_at = min(filter(None, [k.get("close_time"), p.get("close_time")]), default=None)
    roi, annualized = returns(net, closes_at)
    out.update(net_cents=net, kind=(d.get("prop_kind") or ["outcome"])[0], closes_at=closes_at,
               roi=roi, annualized=annualized)
    return out


def returns(net_cents: float | None, closes_at: str | None) -> tuple[float | None, float | None]:
    """Return per dollar spent and its yearly equivalent, for one hedged pair at top of book.

    A pair pays $1 and costs (100 - net)¢ including fees, so ROI = net / (100 - net).
    Only meaningful when net > 0; otherwise there's no return to rank.
    """
    if net_cents is None or net_cents <= 0:
        return None, None
    roi = net_cents / (100 - net_cents)
    days = arb_engine.days_until(closes_at) if closes_at else None
    annualized = roi * 365 / max(days, 1.0) if days is not None else None
    return round(roi, 5), round(annualized, 4) if annualized is not None else None


def rate_opportunity(opp: dict, d: dict | None, score: float | None) -> dict:
    conf, reasons = confidence(d or {}, score if score is not None else 90)
    edge = float(opp.get("edge_cents") or 0)
    money, why = money_from_net(edge)
    reasons.append(why.replace("after fees", "after fees, sized to the book"))
    days = arb_engine.days_until(opp.get("closes_at") or "") if opp.get("closes_at") else None
    ann = opp.get("annualized")
    if days is not None and days > 30 and (ann or 0) < 0.10:
        money *= 0.6
        reasons.append(f"Money tied up ~{days:.0f} days for under 10%/yr (−)")
    if (opp.get("profit") or 0) < 1:
        money *= 0.5
        reasons.append("Under $1 total profit (−)")
    return _finish(conf, money, reasons)
