"""Controllo di calibrazione: il modello e' d'accordo col mercato?

Le note per riga non bastano. Se un modello e' mal calibrato, sbaglia su tutte
le righe insieme e ogni riga sembra un'occasione: e' precisamente il caso in
cui l'output va letto come sintomo, non come lista di scommesse.

Qui si misura l'accordo complessivo con il mercato e si dichiara un verdetto
sulla corsa intera, non sulla singola riga.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from .analysis import EdgeRow

#: soglie oltre le quali una corsa e' da considerare sospetta
MAX_MEAN_DEVIATION = 0.08      # scostamento medio dal mercato, in probabilita'
MAX_LONGSHOT_BIAS = 0.04       # sovrastima sistematica degli esiti improbabili
MAX_IMPLAUSIBLE_SHARE = 0.25   # quota di righe con |edge| oltre il 15%
MAX_PRICE_EDGE = 5.0           # edge medio dovuto alla sola dispersione, in %

LONGSHOT = 0.20                # p di mercato sotto cui un esito e' improbabile
FAVOURITE = 0.50


@dataclass
class Calibration:
    rows: int = 0
    mean_deviation: float = 0.0
    correlation: Optional[float] = None
    longshot_bias: Optional[float] = None
    favourite_bias: Optional[float] = None
    implausible_share: float = 0.0
    mean_price_edge: Optional[float] = None
    price_driven_rows: int = 0
    model_driven_rows: int = 0
    warnings: List[str] = field(default_factory=list)

    @property
    def suspect(self) -> bool:
        return bool(self.warnings)


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _correlation(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) < 3:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx > 0 and dy > 0 else None


def assess(rows: Sequence[EdgeRow]) -> Calibration:
    paired = [r for r in rows if r.p_market is not None and r.edge_pct is not None]
    result = Calibration(rows=len(paired))
    if not paired:
        return result

    model = [r.p_model for r in paired]
    market = [float(r.p_market) for r in paired]
    result.mean_deviation = sum(abs(a - b) for a, b in zip(model, market)) / len(paired)
    result.correlation = _correlation(model, market)

    longshots = [r.p_model - float(r.p_market) for r in paired
                 if float(r.p_market) <= LONGSHOT]
    favourites = [r.p_model - float(r.p_market) for r in paired
                  if float(r.p_market) >= FAVOURITE]
    result.longshot_bias = _mean(longshots)
    result.favourite_bias = _mean(favourites)

    result.implausible_share = (
        sum(1 for r in paired if abs(float(r.edge_pct)) > 15.0) / len(paired)
    )

    price_edges = [r.edge_price_pct for r in paired if r.edge_price_pct is not None]
    result.mean_price_edge = _mean(price_edges)
    for r in paired:
        if r.edge_price_pct is None or r.edge_model_pct is None:
            continue
        if abs(r.edge_price_pct) > abs(r.edge_model_pct):
            result.price_driven_rows += 1
        else:
            result.model_driven_rows += 1

    result.warnings = _warnings(result)
    return result


def _warnings(c: Calibration) -> List[str]:
    out: List[str] = []
    if c.mean_deviation > MAX_MEAN_DEVIATION:
        out.append(
            f"Il modello si scosta dal mercato di {c.mean_deviation * 100:.1f} punti "
            "di probabilita' in media. Su campionati liquidi il mercato e' ben "
            "calibrato: uno scostamento simile indica quasi sempre un problema "
            "del modello, non un'inefficienza del mercato."
        )
    if c.longshot_bias is not None and c.longshot_bias > MAX_LONGSHOT_BIAS:
        out.append(
            f"Sugli esiti che il mercato da' sotto il {LONGSHOT:.0%}, il modello "
            f"assegna in media {c.longshot_bias * 100:+.1f} punti in piu'. E' il "
            "sintomo tipico di un modello troppo piatto: con pochi dati le forze "
            "delle squadre vengono tirate verso la media e le partite squilibrate "
            "diventano equilibrate, gonfiando le quote alte."
        )
    if c.implausible_share > MAX_IMPLAUSIBLE_SHARE:
        out.append(
            f"Il {c.implausible_share:.0%} delle righe supera il 15% di edge in "
            "valore assoluto. Un edge reale e' raro e piccolo: una corsa in cui "
            "abbonda sta misurando un errore, non un'occasione."
        )
    if c.mean_price_edge is not None and c.mean_price_edge > MAX_PRICE_EDGE:
        out.append(
            f"Anche dando ragione al mercato, la quota migliore renderebbe in "
            f"media {c.mean_price_edge:+.1f}%. Su mercati liquidi non e' "
            "possibile: le quote raccolte sono probabilmente stantie, oppure "
            "mescolano operatori non confrontabili."
        )
    return out


def render(c: Calibration) -> str:
    """Blocco da stampare PRIMA della tabella, non dopo."""
    if not c.rows:
        return ""
    line = "=" * 118
    head = [line]

    if c.suspect:
        head += [
            "ATTENZIONE - QUESTA CORSA NON E' UTILIZZABILE COME LISTA DI OCCASIONI",
            line,
        ]
    else:
        head += ["CONTROLLO DI CALIBRAZIONE", line]

    corr = f"{c.correlation:.2f}" if c.correlation is not None else "n/d"
    head += [
        f"  Righe confrontate col mercato : {c.rows}",
        f"  Scostamento medio dal mercato : {c.mean_deviation * 100:.1f} punti di "
        "probabilita'",
        f"  Correlazione col mercato      : {corr}  (1.00 = accordo pieno)",
    ]
    if c.longshot_bias is not None:
        head.append(f"  Scarto sugli esiti improbabili: {c.longshot_bias * 100:+.1f} punti")
    if c.favourite_bias is not None:
        head.append(f"  Scarto sui favoriti           : {c.favourite_bias * 100:+.1f} punti")
    head.append(f"  Righe con |edge| oltre il 15% : {c.implausible_share:.0%}")
    if c.price_driven_rows or c.model_driven_rows:
        head.append(
            f"  Origine dell'edge             : {c.price_driven_rows} righe dalla "
            f"dispersione fra book, {c.model_driven_rows} dal modello"
        )

    if c.warnings:
        head.append("")
        for warning in c.warnings:
            head.append("  ! " + warning.replace("\n", "\n    "))
        head += [
            "",
            "  Cosa fare, in ordine di utilita':",
            "   1. --market-blend 0.3 avvicina le stime al mercato e taglia gli "
            "edge illusori;",
            "   2. escludere le righe marcate INSUFF., dove il modello non ha dati "
            "per stimare;",
            "   3. allungare la finestra di forma (--form-matches, --half-life) se "
            "il campionato e' appena iniziato;",
            "   4. leggere la colonna dell'edge di prezzo nel CSV/JSON: dove domina, "
            "il modello non c'entra e la quota va verificata a mano.",
        ]
    head.append(line)
    return "\n".join(head)
