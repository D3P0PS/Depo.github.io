"""Tipi condivisi fra i provider di quote.

Il modello e' agnostico rispetto alla fonte delle quote: ogni provider
(The Odds API, SharpAPI, ...) traduce la propria risposta in queste strutture.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional

MARKET_H2H = "h2h"
MARKET_TOTALS = "totals"
MARKET_BTTS = "btts"


@dataclass(frozen=True)
class Outcome:
    name: str
    price: float
    point: Optional[float] = None


@dataclass
class BookQuote:
    book_key: str
    book_title: str
    outcomes: List[Outcome]


@dataclass
class OddsEvent:
    event_id: str
    sport_key: str
    commence_time: dt.datetime
    home_team: str
    away_team: str
    #: market_key -> lista di quotazioni per bookmaker
    markets: Dict[str, List[BookQuote]] = field(default_factory=dict)


@dataclass
class OddsFetchResult:
    events: List[OddsEvent] = field(default_factory=list)
    requests_remaining: Optional[str] = None
    requests_used: Optional[str] = None
    notes: List[str] = field(default_factory=list)


def parse_utc(value) -> dt.datetime:
    """Accetta ISO 8601 (con o senza Z) oppure un timestamp unix."""
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc)
    text = str(value).strip()
    if text.isdigit():
        return dt.datetime.fromtimestamp(int(text), tz=dt.timezone.utc)
    parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed
