from arb import rating

PERFECT = {"numbers": ["44.5"], "qualifiers": [], "orientation": "same", "date_gap_days": 0.2, "event_similarity": 100}
BASE = {"event_title": "KC vs LV", "event_time": "2026-10-04T00:00:00Z", "close_time": "2026-10-05T00:00:00Z"}


def test_perfect_match_with_3c_after_fees_is_10():
    conf, _ = rating.confidence(PERFECT, 100)
    money, _ = rating.money_from_net(3.2)
    assert round(1 + 9 * conf * money) == 10


def test_perfect_match_without_gap_is_middling():
    k = {**BASE, "title": "Over 44.5 points", "yes_ask": 0.52, "no_ask": 0.50}
    p = {**BASE, "event_title": "KC vs. LV", "title": "Over 44.5 total points", "yes_ask": 0.52, "no_ask": 0.50}
    r = rating.rate_candidate(k, p, 100, False)
    assert 3 <= r["rating"] <= 5 and r["net_cents"] < 0 and r["kind"] == "total"


def test_real_gap_rates_high():
    k = {**BASE, "title": "Over 44.5 points", "yes_ask": 0.44, "no_ask": 0.58}
    p = {**BASE, "event_title": "KC vs. LV", "title": "Over 44.5 total points", "yes_ask": 0.58, "no_ask": 0.50}
    r = rating.rate_candidate(k, p, 100, False)
    assert r["net_cents"] > 2.5 and r["rating"] >= 9, r


def test_suspicious_gap_never_rates_high():
    k = {**BASE, "title": "Over 44.5 points", "yes_ask": 0.20, "no_ask": 0.81}
    p = {**BASE, "event_title": "KC vs. LV", "title": "Over 44.5 total points", "yes_ask": 0.85, "no_ask": 0.17}
    r = rating.rate_candidate(k, p, 100, False)
    assert r["rating"] <= 4 and any("mismatch" in x for x in r["rating_reasons"])


def test_weak_match_caps_rating_even_with_money():
    conf, _ = rating.confidence({**PERFECT, "numbers": [], "date_gap_days": 5, "event_similarity": 80}, 82)
    money, _ = rating.money_from_net(4)
    assert round(1 + 9 * conf * money) <= 3


def test_labels():
    assert [rating.label(n) for n in (10, 9, 8, 7, 6, 5, 4, 3, 2, 1)] == \
        ["Excellent", "Excellent", "Strong", "Strong", "Fair", "Fair", "Weak", "Weak", "Skip", "Skip"]


def test_slow_low_return_opportunity_is_downgraded():
    fast = rating.rate_opportunity({"edge_cents": 3, "profit": 10, "annualized": 2.0}, PERFECT, 100)
    slow = rating.rate_opportunity({"edge_cents": 3, "profit": 10, "annualized": 0.04,
                                    "closes_at": "2027-06-01T00:00:00Z"}, PERFECT, 100)
    assert fast["rating"] == 10 and slow["rating"] < fast["rating"]
