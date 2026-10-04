"""SQLite storage. One connection shared by the asyncio process; all access goes through `Db`."""
import json
import sqlite3
import threading
import time
from typing import Any

from . import config
from .models import VenueMarket

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    venue TEXT NOT NULL,
    market_id TEXT NOT NULL,
    event_title TEXT,
    title TEXT,
    alt_title TEXT DEFAULT '',
    flipped INTEGER NOT NULL DEFAULT 0,
    close_time TEXT,
    event_time TEXT,
    url TEXT,
    rules TEXT,
    yes_ask REAL,
    no_ask REAL,
    fee_multiplier REAL DEFAULT 1,
    open INTEGER DEFAULT 1,
    updated_at REAL,
    PRIMARY KEY (venue, market_id)
);
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY,
    kalshi_id TEXT NOT NULL,
    pmus_id TEXT NOT NULL,
    score REAL,
    est_cost REAL,  -- top-of-book hedged cost at suggestion time (<1 = visible gap)
    inverted INTEGER NOT NULL DEFAULT 0,  -- suggested orientation: Kalshi YES = Polymarket NO
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    created_at REAL,
    decided_at REAL,
    UNIQUE (kalshi_id, pmus_id)
);
CREATE TABLE IF NOT EXISTS pairs (
    id INTEGER PRIMARY KEY,
    candidate_id INTEGER,
    kalshi_id TEXT NOT NULL,
    pmus_id TEXT NOT NULL,
    inverted INTEGER NOT NULL DEFAULT 0,
    notes TEXT DEFAULT '',
    paused INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',  -- active | settled | removed
    last_checked REAL,
    last_error TEXT,
    created_at REAL,
    UNIQUE (kalshi_id, pmus_id)
);
CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY,
    pair_id INTEGER NOT NULL,
    direction TEXT NOT NULL,
    k_side TEXT, k_avg REAL, k_cost REAL, k_fee REAL,
    p_side TEXT, p_avg REAL, p_cost REAL, p_fee REAL,
    contracts REAL, cost REAL, fees REAL, profit REAL,
    edge_cents REAL, roi REAL, annualized REAL,
    k_book TEXT, p_book TEXT,
    first_seen REAL, last_seen REAL,
    active INTEGER NOT NULL DEFAULT 1,
    alerted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_opp_active ON opportunities (active, pair_id);
CREATE TABLE IF NOT EXISTS paper_positions (
    id INTEGER PRIMARY KEY,
    opportunity_id INTEGER,
    pair_id INTEGER NOT NULL,
    contracts REAL,
    k_side TEXT, k_avg REAL, k_cost REAL, k_fee REAL,
    p_side TEXT, p_avg REAL, p_cost REAL, p_fee REAL,
    opened_at REAL,
    status TEXT NOT NULL DEFAULT 'open',  -- open | settled
    k_result REAL, p_result REAL,
    payout REAL, pnl REAL,
    divergent INTEGER DEFAULT 0,
    settled_at REAL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS devices (token TEXT PRIMARY KEY, created_at REAL, last_ok REAL);
"""


class Db:
    """Thread-safe SQLite access. Each thread gets its own connection: with WAL, the API's reads never wait
    for discovery's bulk writes (a single shared connection + lock stalled the app for seconds every 30 min)."""

    def __init__(self, path: str = config.DB_PATH):
        self.path = path
        self._local = threading.local()
        self.conn.executescript(SCHEMA)

    @property
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, isolation_level=None, timeout=30)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA busy_timeout=30000")
            c.execute("PRAGMA foreign_keys=ON")
            self._local.conn = c
        return c

    # -- generic -------------------------------------------------------------
    def q(self, sql: str, args: tuple = ()) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def x(self, sql: str, args: tuple = ()) -> int:
        return self.conn.execute(sql, args).lastrowid

    # -- settings ------------------------------------------------------------
    def settings(self) -> dict[str, Any]:
        out = dict(config.DEFAULT_SETTINGS)
        for r in self.q("SELECT key, value FROM settings"):
            out[r["key"]] = json.loads(r["value"])
        return out

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        for k, v in changes.items():
            if k in config.DEFAULT_SETTINGS:
                self.x("INSERT INTO settings (key, value) VALUES (?, ?) "
                       "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, json.dumps(v)))
        return self.settings()

    # -- markets -------------------------------------------------------------
    UPSERT_CHUNK = 5000

    def upsert_markets(self, venue: str, markets: list[VenueMarket]) -> None:
        """Bulk save in short transactions so other writers (price loop, API) never wait more than a moment.
        Markets not seen in this pass are marked closed at the end, so readers never see a half-updated state."""
        now = time.time()
        rows = [(m.venue, m.market_id, m.event_title, m.title, m.alt_title, int(m.flipped), m.close_time, m.event_time,
                 m.url, m.rules, m.yes_ask, m.no_ask, m.fee_multiplier, now) for m in markets]
        for i in range(0, len(rows), self.UPSERT_CHUNK):
            self._tx(lambda c, chunk=rows[i:i + self.UPSERT_CHUNK]: c.executemany(
                """INSERT INTO markets (venue, market_id, event_title, title, alt_title, flipped, close_time,
                                        event_time, url, rules, yes_ask, no_ask, fee_multiplier, open, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                   ON CONFLICT(venue, market_id) DO UPDATE SET
                     event_title=excluded.event_title, title=excluded.title, alt_title=excluded.alt_title,
                     flipped=excluded.flipped, close_time=excluded.close_time, event_time=excluded.event_time,
                     url=excluded.url, rules=excluded.rules, yes_ask=excluded.yes_ask, no_ask=excluded.no_ask,
                     fee_multiplier=excluded.fee_multiplier, open=1, updated_at=excluded.updated_at""", chunk))
        self.x("UPDATE markets SET open = 0 WHERE venue = ? AND open = 1 AND updated_at < ?", (venue, now))

    def _tx(self, work) -> None:
        c = self.conn
        c.execute("BEGIN IMMEDIATE")
        try:
            work(c)
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise

    def market(self, venue: str, market_id: str) -> dict | None:
        return self.one("SELECT * FROM markets WHERE venue = ? AND market_id = ?", (venue, market_id))

    def open_markets(self, venue: str) -> list[dict]:
        return self.q("SELECT * FROM markets WHERE venue = ? AND open = 1", (venue,))

    # -- candidates / pairs --------------------------------------------------
    def known_candidate_keys(self) -> set[tuple[str, str]]:
        return {(r["kalshi_id"], r["pmus_id"]) for r in self.q("SELECT kalshi_id, pmus_id FROM candidates")}

    def add_candidates(self, rows: list[tuple[str, str, float, float | None, bool]]) -> None:
        now = time.time()
        self._tx(lambda c: c.executemany(
            "INSERT OR IGNORE INTO candidates (kalshi_id, pmus_id, score, est_cost, inverted, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(*r, now) for r in rows]))

    def active_pairs(self) -> list[dict]:
        return self.q("SELECT * FROM pairs WHERE status = 'active' AND paused = 0")
