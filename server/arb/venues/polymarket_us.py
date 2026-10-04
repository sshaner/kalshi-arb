"""Polymarket US public gateway (no auth). Book lists the YES (long) side; NO ask = 1 - YES bid."""
import asyncio
import json
import logging
import re

import httpx

from .. import config
from ..models import PMUS, Book, Level, VenueMarket
from .http import RateLimiter, get_json

log = logging.getLogger(__name__)

PAGE = 200


class PolymarketUSClient:
    def __init__(self, client: httpx.AsyncClient, base: str = config.PMUS_BASE):
        self.http = client
        self.base = base
        self.limiter = RateLimiter(config.PMUS_RPS)

    async def _get(self, path: str, params=None, allow_404: bool = False) -> dict | None:
        return await get_json(self.http, self.limiter, f"{self.base}{path}", params, allow_404=allow_404)

    async def fetch_markets(self) -> list[VenueMarket]:
        markets: list[VenueMarket] = []
        offset = 0
        while True:
            data = await self._get("/events", {"active": "true", "closed": "false", "limit": PAGE, "offset": offset})
            events = (data or {}).get("events", [])
            for ev in events:
                markets.extend(parse_event(ev))
            if len(events) < PAGE:
                break
            offset += PAGE
        return markets

    async def fetch_quotes(self, slugs: list[str]) -> dict[str, tuple[float | None, float | None]]:
        """Top-of-book (yes_ask, no_ask) for many markets via repeated ?slug=, 50 per request."""
        out: dict[str, tuple[float | None, float | None]] = {}

        async def batch(chunk: list[str]) -> None:
            params = [("slug", s) for s in chunk] + [("limit", str(len(chunk)))]
            data = await self._get("/markets", params) or {}
            for m in data.get("markets", []):
                bid = _px(m.get("bestBidQuote"))
                out[m["slug"]] = (_px(m.get("bestAskQuote")), round(1 - bid, 4) if bid is not None else None)

        res = await asyncio.gather(*(batch(slugs[i:i + 50]) for i in range(0, len(slugs), 50)), return_exceptions=True)
        for e in res:
            if isinstance(e, Exception):
                log.warning("pmus quote batch failed: %r", e)
        return out

    async def fetch_book(self, slug: str) -> Book:
        return parse_book(await self._get(f"/markets/{slug}/book") or {})

    async def fetch_result(self, slug: str) -> float | None:
        """YES (long) settlement value 0-1, or None if not settled yet (endpoint 404s until then)."""
        s = await self._get(f"/markets/{slug}/settlement", allow_404=True)
        try:
            return float((s or {})["settlement"])
        except (KeyError, TypeError, ValueError):
            return None


_NOT_NAMES = {"yes", "no", "over", "under"}
_SIGNED_NUM = re.compile(r"[+-]?\d+(\.\d+)?")


def _is_name(desc: str | None) -> bool:
    d = (desc or "").strip()
    return bool(d) and d.lower() not in _NOT_NAMES and not _SIGNED_NUM.fullmatch(d)


def _px(q) -> float | None:
    try:
        return float(q["value"])
    except (KeyError, TypeError, ValueError):
        return None


def parse_event(ev: dict) -> list[VenueMarket]:
    out = []
    for m in ev.get("markets") or []:
        if not m.get("active") or m.get("closed") or m.get("archived") or m.get("hidden"):
            continue
        if m.get("status") and m["status"] != "MARKET_STATUS_OPEN":
            continue
        try:
            outcomes = json.loads(m.get("outcomes") or "[]")
        except ValueError:
            outcomes = []
        if len(outcomes) != 2:
            continue
        sides = m.get("marketSides") or []
        long_side = next((s for s in sides if s.get("long")), {})
        short_side = next((s for s in sides if not s.get("long")), {})
        label = m.get("title") or m.get("question", "")
        alt = ""
        if _is_name(long_side.get("description")) and _is_name(short_side.get("description")):
            # Head-to-head (moneyline/match winner): one market, YES = first name, NO = second name.
            # Yes/No, Over/Under and spread markets carry team objects too, so key off the side labels instead.
            label = (long_side.get("team") or {}).get("name") or long_side["description"]
            alt = (short_side.get("team") or {}).get("name") or short_side["description"]
        best_bid = _px(m.get("bestBidQuote"))
        ev_slug = ev.get("slug", "")
        out.append(VenueMarket(
            venue=PMUS,
            market_id=m["slug"],
            event_title=ev.get("title", ""),
            title=label,
            close_time=m.get("endDate") or ev.get("endDate", ""),
            event_time=m.get("gameStartTime") or ev.get("endDate") or m.get("endDate", ""),
            url=f"https://polymarket.us/event/{ev_slug}",
            rules=m.get("description", ""),
            yes_ask=_px(m.get("bestAskQuote")),
            no_ask=round(1 - best_bid, 4) if best_bid is not None else None,
            alt_title=alt,
            # Spread markets: the title names the "-line" team ("USC wins by over 5.5"), but when the long/YES
            # side is the "+line" team (Washington +5.5), YES is the negation of the title.
            flipped=(long_side.get("description") or "").strip().startswith("+"),
        ))
    return out


def parse_book(data: dict) -> Book:
    md = data.get("marketData") or {}
    yes_asks = sorted(
        (Level(_px(o["px"]), float(o["qty"])) for o in md.get("offers") or [] if float(o.get("qty", 0)) > 0),
        key=lambda l: l.price,
    )
    no_asks = sorted(
        (Level(round(1 - _px(b["px"]), 4), float(b["qty"])) for b in md.get("bids") or [] if float(b.get("qty", 0)) > 0),
        key=lambda l: l.price,
    )
    return Book(yes_asks=yes_asks, no_asks=no_asks)
