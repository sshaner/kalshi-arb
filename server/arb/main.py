"""Entry point: background loops + the API server in one asyncio process."""
import asyncio
import logging
import sys

import uvicorn

from . import config
from .api import create_app
from .db import Db
from .push import Pusher
from .scanner import Scanner


async def run() -> None:
    if not config.API_TOKEN:
        sys.exit("API_TOKEN is not set")
    db = Db()
    pusher = Pusher(db)
    scanner = Scanner(db, pusher)
    app = create_app(db, scanner, pusher)
    server = uvicorn.Server(uvicorn.Config(app, host=config.WEB_HOST, port=config.WEB_PORT,
                                           log_level="warning", proxy_headers=True))
    await asyncio.gather(
        server.serve(),
        scanner.discovery_loop(),
        scanner.price_loop(),
        scanner.settlement_loop(),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(run())


if __name__ == "__main__":
    main()
