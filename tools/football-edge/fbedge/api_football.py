"""Client per API-Football (api-sports.io) — statistiche extra non coperte da
football-data.org: corner, cartellini, tiri, formazioni.

Piano gratuito: 100 richieste/giorno (verificare il numero esatto con
--af-status, i piani cambiano nel tempo). Con quel budget non si puo'
permettere di ripetere ricerche o chiamate evitabili:

  * la mappatura nome-squadra -> team_id va risolta una volta e tenuta in
    cache il piu' a lungo possibile (un team_id non cambia mai);
  * le statistiche stagionali aggregate (un solo record per squadra) sono
    molto piu' economiche delle statistiche per singola partita.

Come per SharpAPI (vedi sharpapi.py e la sua storia nel changelog: campi
indovinati a memoria hanno gia' causato bug in questo stesso progetto), la
forma esatta delle risposte va verificata con i comandi diagnostici
(--af-status, --af-search-team, --af-leagues, --af-team-stats,
--af-fixtures, --af-fixture-stats, --af-probe) prima di scrivere qualsiasi
logica di estrazione dei campi. Questo modulo si ferma quindi all'accesso
grezzo alle risposte: la modellazione statistica di corner/cartellini viene
dopo, una volta viste risposte reali.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from .httpcache import HttpClient, HttpError, build_url

DEFAULT_BASE = "https://v3.football.api-sports.io"

#: cache lunga per dati che cambiano raramente o mai (id squadre, campionati)
TTL_STATIC = 86400 * 30
#: cache media per statistiche stagionali (si aggiornano dopo ogni giornata)
TTL_SEASON_STATS = 21600
#: cache lunga per partite gia' giocate: il risultato non cambia piu'
TTL_PLAYED_FIXTURE = 86400 * 7


class ApiFootballClient:
    #: il contatore di API-Football e' un budget giornaliero che si esaurisce
    usage_label = "richieste giornaliere"
    usage_is_budget = True

    def __init__(self, api_key: str, http: HttpClient, base: str = DEFAULT_BASE):
        if not api_key:
            raise ValueError("API_FOOTBALL_KEY mancante")
        self.api_key = api_key
        self.http = http
        self.base = base.rstrip("/")
        self.requests_remaining: Optional[str] = None
        self.requests_used: Optional[str] = None

    def _headers(self) -> Dict[str, str]:
        return {"x-apisports-key": self.api_key}

    def _get(self, path: str, params: Dict[str, Any], ttl: int) -> Tuple[str, Any]:
        url = build_url(f"{self.base}{path}", params)
        try:
            resp = self.http.get(url, headers=self._headers(), ttl=ttl)
        except HttpError as exc:
            if exc.status in (401, 403):
                raise HttpError(
                    exc.status, url,
                    "API_FOOTBALL_KEY non valida, scaduta o piano non attivo",
                ) from exc
            if exc.status == 429:
                raise HttpError(
                    429, url, "budget giornaliero di API-Football esaurito"
                ) from exc
            raise
        # nomi da confermare con --af-status: le API di api-sports.io in
        # genere espongono x-ratelimit-requests-{limit,remaining}, ma va
        # verificato sul piano realmente attivo prima di fidarsene nel footer.
        self.requests_remaining = resp.headers.get(
            "x-ratelimit-requests-remaining", self.requests_remaining
        )
        self.requests_used = resp.headers.get(
            "x-ratelimit-requests-limit", self.requests_used
        )
        return url, resp.json()

    # ------------------------------------------------------------ endpoint
    def status(self, ttl: int = 300) -> Any:
        """Info account/piano: /status."""
        _url, payload = self._get("/status", {}, ttl)
        return payload

    def leagues(self, name: Optional[str] = None, ttl: int = TTL_STATIC) -> Any:
        """Elenco campionati con i relativi id: /leagues[?search=...]."""
        params = {"search": name} if name else {}
        _url, payload = self._get("/leagues", params, ttl)
        return payload

    def search_teams(self, name: str, ttl: int = TTL_STATIC) -> Any:
        """Ricerca squadre per nome: /teams?search=... Cache lunga: il
        risultato di una ricerca per nome non cambia quasi mai."""
        _url, payload = self._get("/teams", {"search": name}, ttl)
        return payload

    def team_statistics(
        self, team_id: int, league_id: int, season: int, ttl: int = TTL_SEASON_STATS,
    ) -> Any:
        """Statistiche stagionali aggregate di una squadra in un campionato:
        /teams/statistics?team=...&league=...&season=..."""
        _url, payload = self._get(
            "/teams/statistics",
            {"team": team_id, "league": league_id, "season": season},
            ttl,
        )
        return payload

    def fixtures_by_team(
        self, team_id: int, league_id: int, season: int, last: int = 10,
        ttl: int = TTL_SEASON_STATS,
    ) -> Any:
        """Ultime N partite di una squadra: /fixtures?team=...&last=..."""
        _url, payload = self._get(
            "/fixtures",
            {"team": team_id, "league": league_id, "season": season, "last": last},
            ttl,
        )
        return payload

    def fixture_statistics(self, fixture_id: int, ttl: int = TTL_PLAYED_FIXTURE) -> Any:
        """Statistiche dettagliate di una partita gia' giocata (corner,
        cartellini, tiri, ...): /fixtures/statistics?fixture=..."""
        _url, payload = self._get("/fixtures/statistics", {"fixture": fixture_id}, ttl)
        return payload

    def probe_raw(self, path: str, params: Dict[str, Any], ttl: int = 300) -> Any:
        """Risposta grezza di un endpoint qualsiasi, per ispezione manuale."""
        _url, payload = self._get(path, params, ttl)
        return payload
