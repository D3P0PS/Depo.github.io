"""Confronto fra probabilita' del modello e quote di mercato de-viggate."""

from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .config import Settings
from .devig import consensus_fair
from .football_data import Fixture
from .matching import outcome_role
from .model import FixtureModel, LeagueModel, expected_goals, simulate_fixture
from .odds_types import MARKET_BTTS, MARKET_H2H, MARKET_TOTALS, OddsEvent

# Oltre questa soglia un edge e' quasi sempre un problema di dati (quota
# stantia, squadre abbinate male) piuttosto che un'occasione reale.
IMPLAUSIBLE_EDGE_PCT = 15.0

RELIABILITY_OK = "OK"
RELIABILITY_LOW = "BASSA"
RELIABILITY_NONE = "INSUFF."


@dataclass
class EdgeRow:
    kickoff: dt.datetime
    competition: str
    match_label: str
    market: str
    selection: str
    odds: Optional[float]
    book: str
    n_books: int
    avg_overround: Optional[float]
    p_model: float
    p_model_lo: float
    p_model_hi: float
    p_market: Optional[float]
    edge_pct: Optional[float]        # valore atteso: p * quota - 1, in %
    edge_lo: Optional[float]
    edge_hi: Optional[float]
    delta_pp: Optional[float]        # differenza di probabilita', in punti %
    reliability: str
    reliability_note: str
    lam_home: float
    lam_away: float
    home_matches: int
    away_matches: int
    note: str = ""

    @property
    def sort_key(self) -> Tuple[int, float]:
        # le righe senza quota finiscono in fondo, ma restano visibili
        return (0, -self.edge_pct) if self.edge_pct is not None else (1, 0.0)


# ------------------------------------------------------------- affidabilita'
def assess_reliability(
    league: LeagueModel,
    home_matches: int,
    away_matches: int,
    settings: Settings,
    home_name: str = "la squadra di casa",
    away_name: str = "la squadra in trasferta",
) -> Tuple[str, str]:
    reasons: List[str] = []
    low = min(home_matches, away_matches)

    if low == 0:
        # dire quale delle due manca, non solo che manca qualcosa
        missing = []
        if home_matches == 0:
            missing.append(f"{home_name} non ha partite in casa")
        if away_matches == 0:
            missing.append(f"{away_name} non ha partite in trasferta")
        return (
            RELIABILITY_NONE,
            " e ".join(missing)
            + " nel periodo considerato: quel lato della stima viene dalla sola "
            "media di lega, non dalla squadra. Tipico di neopromosse",
        )
    if low < settings.min_matches:
        scarce = home_name if home_matches <= away_matches else away_name
        side = "in casa" if home_matches <= away_matches else "in trasferta"
        reasons.append(
            f"{scarce} ha solo {low} partite {side} "
            f"(minimo consigliato {settings.min_matches}); tipico di neopromosse "
            "o inizio stagione"
        )
    if league.matches_used < 40:
        reasons.append(
            f"campionato con appena {league.matches_used} partite giocate nel "
            "periodo considerato: medie di lega poco stabili"
        )
    if reasons:
        return RELIABILITY_LOW, "; ".join(reasons)
    return RELIABILITY_OK, ""


# ------------------------------------------------------- estrazione mercati
def _collect_h2h(event: OddsEvent) -> List[Tuple[str, List[float], List[str]]]:
    """[(book, [quota_home, quota_draw, quota_away], [chiavi])] per book completo."""
    out = []
    for quote in event.markets.get(MARKET_H2H, []):
        prices: Dict[str, float] = {}
        for o in quote.outcomes:
            role = outcome_role(o.name, event.home_team, event.away_team)
            if role:
                prices[role] = o.price
        if len(prices) == 3:
            out.append(
                (quote.book_title, [prices["home"], prices["draw"], prices["away"]],
                 ["1X2:home", "1X2:draw", "1X2:away"])
            )
    return out


def _collect_totals(event: OddsEvent) -> Dict[float, List[Tuple[str, List[float], List[str]]]]:
    by_line: Dict[float, List[Tuple[str, List[float], List[str]]]] = {}
    for quote in event.markets.get(MARKET_TOTALS, []):
        grouped: Dict[float, Dict[str, float]] = {}
        for o in quote.outcomes:
            if o.point is None:
                continue
            grouped.setdefault(o.point, {})[o.name.strip().lower()] = o.price
        for point, prices in grouped.items():
            if "over" in prices and "under" in prices:
                tag = f"{point:g}"
                by_line.setdefault(point, []).append(
                    (quote.book_title, [prices["over"], prices["under"]],
                     [f"OU{tag}:over", f"OU{tag}:under"])
                )
    return by_line


def _collect_btts(event: OddsEvent) -> List[Tuple[str, List[float], List[str]]]:
    out = []
    for quote in event.markets.get(MARKET_BTTS, []):
        prices = {o.name.strip().lower(): o.price for o in quote.outcomes}
        if "yes" in prices and "no" in prices:
            out.append(
                (quote.book_title, [prices["yes"], prices["no"]],
                 ["BTTS:yes", "BTTS:no"])
            )
    return out


def _best_price(
    quotes: Sequence[Tuple[str, List[float], List[str]]], index: int
) -> Tuple[float, str]:
    book, price = max(((b, prices[index]) for b, prices, _ in quotes), key=lambda t: t[1])
    return price, book


# ----------------------------------------------------------------- analisi
MARKET_LABELS = {
    "1X2:home": ("1X2", "1 (casa)"),
    "1X2:draw": ("1X2", "X (pareggio)"),
    "1X2:away": ("1X2", "2 (trasferta)"),
    "BTTS:yes": ("BTTS", "Goal (si')"),
    "BTTS:no": ("BTTS", "No Goal"),
}


def _labels(market_id: str) -> Tuple[str, str]:
    if market_id in MARKET_LABELS:
        return MARKET_LABELS[market_id]
    base, sel = market_id.split(":", 1)
    line = base[2:]
    return (f"Over/Under {line}", f"{sel.capitalize()} {line}")


def analyze_fixture(
    fixture: Fixture,
    event: Optional[OddsEvent],
    league: LeagueModel,
    settings: Settings,
) -> Tuple[FixtureModel, List[EdgeRow]]:
    # linee Over/Under: quelle richieste piu' quelle realmente quotate
    totals_quotes = _collect_totals(event) if event else {}
    lines = sorted({*settings.totals_lines, *totals_quotes.keys()})
    lines = [l for l in lines if 0.5 <= l <= 6.5]
    local = dataclasses.replace(settings, totals_lines=lines or [2.5])

    xg = expected_goals(league, fixture.home_id, fixture.away_id, local)
    model = simulate_fixture(xg, local)
    reliability, note = assess_reliability(
        league, xg.home_matches, xg.away_matches, local,
        fixture.home_name, fixture.away_name,
    )

    label = f"{fixture.home_name} - {fixture.away_name}"
    rows: List[EdgeRow] = []

    def add_group(quotes, market_ids, missing_note=""):
        if not quotes:
            for market_id in market_ids:
                if market_id not in model.probs:
                    continue
                lo, hi = model.prob_ci.get(market_id, (model.probs[market_id],) * 2)
                rows.append(_make_row(
                    fixture, label, market_id, None, "-", 0, None,
                    model.probs[market_id], lo, hi, None,
                    reliability, note, xg, missing_note,
                ))
            return

        consensus = consensus_fair([(b, prices) for b, prices, _ in quotes],
                                   local.devig_method)
        fair = consensus["probs"]
        for index, market_id in enumerate(market_ids):
            if market_id not in model.probs:
                continue
            price, book = _best_price(quotes, index)
            p_model_raw = model.probs[market_id]
            p_market = fair[index] if index < len(fair) else None
            p_used = p_model_raw
            if p_market is not None and local.market_blend > 0:
                p_used = (1 - local.market_blend) * p_model_raw + local.market_blend * p_market
            lo, hi = model.prob_ci.get(market_id, (p_model_raw, p_model_raw))
            if local.market_blend > 0 and p_market is not None:
                lo = (1 - local.market_blend) * lo + local.market_blend * p_market
                hi = (1 - local.market_blend) * hi + local.market_blend * p_market
            rows.append(_make_row(
                fixture, label, market_id, price, book, consensus["books"],
                consensus["avg_overround"], p_used, lo, hi, p_market,
                reliability, note, xg,
                "linea con possibilita' di rimborso (push)"
                if model.probs.get(market_id.split(':')[0] + ":push") else "",
            ))

    if event:
        add_group(_collect_h2h(event), ["1X2:home", "1X2:draw", "1X2:away"],
                  "quote 1X2 non disponibili per questo evento")
        for line in lines:
            tag = f"{line:g}"
            add_group(totals_quotes.get(line, []), [f"OU{tag}:over", f"OU{tag}:under"],
                      f"quote Over/Under {tag} non disponibili")
        add_group(_collect_btts(event), ["BTTS:yes", "BTTS:no"],
                  "mercato BTTS non coperto dal piano The Odds API in uso")
    else:
        for market_id in list(model.probs):
            if market_id.endswith(":push"):
                continue
            lo, hi = model.prob_ci.get(market_id, (model.probs[market_id],) * 2)
            rows.append(_make_row(
                fixture, label, market_id, None, "-", 0, None,
                model.probs[market_id], lo, hi, None, reliability, note, xg,
                "nessuna quota abbinata a questo incontro",
            ))

    return model, rows


def _make_row(
    fixture: Fixture,
    label: str,
    market_id: str,
    odds: Optional[float],
    book: str,
    n_books: int,
    avg_overround: Optional[float],
    p_model: float,
    p_lo: float,
    p_hi: float,
    p_market: Optional[float],
    reliability: str,
    reliability_note: str,
    xg,
    note: str,
) -> EdgeRow:
    market, selection = _labels(market_id)
    edge = edge_lo = edge_hi = delta = None
    if odds:
        edge = (p_model * odds - 1.0) * 100.0
        edge_lo = (p_lo * odds - 1.0) * 100.0
        edge_hi = (p_hi * odds - 1.0) * 100.0
        if abs(edge) > IMPLAUSIBLE_EDGE_PCT:
            extra = (
                f"edge oltre {IMPLAUSIBLE_EDGE_PCT:g}% in valore assoluto: prima di "
                "crederci, verificare che le squadre siano abbinate correttamente "
                "fra le due fonti e che la quota non sia ferma da ore"
            )
            note = f"{note}; {extra}" if note else extra
    if p_market is not None:
        delta = (p_model - p_market) * 100.0
    return EdgeRow(
        kickoff=fixture.kickoff,
        competition=fixture.competition,
        match_label=label,
        market=market,
        selection=selection,
        odds=odds,
        book=book,
        n_books=n_books,
        avg_overround=avg_overround,
        p_model=p_model,
        p_model_lo=p_lo,
        p_model_hi=p_hi,
        p_market=p_market,
        edge_pct=edge,
        edge_lo=edge_lo,
        edge_hi=edge_hi,
        delta_pp=delta,
        reliability=reliability,
        reliability_note=reliability_note,
        lam_home=xg.home,
        lam_away=xg.away,
        home_matches=xg.home_matches,
        away_matches=xg.away_matches,
        note=note,
    )
