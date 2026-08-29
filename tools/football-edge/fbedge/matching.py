"""Abbinamento fra i fixture di football-data.org e gli eventi di The Odds API.

I nomi squadra differiscono fra le due fonti ("Internazionale" vs "Inter Milan"),
quindi si combinano: normalizzazione, tabella di alias, similarita' testuale e
vicinanza dell'orario di inizio.
"""

from __future__ import annotations

import datetime as dt
import difflib
import re
import unicodedata
from typing import Dict, List, Optional, Tuple

from .config import NOISE_TOKENS, TEAM_ALIASES
from .football_data import Fixture
from .odds_api import OddsEvent


def normalize_team(name: str) -> str:
    """minuscolo, senza accenti, senza punteggiatura e senza sigle societarie."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    text = TEAM_ALIASES.get(text, text)
    tokens = [t for t in text.split() if t not in NOISE_TOKENS]
    if not tokens:                       # nome composto solo da sigle
        tokens = text.split()
    normalized = " ".join(tokens)
    return TEAM_ALIASES.get(normalized, normalized)


def name_similarity(a: str, b: str) -> float:
    na, nb = normalize_team(a), normalize_team(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    # un nome contenuto nell'altro ("verona" / "hellas verona") vale molto
    if na in nb or nb in na:
        return 0.92
    tokens_a, tokens_b = set(na.split()), set(nb.split())
    jaccard = len(tokens_a & tokens_b) / max(1, len(tokens_a | tokens_b))
    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    return max(ratio, 0.5 * ratio + 0.5 * jaccard)


def pair_score(fixture: Fixture, event: OddsEvent) -> float:
    return 0.5 * (
        name_similarity(fixture.home_name, event.home_team)
        + name_similarity(fixture.away_name, event.away_team)
    )


def match_fixtures(
    fixtures: List[Fixture],
    events: List[OddsEvent],
    threshold: float,
    kickoff_tolerance_minutes: int,
) -> Tuple[Dict[int, OddsEvent], List[Fixture]]:
    """Assegna a ogni fixture al massimo un evento quote (accoppiamento greedy)."""
    tolerance = dt.timedelta(minutes=kickoff_tolerance_minutes)
    candidates: List[Tuple[float, int, int]] = []
    for fi, fixture in enumerate(fixtures):
        for ei, event in enumerate(events):
            if abs(event.commence_time - fixture.kickoff) > tolerance:
                continue
            score = pair_score(fixture, event)
            if score >= threshold:
                candidates.append((score, fi, ei))

    candidates.sort(reverse=True)
    matched: Dict[int, OddsEvent] = {}
    used_fixtures, used_events = set(), set()
    for score, fi, ei in candidates:
        if fi in used_fixtures or ei in used_events:
            continue
        used_fixtures.add(fi)
        used_events.add(ei)
        matched[fixtures[fi].match_id] = events[ei]

    unmatched = [f for i, f in enumerate(fixtures) if i not in used_fixtures]
    return matched, unmatched


def outcome_role(
    outcome_name: str, home_team: str, away_team: str, threshold: float = 0.70
) -> Optional[str]:
    """Mappa il nome di un esito 1X2 su 'home' / 'draw' / 'away'.

    Sceglie il piu' simile fra le due squadre, non il primo sopra soglia:
    con nomi vicini ("Manchester City" / "Manchester United") la prima
    corrispondenza utile sarebbe spesso quella sbagliata.
    """
    if (outcome_name or "").strip().lower() in ("draw", "tie", "pareggio", "x"):
        return "draw"
    s_home = name_similarity(outcome_name, home_team)
    s_away = name_similarity(outcome_name, away_team)
    if max(s_home, s_away) < threshold:
        return None
    return "home" if s_home >= s_away else "away"
