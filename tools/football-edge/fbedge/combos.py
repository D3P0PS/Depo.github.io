"""Suggerimenti di combinazioni ("bet builder") fra mercati-gol dello stesso match.

Calcola la probabilita' congiunta ESATTA dalla griglia Poisson bivariata del
modello, non il prodotto delle probabilita' singole: 1X2 e Over/Under sullo
stesso match sono correlati (es. "1 casa" e "Over 2.5" tendono ad andare
insieme piu' spesso di quanto darebbe l'indipendenza), quindi moltiplicare
gli edge come se fossero indipendenti sovrastimerebbe quasi sempre il
risultato.

Copre solo mercati basati sui gol (1X2, Over/Under, BTTS): l'unico spazio
campionario che il modello conosce. Corner, cartellini, tiri e primo tempo
non sono stimati da nessuna parte di questo strumento e non compaiono qui:
mostrare una quota per quei mercati significherebbe inventarla.

La "quota equa" restituita e' quella del modello, non una quota reale di
bet builder: nessun provider di quote usato da questo tool fornisce prezzi
per combinazioni sullo stesso match. Va confrontata con quella vera del
bookmaker prima di scommettere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence

from .analysis import IMPLAUSIBLE_EDGE_PCT, RELIABILITY_OK, EdgeRow
from .config import Settings
from .model import joint_score_matrix

Predicate = Callable[[int, int], bool]


def _predicate(market_id: str) -> Predicate:
    family, sel = market_id.split(":", 1)
    if family == "1X2":
        return {
            "home": lambda x, y: x > y,
            "draw": lambda x, y: x == y,
            "away": lambda x, y: x < y,
        }[sel]
    if family == "BTTS":
        if sel == "yes":
            return lambda x, y: x >= 1 and y >= 1
        return lambda x, y: not (x >= 1 and y >= 1)
    if family.startswith("OU"):
        line = float(family[2:])
        if sel == "over":
            return lambda x, y: (x + y) > line
        if sel == "under":
            return lambda x, y: (x + y) < line
    raise ValueError(f"mercato non gestito per combo: {market_id}")


def combo_probability(
    lam_home: float, lam_away: float, lambda_cov: float, max_goals: int,
    market_ids: Sequence[str],
) -> float:
    """Probabilita' congiunta di piu' esiti-gol sullo stesso match."""
    matrix = joint_score_matrix(lam_home, lam_away, lambda_cov, max_goals)
    preds = [_predicate(m) for m in market_ids]
    n = len(matrix) - 1
    total = 0.0
    for x in range(n + 1):
        row = matrix[x]
        for y in range(n + 1):
            p = row[y]
            if p and all(pred(x, y) for pred in preds):
                total += p
    return total


def _market_family(market_id: str) -> str:
    return market_id.split(":", 1)[0]


@dataclass
class ComboSuggestion:
    legs: List[EdgeRow]
    joint_prob: float
    fair_odds: float


def suggest_combos(
    match_rows: Sequence[EdgeRow], settings: Settings, max_combos: int = 2,
) -> List[ComboSuggestion]:
    """Combo a 2 gambe fra segnali gia' positivi dello stesso match.

    Prende solo righe con quota reale, affidabilita' OK ed edge positivo ma
    plausibile (sotto la soglia oltre la quale un edge e' quasi sempre un
    errore di dati). Una sola gamba per famiglia di mercato (la migliore per
    edge), cosi' non si propongono mai due selezioni della stessa famiglia
    che sarebbero ridondanti o contraddittorie fra loro (es. Over e Under
    della stessa linea).
    """
    candidates = [
        r for r in match_rows
        if r.odds is not None
        and r.reliability == RELIABILITY_OK
        and r.edge_pct is not None
        and 0 < r.edge_pct <= IMPLAUSIBLE_EDGE_PCT
        and r.market_id
    ]
    if len(candidates) < 2:
        return []

    best_per_family: Dict[str, EdgeRow] = {}
    for r in candidates:
        fam = _market_family(r.market_id)
        current = best_per_family.get(fam)
        if current is None or (r.edge_pct or 0) > (current.edge_pct or 0):
            best_per_family[fam] = r

    legs = list(best_per_family.values())
    if len(legs) < 2:
        return []

    combos: List[ComboSuggestion] = []
    for i in range(len(legs)):
        for j in range(i + 1, len(legs)):
            a, b = legs[i], legs[j]
            joint = combo_probability(
                a.lam_home, a.lam_away, settings.lambda_cov, settings.max_goals,
                [a.market_id, b.market_id],
            )
            if joint <= 0:
                continue
            combos.append(ComboSuggestion(legs=[a, b], joint_prob=joint, fair_odds=1.0 / joint))

    combos.sort(key=lambda c: (c.legs[0].edge_pct or 0) + (c.legs[1].edge_pct or 0), reverse=True)
    return combos[:max_combos]
