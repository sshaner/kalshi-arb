from datetime import datetime, timedelta, timezone

from arb.arb_engine import directions, evaluate, walk
from arb.fees import kalshi_fee, pmus_fee
from arb.models import Book, Level

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
CLOSE = (NOW + timedelta(days=36.5)).isoformat()


def book(yes, no):
    return Book([Level(p, q) for p, q in yes], [Level(p, q) for p, q in no])


# -- fees ---------------------------------------------------------------------
def test_kalshi_fee_published_example():
    # 0.07 * 1 * 0.5 * 0.5 = 0.0175 -> rounds up to $0.02
    assert kalshi_fee(1, 0.50) == 0.02
    # 100 contracts at 50c: 1.75 exactly, no rounding up
    assert kalshi_fee(100, 0.50) == 1.75


def test_kalshi_fee_multiplier():
    assert kalshi_fee(100, 0.50, multiplier=0.5) == 0.88


def test_pmus_fee():
    # 0.0695 * 1000 * 0.1 * 0.9 = 6.255 -> 6.26
    assert pmus_fee(1000, 0.10) == 6.26
    assert pmus_fee(0, 0.5) == 0.0


def test_fee_no_float_noise_roundup():
    # 0.07 * 100 * 0.2 * 0.8 = 1.12 exactly; must not become 1.13
    assert kalshi_fee(100, 0.2) == 1.12


# -- directions ---------------------------------------------------------------
def test_directions():
    assert directions(False) == [("yes", "no"), ("no", "yes")]
    assert directions(True) == [("yes", "yes"), ("no", "no")]


# -- engine -------------------------------------------------------------------
def test_no_arb_when_prices_sum_to_one():
    k = book(yes=[(0.50, 100)], no=[(0.51, 100)])
    p = book(yes=[(0.50, 100)], no=[(0.51, 100)])
    assert evaluate(k, p, kalshi_id="K", pmus_id="P", inverted=False, close_time=CLOSE, now=NOW) is None


def test_simple_arb_kyes_pno():
    k = book(yes=[(0.40, 100)], no=[(0.62, 100)])
    p = book(yes=[(0.58, 100)], no=[(0.50, 100)])
    o = evaluate(k, p, kalshi_id="K", pmus_id="P", inverted=False, close_time=CLOSE, now=NOW)
    assert o is not None
    assert o.direction == "kyes_pno"
    assert o.contracts == 100
    # cost 40 + 50 = 90; fees 0.07*100*.4*.6=1.68 + 0.0695*100*.5*.5=1.7375->1.74
    assert o.cost == 90.0
    assert o.fees == round(1.68 + 1.74, 2)
    assert o.profit == round(100 - 90 - 3.42, 4)
    assert abs(o.edge_cents - 6.58) < 1e-6
    # ~10% days-out=36.5 -> roi*10
    assert abs(o.annualized - o.roi * 10) < 1e-6


def test_inverted_pair_uses_same_sides():
    k = book(yes=[(0.40, 50)], no=[(0.70, 50)])
    p = book(yes=[(0.45, 50)], no=[(0.70, 50)])
    o = evaluate(k, p, kalshi_id="K", pmus_id="P", inverted=True, close_time=CLOSE, now=NOW)
    assert o is not None and o.direction == "kyes_pyes"
    assert o.kalshi.side == "yes" and o.pmus.side == "yes"


def test_walk_stops_at_unprofitable_level():
    k = [Level(0.40, 10), Level(0.55, 1000)]
    p = [Level(0.50, 1000)]
    k_fills, p_fills = walk(k, p, 0.07, 1.0, 0.0695)
    assert k_fills == [(0.40, 10)]
    assert p_fills == [(0.50, 10)]


def test_walk_respects_max_stake():
    k = [Level(0.40, 1000)]
    p = [Level(0.50, 1000)]
    k_fills, _ = walk(k, p, 0.07, 1.0, 0.0695, max_stake=90)
    assert sum(q for _, q in k_fills) == 100  # 100 * 0.90 = $90


def test_walk_multiple_levels():
    k = [Level(0.30, 5), Level(0.35, 5)]
    p = [Level(0.40, 3), Level(0.45, 20)]
    k_fills, p_fills = walk(k, p, 0.07, 1.0, 0.0695)
    assert sum(q for _, q in k_fills) == sum(q for _, q in p_fills) == 10
    assert k_fills[0] == (0.30, 3)


def test_empty_books():
    o = evaluate(book([], []), book([], []), kalshi_id="K", pmus_id="P", inverted=False, close_time=CLOSE, now=NOW)
    assert o is None
