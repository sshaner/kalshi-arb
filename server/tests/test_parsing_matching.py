import json
from pathlib import Path

from arb import matcher
from arb.db import Db
from arb.paper import leg_payout, settle, summary
from arb.venues import kalshi, polymarket_us

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_kalshi_orderbook_inverts_bids():
    b = kalshi.parse_orderbook(load("kalshi_orderbook.json"))
    # best NO bid 0.78 -> YES ask 0.22; best YES bid 0.09 -> NO ask 0.91
    assert b.yes_asks[0].price == 0.22
    assert b.no_asks[0].price == 0.91
    assert all(b.yes_asks[i].price <= b.yes_asks[i + 1].price for i in range(len(b.yes_asks) - 1))


def test_pmus_book():
    b = polymarket_us.parse_book(load("pmus_book.json"))
    assert b.yes_asks[0].price == 0.089 and b.yes_asks[0].size == 137
    assert b.no_asks[0].price == round(1 - 0.065, 4)


def test_kalshi_event_parse():
    ev = load("kalshi_events.json")["events"][0]
    ms = kalshi.parse_event(ev, {ev["series_ticker"]: 0.5})
    assert ms and ms[0].venue == "kalshi"
    assert ms[0].fee_multiplier == 0.5
    assert ms[0].event_title == ev["title"]


def test_pmus_event_parse():
    ev = load("pmus_events.json")["events"][0]
    ms = polymarket_us.parse_event(ev)
    assert ms and ms[0].venue == "pmus"
    assert ms[0].url.endswith(ev["slug"])
    assert ms[0].event_title == "National League Champion"


def test_matcher_finds_same_event():
    k = [
        {"market_id": "K1", "event_title": "National League champion 2026", "title": "Atlanta Braves",
         "event_time": "2026-10-20T00:00:00Z", "close_time": "2026-10-25T00:00:00Z", "yes_ask": 0.08, "no_ask": 0.93},
        {"market_id": "K2", "event_title": "Super Bowl champion", "title": "Kansas City",
         "event_time": "2027-02-10T00:00:00Z", "close_time": "2027-02-10T00:00:00Z", "yes_ask": 0.2, "no_ask": 0.81},
    ]
    p = [{"market_id": "P1", "event_title": "National League Champion", "title": "Atlanta Braves",
          "event_time": "2026-10-20T23:59:00Z", "close_time": "2026-11-06T21:20:09Z", "yes_ask": 0.089, "no_ask": 0.935}]
    out = matcher.suggest(k, p, min_score=80, window_days=7, skip=set())
    assert [(a, b) for a, b, *_ in out] == [("K1", "P1")]
    assert out[0][3] == round(0.08 + 0.935, 4)
    assert matcher.suggest(k, p, min_score=80, window_days=7, skip={("K1", "P1")}) == []


def test_matcher_date_window_excludes():
    k = [{"market_id": "K1", "event_title": "Lakers vs Celtics", "title": "Lakers",
          "event_time": "2026-11-01T00:00:00Z", "close_time": "2026-11-01T00:00:00Z", "yes_ask": 0.5, "no_ask": 0.5}]
    p = [{"market_id": "P1", "event_title": "Lakers vs Celtics", "title": "Lakers",
          "event_time": "2026-12-20T00:00:00Z", "close_time": "2026-12-20T00:00:00Z", "yes_ask": 0.5, "no_ask": 0.5}]
    assert matcher.suggest(k, p, min_score=80, window_days=3, skip=set()) == []


def test_paper_settlement(tmp_path):
    db = Db(str(tmp_path / "t.db"))
    pid = db.x("""INSERT INTO paper_positions (pair_id, contracts, k_side, k_avg, k_cost, k_fee,
                  p_side, p_avg, p_cost, p_fee, opened_at) VALUES (1, 100, 'yes', .4, 40, 1.68, 'no', .5, 50, 1.74, 0)""")
    pos = db.one("SELECT * FROM paper_positions WHERE id = ?", (pid,))
    res = settle(db, pos, k_yes=1.0, p_yes=1.0)  # consistent: Kalshi YES wins, PM NO loses
    assert res["payout"] == 100 and not res["divergent"]
    assert res["pnl"] == round(100 - 93.42, 4)
    s = summary(db)
    assert s["settled_count"] == 1 and s["divergent_count"] == 0


def test_paper_divergent(tmp_path):
    db = Db(str(tmp_path / "t.db"))
    pid = db.x("""INSERT INTO paper_positions (pair_id, contracts, k_side, k_avg, k_cost, k_fee,
                  p_side, p_avg, p_cost, p_fee, opened_at) VALUES (1, 10, 'yes', .4, 4, .17, 'no', .5, 5, .18, 0)""")
    pos = db.one("SELECT * FROM paper_positions WHERE id = ?", (pid,))
    res = settle(db, pos, k_yes=0.0, p_yes=1.0)  # both legs lose
    assert res["divergent"] and res["payout"] == 0


def test_leg_payout_split():
    assert leg_payout("yes", 0.5, 10) == 5
    assert leg_payout("no", 0.0, 10) == 10


def test_matcher_skips_unquoted():
    k = [{"market_id": "K1", "event_title": "Lakers vs Celtics", "title": "Lakers", "yes_ask": 0.0, "no_ask": 1.0}]
    p = [{"market_id": "P1", "event_title": "Lakers vs Celtics", "title": "Lakers", "yes_ask": 0.5, "no_ask": 0.5}]
    assert matcher.suggest(k, p, min_score=80, window_days=3, skip=set()) == []


def test_numbers_and_qualifiers():
    assert matcher.numbers("Over 26.5 points") == matcher.numbers("over 26.50 total points")
    assert matcher.numbers("Over 26.5") != matcher.numbers("Over 57.5")
    assert matcher.numbers("Champion 2026") == frozenset()
    assert matcher.qualifiers("1st Half Total") != matcher.qualifiers("Total")
    assert matcher.qualifiers("Army vs Louisiana Tech: Spread") == matcher.qualifiers("Army vs. Louisiana Tech")
    assert matcher.qualifiers("NBA Finals") == matcher.qualifiers("NBA Final")


def test_matcher_rejects_different_lines():
    base = {"event_title": "BYU vs TCU", "event_time": "2026-10-04T00:00:00Z", "close_time": "2026-10-04T00:00:00Z",
            "yes_ask": 0.5, "no_ask": 0.5}
    k = [{**base, "market_id": "K1", "title": "Over 26.5 points"}, {**base, "market_id": "K2", "title": "Over 57.5 points"}]
    p = [{**base, "market_id": "P1", "event_title": "BYU vs. TCU", "title": "Over 57.5 points"}]
    out = matcher.suggest(k, p, min_score=80, window_days=3, skip=set())
    assert [(a, b) for a, b, *_ in out] == [("K2", "P1")]
    assert out[0][4] is False


def test_matcher_drops_implausible_gap():
    base = {"event_title": "Golf Championship", "event_time": "2026-10-04T00:00:00Z", "close_time": "2026-10-04T00:00:00Z"}
    k = [{**base, "market_id": "K1", "title": "Brandon Stone", "yes_ask": 0.005, "no_ask": 0.996}]
    p = [{**base, "market_id": "P1", "title": "Brandon Stone", "yes_ask": 0.99, "no_ask": 0.006}]
    assert matcher.suggest(k, p, min_score=80, window_days=3, skip=set()) == []


H2H = {"event_title": "USC vs. Penn State", "event_time": "2026-10-04T00:00:00Z", "close_time": "2026-10-04T00:00:00Z"}


def test_head_to_head_same_and_inverted():
    k = [{**H2H, "event_title": "USC vs Penn State", "market_id": "K-USC", "title": "USC", "yes_ask": 0.40, "no_ask": 0.62},
         {**H2H, "event_title": "USC vs Penn State", "market_id": "K-PSU", "title": "Penn State", "yes_ask": 0.61, "no_ask": 0.41}]
    p = [{**H2H, "market_id": "P1", "title": "USC", "alt_title": "Penn State", "yes_ask": 0.41, "no_ask": 0.60}]
    out = {a: inv for a, b, _, _, inv in matcher.suggest(k, p, min_score=80, window_days=3, skip=set())}
    assert out == {"K-USC": False, "K-PSU": True}


def test_opposite_team_without_alt_is_rejected():
    k = [{**H2H, "market_id": "K-PSU", "title": "Penn State", "yes_ask": 0.6, "no_ask": 0.42}]
    p = [{**H2H, "market_id": "P1", "title": "USC (Reg. Time)", "alt_title": "", "yes_ask": 0.41, "no_ask": 0.6}]
    assert matcher.suggest(k, p, min_score=80, window_days=3, skip=set()) == []


def test_pmus_head_to_head_parse():
    ev = {"title": "USC vs. Penn State", "slug": "usc-psu", "markets": [{
        "slug": "m1", "active": True, "closed": False, "status": "MARKET_STATUS_OPEN", "title": "USC vs Penn State",
        "outcomes": '["USC","Penn State"]',
        "marketSides": [{"description": "Trojans", "long": True, "team": {"name": "USC"}},
                        {"description": "Nittany Lions", "long": False, "team": {"name": "Penn State"}}]}, {
        "slug": "m2", "active": True, "closed": False, "status": "MARKET_STATUS_OPEN", "title": "USC (Reg. Time)",
        "outcomes": '["Yes","No"]',
        "marketSides": [{"description": "Yes", "long": True, "team": {"name": "USC"}},
                        {"description": "No", "long": False, "team": {"name": "USC"}}]}]}
    ms = {m.market_id: m for m in polymarket_us.parse_event(ev)}
    assert (ms["m1"].title, ms["m1"].alt_title) == ("USC", "Penn State")
    assert (ms["m2"].title, ms["m2"].alt_title) == ("USC (Reg. Time)", "")


def test_prop_kind():
    assert matcher.prop_kind("Texas wins by over 20.5 points") == ("spread",)
    assert matcher.prop_kind("Kyrian Jacquet -1.5 games") == ("spread",)
    assert matcher.prop_kind("Over 20.5 total points") == ("total", "game")
    assert matcher.prop_kind("Indiana over 30.5 points") == ("total", "team")
    assert matcher.prop_kind("UTSA over 4.5 total touchdowns")[:2] == ("total", "team")
    assert matcher.prop_kind("Tulane") == ("outcome",)


def test_spread_vs_total_rejected():
    base = {"event_title": "Texas vs Oklahoma", "event_time": "2026-10-04T00:00:00Z",
            "close_time": "2026-10-04T00:00:00Z", "yes_ask": 0.5, "no_ask": 0.52}
    k = [{**base, "market_id": "K1", "title": "Texas wins by over 20.5 points"}]
    p = [{**base, "market_id": "P1", "event_title": "Texas vs. Oklahoma", "title": "Over 20.5 total points"}]
    assert matcher.suggest(k, p, min_score=80, window_days=3, skip=set()) == []
    p[0]["title"] = "Texas wins by over 20.5 points"
    assert len(matcher.suggest(k, p, min_score=80, window_days=3, skip=set())) == 1


def test_event_numbers_must_match():
    base = {"event_time": "2026-10-04T00:00:00Z", "close_time": "2026-10-04T00:00:00Z", "yes_ask": 0.5, "no_ask": 0.52}
    k = [{**base, "market_id": "K1", "event_title": "Top Fantasy QB", "title": "Sam Darnold"}]
    p = [{**base, "market_id": "P1", "event_title": "Top 5 QB Fantasy Football Weeks 1-18", "title": "Sam Darnold"}]
    assert matcher.suggest(k, p, min_score=60, window_days=3, skip=set()) == []


def test_flipped_spread_market_is_inverted():
    base = {"event_title": "Washington vs USC", "event_time": "2026-10-04T00:00:00Z",
            "close_time": "2026-10-04T00:00:00Z"}
    k = [{**base, "market_id": "K1", "title": "USC wins by over 5.5 points", "yes_ask": 0.20, "no_ask": 0.81}]
    p = [{**base, "market_id": "P1", "event_title": "Washington vs. USC", "title": "USC wins by over 5.5 points",
          "flipped": True, "yes_ask": 0.845, "no_ask": 0.17}]
    out = matcher.suggest(k, p, min_score=80, window_days=3, skip=set())
    assert len(out) == 1 and out[0][4] is True
    assert out[0][3] == round(min(0.20 + 0.845, 0.81 + 0.17), 4)


def test_pmus_plus_line_spread_parse_flipped():
    ev = {"title": "Washington vs. USC", "slug": "wash-usc", "markets": [{
        "slug": "pos", "active": True, "closed": False, "status": "MARKET_STATUS_OPEN",
        "title": "USC wins by over 5.5 points", "outcomes": '["+5.50","-5.50"]',
        "marketSides": [{"description": "+5.50", "long": True, "team": {"name": "Washington"}},
                        {"description": "-5.50", "long": False, "team": {"name": "USC"}}]}, {
        "slug": "neg", "active": True, "closed": False, "status": "MARKET_STATUS_OPEN",
        "title": "USC wins by over 1.5 points", "outcomes": '["-1.50","+1.50"]',
        "marketSides": [{"description": "-1.50", "long": True, "team": {"name": "USC"}},
                        {"description": "+1.50", "long": False, "team": {"name": "Washington"}}]}]}
    ms = {m.market_id: m for m in polymarket_us.parse_event(ev)}
    assert ms["pos"].flipped is True and ms["neg"].flipped is False
    assert ms["pos"].alt_title == ""  # spread sides are numbers, not names


def test_entity_distinguishers():
    assert not matcher.entities_agree(matcher.entity("Louisiana Tech"), matcher.entity("Louisiana"))
    assert not matcher.entities_agree(matcher.entity("Oklahoma St."), matcher.entity("Oklahoma"))
    assert matcher.entities_agree(matcher.entity("Oklahoma St."), matcher.entity("Oklahoma State"))
    assert matcher.entities_agree(matcher.entity("Texas A&M"), matcher.entity("Texas A&M Aggies"))
    assert matcher.entities_agree(matcher.entity("Charlton"), matcher.entity("Charlton Athletic FC"))
    assert not matcher.entities_agree(matcher.entity("Malta wins 2-0"), matcher.entity("AND wins 2-0"))


def test_method_of_victory_not_moneyline():
    assert matcher.qualifiers("Method of Victory | Natalia Silva by Decision") != matcher.qualifiers("Natalia Silva")
    assert matcher.qualifiers("Heisman Trophy Finalists") != matcher.qualifiers("Heisman Trophy Winner")
    assert matcher.qualifiers("Headline: Exactly 0.3%") != matcher.qualifiers("Above 0.3%")


def test_same_matchup():
    assert matcher.event_sides("Army vs Louisiana Tech: Spread") == ["army", "louisiana tech"]
    assert matcher.same_matchup("Army vs Louisiana Tech", "Louisiana Tech vs. Army")
    assert not matcher.same_matchup("Army vs Louisiana Tech", "Louisiana vs. Louisiana Tech")
    assert matcher.same_matchup("EPL Golden Boot", "English Premier League Golden Boot")


def test_fighter_specific_vs_generic_rejected():
    base = {"event_time": "2026-10-04T00:00:00Z", "close_time": "2026-10-04T00:00:00Z", "yes_ask": 0.2, "no_ask": 0.82}
    k = [{**base, "market_id": "K1", "event_title": "Natalia Silva vs Cong Wang: Method of Victory",
          "title": "Natalia Silva by KO/TKO/DQ"}]
    p = [{**base, "market_id": "P1", "event_title": "Natalia Silva vs. Cong Wang", "title": "KO/TKO/DQ method"}]
    assert matcher.suggest(k, p, min_score=80, window_days=3, skip=set()) == []


def test_draw_named_none_rejected():
    assert not matcher.entities_agree(matcher.entity("Iceland"), matcher.entity("None"))
    assert not matcher.entities_agree(matcher.entity("Florida"), matcher.entity("South Florida"))


def test_match_details_orientations():
    base = {"event_title": "Washington vs USC", "event_time": "2026-10-04T00:00:00Z", "close_time": "2026-10-05T00:00:00Z"}
    k = {**base, "title": "USC wins by over 5.5 points"}
    flipped = {**base, "event_title": "Washington vs. USC", "title": "USC wins by over 5.5 points", "flipped": True}
    d = matcher.match_details(k, flipped)
    assert d["orientation"] == "inverse_flipped_spread" and d["numbers"] == ["5.5"] and d["prop_kind"] == ["spread"]
    assert d["date_gap_days"] == 0.0
    h2h = {**base, "event_title": "USC vs. Penn State", "title": "USC", "alt_title": "Penn State"}
    kp = {**base, "event_title": "USC vs Penn State", "title": "Penn State"}
    assert matcher.match_details(kp, h2h)["orientation"] == "inverse_head_to_head"
    assert matcher.match_details({**kp, "title": "USC"}, h2h)["orientation"] == "same"
