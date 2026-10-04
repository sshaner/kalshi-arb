"""Apple Push Notification service sender (token-based auth, HTTP/2)."""
import json
import logging
import time

import httpx
import jwt

from . import config
from .db import Db

log = logging.getLogger(__name__)


class Pusher:
    def __init__(self, db: Db):
        self.db = db
        self._jwt: str | None = None
        self._jwt_at = 0.0
        self._key: str | None = None
        self.http = httpx.AsyncClient(http2=True, timeout=15)
        self.last_error: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(config.APNS_KEY_PATH and config.APNS_KEY_ID and config.APNS_TEAM_ID)

    def _token(self) -> str:
        # Apple rejects tokens older than an hour and throttles refreshes more often than every 20 min.
        if self._jwt and time.time() - self._jwt_at < 45 * 60:
            return self._jwt
        if self._key is None:
            with open(config.APNS_KEY_PATH) as f:
                self._key = f.read()
        self._jwt = jwt.encode({"iss": config.APNS_TEAM_ID, "iat": int(time.time())}, self._key,
                               algorithm="ES256", headers={"kid": config.APNS_KEY_ID})
        self._jwt_at = time.time()
        return self._jwt

    async def send(self, title: str, body: str, data: dict | None = None) -> int:
        """Send to every registered device. Returns number of successful deliveries."""
        if not self.enabled:
            log.info("APNs not configured; would push: %s | %s", title, body)
            return 0
        payload = {"aps": {"alert": {"title": title, "body": body}, "sound": "default"}, **(data or {})}
        sent = 0
        for d in self.db.q("SELECT token FROM devices"):
            token = d["token"]
            try:
                r = await self.http.post(
                    f"{config.APNS_HOST}/3/device/{token}",
                    content=json.dumps(payload),
                    headers={
                        "authorization": f"bearer {self._token()}",
                        "apns-topic": config.APNS_BUNDLE_ID,
                        "apns-push-type": "alert",
                        "apns-priority": "10",
                    },
                )
            except httpx.HTTPError as e:
                self.last_error = f"{type(e).__name__}: {e}"
                log.warning("APNs send failed: %s", self.last_error)
                continue
            if r.status_code == 200:
                sent += 1
                self.db.x("UPDATE devices SET last_ok = ? WHERE token = ?", (time.time(), token))
            elif r.status_code == 410 or (r.status_code == 400 and "BadDeviceToken" in r.text):
                log.info("Dropping dead device token %s…", token[:8])
                self.db.x("DELETE FROM devices WHERE token = ?", (token,))
            else:
                self.last_error = f"HTTP {r.status_code}: {r.text[:200]}"
                log.warning("APNs error: %s", self.last_error)
        return sent
