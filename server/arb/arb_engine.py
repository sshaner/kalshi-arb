"""Cross-venue arbitrage math. Pure functions, no I/O.

A pair says Kalshi market K and Polymarket US market P describe the same outcome
(or, when `inverted`, that K's YES is P's NO). Buying complementary sides on the two
venues pays exactly $1 per contract at resolution, so any combined cost + fees below
$1 is locked-in profit — provided both venues resolve consistently.
"""
from datetime import datetime, timezone

from .fees import kalshi_fee, pmus_fee
from .models import KALSHI, PMUS, Book, Leg, Level, Opportunity


def directions(inverted: bool) -> list[tuple[str, str]]:
    """(kalshi_side, pmus_side) combinations that together pay $1."""
    if inverted:
        return [("yes", "yes"), ("no", "no")]
    return [("yes", "no"), ("no", "yes")]


def _ladder(book: Book, side: str) -> list[Level]:
    return book.yes_asks if side == "yes" else book.no_asks


def _leg_cost(fills: list[tuple[float, float]], fee_fn) -> tuple[float, float, float]:
    """fills = [(price, qty)] -> (contracts, cost, fee). Fee is charged per price level (conservative)."""
    qty = sum(q for _, q in fills)
    cost = sum(p * q for p, q in fills)
    fee = sum(fee_fn(q, p) for p, q in fills)
    return qty, cost, fee


def walk(
    k_ladder: list[Level],
    p_ladder: list[Level],
    k_coef: float,
    k_mult: float,
    p_coef: float,
    max_stake: float | None = None,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Consume both ask ladders level by level while the marginal contract is profitable.

    Returns the fills taken on each leg. Marginal edge uses the unrounded fee rate;
    exact (rounded) fees are applied afterwards by the caller.
    """
    k_fills: list[tuple[float, float]] = []
    p_fills: list[tuple[float, float]] = []
    ki = pi = 0
    k_left = k_ladder[0].size if k_ladder else 0.0
    p_left = p_ladder[0].size if p_ladder else 0.0
    spent = 0.0
    while ki < len(k_ladder) and pi < len(p_ladder):
        kp, pp = k_ladder[ki].price, p_ladder[pi].price
        marginal = 1.0 - kp - pp - k_coef * k_mult * kp * (1 - kp) - p_coef * pp * (1 - pp)
        if marginal <= 0:
            break
        q = min(k_left, p_left)
        if max_stake is not None:
            per = kp + pp
            room = (max_stake - spent) / per if per > 0 else q
            q = min(q, float(int(room)))  # whole contracts
            if q <= 0:
                break
        if q > 0:
            k_fills.append((kp, q))
            p_fills.append((pp, q))
            spent += q * (kp + pp)
        k_left -= q
        p_left -= q
        if k_left <= 1e-9:
            ki += 1
            k_left = k_ladder[ki].size if ki < len(k_ladder) else 0.0
        if p_left <= 1e-9:
            pi += 1
            p_left = p_ladder[pi].size if pi < len(p_ladder) else 0.0
        if max_stake is not None and spent >= max_stake:
            break
    return k_fills, p_fills


def _merge(fills: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: dict[float, float] = {}
    for p, q in fills:
        merged[p] = merged.get(p, 0.0) + q
    return sorted(merged.items())


def days_until(iso: str, now: datetime | None = None) -> float | None:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    now = now or datetime.now(timezone.utc)
    return max((t - now).total_seconds() / 86400, 0.0)


def evaluate(
    k_book: Book,
    p_book: Book,
    *,
    kalshi_id: str,
    pmus_id: str,
    inverted: bool,
    close_time: str,
    k_coef: float = 0.07,
    k_mult: float = 1.0,
    p_coef: float = 0.0695,
    max_stake: float | None = None,
    now: datetime | None = None,
) -> Opportunity | None:
    """Best opportunity across both directions, or None if nothing is profitable."""
    best: Opportunity | None = None
    for k_side, p_side in directions(inverted):
        k_fills, p_fills = walk(_ladder(k_book, k_side), _ladder(p_book, p_side), k_coef, k_mult, p_coef, max_stake)
        if not k_fills:
            continue
        k_fills, p_fills = _merge(k_fills), _merge(p_fills)
        kq, kc, kf = _leg_cost(k_fills, lambda q, p: kalshi_fee(q, p, k_coef, k_mult))
        pq, pc, pf = _leg_cost(p_fills, lambda q, p: pmus_fee(q, p, p_coef))
        contracts = min(kq, pq)
        cost, fees = kc + pc, kf + pf
        profit = contracts - cost - fees
        if profit <= 0:
            continue
        roi = profit / (cost + fees)
        days = days_until(close_time, now)
        annualized = roi * 365 / max(days, 1.0) if days is not None else None
        opp = Opportunity(
            direction=f"k{k_side}_p{p_side}",
            kalshi=Leg(KALSHI, kalshi_id, k_side, kq, kc / kq, round(kc, 4), round(kf, 2)),
            pmus=Leg(PMUS, pmus_id, p_side, pq, pc / pq, round(pc, 4), round(pf, 2)),
            contracts=contracts,
            cost=round(cost, 4),
            fees=round(fees, 2),
            profit=round(profit, 4),
            edge_cents=round(profit / contracts * 100, 3),
            roi=roi,
            annualized=annualized,
        )
        if best is None or opp.profit > best.profit:
            best = opp
    return best
