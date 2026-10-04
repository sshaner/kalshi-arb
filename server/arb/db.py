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
    def __init__(self, path: str = config.DB_PATH):
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.lock = threading.Lock()

    # -- generic -------------------------------------------------------------
    def q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def x(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            cur = self.conn.execute(sql, args)
            return cur.lastrowid

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
    def upsert_markets(self, venue: str, markets: list[VenueMarket]) -> None:
        now = time.time()
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                self.conn.execute("UPDATE markets SET open = 0 WHERE venue = ?", (venue,))
                self.conn.executemany(
                    """INSERT INTO markets (venue, market_id, event_title, title, alt_title, flipped, close_time,
                                            event_time, url, rules, yes_ask, no_ask, fee_multiplier, open, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                       ON CONFLICT(venue, market_id) DO UPDATE SET
                         event_title=excluded.event_title, title=excluded.title, alt_title=excluded.alt_title, flipped=excluded.flipped,
                         close_time=excluded.close_time,
                         event_time=excluded.event_time, url=excluded.url, rules=excluded.rules,
                         yes_ask=excluded.yes_ask, no_ask=excluded.no_ask, fee_multiplier=excluded.fee_multiplier,
                         open=1, updated_at=excluded.updated_at""",
                    [(m.venue, m.market_id, m.event_title, m.title, m.alt_title, int(m.flipped), m.close_time, m.event_time, m.url, m.rules,
                      m.yes_ask, m.no_ask, m.fee_multiplier, now) for m in markets],
                )
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
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
        with self.lock:
            self.conn.executemany(
                "INSERT OR IGNORE INTO candidates (kalshi_id, pmus_id, score, est_cost, inverted, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(*r, now) for r in rows])

    def active_pairs(self) -> list[dict]:
        return self.q("SELECT * FROM pairs WHERE status = 'active' AND paused = 0")
