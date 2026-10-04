"""Suggest Kalshi <-> Polymarket US market pairs. Suggestions only; a human approves each one in the app.

Both venues list 50k-150k open markets, so all-pairs fuzzy matching is out of the question. Instead:
  1. drop markets with no live quote (nothing to arbitrage),
  2. block on rare tokens (an inverted index over Kalshi titles, skipping words that appear everywhere),
  3. require the event/close dates to be within a window,
  4. require the same numeric line and the same period/prop qualifiers,
  5. require the *outcome* entity (team/player) to agree — or to be Polymarket's NO side, which makes an
     inverted pair (Polymarket US runs a head-to-head game as one market: YES = first team, NO = second),
  6. fuzzy-score what survives, and drop pairs whose top-of-book gap is implausibly large.
"""
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime

from rapidfuzz import fuzz

STOPWORDS = {"will", "the", "a", "an", "of", "in", "on", "by", "be", "to", "for", "who", "which", "what", "win", "wins",
             "winner", "yes", "no", "vs", "v", "at", "and", "or", "game", "match", "before", "after", "than", "over",
             "under", "more", "less", "is", "are", "2025", "2026", "2027"}
_PUNCT = re.compile(r"[^a-z0-9. ]+")
_NUM = re.compile(r"(?<![a-z0-9])\d+(?:\.\d+)?")
_YEAR = re.compile(r"^(19|20)\d\d$")

# Kalshi decorates event titles with "Spread"/"Total Points"/"Team Total" and Polymarket doesn't, so only
# words that pick a *different* market (period, prop type, round) are listed. Values fold plurals/synonyms.
QUALIFIERS = {
    "1st": "1st", "first": "1st", "2nd": "2nd", "second": "2nd", "3rd": "3rd", "third": "3rd", "4th": "4th",
    "fourth": "4th", "half": "half", "halftime": "half", "1h": "half", "2h": "half", "quarter": "quarter",
    "period": "period", "inning": "inning", "innings": "inning", "set": "set", "map": "map", "round": "round",
    "cut": "cut", "top": "top", "podium": "podium", "exact": "exact", "scores": "scores", "overtime": "ot",
    "ot": "ot", "draw": "draw", "tie": "draw", "both": "both", "sweep": "sweep", "mvp": "mvp", "rookie": "rookie",
    "playoff": "playoff", "playoffs": "playoff", "qualify": "qualify", "qualifiers": "qualify",
    "final": "final", "finals": "final", "semifinal": "semifinal", "semifinals": "semifinal",
    "conference": "conference", "division": "division", "seed": "seed", "pole": "pole", "lap": "lap",
    "exactly": "exact", "decision": "method", "ko": "method", "tko": "method", "dq": "method", "submission": "method",
    "method": "method", "finish": "method", "finalist": "finalist", "finalists": "finalist", "nominee": "finalist",
    "nominees": "finalist", "combo": "combo", "parlay": "combo", "goods": "goods", "services": "services",
}
# Words in an outcome label that describe the bet rather than who it's about.
GENERIC = (STOPWORDS - {"and", "or"}) | set(QUALIFIERS) | {
    "points", "point", "pts", "goals", "goal", "total", "totals", "scored", "reg", "time", "regulation", "runs", "run",
    "games", "sets", "yards", "yds", "fc", "cf", "sc", "ec", "afc", "club", "plus", "above", "below", "between",
    "exactly", "least", "most", "margin", "spread", "line", "any", "other", "field",
}

MAX_DF = 1500        # tokens in more Kalshi markets than this are useless for blocking
RARE_TOKENS = 3      # how many of a market's rarest tokens to block on
MAX_BLOCK = 4000     # cap on candidates scored per Polymarket market
ENTITY_MIN = 80      # outcome-entity similarity needed when both sides name one

# Words that turn one team into a different team: "Texas" vs "Texas Tech", "Oklahoma" vs "Oklahoma St.".
# If one entity has any of these and the other doesn't, they're different outcomes.
DISTINGUISHERS = {"tech", "state", "st", "southern", "northern", "eastern", "western", "central", "am", "international",
                  "christian", "baptist", "city", "united", "atlantic", "pacific", "monroe", "lafayette", "poly",
                  "methodist", "wesleyan", "jr", "ii", "iii", "women", "womens", "w", "u21", "u23", "u20", "u19", "b",
                  "south", "north", "east", "west", "new", "oh", "ohio", "fl", "upstate"}


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


def normalize(text: str) -> str:
    words = _PUNCT.sub(" ", _ascii(text)).split()
    return " ".join(w.strip(".") for w in words if w.strip(".") and w.strip(".") not in STOPWORDS)


def numbers(text: str) -> frozenset[str]:
    """Lines/thresholds in a title (26.5, 3, 100000), ignoring years and signs."""
    out = set()
    for n in _NUM.findall(_ascii(text).replace(",", "")):
        if not _YEAR.match(n):
            out.add(str(float(n)))
    return frozenset(out)


def qualifiers(text: str) -> frozenset[str]:
    return frozenset(QUALIFIERS[w] for w in _PUNCT.sub(" ", _ascii(text)).split() if w in QUALIFIERS)


_SPREAD = re.compile(r"\bwins? by\b|\bby (over|more than)\b|(?<![a-z0-9.])[+-]\d+(\.\d+)?\b|\bspread\b|\bhandicap\b")
_TOTAL = re.compile(r"\b(over|under)\b|\btotal\b|\bscored\b|\d\+ ")
_STATS = ("touchdown", "corner", "rebound", "assist", "three", "strikeout", "hit", "home run", "card", "ace",
          "passing", "rushing", "receiving", "yards", "sack", "save", "shot", "kill")


def prop_kind(label: str) -> tuple[str, ...]:
    """What kind of bet an outcome label is: spread, total (game vs team), stat type, or plain outcome."""
    t = _ascii(label)
    stats = tuple(sorted(w for w in _STATS if re.search(rf"\b{w}s?\b", t)))
    if _SPREAD.search(t):
        return ("spread", *stats)
    if _TOTAL.search(t):
        return ("total", "team" if entity(label) else "game", *stats)
    return ("outcome", *stats)


def entity(label: str) -> str:
    """The who/what of an outcome label: 'Chicago Bears over 35.5 total points' -> 'chicago bears'."""
    words = _PUNCT.sub(" ", _ascii(label).replace("&", "")).split()
    return " ".join(w.strip(".") for w in words
                    if w.strip(".") and w.strip(".") not in GENERIC and not _NUM.fullmatch(w.strip("+-.")))


def _distinguishers(e: str) -> set[str]:
    return {("state" if w == "st" else w) for w in e.replace("&", "").split() if w in DISTINGUISHERS}


def entities_agree(a: str, b: str) -> bool:
    if not a or not b:
        return True  # one side keeps the entity in the event title; let the event score decide
    if _distinguishers(a) != _distinguishers(b):
        return False
    return fuzz.token_set_ratio(a, b) >= ENTITY_MIN


_VS = re.compile(r"\s+(?:vs\.?|v\.?|@|at)\s+", re.I)


def event_sides(event_title: str) -> list[str] | None:
    """['army', 'louisiana tech'] for 'Army vs Louisiana Tech: Spread'; None if it isn't a head-to-head event."""
    head = re.split(r"[:|]", event_title or "", maxsplit=1)[0]
    parts = _VS.split(head)
    if len(parts) != 2:
        return None
    sides = [entity(x) for x in parts]
    return sides if all(sides) else None


def same_matchup(k_event: str, p_event: str) -> bool:
    """Both head-to-head events must name the same two competitors (in either order)."""
    a, b = event_sides(k_event), event_sides(p_event)
    if a is None or b is None:
        return True
    return ((entities_agree(a[0], b[0]) and entities_agree(a[1], b[1]))
            or (entities_agree(a[0], b[1]) and entities_agree(a[1], b[0])))


def _names_competitor(ent: str, event_title: str) -> bool:
    sides = event_sides(event_title)
    return bool(ent and sides and any(entities_agree(ent, side) for side in sides))


def _date(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _dates(m: dict) -> list[datetime]:
    return [d for d in (_date(m.get("event_time")), _date(m.get("close_time"))) if d]


def _close(da: list[datetime], db: list[datetime], window_days: float) -> bool:
    if not da or not db:
        return True  # can't tell; let the score decide
    return min(abs((x - y).total_seconds()) for x in da for y in db) <= window_days * 86400


def dates_close(a: dict, b: dict, window_days: float) -> bool:
    return _close(_dates(a), _dates(b), window_days)


def quoted(m: dict) -> bool:
    """At least one side has a real ask strictly between 0 and 1."""
    return any(v is not None and 0 < v < 1 for v in (m.get("yes_ask"), m.get("no_ask")))


def est_cost(k: dict, p: dict, inverted: bool = False) -> float | None:
    """Cheapest top-of-book cost of the hedged pair, before fees. <1 means a visible gap."""
    if inverted:
        combos = [(k.get("yes_ask"), p.get("yes_ask")), (k.get("no_ask"), p.get("no_ask"))]
    else:
        combos = [(k.get("yes_ask"), p.get("no_ask")), (k.get("no_ask"), p.get("yes_ask"))]
    costs = [a + b for a, b in combos if a and b and 0 < a < 1 and 0 < b < 1]
    return round(min(costs), 4) if costs else None


def orientation(k: dict, p: dict) -> bool | None:
    """False = Kalshi YES is Polymarket YES, True = Kalshi YES is Polymarket NO, None = outcomes don't line up."""
    o = _title_orientation(k, p)
    return None if o is None else o != bool(p.get("flipped"))


def _title_orientation(k: dict, p: dict) -> bool | None:
    """Like orientation(), but relative to Polymarket's *title* rather than its YES side."""
    k_label = k["title"]
    if numbers(k_label) != numbers(p["title"]):
        return None
    # Event numbers too: "Top 5 QB, Weeks 1-18" is not "Top QB, Week 4".
    if numbers(k.get("event_title", "")) - numbers(k_label) != numbers(p.get("event_title", "")) - numbers(p["title"]):
        return None
    if prop_kind(k_label) != prop_kind(p["title"]):
        return None
    k_ent = entity(k_label)
    p_ent = entity(p["title"])
    alt_ent = entity(p.get("alt_title") or "")
    # One label names a competitor and the other names nobody: e.g. "Silva by KO" vs "KO/TKO/DQ" (any fighter).
    if bool(k_ent) != bool(p_ent) and not alt_ent and (
            _names_competitor(k_ent, k.get("event_title", "")) or _names_competitor(p_ent, p.get("event_title", ""))):
        return None
    if entities_agree(k_ent, entity(p["title"])):
        # Polymarket's NO side may still be the closer entity match.
        if alt_ent and k_ent and entities_agree(k_ent, alt_ent) and \
                fuzz.token_set_ratio(k_ent, alt_ent) > fuzz.token_set_ratio(k_ent, entity(p["title"])):
            return True
        return False
    if alt_ent and k_ent and entities_agree(k_ent, alt_ent):
        return True
    return None


def suggest(
    kalshi: list[dict],
    pmus: list[dict],
    *,
    min_score: float,
    window_days: float,
    skip: set[tuple[str, str]],
    per_market: int = 2,
    min_est_cost: float = 0.75,
) -> list[tuple[str, str, float, float | None, bool]]:
    """Returns (kalshi_id, pmus_id, score, est_cost, inverted) for plausible pairs not already in `skip`."""
    kalshi = [m for m in kalshi if quoted(m)]
    pmus = [m for m in pmus if quoted(m)]
    k_texts = [normalize(f"{m['event_title']} {m['title']}") for m in kalshi]
    k_events = [normalize(m["event_title"]) for m in kalshi]
    k_quals = [qualifiers(f"{m['event_title']} {m['title']}") for m in kalshi]
    k_dates = [_dates(m) for m in kalshi]
    df: Counter[str] = Counter()
    for t in k_texts:
        df.update(set(t.split()))
    index: dict[str, list[int]] = defaultdict(list)
    for i, t in enumerate(k_texts):
        for tok in set(t.split()):
            if df[tok] <= MAX_DF:
                index[tok].append(i)

    out: list[tuple[str, str, float, float | None, bool]] = []
    for p in pmus:
        # Block on the event plus both outcome labels so inverted head-to-head pairs are found too.
        text = normalize(f"{p['event_title']} {p['title']} {p.get('alt_title') or ''}")
        p_event = normalize(p["event_title"])
        p_quals = qualifiers(f"{p['event_title']} {p['title']}")
        toks = [t for t in set(text.split()) if 0 < df.get(t, 0) <= MAX_DF]
        if not toks:
            continue
        rare = sorted(toks, key=lambda t: df[t])[:RARE_TOKENS]
        hits = Counter(i for t in rare for i in index[t])
        need = min(2, len(rare))
        block = [i for i, c in hits.most_common(MAX_BLOCK) if c >= need]
        p_dates = _dates(p)
        scored = []
        for i in block:
            if k_quals[i] != p_quals or not _close(k_dates[i], p_dates, window_days):
                continue
            event_score = fuzz.token_set_ratio(p_event, k_events[i])
            if event_score < min_score or not same_matchup(kalshi[i]["event_title"], p["event_title"]):
                continue
            inverted = orientation(kalshi[i], p)
            if inverted is None:
                continue
            score = 0.6 * event_score + 0.4 * fuzz.token_set_ratio(text, k_texts[i])
            scored.append((score, i, inverted))
        scored.sort(key=lambda s: s[0], reverse=True)
        taken = 0
        for score, i, inverted in scored:
            k = kalshi[i]
            if (k["market_id"], p["market_id"]) in skip:
                continue
            est = est_cost(k, p, inverted)
            # Identical markets never quote a 25%+ gap; that's a mismatch.
            if est is not None and est < min_est_cost:
                continue
            out.append((k["market_id"], p["market_id"], round(score, 1), est, inverted))
            taken += 1
            if taken >= per_market:
                break
    return out
