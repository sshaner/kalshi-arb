import os
from dotenv import load_dotenv

load_dotenv()


def _int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)).split("#")[0].strip())


def _float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)).split("#")[0].strip())


def _str(key: str, default: str = "") -> str:
    return os.getenv(key, default).split("#")[0].strip()


API_TOKEN = _str("API_TOKEN")
DB_PATH = _str("DB_PATH", "arb.db")
WEB_HOST = _str("WEB_HOST", "127.0.0.1")
WEB_PORT = _int("WEB_PORT", 8095)

KALSHI_BASE = _str("KALSHI_BASE", "https://api.elections.kalshi.com/trade-api/v2")
PMUS_BASE = _str("PMUS_BASE", "https://gateway.polymarket.us/v1")

# Loop cadence (seconds)
DISCOVERY_INTERVAL = _int("DISCOVERY_INTERVAL", 30 * 60)
PRICE_INTERVAL = _int("PRICE_INTERVAL", 5)
SETTLEMENT_INTERVAL = _int("SETTLEMENT_INTERVAL", 60 * 60)
BOOK_MAX_AGE = _float("BOOK_MAX_AGE", 10.0)

# Request rate per venue (requests/second). Kalshi's basic tier allows 20 reads/s.
KALSHI_RPS = _float("KALSHI_RPS", 10)
PMUS_RPS = _float("PMUS_RPS", 10)

# Fees (taker). Kalshi also applies a per-series multiplier fetched from /series.
KALSHI_FEE_COEF = _float("KALSHI_FEE_COEF", 0.07)
PMUS_FEE_COEF = _float("PMUS_FEE_COEF", 0.0695)

# APNs
APNS_KEY_PATH = _str("APNS_KEY_PATH")
APNS_KEY_ID = _str("APNS_KEY_ID")
APNS_TEAM_ID = _str("APNS_TEAM_ID")
APNS_BUNDLE_ID = _str("APNS_BUNDLE_ID", "org.shnr.arbscanner")
APNS_HOST = _str("APNS_HOST", "https://api.push.apple.com")

# Defaults for runtime-editable settings (stored in the DB, edited from the app)
DEFAULT_SETTINGS = {
    "scan_enabled": True,
    "min_edge_cents": 1.0,        # net profit per contract after fees
    "min_profit_dollars": 1.0,    # net profit for the full fillable size
    "min_annualized": 0.0,        # e.g. 0.2 = 20%/yr; 0 disables
    "paper_max_stake": 500.0,     # $ cap across both legs per opportunity
    "alert_cooldown_min": 30,
    "quiet_hours_start": None,    # hour 0-23 server local time, or None
    "quiet_hours_end": None,
    "match_min_score": 82,
    "match_date_window_days": 7,
}
