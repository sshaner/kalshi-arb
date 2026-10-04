"""The three background loops: discovery, price scanning, settlement."""
import asyncio
import json
import logging
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime

import httpx

from . import arb_engine, config, matcher, paper, rating
from .db import Db
from .models import KALSHI, PMUS
from .push import Pusher
from .venues.kalshi import KalshiClient
from .venues.polymarket_us import PolymarketUSClient

log = logging.getLogger(__name__)


def _match_in_process(db_path: str, min_score: float, window_days: float) -> list:
    """Runs in a child process: its own DB connection, its own GIL."""
    db = Db(db_path)
    return matcher.suggest(db.open_markets(KALSHI), db.open_markets(PMUS), min_score=min_score,
                           window_days=window_days, skip=db.known_candidate_keys())


def _rate_in_process(db_path: str) -> int:
    """Re-rate every pending candidate against the latest prices (child process; writes its own results)."""
    db = Db(db_path)
    rows = db.q("""SELECT c.id, c.score, c.inverted, k.title AS k_title, k.event_title AS k_event,
                          k.event_time AS k_event_time, k.close_time AS k_close, k.yes_ask AS k_yes, k.no_ask AS k_no,
                          k.fee_multiplier AS k_mult, p.title AS p_title, p.event_title AS p_event,
                          p.alt_title AS p_alt, p.flipped AS p_flipped, p.event_time AS p_event_time,
                          p.close_time AS p_close, p.yes_ask AS p_yes, p.no_ask AS p_no
                   FROM candidates c
                   JOIN markets k ON k.venue = 'kalshi' AND k.market_id = c.kalshi_id
                   JOIN markets p ON p.venue = 'pmus' AND p.market_id = c.pmus_id
                   WHERE c.status = 'pending'""")
    updates, stale = [], []
    for r in rows:
        k = {"title": r["k_title"], "event_title": r["k_event"], "event_time": r["k_event_time"],
             "close_time": r["k_close"], "yes_ask": r["k_yes"], "no_ask": r["k_no"], "fee_multiplier": r["k_mult"]}
        p = {"title": r["p_title"], "event_title": r["p_event"], "alt_title": r["p_alt"], "flipped": r["p_flipped"],
             "event_time": r["p_event_time"], "close_time": r["p_close"], "yes_ask": r["p_yes"], "no_ask": r["p_no"]}
        if not matcher.still_compatible(k, p):
            stale.append(r["id"])
            continue
        rated = rating.rate_candidate(k, p, r["score"] or 0, bool(r["inverted"]))
        rated["rating_reasons"] = json.dumps(rated["rating_reasons"])
        updates.append({**rated, "id": r["id"]})
    for i in range(0, len(updates), 2000):
        db.update_ratings(updates[i:i + 2000])
    if stale:
        # Hidden from Review, kept for the record (and so discovery never re-suggests them).
        db._tx(lambda c: c.executemany(
            "UPDATE candidates SET status = 'auto_rejected', decided_at = ? WHERE id = ?",
            [(time.time(), i) for i in stale]))
        log.info("auto-rejected %d stale suggestions", len(stale))
    return len(updates)


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
                await asyncio.to_thread(self.db.upsert_markets, KALSHI, k_res)
                st["kalshi_markets"] = len(k_res)
            if isinstance(p_res, Exception):
                errors.append(f"pmus: {p_res!r}")
            else:
                await asyncio.to_thread(self.db.upsert_markets, PMUS, p_res)
                st["pmus_markets"] = len(p_res)

            s = self.db.settings()
            # The matcher is a CPU-bound Python loop; in a thread it starves API requests through the GIL
            # (Review took 6-8 s during discovery). A separate process keeps the API responsive.
            loop = asyncio.get_running_loop()
            with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn")) as pool:
                suggestions = await loop.run_in_executor(
                    pool, _match_in_process, self.db.path,
                    float(s["match_min_score"]), float(s["match_date_window_days"]))
                await asyncio.to_thread(self.db.add_candidates, suggestions)
                # Re-rate every pending pair against the prices just fetched (also a child process).
                st["rated"] = await loop.run_in_executor(pool, _rate_in_process, self.db.path)
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
        p_m = self.db.market(PMUS, pair["pmus_id"]) or {}
        cand = (self.db.one("SELECT score FROM candidates WHERE id = ?", (pair["candidate_id"],))
                if pair.get("candidate_id") else None)
        rated = rating.rate_opportunity(
            {"edge_cents": opp.edge_cents, "profit": opp.profit, "annualized": opp.annualized,
             "closes_at": min(filter(None, [k_m.get("close_time"), p_m.get("close_time")]), default=None)},
            matcher.match_details(k_m, p_m) if k_m and p_m else None, cand and cand["score"])
        title = (f"{rated['rating']}/10 {rated['rating_label']} arb: "
                 f"{k_m.get('event_title', '')} — {k_m.get('title', '')}").strip(" —")[:120]
        per_pair = (opp.cost + opp.fees) / opp.contracts * 100
        ann = f", ~{opp.annualized * 100:.0f}%/yr" if opp.annualized else ""
        body = (f"Buy {opp.kalshi.side.upper()} on Kalshi + {opp.pmus.side.upper()} on Polymarket US for "
                f"{per_pair:.1f}¢ per pair incl. fees → ${opp.profit:.2f} profit on {opp.contracts:.0f} contracts{ann}. "
                f"Tap for the walkthrough.")
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
