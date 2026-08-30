"""Storico cartellini per squadra da SofaScore, con budget di richieste limitato.

Strategia (non "tutte le squadre di tutti i campionati", troppo costoso sul
piano gratuito): il modello sui gol gira per primo, gratis; solo per le
partite del giorno con l'edge migliore si guarda anche lo storico cartellini
delle due squadre coinvolte, e solo se non gia' in cache e non scaduto.

Il collegamento fixture (football-data) -> squadra (SofaScore) passa
dall'evento SofaScore della stessa giornata/campionato: e' li' che si legge
gia' l'id squadra SofaScore, non serve una ricerca per nome a parte.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .analysis import EdgeRow
from .config import COMPETITIONS, Competition
from .httpcache import HttpError
from .matching import name_similarity
from .sofascore import SofaScoreClient, parse_card_totals
from .sofascore_cache import TeamCardStats

#: partite storiche da guardare per costruire la media di una squadra
HISTORY_MATCHES = 5
#: soglia di similarita' nome per accettare un abbinamento fixture<->evento
NAME_MATCH_THRESHOLD = 0.72


def find_sofascore_event(
    client: SofaScoreClient, competition: Competition, date: str,
    home_name: str, away_name: str,
) -> Optional[dict]:
    """Trova l'evento SofaScore di una partita, dato campionato+data+squadre.

    Ritorna None se il campionato non ha ancora un category/tournament id
    scoperto (vedi config.py), se l'API non risponde nella forma attesa, o
    se nessun evento supera la soglia di somiglianza sui nomi.
    """
    if competition.sofascore_category_id is None or competition.sofascore_tournament_id is None:
        return None
    try:
        payload = client.category_scheduled_events(competition.sofascore_category_id, date)
    except HttpError:
        return None
    if not isinstance(payload, dict):
        return None
    events = payload.get("events")
    if not isinstance(events, list):
        return None

    best_score, best_event = 0.0, None
    for event in events:
        if not isinstance(event, dict):
            continue
        tour = event.get("tournament", {})
        unique = tour.get("uniqueTournament", {}) if isinstance(tour, dict) else {}
        if unique.get("id") != competition.sofascore_tournament_id:
            continue
        home = event.get("homeTeam", {})
        away = event.get("awayTeam", {})
        if not isinstance(home, dict) or not isinstance(away, dict):
            continue
        score = 0.5 * (
            name_similarity(home_name, home.get("name", ""))
            + name_similarity(away_name, away.get("name", ""))
        )
        if score > best_score:
            best_score, best_event = score, event

    if best_score < NAME_MATCH_THRESHOLD:
        return None
    return best_event


def fetch_team_card_history(
    client: SofaScoreClient, team_id: int, team_name: str,
    n_matches: int = HISTORY_MATCHES,
) -> Optional[TeamCardStats]:
    """Media cartellini di una squadra sulle sue ultime N partite finite.

    Usa team_events(), endpoint non confermato dalla documentazione ufficiale
    vista finora: se la risposta non ha la forma attesa, torna None invece
    di inventare una media da dati parziali o sbagliati.
    """
    try:
        events_payload = client.team_events(team_id, page=0, direction="last")
    except HttpError:
        return None
    if not isinstance(events_payload, dict):
        return None
    events = events_payload.get("events")
    if not isinstance(events, list):
        return None

    yellow_total = red_total = used = 0
    for event in events:
        if used >= n_matches:
            break
        if not isinstance(event, dict):
            continue
        if event.get("status", {}).get("type") != "finished":
            continue
        event_id = event.get("id")
        if not isinstance(event_id, int):
            continue
        home = event.get("homeTeam", {})
        is_home = isinstance(home, dict) and home.get("id") == team_id

        try:
            incidents_payload = client.event_incidents(event_id)
        except HttpError:
            continue
        counts = parse_card_totals(incidents_payload)
        if counts is None:
            continue

        if is_home:
            yellow_total += counts["home_yellow"]
            red_total += counts["home_red"]
        else:
            yellow_total += counts["away_yellow"]
            red_total += counts["away_red"]
        used += 1

    if used == 0:
        return None

    return TeamCardStats(
        team_id=team_id,
        team_name=team_name,
        updated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        matches_used=used,
        yellow_avg=round(yellow_total / used, 2),
        red_avg=round(red_total / used, 2),
    )


def top_matches_for_enrichment(
    rows: Sequence[EdgeRow], max_matches: int, now: Optional[dt.datetime] = None,
) -> List[EdgeRow]:
    """Le N partite col miglior edge, una per match (non una per mercato).

    Priorita' a chi deve ancora giocare: su una partita gia' calciata la
    "verifica statistica" non serve piu' a nessuno, la scommessa non e' piu'
    piazzabile. Le partite gia' iniziate riempiono solo gli eventuali posti
    avanzati, non scavalcano mai quelle ancora da giocare.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    best_per_match: Dict[Tuple[dt.datetime, str, str], EdgeRow] = {}
    for row in rows:
        if row.edge_pct is None:
            continue
        key = (row.kickoff, row.competition, row.match_label)
        current = best_per_match.get(key)
        if current is None or row.edge_pct > current.edge_pct:
            best_per_match[key] = row

    upcoming = [r for r in best_per_match.values() if r.kickoff > now]
    started = [r for r in best_per_match.values() if r.kickoff <= now]
    upcoming.sort(key=lambda r: r.edge_pct or 0.0, reverse=True)
    started.sort(key=lambda r: r.edge_pct or 0.0, reverse=True)

    ranked = upcoming[:max_matches]
    if len(ranked) < max_matches:
        ranked += started[: max_matches - len(ranked)]
    return ranked


def _split_match_label(label: str) -> Tuple[str, str]:
    if " - " in label:
        home, _, away = label.partition(" - ")
        return home, away
    return label, ""


@dataclass
class MatchCardCheck:
    home: Optional[TeamCardStats] = None
    away: Optional[TeamCardStats] = None
    note: str = ""


def enrich_top_matches(
    rows: Sequence[EdgeRow],
    client: Optional[SofaScoreClient],
    cache: Dict[int, TeamCardStats],
    max_matches: int,
    max_requests: int,
) -> Dict[str, MatchCardCheck]:
    """Arricchisce solo le top N partite del giorno, nel budget di richieste dato.

    Aggiorna `cache` sul posto (chi chiama e' responsabile di salvarla su
    disco dopo). Le squadre gia' in cache e non scadute non consumano
    budget: vengono riusate cosi' come sono.
    """
    results: Dict[str, MatchCardCheck] = {}
    if client is None:
        return results

    requests_left = max_requests
    for row in top_matches_for_enrichment(rows, max_matches):
        competition = COMPETITIONS.get(row.competition)
        if competition is None or competition.sofascore_category_id is None:
            results[row.match_label] = MatchCardCheck(
                note="campionato non ancora collegato a SofaScore"
            )
            continue

        date_str = row.kickoff.date().isoformat()
        home_label, away_label = _split_match_label(row.match_label)
        event = find_sofascore_event(client, competition, date_str, home_label, away_label)
        if event is None:
            results[row.match_label] = MatchCardCheck(
                note="evento non trovato su SofaScore per questa partita"
            )
            continue

        home_team = event.get("homeTeam", {}) if isinstance(event, dict) else {}
        away_team = event.get("awayTeam", {}) if isinstance(event, dict) else {}
        home_id, away_id = home_team.get("id"), away_team.get("id")

        for team_id, team_name, fallback_name in (
            (home_id, home_team.get("name"), home_label),
            (away_id, away_team.get("name"), away_label),
        ):
            if team_id is None:
                continue
            current = cache.get(team_id)
            if current is not None and not current.is_stale():
                continue  # gia' fresco: zero costo
            if requests_left <= 0:
                continue  # budget esaurito per questa corsa: si tiene il vecchio dato, se c'e'
            fresh = fetch_team_card_history(client, team_id, team_name or fallback_name)
            requests_left -= 1
            if fresh is not None:
                cache[team_id] = fresh

        note = "" if requests_left > 0 or (home_id in cache and away_id in cache) else (
            "budget di richieste esaurito per questa corsa: alcuni dati "
            "potrebbero mancare o essere vecchi, si completano al prossimo giro"
        )
        results[row.match_label] = MatchCardCheck(
            home=cache.get(home_id), away=cache.get(away_id), note=note,
        )

    return results
