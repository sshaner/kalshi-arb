"""One category list across both venues. Kalshi events carry `category` ("Elections", "Climate and Weather", …),
Polymarket US events a lowercase one ("politics", "macro", …); both map onto the names below. A pair takes Kalshi's
category (finer-grained and on every event), falling back to Polymarket US's."""

OTHER = "Other"
PINNED = ("Politics",)  # listed first in the app; everything else alphabetical, Other last

_MAP = {
    # Kalshi
    "politics": "Politics", "elections": "Politics",
    "sports": "Sports",
    "entertainment": "Entertainment", "culture": "Entertainment", "social": "Entertainment",
    "economics": "Economics",
    "financials": "Finance", "commodities": "Finance",
    "companies": "Companies", "business": "Companies",
    "crypto": "Crypto",
    "science and technology": "Science & Tech",
    "climate and weather": "Weather",
    "mentions": "Mentions",
    "world": "World",
    "health": "Health",
    "transportation": "Transportation",
    # Polymarket US (only the ones that differ from the above)
    "macro": "Economics",
    "finance": "Finance",
    "geopolitics": "World",
    "technology": "Science & Tech", "science": "Science & Tech",
}


def normalize(raw: str | None) -> str:
    """Venue category -> app category. Unknown non-empty values pass through title-cased so new ones still show up."""
    r = (raw or "").strip()
    if not r:
        return ""
    return _MAP.get(r.lower(), r.title())


def sort_key(name: str) -> tuple:
    if name in PINNED:
        return (0, PINNED.index(name), "")
    return (2 if name == OTHER else 1, 0, name.lower())


# SQL for a pair's category, given `markets` rows joined as k (Kalshi) and p (Polymarket US).
PAIR_SQL = "COALESCE(NULLIF(k.category, ''), NULLIF(p.category, ''), 'Other')"


def pair_category(k: dict | None, p: dict | None) -> str:
    return (k or {}).get("category") or (p or {}).get("category") or OTHER
