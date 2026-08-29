"""Rimozione del margine del bookmaker (overround) dalle quote.

Le quote lorde di un book sommano a piu' del 100% di probabilita' implicita:
la differenza e' il margine. Confrontare il modello con le probabilita' lorde
gonfierebbe gli edge negativi e sgonfierebbe quelli positivi, quindi il
margine va tolto prima del confronto.

Metodi implementati:
  * ``multiplicative`` - riscala proporzionalmente (il piu' semplice, tende a
    sottostimare la probabilita' dei favoriti);
  * ``shin`` - modello di Shin (1993), assume una quota di scommettitori
    informati; di norma piu' accurato sui mercati 1X2;
  * ``power`` - eleva le probabilita' grezze a un esponente comune.
"""

from __future__ import annotations

import math
from typing import Dict, List, Sequence, Tuple


def implied_raw(odds: Sequence[float]) -> List[float]:
    return [1.0 / o for o in odds]


def overround(odds: Sequence[float]) -> float:
    return sum(implied_raw(odds)) - 1.0


def _multiplicative(raw: Sequence[float]) -> List[float]:
    total = sum(raw)
    return [q / total for q in raw]


def _shin(raw: Sequence[float], tol: float = 1e-10, max_iter: int = 200) -> List[float]:
    """Trova z tale che le probabilita' di Shin sommino a 1 (bisezione)."""
    total = sum(raw)
    if total <= 1.0 or len(raw) < 2:
        return _multiplicative(raw)

    def probs_for(z: float) -> List[float]:
        if z <= 1e-12:
            return _multiplicative(raw)
        out = []
        for q in raw:
            root = math.sqrt(z * z + 4.0 * (1.0 - z) * q * q / total)
            out.append((root - z) / (2.0 * (1.0 - z)))
        return out

    lo, hi = 0.0, 0.99
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        s = sum(probs_for(mid))
        if abs(s - 1.0) < tol:
            break
        if s > 1.0:
            lo = mid
        else:
            hi = mid
    probs = probs_for(0.5 * (lo + hi))
    s = sum(probs)
    return [p / s for p in probs] if s > 0 else _multiplicative(raw)


def _power(raw: Sequence[float], tol: float = 1e-10, max_iter: int = 200) -> List[float]:
    """Trova k tale che sum(q_i^k) = 1."""
    if sum(raw) <= 1.0:
        return _multiplicative(raw)
    lo, hi = 0.5, 3.0
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        s = sum(q ** mid for q in raw)
        if abs(s - 1.0) < tol:
            break
        if s > 1.0:
            lo = mid
        else:
            hi = mid
    k = 0.5 * (lo + hi)
    probs = [q ** k for q in raw]
    s = sum(probs)
    return [p / s for p in probs] if s > 0 else _multiplicative(raw)


_METHODS = {
    "multiplicative": _multiplicative,
    "shin": _shin,
    "power": _power,
}


def fair_probabilities(odds: Sequence[float], method: str = "shin") -> List[float]:
    """Probabilita' 'eque' (senza margine) a partire dalle quote decimali."""
    if not odds or any(o <= 1.0 for o in odds):
        raise ValueError("quote decimali non valide (devono essere > 1.0)")
    fn = _METHODS.get(method)
    if fn is None:
        raise ValueError(f"metodo di devig sconosciuto: {method}")
    return fn(implied_raw(odds))


def consensus_fair(
    quotes: Sequence[Tuple[str, Sequence[float]]], method: str = "shin"
) -> Dict[str, object]:
    """Media delle probabilita' eque calcolate bookmaker per bookmaker.

    De-viggare ogni book separatamente e poi mediare e' piu' corretto che
    mediare le quote lorde, perche' i margini variano molto fra operatori.
    """
    per_book: List[List[float]] = []
    margins: List[float] = []
    for _book, odds in quotes:
        try:
            per_book.append(fair_probabilities(odds, method))
            margins.append(overround(odds))
        except (ValueError, ZeroDivisionError):
            continue
    if not per_book:
        return {"probs": [], "books": 0, "avg_overround": float("nan")}
    n_out = len(per_book[0])
    avg = [sum(b[i] for b in per_book) / len(per_book) for i in range(n_out)]
    total = sum(avg)
    if total > 0:
        avg = [p / total for p in avg]
    return {
        "probs": avg,
        "books": len(per_book),
        "avg_overround": sum(margins) / len(margins),
    }
