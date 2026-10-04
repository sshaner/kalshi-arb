from dataclasses import dataclass, field
import time

KALSHI = "kalshi"
PMUS = "pmus"


@dataclass
class Level:
    price: float  # dollars, 0-1
    size: float   # contracts


@dataclass
class Book:
    """Ask ladders for buying each side, ascending by price."""
    yes_asks: list[Level]
    no_asks: list[Level]
    fetched_at: float = field(default_factory=time.time)

    def to_dict(self, depth: int = 10) -> dict:
        return {
            "yes_asks": [[l.price, l.size] for l in self.yes_asks[:depth]],
            "no_asks": [[l.price, l.size] for l in self.no_asks[:depth]],
            "fetched_at": self.fetched_at,
        }


@dataclass
class VenueMarket:
    venue: str
    market_id: str          # Kalshi ticker | Polymarket US slug
    event_title: str
    title: str              # outcome label the YES side refers to
    close_time: str         # ISO 8601
    event_time: str         # best guess at when the underlying happens (ISO), for matching
    url: str
    rules: str = ""
    yes_ask: float | None = None
    no_ask: float | None = None
    fee_multiplier: float = 1.0
    status: str = "open"
    alt_title: str = ""     # outcome the NO side refers to, when it's a named entity (Polymarket US head-to-head)
    flipped: bool = False   # YES is the *negation* of `title` (Polymarket US "+line" spread markets)

    @property
    def match_text(self) -> str:
        return f"{self.event_title} {self.title}".strip()


@dataclass
class Leg:
    venue: str
    market_id: str
    side: str          # "yes" | "no"
    contracts: float
    avg_price: float
    cost: float
    fee: float


@dataclass
class Opportunity:
    direction: str     # "kyes_pno" etc.
    kalshi: Leg
    pmus: Leg
    contracts: float
    cost: float        # both legs, excl fees
    fees: float
    profit: float      # contracts * $1 - cost - fees
    edge_cents: float  # profit per contract in cents
    roi: float
    annualized: float | None
