"""Accesso a The Odds API (v4) per le quote reali di piu' bookmaker.

Piano gratuito: ~500 crediti/mese. Il costo di una chiamata e'
`n_mercati x n_regioni`, quindi `markets=h2h,totals&regions=eu` costa 2 crediti.
I contatori rimanenti vengono letti dagli header `x-requests-*` e riportati
nell'output, cosi' il budget resta visibile.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .httpcache import HttpClient, HttpError, build_url

BASE = "https://api.the-odds-api.com/v4"

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
    # market_key -> lista di quotazioni per bookmaker
    markets: Dict[str, List[BookQuote]] = field(default_factory=dict)


@dataclass
class OddsFetchResult:
    events: List[OddsEvent] = field(default_factory=list)
    requests_remaining: Optional[str] = None
    requests_used: Optional[str] = None
    notes: List[str] = field(default_factory=list)


def _parse_utc(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


class OddsApiClient:
    def __init__(self, api_key: str, http: HttpClient, regions: str = "eu"):
        if not api_key:
            raise ValueError("ODDS_API_KEY mancante")
        self.api_key = api_key
        self.http = http
        self.regions = regions
        self.requests_remaining: Optional[str] = None
        self.requests_used: Optional[str] = None

    def fetch(
        self,
        sport_key: str,
        markets: List[str],
        ttl: int,
        bookmakers: Optional[str] = None,
    ) -> OddsFetchResult:
        """Scarica le quote di uno sport. Degrada se un mercato non e' disponibile."""
        result = OddsFetchResult()
        wanted = list(markets)

        while wanted:
            params = {
                "apiKey": self.api_key,
                "regions": None if bookmakers else self.regions,
                "bookmakers": bookmakers,
                "markets": ",".join(wanted),
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            }
            url = build_url(f"{BASE}/sports/{sport_key}/odds", params)
            try:
                resp = self.http.get(url, ttl=ttl)
            except HttpError as exc:
                # 422 = mercato non valido per il piano/sport: togli gli extra.
                if exc.status == 422 and MARKET_BTTS in wanted:
                    wanted = [m for m in wanted if m != MARKET_BTTS]
                    result.notes.append(
                        f"[{sport_key}] mercato BTTS non disponibile "
                        "(richiede un piano a pagamento di The Odds API): "
                        "riporto solo la probabilita' di modello, senza edge."
                    )
                    continue
                if exc.status == 401:
                    raise HttpError(
                        401, url, "ODDS_API_KEY non valida o quota mensile esaurita"
                    ) from exc
                if exc.status == 404:
                    result.notes.append(
                        f"[{sport_key}] campionato non offerto da The Odds API "
                        "in questo momento (fuori stagione o senza quote aperte)."
                    )
                    return result
                raise

            self.requests_remaining = resp.headers.get(
                "x-requests-remaining", self.requests_remaining
            )
            self.requests_used = resp.headers.get("x-requests-used", self.requests_used)
            result.requests_remaining = self.requests_remaining
            result.requests_used = self.requests_used
            result.events = [self._parse_event(e) for e in resp.json()]
            return result

        return result

    @staticmethod
    def _parse_event(raw: dict) -> OddsEvent:
        event = OddsEvent(
            event_id=raw.get("id", ""),
            sport_key=raw.get("sport_key", ""),
            commence_time=_parse_utc(raw["commence_time"]),
            home_team=raw.get("home_team", ""),
            away_team=raw.get("away_team", ""),
        )
        for book in raw.get("bookmakers", []):
            for market in book.get("markets", []):
                outcomes = [
                    Outcome(
                        name=o.get("name", ""),
                        price=float(o["price"]),
                        point=(float(o["point"]) if o.get("point") is not None else None),
                    )
                    for o in market.get("outcomes", [])
                    if o.get("price")
                ]
                if not outcomes:
                    continue
                event.markets.setdefault(market.get("key", ""), []).append(
                    BookQuote(
                        book_key=book.get("key", ""),
                        book_title=book.get("title", book.get("key", "")),
                        outcomes=outcomes,
                    )
                )
        return event
