"""Client per l'API SofaScore via RapidAPI (host sportapi7.p.rapidapi.com) —
statistiche extra non coperte da football-data.org: corner, cartellini, tiri,
possesso palla, formazioni.

Non e' un'API ufficiale di SofaScore: e' un wrapper di terze parti su
RapidAPI che ne rispecchia (con possibili differenze) la struttura interna,
non documentata pubblicamente in modo ufficiale. Come gia' successo con
SharpAPI in questo stesso progetto, i nomi dei campi ESATTI vanno verificati
con i comandi diagnostici prima di scrivere qualsiasi logica di parsing:
indovinare a memoria la struttura di un'API non ufficiale e' il modo piu'
rapido per introdurre un bug silenzioso. Questo modulo si ferma quindi
all'accesso grezzo agli endpoint; la modellazione statistica di
corner/cartellini viene dopo, una volta viste risposte reali.

Il limite del piano gratuito va verificato nella dashboard di RapidAPI:
questa API non espone un endpoint /status standard come API-Football per
leggerlo via codice, quindi il consumo residuo non e' sempre disponibile
dagli header di risposta (dipende dal piano).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from .httpcache import HttpClient, HttpError, build_url

DEFAULT_HOST = "sportapi7.p.rapidapi.com"

#: cache lunga: una ricerca per nome squadra/torneo non cambia quasi mai
TTL_STATIC = 86400 * 7
#: cache media: il calendario partite di una data si aggiorna nel corso del giorno
TTL_SCHEDULE = 3600
#: cache lunga: le statistiche di una partita gia' giocata non cambiano piu'
TTL_PLAYED_EVENT = 86400 * 7


class SofaScoreClient:
    usage_label = "richieste (verifica il piano nella dashboard RapidAPI)"
    usage_is_budget = True

    def __init__(self, api_key: str, http: HttpClient, host: str = DEFAULT_HOST):
        if not api_key:
            raise ValueError("SOFASCORE_API_KEY mancante")
        self.api_key = api_key
        self.http = http
        self.host = host
        self.base = f"https://{host}"
        self.requests_remaining: Optional[str] = None
        self.requests_used: Optional[str] = None

    def _headers(self) -> Dict[str, str]:
        return {"x-rapidapi-key": self.api_key, "x-rapidapi-host": self.host}

    def _get(self, path: str, params: Dict[str, Any], ttl: int) -> Tuple[str, Any]:
        url = build_url(f"{self.base}{path}", params)
        try:
            resp = self.http.get(url, headers=self._headers(), ttl=ttl)
        except HttpError as exc:
            if exc.status in (401, 403):
                # il body di RapidAPI di solito dice la causa esatta (chiave
                # non valida, o valida ma non iscritta a QUESTA api): non
                # sostituirlo con un messaggio generico, va mostrato per intero
                raise HttpError(
                    exc.status, url,
                    f"{exc.body}\n(probabile causa: chiave RapidAPI valida ma "
                    "non iscritta al prodotto SofaScore/sportapi7, o host "
                    "sbagliato - verifica nella dashboard RapidAPI)",
                ) from exc
            if exc.status == 429:
                raise HttpError(429, url, f"{exc.body}\n(budget RapidAPI esaurito?)") from exc
            raise
        self.requests_remaining = resp.headers.get(
            "x-ratelimit-requests-remaining", self.requests_remaining
        )
        self.requests_used = resp.headers.get(
            "x-ratelimit-requests-limit", self.requests_used
        )
        return url, resp.json()

    # ------------------------------------------------------------ endpoint
    def search(self, query: str, ttl: int = TTL_STATIC) -> Any:
        """Ricerca libera (squadre, giocatori, tornei, eventi):
        /api/v1/search/{query}"""
        _url, payload = self._get(f"/api/v1/search/{query}", {}, ttl)
        return payload

    def categories_with_events(
        self, sport: str, date: str, timezone_offset: int = 0, ttl: int = TTL_SCHEDULE,
    ) -> Any:
        """Campionati/nazioni con almeno una partita in una data (YYYY-MM-DD):
        /api/v1/sport/{sport}/{date}/{timezoneOffset}/categories

        Primo passo del flusso ufficiale: non esiste un endpoint diretto
        'tutte le partite di oggi', va passato per le categorie."""
        path = f"/api/v1/sport/{sport}/{date}/{timezone_offset}/categories"
        _url, payload = self._get(path, {}, ttl)
        return payload

    def category_scheduled_events(
        self, category_id: int, date: str, ttl: int = TTL_SCHEDULE,
    ) -> Any:
        """Partite di una categoria (campionato) in una data (YYYY-MM-DD):
        /api/v1/category/{id}/scheduled-events/{date}

        Secondo passo del flusso: l'id categoria viene da categories_with_events()."""
        path = f"/api/v1/category/{category_id}/scheduled-events/{date}"
        _url, payload = self._get(path, {}, ttl)
        return payload

    def live_events(self, ttl: int = 60) -> Any:
        """Partite di calcio in corso in questo momento:
        /api/v1/sport/football/events/live"""
        _url, payload = self._get("/api/v1/sport/football/events/live", {}, ttl)
        return payload

    def team_events(
        self, team_id: int, page: int = 0, direction: str = "last", ttl: int = TTL_SCHEDULE,
    ) -> Any:
        """Partite recenti o prossime di una squadra:
        /api/v1/team/{team_id}/events/{last|next}/{page}

        Non confermato dalla documentazione ufficiale vista finora (che copre
        solo il flusso categorie->eventi): verificare con --ss-team-events
        prima di usarlo per davvero."""
        direction = direction if direction in ("last", "next") else "last"
        _url, payload = self._get(f"/api/v1/team/{team_id}/events/{direction}/{page}", {}, ttl)
        return payload

    def event_details(self, event_id: int, ttl: int = TTL_SCHEDULE) -> Any:
        """Dettagli di un evento (squadre, torneo, orario, punteggio):
        /api/v1/event/{event_id}"""
        _url, payload = self._get(f"/api/v1/event/{event_id}", {}, ttl)
        return payload

    def event_statistics(self, event_id: int, ttl: int = TTL_PLAYED_EVENT) -> Any:
        """Statistiche di squadra di una partita (corner, tiri, possesso, ...),
        disponibili solo a partita iniziata/conclusa: /api/v1/event/{event_id}/statistics"""
        _url, payload = self._get(f"/api/v1/event/{event_id}/statistics", {}, ttl)
        return payload

    def event_incidents(self, event_id: int, ttl: int = TTL_PLAYED_EVENT) -> Any:
        """Eventi della partita minuto per minuto - gol, cartellini,
        sostituzioni, VAR: /api/v1/event/{event_id}/incidents

        E' probabilmente la fonte giusta per i CARTELLINI (le statistiche
        aggregate a volte non li scompongono per giocatore/minuto)."""
        _url, payload = self._get(f"/api/v1/event/{event_id}/incidents", {}, ttl)
        return payload

    def event_lineups(self, event_id: int, ttl: int = TTL_SCHEDULE) -> Any:
        """Formazioni e statistiche per giocatore: /api/v1/event/{event_id}/lineups"""
        _url, payload = self._get(f"/api/v1/event/{event_id}/lineups", {}, ttl)
        return payload

    def standings(
        self, tournament_id: int, season_id: int, type_: str = "total",
        ttl: int = TTL_STATIC,
    ) -> Any:
        """Classifica di un torneo/stagione:
        /api/v1/unique-tournament/{id}/season/{seasonId}/standings/{type}

        type_: 'total' (classifica generale), 'home' (solo in casa),
        'away' (solo in trasferta). tournament_id e season_id si leggono da
        event['tournament']['uniqueTournament']['id'] e event['season']['id']
        di un evento gia' recuperato (es. da category_scheduled_events)."""
        type_ = type_ if type_ in ("total", "home", "away") else "total"
        path = f"/api/v1/unique-tournament/{tournament_id}/season/{season_id}/standings/{type_}"
        _url, payload = self._get(path, {}, ttl)
        return payload

    def event_odds(self, event_id: int, provider_id: int = 1, ttl: int = TTL_SCHEDULE) -> Any:
        """Quote di un evento per un bookmaker (provider_id, default 1):
        /api/v1/event/{event_id}/odds/{providerId}/all

        Se questa API offre davvero quote reali per evento, potrebbe coprire
        anche corner/cartellini come mercati quotati (da verificare: non e'
        detto che il provider_id=1 copra questi campionati o quei mercati)."""
        path = f"/api/v1/event/{event_id}/odds/{provider_id}/all"
        _url, payload = self._get(path, {}, ttl)
        return payload

    def probe_raw(self, path: str, params: Dict[str, Any], ttl: int = 300) -> Any:
        """Risposta grezza di un path qualsiasi, per esplorare l'API a mano."""
        path = path if path.startswith("/") else f"/{path}"
        _url, payload = self._get(path, params, ttl)
        return payload


#: valori di incidentClass osservati per i cartellini. "yellowRed" e' il
#: secondo giallo che diventa espulsione: conta come rosso, non come giallo
#: aggiuntivo, altrimenti si conterebbe un cartellino di troppo.
_RED_CARD_CLASSES = {"red", "yellowRed"}
_YELLOW_CARD_CLASSES = {"yellow"}


def parse_card_totals(incidents_payload: Any) -> Optional[Dict[str, int]]:
    """Conta i cartellini per squadra da /event/{id}/incidents.

    Confermato su una risposta reale (Fiorentina-Frosinone, 2026-08-30):
    ogni cartellino e' un elemento con incidentType == "card", isHome (bool)
    e incidentClass ("yellow" | "red" | "yellowRed" per il secondo giallo).

    Ritorna {"home_yellow", "home_red", "away_yellow", "away_red"}, oppure
    None se il payload non ha la forma attesa (partita non ancora iniziata,
    o l'API ha cambiato struttura): meglio niente dato che un dato sbagliato
    spacciato per giusto.
    """
    if not isinstance(incidents_payload, dict):
        return None
    incidents = incidents_payload.get("incidents")
    if not isinstance(incidents, list):
        return None

    counts = {"home_yellow": 0, "home_red": 0, "away_yellow": 0, "away_red": 0}
    for item in incidents:
        if not isinstance(item, dict) or item.get("incidentType") != "card":
            continue
        side = "home" if item.get("isHome") else "away"
        card_class = item.get("incidentClass")
        if card_class in _RED_CARD_CLASSES:
            counts[f"{side}_red"] += 1
        elif card_class in _YELLOW_CARD_CLASSES:
            counts[f"{side}_yellow"] += 1
        # classi non riconosciute vengono ignorate, non contate a caso
    return counts
