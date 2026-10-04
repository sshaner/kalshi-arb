"""The three background loops: discovery, price scanning, settlement."""
import asyncio
import json
import logging
import time
from datetime import datetime

import httpx

from . import arb_engine, config, matcher, paper
from .db import Db
from .models import KALSHI, PMUS
from .push import Pusher
from .venues.kalshi import KalshiClient
from .venues.polymarket_us import PolymarketUSClient

log = logging.getLogger(__name__)


def _past(iso: str | None) -> bool:
    d = arb_engine.days_until(iso or "")
    return d is not None and d <= 0


def _in_quiet_hours(s: dict) -> bool:
    start, end = s.get("quiet_hours_start"), s.get("quiet_hours_end")
    if start is None or end is None:
        return False
    h = datetime.now().hour
    return start <= h < end if start <= end else (h >= start or h < end)


class Scanner:
    def __init__(self, db: Db, pusher: Pusher, http: httpx.AsyncClient | None = None):
        self.db = db
        self.pusher = pusher
        self.http = http or httpx.AsyncClient(headers={"User-Agent": "kalshi-arb/1.0"})
        self.kalshi = KalshiClient(self.http)
        self.pmus = PolymarketUSClient(self.http)
        self.discovery_now = asyncio.Event()
        self.status: dict = {
            "started_at": time.time(),
            "discovery": {"last_run": None, "duration": None, "kalshi_markets": 0, "pmus_markets": 0,
                          "new_candidates": 0, "error": None, "running": False},
            "prices": {"last_run": None, "duration": None, "pairs": 0, "active_opportunities": 0, "error": None},
            "settlement": {"last_run": None, "settled": 0, "error": None},
        }

    # -- discovery -----------------------------------------------------------
    async def discover(self) -> None:
        st = self.status["discovery"]
        st["running"] = True
        t0 = time.time()
        try:
            k_res, p_res = await asyncio.gather(self.kalshi.fetch_markets(), self.pmus.fetch_markets(),
                                                return_exceptions=True)
            errors = []
            if isinstance(k_res, Exception):
                errors.append(f"kalshi: {k_res!r}")
            else:
                self.db.upsert_markets(KALSHI, k_res)
                st["kalshi_markets"] = len(k_res)
            if isinstance(p_res, Exception):
                errors.append(f"pmus: {p_res!r}")
            else:
                self.db.upsert_markets(PMUS, p_res)
                st["pmus_markets"] = len(p_res)

            s = self.db.settings()
            skip = self.db.known_candidate_keys()
            suggestions = await asyncio.to_thread(
                matcher.suggest,
                self.db.open_markets(KALSHI), self.db.open_markets(PMUS),
                min_score=float(s["match_min_score"]), window_days=float(s["match_date_window_days"]), skip=skip,
            )
            self.db.add_candidates(suggestions)
            st["new_candidates"] = len(suggestions)
            st["error"] = "; ".join(errors) or None
            log.info("discovery: kalshi=%s pmus=%s new_candidates=%s", st["kalshi_markets"], st["pmus_markets"],
                     len(suggestions))
        except Exception as e:  # keep the loop alive
            log.exception("discovery failed")
            st["error"] = repr(e)
        finally:
            st["running"] = False
            st["last_run"] = time.time()
            st["duration"] = round(time.time() - t0, 1)

    async def discovery_loop(self) -> None:
        while True:
            await self.discover()
            try:
                await asyncio.wait_for(self.discovery_now.wait(), timeout=config.DISCOVERY_INTERVAL)
            except asyncio.TimeoutError:
                pass
            self.discovery_now.clear()

    # -- prices --------------------------------------------------------------
    async def scan_pair(self, pair: dict, s: dict) -> bool:
        k_m = self.db.market(KALSHI, pair["kalshi_id"]) or {}
        p_m = self.db.market(PMUS, pair["pmus_id"]) or {}
        close_time = min(filter(None, [k_m.get("close_time"), p_m.get("close_time")]), default="")
        if _past(close_time):
            return False
        try:
            k_book, p_book = await asyncio.gather(self.kalshi.fetch_book(pair["kalshi_id"]),
                                                  self.pmus.fetch_book(pair["pmus_id"]))
        except Exception as e:
            self.db.x("UPDATE pairs SET last_error = ?, last_checked = ? WHERE id = ?", (repr(e)[:300], time.time(), pair["id"]))
            return False
        now = time.time()
        self.db.x("UPDATE pairs SET last_error = NULL, last_checked = ? WHERE id = ?", (now, pair["id"]))
        if now - min(k_book.fetched_at, p_book.fetched_at) > config.BOOK_MAX_AGE:
            return False

        opp = arb_engine.evaluate(
            k_book, p_book,
            kalshi_id=pair["kalshi_id"], pmus_id=pair["pmus_id"], inverted=bool(pair["inverted"]),
            close_time=close_time, k_coef=config.KALSHI_FEE_COEF, k_mult=float(k_m.get("fee_multiplier") or 1),
            p_coef=config.PMUS_FEE_COEF, max_stake=float(s["paper_max_stake"]) or None,
        )
        ok = (opp is not None
              and opp.edge_cents >= float(s["min_edge_cents"])
              and opp.profit >= float(s["min_profit_dollars"])
              and (not s["min_annualized"] or (opp.annualized or 0) >= float(s["min_annualized"])))
        if not ok:
            self.db.x("UPDATE opportunities SET active = 0 WHERE pair_id = ? AND active = 1", (pair["id"],))
            return False

        existing = self.db.one("SELECT id FROM opportunities WHERE pair_id = ? AND direction = ? AND active = 1",
                               (pair["id"], opp.direction))
        fields = (opp.kalshi.side, opp.kalshi.avg_price, opp.kalshi.cost, opp.kalshi.fee,
                  opp.pmus.side, opp.pmus.avg_price, opp.pmus.cost, opp.pmus.fee,
                  opp.contracts, opp.cost, opp.fees, opp.profit, opp.edge_cents, opp.roi, opp.annualized,
                  json.dumps(k_book.to_dict()), json.dumps(p_book.to_dict()))
        # Only one direction can be live per pair; retire the other.
        self.db.x("UPDATE opportunities SET active = 0 WHERE pair_id = ? AND direction != ? AND active = 1",
                  (pair["id"], opp.direction))
        if existing:
            self.db.x("""UPDATE opportunities SET k_side=?, k_avg=?, k_cost=?, k_fee=?, p_side=?, p_avg=?, p_cost=?, p_fee=?,
                         contracts=?, cost=?, fees=?, profit=?, edge_cents=?, roi=?, annualized=?, k_book=?, p_book=?,
                         last_seen=? WHERE id=?""", (*fields, now, existing["id"]))
            return True

        opp_id = self.db.x("""INSERT INTO opportunities (k_side, k_avg, k_cost, k_fee, p_side, p_avg, p_cost, p_fee,
                         contracts, cost, fees, profit, edge_cents, roi, annualized, k_book, p_book,
                         pair_id, direction, first_seen, last_seen)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                           (*fields, pair["id"], opp.direction, now, now))
        paper.open_position(self.db, opp_id, pair["id"], opp)
        await self._alert(opp_id, pair, opp, k_m, s)
        return True

    async def _alert(self, opp_id: int, pair: dict, opp, k_m: dict, s: dict) -> None:
        cooldown = float(s["alert_cooldown_min"]) * 60
        recent = self.db.one("SELECT MAX(first_seen) AS t FROM opportunities WHERE pair_id = ? AND alerted = 1",
                             (pair["id"],))
        if (recent and recent["t"] and time.time() - recent["t"] < cooldown) or _in_quiet_hours(s):
            return
        title = f"{k_m.get('event_title', '')} — {k_m.get('title', '')}".strip(" —")[:120]
        ann = f", {opp.annualized * 100:.0f}%/yr" if opp.annualized else ""
        body = (f"Kalshi {opp.kalshi.side.upper()} {opp.kalshi.avg_price * 100:.1f}¢ + "
                f"PM US {opp.pmus.side.upper()} {opp.pmus.avg_price * 100:.1f}¢ → "
                f"{opp.edge_cents:.1f}¢/ct, ${opp.profit:.2f} on {opp.contracts:.0f}{ann}")
        self.db.x("UPDATE opportunities SET alerted = 1 WHERE id = ?", (opp_id,))
        await self.pusher.send(title, body, {"opp_id": opp_id})

    async def scan_once(self) -> None:
        st = self.status["prices"]
        s = self.db.settings()
        if not s["scan_enabled"]:
            return
        t0 = time.time()
        pairs = self.db.active_pairs()
        # Cheap pass: bulk top-of-book for every pair; only pairs that could clear $1 get full books.
        k_quotes, p_quotes = await asyncio.gather(
            self.kalshi.fetch_quotes(sorted({p["kalshi_id"] for p in pairs})),
            self.pmus.fetch_quotes(sorted({p["pmus_id"] for p in pairs})),
        )
        live = {r["pair_id"] for r in self.db.q("SELECT DISTINCT pair_id FROM opportunities WHERE active = 1")}
        deep = []
        for p in pairs:
            ky, kn = k_quotes.get(p["kalshi_id"], (None, None))
            py, pn = p_quotes.get(p["pmus_id"], (None, None))
            est = matcher.est_cost({"yes_ask": ky, "no_ask": kn}, {"yes_ask": py, "no_ask": pn}, bool(p["inverted"]))
            if p["id"] in live or (est is not None and est < 1.0):
                deep.append(p)
        results = await asyncio.gather(*(self.scan_pair(p, s) for p in deep), return_exceptions=True)
        now = time.time()
        self.db.x("UPDATE pairs SET last_checked = ? WHERE status = 'active' AND paused = 0 AND last_error IS NULL",
                  (now,))
        errs = [r for r in results if isinstance(r, Exception)]
        for e in errs:
            log.warning("scan_pair error: %r", e)
        st.update(last_run=now, duration=round(now - t0, 2), pairs=len(pairs), deep_scanned=len(deep),
                  active_opportunities=sum(1 for r in results if r is True),
                  error=repr(errs[0]) if errs else None)

    async def price_loop(self) -> None:
        while True:
            try:
                await self.scan_once()
            except Exception as e:
                log.exception("price loop failed")
                self.status["prices"]["error"] = repr(e)
            await asyncio.sleep(config.PRICE_INTERVAL)

    # -- settlement ----------------------------------------------------------
    async def settle_once(self) -> None:
        st = self.status["settlement"]
        settled = 0
        pair_ids = {r["pair_id"] for r in self.db.q("SELECT DISTINCT pair_id FROM paper_positions WHERE status = 'open'")}
        pair_ids |= {r["id"] for r in self.db.q("SELECT id FROM pairs WHERE status = 'active'")}
        for pid in pair_ids:
            pair = self.db.one("SELECT * FROM pairs WHERE id = ?", (pid,))
            if not pair:
                continue
            k_m = self.db.market(KALSHI, pair["kalshi_id"]) or {}
            p_m = self.db.market(PMUS, pair["pmus_id"]) or {}
            if not (_past(k_m.get("close_time")) or _past(p_m.get("close_time")) or not k_m.get("open") or not p_m.get("open")):
                continue
            try:
                k_yes, p_yes = await asyncio.gather(self.kalshi.fetch_result(pair["kalshi_id"]),
                                                    self.pmus.fetch_result(pair["pmus_id"]))
            except Exception as e:
                st["error"] = repr(e)
                continue
            if k_yes is None or p_yes is None:
                continue
            for pos in self.db.q("SELECT * FROM paper_positions WHERE pair_id = ? AND status = 'open'", (pid,)):
                res = paper.settle(self.db, pos, k_yes, p_yes)
                settled += 1
                if res["divergent"]:
                    await self.pusher.send("Divergent resolution",
                                           f"{k_m.get('title', pair['kalshi_id'])}: venues disagreed, P&L ${res['pnl']:.2f}",
                                           {"pair_id": pid})
            self.db.x("UPDATE pairs SET status = 'settled' WHERE id = ?", (pid,))
            self.db.x("UPDATE opportunities SET active = 0 WHERE pair_id = ?", (pid,))
        st.update(last_run=time.time(), settled=settled)

    async def settlement_loop(self) -> None:
        while True:
            try:
                await self.settle_once()
            except Exception as e:
                log.exception("settlement loop failed")
                self.status["settlement"]["error"] = repr(e)
            await asyncio.sleep(config.SETTLEMENT_INTERVAL)
