"""Provider quote: SharpAPI (api.sharpapi.io).

ATTENZIONE - mappatura da verificare.
La documentazione di SharpAPI non era raggiungibile dall'ambiente in cui
questo file e' stato scritto, quindi la traduzione dei campi e' ricostruita
in modo difensivo: per ogni informazione si accettano piu' nomi plausibili
(``price``/``odds``/``decimal_odds``, ``commence_time``/``start_time``/...).
Il parser e' volutamente tollerante e non lancia eccezioni su campi
sconosciuti: li ignora e li elenca fra le note.

Per verificare la mappatura sui dati reali:

    python3 edge_scan.py --odds-provider sharpapi --list-leagues
    python3 edge_scan.py --odds-provider sharpapi --dump-odds --competitions SA

Il primo comando elenca i campionati come li chiama SharpAPI (i codici vanno
poi messi in un file passato a --league-map). Il secondo stampa la risposta
grezza e un riepilogo dei campi riconosciuti e di quelli ignorati.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .httpcache import HttpClient, HttpError, build_url
from .odds_types import (
    MARKET_BTTS,
    MARKET_H2H,
    MARKET_TOTALS,
    BookQuote,
    OddsEvent,
    OddsFetchResult,
    Outcome,
    parse_utc,
)

DEFAULT_BASE = "https://api.sharpapi.io"
DEFAULT_ODDS_PATH = "/api/v1/odds"
LEAGUE_DISCOVERY_PATHS = ["/api/v1/leagues", "/api/v1/sports", "/api/v1/competitions"]

# --- sinonimi accettati per ogni campo -------------------------------------
EVENT_LIST_KEYS = ("data", "events", "odds", "results", "items")
EVENT_ID_KEYS = ("id", "event_id", "eventId", "uuid", "key")
START_KEYS = ("commence_time", "start_time", "startTime", "starts_at", "startsAt",
              "commence", "event_time", "scheduled", "start", "kickoff", "date")
HOME_KEYS = ("home_team", "homeTeam", "home", "home_name", "homeName", "home_team_name")
AWAY_KEYS = ("away_team", "awayTeam", "away", "away_name", "awayName", "away_team_name")
LEAGUE_KEYS = ("sport_key", "league", "league_key", "competition", "sport")
BOOK_LIST_KEYS = ("bookmakers", "books", "sportsbooks", "offers", "prices")
BOOK_ID_KEYS = ("key", "id", "book", "bookmaker", "sportsbook", "book_key", "slug")
BOOK_NAME_KEYS = ("title", "name", "book_name", "display_name", "bookmaker_name")
MARKET_LIST_KEYS = ("markets", "market", "lines", "odds")
MARKET_ID_KEYS = ("key", "market", "market_key", "type", "name", "market_type")
OUTCOME_LIST_KEYS = ("outcomes", "selections", "prices", "runners", "options")
OUTCOME_NAME_KEYS = ("name", "selection", "label", "outcome", "team", "side", "participant")
PRICE_KEYS = ("price", "odds", "decimal", "decimal_odds", "decimalOdds", "dec",
              "value", "odds_decimal")
POINT_KEYS = ("point", "line", "handicap", "total", "threshold", "points")

# nome del mercato lato SharpAPI -> nome interno
MARKET_SYNONYMS = {
    "h2h": MARKET_H2H, "moneyline": MARKET_H2H, "money_line": MARKET_H2H,
    "ml": MARKET_H2H, "1x2": MARKET_H2H, "match_winner": MARKET_H2H,
    "match_result": MARKET_H2H, "win_draw_win": MARKET_H2H, "three_way": MARKET_H2H,
    "totals": MARKET_TOTALS, "total": MARKET_TOTALS, "over_under": MARKET_TOTALS,
    "overunder": MARKET_TOTALS, "ou": MARKET_TOTALS, "total_goals": MARKET_TOTALS,
    "btts": MARKET_BTTS, "both_teams_to_score": MARKET_BTTS,
    "bothteamstoscore": MARKET_BTTS, "both_teams_score": MARKET_BTTS,
    "gg_ng": MARKET_BTTS,
}


def _first(obj: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if isinstance(obj, dict) and obj.get(key) not in (None, ""):
            return obj[key]
    return None


def _as_list(payload: Any) -> List[Any]:
    """Estrae la lista di eventi da una risposta che puo' essere incapsulata."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in EVENT_LIST_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return value
        # {"data": {"events": [...]}}
        for value in payload.values():
            if isinstance(value, (list, dict)):
                nested = _as_list(value)
                if nested:
                    return nested
    return []


def _to_decimal_odds(raw: Any, style: str = "auto") -> Optional[float]:
    """Normalizza a quota decimale. Riconosce il formato americano."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if style == "decimal":
        return value if value > 1.0 else None
    if style == "american" or (style == "auto" and (value <= -100 or value >= 100)):
        if value > 0:
            return 1.0 + value / 100.0
        if value < 0:
            return 1.0 + 100.0 / abs(value)
        return None
    return value if value > 1.0 else None


def _market_name(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    key = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    return MARKET_SYNONYMS.get(key)


def _team_name(value: Any) -> str:
    """La squadra puo' essere una stringa o un oggetto {name: ...}."""
    if isinstance(value, dict):
        return str(_first(value, ("name", "title", "display_name", "abbr")) or "")
    return str(value or "")


class SharpApiClient:
    """Client SharpAPI con la stessa interfaccia di OddsApiClient."""

    def __init__(
        self,
        api_key: str,
        http: HttpClient,
        base: str = DEFAULT_BASE,
        odds_path: str = DEFAULT_ODDS_PATH,
        auth_style: str = "bearer",
        league_param: str = "league",
        odds_format: str = "auto",
    ):
        if not api_key:
            raise ValueError("SHARPAPI_KEY mancante")
        self.api_key = api_key
        self.http = http
        self.base = base.rstrip("/")
        self.odds_path = "/" + odds_path.strip("/")
        self.auth_style = auth_style
        self.league_param = league_param
        self.odds_format = odds_format
        self.requests_remaining: Optional[str] = None
        self.requests_used: Optional[str] = None
        self.unknown_fields: set[str] = set()

    # ------------------------------------------------------------ trasporto
    def _auth(self) -> Tuple[Dict[str, str], Dict[str, str]]:
        """Ritorna (header, parametri) a seconda dello stile di autenticazione."""
        if self.auth_style == "query":
            return {}, {"apiKey": self.api_key}
        if self.auth_style == "x-api-key":
            return {"X-API-Key": self.api_key}, {}
        return {"Authorization": f"Bearer {self.api_key}"}, {}

    def _get(self, path: str, params: Dict[str, Any], ttl: int):
        headers, auth_params = self._auth()
        url = build_url(f"{self.base}{path}", {**params, **auth_params})
        resp = self.http.get(url, headers, ttl=ttl)
        for header, attr in (("x-ratelimit-remaining", "requests_remaining"),
                             ("x-requests-remaining", "requests_remaining"),
                             ("x-ratelimit-used", "requests_used"),
                             ("x-requests-used", "requests_used")):
            if resp.headers.get(header):
                setattr(self, attr, resp.headers[header])
        return url, resp.json()

    # ------------------------------------------------------------ scoperta
    def discover_leagues(self, ttl: int) -> List[Tuple[str, Any]]:
        """Prova gli endpoint plausibili di elenco campionati. Non solleva."""
        found: List[Tuple[str, Any]] = []
        for path in LEAGUE_DISCOVERY_PATHS:
            try:
                url, payload = self._get(path, {}, ttl)
            except HttpError as exc:
                found.append((path, f"non disponibile ({exc.status or 'errore rete'})"))
                continue
            found.append((path, payload))
        return found

    def dump_raw(self, league_key: str, markets: List[str], ttl: int) -> Tuple[str, Any]:
        return self._get(
            self.odds_path,
            {self.league_param: league_key, "markets": ",".join(markets)},
            ttl,
        )

    # -------------------------------------------------------------- quote
    def fetch(
        self,
        sport_key: str,
        markets: List[str],
        ttl: int,
        bookmakers: Optional[str] = None,
    ) -> OddsFetchResult:
        result = OddsFetchResult()
        params: Dict[str, Any] = {
            self.league_param: sport_key,
            "markets": ",".join(markets),
        }
        if bookmakers:
            params["bookmakers"] = bookmakers
        try:
            _url, payload = self._get(self.odds_path, params, ttl)
        except HttpError as exc:
            if exc.status in (401, 403):
                raise HttpError(
                    exc.status, exc.url,
                    "SHARPAPI_KEY rifiutata. Verificare la chiave e lo stile di "
                    "autenticazione con --sharpapi-auth (bearer | x-api-key | query)",
                ) from exc
            if exc.status == 404:
                result.notes.append(
                    f"[sharpapi] nessun dato per '{sport_key}' su {self.odds_path}. "
                    "Il codice campionato o il percorso potrebbero essere diversi: "
                    "usare --list-leagues per scoprirli e --league-map per mapparli."
                )
                return result
            raise

        raw_events = _as_list(payload)
        if not raw_events:
            result.notes.append(
                "[sharpapi] risposta ricevuta ma nessun evento riconosciuto nella "
                "struttura JSON: eseguire --dump-odds e adeguare la mappatura in "
                "fbedge/sharpapi.py"
            )
            return result

        for raw in raw_events:
            event = self._parse_event(raw, sport_key)
            if event is not None:
                result.events.append(event)

        if not result.events:
            result.notes.append(
                f"[sharpapi] {len(raw_events)} eventi ricevuti ma nessuno "
                "interpretabile (campi squadra/orario/quota non riconosciuti). "
                "Eseguire --dump-odds."
            )
        result.requests_remaining = self.requests_remaining
        result.requests_used = self.requests_used
        if self.unknown_fields:
            result.notes.append(
                "[sharpapi] mercati ignorati perche' non mappati: "
                + ", ".join(sorted(self.unknown_fields))
            )
        return result

    # ------------------------------------------------------------- parsing
    def _parse_event(self, raw: Any, fallback_league: str) -> Optional[OddsEvent]:
        if not isinstance(raw, dict):
            return None
        start = _first(raw, START_KEYS)
        home = _team_name(_first(raw, HOME_KEYS))
        away = _team_name(_first(raw, AWAY_KEYS))

        # forma alternativa: {"teams": {"home": ..., "away": ...}}
        teams = raw.get("teams")
        if isinstance(teams, dict):
            home = home or _team_name(teams.get("home"))
            away = away or _team_name(teams.get("away"))
        elif isinstance(teams, list) and len(teams) == 2 and not (home and away):
            home, away = _team_name(teams[0]), _team_name(teams[1])

        if not (start and home and away):
            return None
        try:
            kickoff = parse_utc(start)
        except (ValueError, TypeError, OSError):
            return None

        event = OddsEvent(
            event_id=str(_first(raw, EVENT_ID_KEYS) or f"{home}-{away}-{kickoff:%s}"),
            sport_key=str(_first(raw, LEAGUE_KEYS) or fallback_league),
            commence_time=kickoff,
            home_team=home,
            away_team=away,
        )

        for book_raw in _as_list_field(raw, BOOK_LIST_KEYS):
            self._parse_book(book_raw, event)
        return event if event.markets else event

    def _parse_book(self, raw: Any, event: OddsEvent) -> None:
        if not isinstance(raw, dict):
            return
        book_key = str(_first(raw, BOOK_ID_KEYS) or "?")
        book_title = str(_first(raw, BOOK_NAME_KEYS) or book_key)

        for market_raw in _as_list_field(raw, MARKET_LIST_KEYS):
            if not isinstance(market_raw, dict):
                continue
            market_id = _market_name(_first(market_raw, MARKET_ID_KEYS))
            if market_id is None:
                label = _first(market_raw, MARKET_ID_KEYS)
                if label:
                    self.unknown_fields.add(str(label))
                continue
            outcomes: List[Outcome] = []
            for outcome_raw in _as_list_field(market_raw, OUTCOME_LIST_KEYS):
                if not isinstance(outcome_raw, dict):
                    continue
                price = _to_decimal_odds(_first(outcome_raw, PRICE_KEYS), self.odds_format)
                name = _first(outcome_raw, OUTCOME_NAME_KEYS)
                if price is None or name is None:
                    continue
                point = _first(outcome_raw, POINT_KEYS)
                if point is None:
                    point = _first(market_raw, POINT_KEYS)
                try:
                    point_value = float(point) if point is not None else None
                except (TypeError, ValueError):
                    point_value = None
                outcomes.append(Outcome(_team_name(name), price, point_value))
            if outcomes:
                event.markets.setdefault(market_id, []).append(
                    BookQuote(book_key, book_title, outcomes)
                )


def _as_list_field(obj: Dict[str, Any], keys: Iterable[str]) -> List[Any]:
    value = _first(obj, keys)
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        # {"h2h": {...}, "totals": {...}} -> lista con la chiave iniettata
        out = []
        for key, item in value.items():
            if isinstance(item, dict):
                merged = dict(item)
                merged.setdefault("key", key)
                out.append(merged)
            elif isinstance(item, list):
                out.extend(item)
        return out
    return []


def summarize_structure(payload: Any, depth: int = 0, max_depth: int = 4) -> str:
    """Riassunto della forma del JSON, per capire cosa restituisce l'API."""
    pad = "  " * depth
    if depth > max_depth:
        return f"{pad}..."
    if isinstance(payload, dict):
        lines = []
        for key, value in list(payload.items())[:25]:
            kind = type(value).__name__
            if isinstance(value, (dict, list)):
                lines.append(f"{pad}{key}: {kind}")
                lines.append(summarize_structure(value, depth + 1, max_depth))
            else:
                lines.append(f"{pad}{key}: {kind} = {json.dumps(value, default=str)[:60]}")
        return "\n".join(l for l in lines if l.strip())
    if isinstance(payload, list):
        if not payload:
            return f"{pad}[] (vuoto)"
        return f"{pad}[{len(payload)} elementi], il primo:\n" + summarize_structure(
            payload[0], depth + 1, max_depth
        )
    return f"{pad}{type(payload).__name__}"
