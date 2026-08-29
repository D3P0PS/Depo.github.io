"""Accesso a football-data.org (API v4) per calendario, risultati e forma.

Piano gratuito: 10 richieste/minuto. Per limitare le chiamate scarichiamo
l'intero calendario stagionale di ogni competizione (1 richiesta) e da li'
ricaviamo sia le medie di lega sia lo storico di ogni squadra.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .config import Competition
from .httpcache import HttpClient, HttpError, RateLimiter, build_url

BASE = "https://api.football-data.org/v4"


@dataclass(frozen=True)
class PlayedMatch:
    date: dt.datetime
    competition: str
    home_id: int
    home_name: str
    away_id: int
    away_name: str
    home_goals: int
    away_goals: int


@dataclass(frozen=True)
class Fixture:
    match_id: int
    competition: str
    competition_name: str
    kickoff: dt.datetime
    home_id: int
    home_name: str
    away_id: int
    away_name: str
    matchday: Optional[int] = None


@dataclass
class LeagueHistory:
    competition: str
    matches: List[PlayedMatch] = field(default_factory=list)
    #: competizioni non scaricabili col piano corrente, con motivo
    skipped: Dict[str, str] = field(default_factory=dict)


def _parse_utc(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def current_season_start_year(today: Optional[dt.date] = None) -> int:
    """Le stagioni europee iniziano d'estate: luglio->giugno."""
    today = today or dt.date.today()
    return today.year if today.month >= 7 else today.year - 1


class FootballDataClient:
    def __init__(self, api_key: str, http: HttpClient):
        if not api_key:
            raise ValueError("FOOTBALL_DATA_API_KEY mancante")
        self.api_key = api_key
        self.http = http
        # il piano free consente 10 chiamate/minuto
        self.http.rate_limiter = self.http.rate_limiter or RateLimiter(10, 60.0)

    @property
    def _headers(self) -> Dict[str, str]:
        return {"X-Auth-Token": self.api_key}

    # ------------------------------------------------------------- calendario
    def fixtures(
        self,
        comp: Competition,
        date_from: dt.date,
        date_to: dt.date,
        ttl: int,
    ) -> List[Fixture]:
        url = build_url(
            f"{BASE}/competitions/{comp.code}/matches",
            {
                "dateFrom": date_from.isoformat(),
                "dateTo": date_to.isoformat(),
                "status": "SCHEDULED,TIMED",
            },
        )
        payload = self.http.get(url, self._headers, ttl=ttl).json()
        out: List[Fixture] = []
        for m in payload.get("matches", []):
            home, away = m.get("homeTeam") or {}, m.get("awayTeam") or {}
            if not home.get("id") or not away.get("id"):
                continue  # accoppiamento non ancora definito (playoff, coppe)
            out.append(
                Fixture(
                    match_id=m["id"],
                    competition=comp.code,
                    competition_name=comp.name,
                    kickoff=_parse_utc(m["utcDate"]),
                    home_id=home["id"],
                    home_name=home.get("shortName") or home.get("name", ""),
                    away_id=away["id"],
                    away_name=away.get("shortName") or away.get("name", ""),
                    matchday=m.get("matchday"),
                )
            )
        return sorted(out, key=lambda f: f.kickoff)

    # ------------------------------------------------------------- risultati
    def finished_matches(
        self, comp: Competition, season: int, ttl: int
    ) -> List[PlayedMatch]:
        url = build_url(
            f"{BASE}/competitions/{comp.code}/matches",
            {"season": season, "status": "FINISHED"},
        )
        payload = self.http.get(url, self._headers, ttl=ttl).json()
        out: List[PlayedMatch] = []
        for m in payload.get("matches", []):
            score = ((m.get("score") or {}).get("fullTime") or {})
            hg, ag = score.get("home"), score.get("away")
            if hg is None or ag is None:
                continue
            home, away = m.get("homeTeam") or {}, m.get("awayTeam") or {}
            if not home.get("id") or not away.get("id"):
                continue
            out.append(
                PlayedMatch(
                    date=_parse_utc(m["utcDate"]),
                    competition=comp.code,
                    home_id=home["id"],
                    home_name=home.get("shortName") or home.get("name", ""),
                    away_id=away["id"],
                    away_name=away.get("shortName") or away.get("name", ""),
                    home_goals=int(hg),
                    away_goals=int(ag),
                )
            )
        return out

    # ----------------------------------------------------------------- helper
    def load_history(
        self,
        comp: Competition,
        seasons: List[int],
        ttl: int,
    ) -> Tuple[List[PlayedMatch], Optional[str]]:
        """Ritorna (partite, motivo_di_esclusione). Nessun fallimento silenzioso."""
        matches: List[PlayedMatch] = []
        for season in seasons:
            try:
                matches.extend(self.finished_matches(comp, season, ttl))
            except HttpError as exc:
                if exc.status in (403, 429):
                    reason = (
                        "non inclusa nel piano football-data.org in uso"
                        if exc.status == 403
                        else "limite di richieste football-data.org raggiunto"
                    )
                    if not matches:
                        return [], reason
                    # la stagione corrente c'e', manca solo lo storico precedente
                    break
                raise
        return matches, None
