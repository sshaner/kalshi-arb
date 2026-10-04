"""REST API for the iOS app. Every route requires `Authorization: Bearer <API_TOKEN>`."""
import json
import secrets
import time
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel

from . import arb_engine, config, matcher, paper, rating
from .models import KALSHI, PMUS


def _auth(authorization: str = Header(default="")) -> None:
    expected = config.API_TOKEN
    supplied = authorization.removeprefix("Bearer ").strip()
    if not expected or not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="unauthorized")


class ApproveBody(BaseModel):
    inverted: bool = False
    notes: str = ""


class PairPatch(BaseModel):
    paused: bool | None = None
    notes: str | None = None
    inverted: bool | None = None


class DeviceBody(BaseModel):
    token: str


def _market_view(m: dict | None) -> dict | None:
    if not m:
        return None
    out = {k: m.get(k) for k in ("venue", "market_id", "event_title", "title", "alt_title", "flipped", "close_time",
                                 "event_time", "url", "rules", "yes_ask", "no_ask", "open")}
    # SQLite stores these as 0/1; the app's JSON decoder needs real booleans.
    out["flipped"] = bool(out["flipped"])
    out["open"] = bool(out["open"])
    return out


def _top_size(book: dict, side: str) -> float | None:
    levels = book.get("yes_asks" if side == "yes" else "no_asks") or []
    return levels[0][1] if levels else None


def create_app(db, scanner, pusher) -> FastAPI:
    app = FastAPI(title="kalshi-arb", dependencies=[Depends(_auth)])
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    def details(k: dict | None, p: dict | None) -> dict | None:
        return matcher.match_details(k, p) if k and p else None

    def pair_view(p: dict) -> dict:
        k, pm = db.market(KALSHI, p["kalshi_id"]), db.market(PMUS, p["pmus_id"])
        return {**p, "inverted": bool(p["inverted"]), "paused": bool(p["paused"]),
                "kalshi": _market_view(k), "pmus": _market_view(pm), "match_details": details(k, pm)}

    def opp_view(o: dict, books: bool = False) -> dict:
        pair = db.one("SELECT * FROM pairs WHERE id = ?", (o["pair_id"],))
        out = {k: v for k, v in o.items() if k not in ("k_book", "p_book")}
        out["active"] = bool(o["active"])
        out["pair"] = pair_view(pair) if pair else None
        k_book, p_book = json.loads(o["k_book"] or "{}"), json.loads(o["p_book"] or "{}")
        # Depth at the best price on each leg's side: how many contracts are really available there.
        out["k_top_size"] = _top_size(k_book, o["k_side"])
        out["p_top_size"] = _top_size(p_book, o["p_side"])
        closes = [m["close_time"] for m in (out["pair"] or {}).values() if isinstance(m, dict) and m.get("close_time")]
        out["days_to_close"] = arb_engine.days_until(min(closes)) if closes else None
        cand = db.one("SELECT score FROM candidates WHERE id = ?", (pair["candidate_id"],)) if pair else None
        out.update(rating.rate_opportunity({**o, "closes_at": min(closes) if closes else None},
                                           (out["pair"] or {}).get("match_details"), cand and cand["score"]))
        if books:
            out["k_book"], out["p_book"] = k_book, p_book
        return out

    @app.get("/api/status")
    def status() -> dict:
        counts = db.one("""SELECT
            (SELECT COUNT(*) FROM candidates WHERE status = 'pending') AS pending_candidates,
            (SELECT COUNT(*) FROM pairs WHERE status = 'active') AS active_pairs,
            (SELECT COUNT(*) FROM opportunities WHERE active = 1) AS live_opportunities,
            (SELECT MAX(edge_cents) FROM opportunities WHERE active = 1) AS best_edge_cents,
            (SELECT COUNT(*) FROM devices) AS devices""")
        return {"server_time": time.time(), **scanner.status, "counts": counts, "paper": paper.summary(db),
                "push": {"enabled": pusher.enabled, "last_error": pusher.last_error},
                "settings": db.settings()}

    # -- opportunities -------------------------------------------------------
    @app.get("/api/opportunities")
    def opportunities(active: bool = True, limit: int = 100) -> list[dict]:
        rows = db.q("SELECT * FROM opportunities WHERE active = ? ORDER BY "
                    + ("profit DESC" if active else "last_seen DESC") + " LIMIT ?", (int(active), limit))
        views = [opp_view(o) for o in rows]
        return sorted(views, key=lambda v: -v["rating"]) if active else views

    @app.get("/api/opportunities/{opp_id}")
    def opportunity(opp_id: int) -> dict:
        o = db.one("SELECT * FROM opportunities WHERE id = ?", (opp_id,))
        if not o:
            raise HTTPException(404)
        return opp_view(o, books=True)

    # -- candidates ----------------------------------------------------------
    SORTS = {
        "rating": "c.rating IS NULL, c.rating DESC, c.net_cents DESC",
        "gap": "c.net_cents IS NULL, c.net_cents DESC, c.rating DESC",
        "closing": "c.closes_at IS NULL, c.closes_at ASC, c.rating DESC",
        "score": "c.score DESC, c.rating DESC",
    }

    def candidate_filter(status: str, min_rating: int, kind: str, orientation: str, has_gap: bool,
                         closes_within_days: float | None, q: str) -> tuple[str, list]:
        where, args = ["c.status = ?"], [status]
        if min_rating > 1:
            where.append("c.rating >= ?")
            args.append(min_rating)
        if kind in ("outcome", "spread", "total"):
            where.append("c.kind = ?")
            args.append(kind)
        if orientation in ("same", "inverse"):
            where.append("c.inverted = ?")
            args.append(1 if orientation == "inverse" else 0)
        if has_gap:
            where.append("c.net_cents > 0")
        if closes_within_days:
            cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + closes_within_days * 86400))
            where.append("c.closes_at IS NOT NULL AND c.closes_at <= ?")
            args.append(cutoff)
        if q.strip():
            like = f"%{q.strip()}%"
            where.append("(k.title LIKE ? OR k.event_title LIKE ? OR p.title LIKE ? OR p.event_title LIKE ?)")
            args += [like] * 4
        return " AND ".join(where), args

    FROM_CANDIDATES = """FROM candidates c
        LEFT JOIN markets k ON k.venue = 'kalshi' AND k.market_id = c.kalshi_id
        LEFT JOIN markets p ON p.venue = 'pmus' AND p.market_id = c.pmus_id"""

    @app.get("/api/candidates")
    def candidates(status: str = "pending", limit: int = 100, offset: int = 0, min_rating: int = 1,
                   kind: str = "any", orientation: str = "any", has_gap: bool = False,
                   closes_within_days: float | None = None, q: str = "", sort: str = "rating") -> list[dict]:
        where, args = candidate_filter(status, min_rating, kind, orientation, has_gap, closes_within_days, q)
        rows = db.q(f"SELECT c.* {FROM_CANDIDATES} WHERE {where} ORDER BY {SORTS.get(sort, SORTS['rating'])} "
                    "LIMIT ? OFFSET ?", (*args, min(limit, 500), offset))
        out = []
        for c in rows:
            k, pm = db.market(KALSHI, c["kalshi_id"]), db.market(PMUS, c["pmus_id"])
            out.append({**c, "inverted": bool(c["inverted"]), "kalshi": _market_view(k), "pmus": _market_view(pm),
                        "match_details": details(k, pm),
                        "rating_reasons": json.loads(c["rating_reasons"]) if c.get("rating_reasons") else []})
        return out

    @app.get("/api/candidates/count")
    def candidate_count(status: str = "pending", min_rating: int = 1, kind: str = "any", orientation: str = "any",
                        has_gap: bool = False, closes_within_days: float | None = None, q: str = "") -> dict:
        where, args = candidate_filter(status, min_rating, kind, orientation, has_gap, closes_within_days, q)
        matching = db.one(f"SELECT COUNT(*) AS n {FROM_CANDIDATES} WHERE {where}", tuple(args))["n"]
        total = db.one("SELECT COUNT(*) AS n FROM candidates WHERE status = ?", (status,))["n"]
        by_rating = {r["rating"]: r["n"] for r in db.q(
            "SELECT rating, COUNT(*) AS n FROM candidates WHERE status = ? GROUP BY rating", (status,))}
        return {"matching": matching, "total": total, "by_rating": by_rating}

    @app.post("/api/candidates/{cid}/approve")
    def approve(cid: int, body: ApproveBody) -> dict:
        c = db.one("SELECT * FROM candidates WHERE id = ?", (cid,))
        if not c:
            raise HTTPException(404)
        db.x("UPDATE candidates SET status = 'approved', decided_at = ? WHERE id = ?", (time.time(), cid))
        db.x("""INSERT INTO pairs (candidate_id, kalshi_id, pmus_id, inverted, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(kalshi_id, pmus_id) DO UPDATE SET inverted = excluded.inverted, notes = excluded.notes,
                  status = 'active', paused = 0""",
             (cid, c["kalshi_id"], c["pmus_id"], int(body.inverted), body.notes, time.time()))
        return pair_view(db.one("SELECT * FROM pairs WHERE kalshi_id = ? AND pmus_id = ?", (c["kalshi_id"], c["pmus_id"])))

    @app.post("/api/candidates/approve-bulk")
    def approve_bulk(min_score: float = 98.0) -> dict:
        """Approve every pending candidate at or above min_score, in its suggested orientation."""
        rows = db.q("SELECT * FROM candidates WHERE status = 'pending' AND score >= ?", (min_score,))
        for c in rows:
            approve(c["id"], ApproveBody(inverted=bool(c["inverted"]), notes=f"bulk-approved (score {c['score']})"))
        return {"approved": len(rows)}

    @app.post("/api/candidates/{cid}/reject")
    def reject(cid: int) -> dict:
        db.x("UPDATE candidates SET status = 'rejected', decided_at = ? WHERE id = ?", (time.time(), cid))
        return {"ok": True}

    @app.post("/api/discovery/run")
    def run_discovery() -> dict:
        scanner.discovery_now.set()
        return {"ok": True}

    # -- pairs ---------------------------------------------------------------
    @app.get("/api/pairs")
    def pairs(status: str = "active") -> list[dict]:
        return [pair_view(p) for p in db.q("SELECT * FROM pairs WHERE status = ? ORDER BY id DESC", (status,))]

    @app.patch("/api/pairs/{pid}")
    def patch_pair(pid: int, body: PairPatch) -> dict:
        p = db.one("SELECT * FROM pairs WHERE id = ?", (pid,))
        if not p:
            raise HTTPException(404)
        if body.paused is not None:
            db.x("UPDATE pairs SET paused = ? WHERE id = ?", (int(body.paused), pid))
            if body.paused:
                db.x("UPDATE opportunities SET active = 0 WHERE pair_id = ?", (pid,))
        if body.notes is not None:
            db.x("UPDATE pairs SET notes = ? WHERE id = ?", (body.notes, pid))
        if body.inverted is not None:
            db.x("UPDATE pairs SET inverted = ? WHERE id = ?", (int(body.inverted), pid))
            db.x("UPDATE opportunities SET active = 0 WHERE pair_id = ?", (pid,))
        return pair_view(db.one("SELECT * FROM pairs WHERE id = ?", (pid,)))

    @app.delete("/api/pairs/{pid}")
    def delete_pair(pid: int) -> dict:
        db.x("UPDATE pairs SET status = 'removed' WHERE id = ?", (pid,))
        db.x("UPDATE opportunities SET active = 0 WHERE pair_id = ?", (pid,))
        return {"ok": True}

    # -- paper ---------------------------------------------------------------
    @app.get("/api/paper/positions")
    def positions(status: str = "open", limit: int = 200) -> list[dict]:
        rows = db.q("SELECT * FROM paper_positions WHERE status = ? ORDER BY id DESC LIMIT ?", (status, limit))
        out = []
        for r in rows:
            pair = db.one("SELECT * FROM pairs WHERE id = ?", (r["pair_id"],))
            out.append({**r, "divergent": bool(r["divergent"]), "pair": pair_view(pair) if pair else None})
        return out

    @app.get("/api/paper/summary")
    def paper_summary() -> dict:
        return paper.summary(db)

    # -- settings / devices / push -------------------------------------------
    @app.get("/api/settings")
    def get_settings() -> dict:
        return db.settings()

    @app.put("/api/settings")
    def put_settings(changes: dict[str, Any]) -> dict:
        unknown = set(changes) - set(config.DEFAULT_SETTINGS)
        if unknown:
            raise HTTPException(400, f"unknown settings: {sorted(unknown)}")
        return db.update_settings(changes)

    @app.post("/api/devices")
    def register_device(body: DeviceBody) -> dict:
        token = body.token.strip().lower()
        if not token or not all(ch in "0123456789abcdef" for ch in token):
            raise HTTPException(400, "token must be hex")
        db.x("INSERT OR IGNORE INTO devices (token, created_at) VALUES (?, ?)", (token, time.time()))
        return {"ok": True}

    @app.post("/api/push/test")
    async def push_test() -> dict:
        sent = await pusher.send("Arb Scanner", "Test notification — push is working.", {})
        return {"sent": sent, "enabled": pusher.enabled, "last_error": pusher.last_error}

    return app
