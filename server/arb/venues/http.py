"""Shared HTTP plumbing for venue clients: a token-bucket rate limiter and patient 429 handling."""
import asyncio
import logging
import time

import httpx

log = logging.getLogger(__name__)


class RateLimiter:
    """Allow at most `rate` requests per second (bursts up to `burst`), shared by every caller."""

    def __init__(self, rate: float, burst: int | None = None):
        self.rate = rate
        self.capacity = burst or max(1, int(rate))
        self.tokens = float(self.capacity)
        self.updated = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self.lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                await asyncio.sleep((1 - self.tokens) / self.rate)


async def get_json(http: httpx.AsyncClient, limiter: RateLimiter, url: str, params=None,
                   allow_404: bool = False, attempts: int = 6):
    delay = 1.0
    r = None
    for _ in range(attempts):
        await limiter.acquire()
        r = await http.get(url, params=params, timeout=20)
        if r.status_code == 429 or r.status_code >= 500:
            retry_after = r.headers.get("retry-after")
            wait = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else delay
            log.info("HTTP %s from %s; backing off %.1fs", r.status_code, url.split("?")[0], wait)
            await asyncio.sleep(wait)
            delay = min(delay * 2, 16)
            continue
        if allow_404 and r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return None
