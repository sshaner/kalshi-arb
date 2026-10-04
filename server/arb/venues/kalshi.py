"""Kalshi public market data (no auth). Orderbook is bids-only: YES ask = 1 - NO bid."""
import asyncio
import logging

import httpx

from .. import config
from ..models import KALSHI, Book, Level, VenueMarket
from .http import RateLimiter, get_json

log = logging.getLogger(__name__)


class KalshiClient:
    def __init__(self, client: httpx.AsyncClient, base: str = config.KALSHI_BASE):
        self.http = client
        self.base = base
        self.limiter = RateLimiter(config.KALSHI_RPS)

    async def _get(self, path: str, params: dict | None = None) -> dict:
        return await get_json(self.http, self.limiter, f"{self.base}{path}", params) or {}

    async def fee_multipliers(self) -> dict[str, float]:
        data = await self._get("/series")
        out = {}
        for s in data.get("series", []):
            try:
                out[s["ticker"]] = float(s.get("fee_multiplier") or 1)
            except (TypeError, ValueError):
                out[s["ticker"]] = 1.0
        return out

    async def fetch_markets(self) -> list[VenueMarket]:
        mults = await self.fee_multipliers()
        markets: list[VenueMarket] = []
        cursor = ""
        while True:
            params = {"status": "open", "with_nested_markets": "true", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            data = await self._get("/events", params)
            for ev in data.get("events", []):
                markets.extend(parse_event(ev, mults))
            cursor = data.get("cursor") or ""
            if not cursor or not data.get("events"):
                break
        return markets

    async def fetch_quotes(self, tickers: list[str]) -> dict[str, tuple[float | None, float | None]]:
        """Top-of-book (yes_ask, no_ask) for many markets, 100 per request."""
        out: dict[str, tuple[float | None, float | None]] = {}

        async def batch(chunk: list[str]) -> None:
            data = await self._get("/markets", {"tickers": ",".join(chunk), "limit": len(chunk)})
            for m in data.get("markets", []):
                out[m["ticker"]] = (_f(m.get("yes_ask_dollars")), _f(m.get("no_ask_dollars")))

        res = await asyncio.gather(*(batch(tickers[i:i + 100]) for i in range(0, len(tickers), 100)), return_exceptions=True)
        for e in res:
            if isinstance(e, Exception):
                log.warning("kalshi quote batch failed: %r", e)
        return out

    async def fetch_book(self, ticker: str) -> Book:
        return parse_orderbook(await self._get(f"/markets/{ticker}/orderbook"))

    async def fetch_result(self, ticker: str) -> float | None:
        """YES settlement value (1.0/0.0), or None if not settled yet."""
        m = (await self._get(f"/markets/{ticker}")).get("market", {})
        if m.get("status") not in ("finalized", "settled"):
            return None
        result = (m.get("result") or "").lower()
        if result == "yes":
            return 1.0
        if result == "no":
            return 0.0
        return None


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_event(ev: dict, mults: dict[str, float]) -> list[VenueMarket]:
    out = []
    series = ev.get("series_ticker", "")
    for m in ev.get("markets") or []:
        if m.get("mve_collection_ticker") or m.get("market_type", "binary") != "binary":
            continue
        if m.get("status") not in ("active", "open"):
            continue
        out.append(VenueMarket(
            venue=KALSHI,
            market_id=m["ticker"],
            event_title=ev.get("title", ""),
            title=m.get("yes_sub_title") or m.get("title", ""),
            close_time=m.get("close_time", ""),
            event_time=m.get("expected_expiration_time") or m.get("close_time", ""),
            url=f"https://kalshi.com/markets/{series.lower()}" if series else f"https://kalshi.com/markets/{m['ticker']}",
            rules=m.get("rules_primary", ""),
            yes_ask=_f(m.get("yes_ask_dollars")),
            no_ask=_f(m.get("no_ask_dollars")),
            fee_multiplier=mults.get(series, 1.0),
        ))
    return out


def parse_orderbook(data: dict) -> Book:
    ob = data.get("orderbook_fp") or {}
    yes_bids = [(float(p), float(q)) for p, q in ob.get("yes_dollars") or []]
    no_bids = [(float(p), float(q)) for p, q in ob.get("no_dollars") or []]
    yes_asks = sorted((Level(round(1 - p, 4), q) for p, q in no_bids if q > 0), key=lambda l: l.price)
    no_asks = sorted((Level(round(1 - p, 4), q) for p, q in yes_bids if q > 0), key=lambda l: l.price)
    return Book(yes_asks=yes_asks, no_asks=no_asks)
