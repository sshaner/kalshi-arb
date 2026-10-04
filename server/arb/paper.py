"""Paper trading: record simulated fills when an opportunity appears, value them at settlement."""
import time

from .db import Db


def open_position(db: Db, opp_id: int, pair_id: int, o) -> int:
    return db.x(
        """INSERT INTO paper_positions (opportunity_id, pair_id, contracts,
               k_side, k_avg, k_cost, k_fee, p_side, p_avg, p_cost, p_fee, opened_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (opp_id, pair_id, o.contracts,
         o.kalshi.side, o.kalshi.avg_price, o.kalshi.cost, o.kalshi.fee,
         o.pmus.side, o.pmus.avg_price, o.pmus.cost, o.pmus.fee, time.time()),
    )


def leg_payout(side: str, yes_value: float, contracts: float) -> float:
    """yes_value is the YES settlement (1, 0, or a fraction for a split/void resolution)."""
    return contracts * (yes_value if side == "yes" else 1 - yes_value)


def settle(db: Db, pos: dict, k_yes: float, p_yes: float) -> dict:
    payout = (leg_payout(pos["k_side"], k_yes, pos["contracts"])
              + leg_payout(pos["p_side"], p_yes, pos["contracts"]))
    spent = pos["k_cost"] + pos["k_fee"] + pos["p_cost"] + pos["p_fee"]
    pnl = round(payout - spent, 4)
    # A hedged pair pays exactly `contracts`. Anything else means the venues disagreed.
    divergent = int(abs(payout - pos["contracts"]) > 1e-6)
    db.x("""UPDATE paper_positions SET status = 'settled', k_result = ?, p_result = ?, payout = ?, pnl = ?,
              divergent = ?, settled_at = ? WHERE id = ?""",
         (k_yes, p_yes, round(payout, 4), pnl, divergent, time.time(), pos["id"]))
    return {"payout": payout, "pnl": pnl, "divergent": bool(divergent)}


def summary(db: Db) -> dict:
    r = db.one("""SELECT
        COUNT(*) FILTER (WHERE status = 'open') AS open_count,
        COALESCE(SUM(k_cost + k_fee + p_cost + p_fee) FILTER (WHERE status = 'open'), 0) AS open_capital,
        COALESCE(SUM(contracts - (k_cost + k_fee + p_cost + p_fee)) FILTER (WHERE status = 'open'), 0) AS open_expected_pnl,
        COUNT(*) FILTER (WHERE status = 'settled') AS settled_count,
        COALESCE(SUM(pnl) FILTER (WHERE status = 'settled'), 0) AS realized_pnl,
        COALESCE(SUM(divergent) FILTER (WHERE status = 'settled'), 0) AS divergent_count
        FROM paper_positions""")
    return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in (r or {}).items()}
