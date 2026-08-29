"""Verifica del modello su dati sintetici, senza rete e senza chiavi API.

Serve a controllare che la matematica sia coerente (probabilita' che sommano
a 1, medie marginali corrette, devig, segno dell'edge, marcatura delle righe
poco affidabili) e a mostrare l'aspetto dell'output prima di spendere crediti
API.
"""

from __future__ import annotations

import datetime as dt
import math
import random
from typing import List, Tuple

from .analysis import RELIABILITY_OK, analyze_fixture
from .config import Settings
from .devig import fair_probabilities
from .football_data import Fixture, PlayedMatch
from .model import (
    build_league_model,
    joint_score_matrix,
    market_probabilities,
    poisson_pmf,
)
from .odds_types import BookQuote, OddsEvent, Outcome
from .report import SEPARATOR, render_footer, render_notes, render_table

# Frasi che l'output non deve mai contenere: nessun esito e' presentato
# come certo o garantito.
FORBIDDEN_PHRASES = [
    "pick sicuro", "scommessa sicura", "colpo sicuro", "vincita garantita",
    "certezza matematica", "vincita assicurata", "esito garantito",
]


def _poisson_sample(rng: random.Random, lam: float) -> int:
    """Knuth: sufficiente per i lambda piccoli del calcio."""
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _synthetic_league(rng: random.Random, now: dt.datetime) -> Tuple[List[PlayedMatch], dict]:
    """Campionato finto: 8 squadre consolidate + 1 neopromossa con 2 partite."""
    labels = ["Alfa", "Bravo", "Cortina", "Delta", "Epiro", "Fenice", "Gaeta", "Halberd"]
    strengths = {i: 0.75 + 0.12 * i for i in range(1, 9)}   # attacco relativo
    names = {i: labels[i - 1] for i in range(1, 9)}
    names[99] = "Neopromossa"
    strengths[99] = 0.85

    matches: List[PlayedMatch] = []
    established = list(range(1, 9))
    day = 0
    for home in established:
        for away in established:
            if home == away:
                continue
            day += 3
            lam_h = 1.45 * strengths[home] / strengths[away]
            lam_a = 1.15 * strengths[away] / strengths[home]
            matches.append(
                PlayedMatch(
                    date=now - dt.timedelta(days=200 - day % 200),
                    competition="TEST",
                    home_id=home, home_name=names[home],
                    away_id=away, away_name=names[away],
                    home_goals=_poisson_sample(rng, lam_h),
                    away_goals=_poisson_sample(rng, lam_a),
                )
            )
    # la neopromossa ha giocato pochissimo: 2 partite in casa, 1 in trasferta
    for i, (h, a) in enumerate([(99, 3), (99, 5), (4, 99)]):
        matches.append(
            PlayedMatch(
                date=now - dt.timedelta(days=20 - 7 * i),
                competition="TEST",
                home_id=h, home_name=names[h],
                away_id=a, away_name=names[a],
                home_goals=_poisson_sample(rng, 1.3),
                away_goals=_poisson_sample(rng, 1.2),
            )
        )
    return matches, names


def _synthetic_event(kickoff: dt.datetime, home: str, away: str) -> OddsEvent:
    event = OddsEvent(
        event_id="test", sport_key="soccer_test", commence_time=kickoff,
        home_team=home, away_team=away,
    )
    event.markets["h2h"] = [
        BookQuote("bet365", "Bet365", [
            Outcome(home, 2.10), Outcome("Draw", 3.40), Outcome(away, 3.60)]),
        BookQuote("pinnacle", "Pinnacle", [
            Outcome(home, 2.18), Outcome("Draw", 3.45), Outcome(away, 3.55)]),
    ]
    event.markets["totals"] = [
        BookQuote("bet365", "Bet365", [
            Outcome("Over", 1.95, 2.5), Outcome("Under", 1.87, 2.5)]),
        BookQuote("pinnacle", "Pinnacle", [
            Outcome("Over", 2.00, 2.5), Outcome("Under", 1.92, 2.5)]),
    ]
    return event


def run_self_test(settings: Settings) -> int:
    failures: List[str] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        status = "OK  " if condition else "FAIL"
        print(f"  [{status}] {label}" + (f" - {detail}" if detail else ""))
        if not condition:
            failures.append(label)

    print(SEPARATOR)
    print("SELF-TEST (dati sintetici, nessuna chiamata di rete)")
    print(SEPARATOR)

    # 1) Poisson bivariato -------------------------------------------------
    matrix = joint_score_matrix(1.7, 1.05, settings.lambda_cov, settings.max_goals)
    total = sum(sum(row) for row in matrix)
    n = len(matrix) - 1
    mean_h = sum(x * sum(matrix[x]) for x in range(n + 1))
    mean_a = sum(y * sum(matrix[x][y] for x in range(n + 1)) for y in range(n + 1))
    check("la griglia dei risultati somma a 1", abs(total - 1) < 1e-9, f"{total:.12f}")
    check("media marginale casa = lambda", abs(mean_h - 1.7) < 5e-3, f"{mean_h:.4f}")
    check("media marginale trasferta = lambda", abs(mean_a - 1.05) < 5e-3, f"{mean_a:.4f}")
    check("pmf di Poisson normalizzata", abs(sum(poisson_pmf(1.3, 40)) - 1) < 1e-9)

    probs = market_probabilities(matrix, [2.5])
    check("1X2 somma a 1",
          abs(probs["1X2:home"] + probs["1X2:draw"] + probs["1X2:away"] - 1) < 1e-9)
    check("Over/Under 2.5 somma a 1",
          abs(probs["OU2.5:over"] + probs["OU2.5:under"] - 1) < 1e-9)
    check("BTTS somma a 1", abs(probs["BTTS:yes"] + probs["BTTS:no"] - 1) < 1e-9)

    # correlazione positiva indotta da lambda_3
    def correlation(cov: float) -> float:
        m = joint_score_matrix(1.7, 1.05, cov, 14)
        k = len(m) - 1
        ex = sum(x * sum(m[x]) for x in range(k + 1))
        ey = sum(y * sum(m[x][y] for x in range(k + 1)) for y in range(k + 1))
        exy = sum(x * y * m[x][y] for x in range(k + 1) for y in range(k + 1))
        return exy - ex * ey
    check("lambda_3 introduce covarianza positiva", correlation(0.15) > 0.1,
          f"cov={correlation(0.15):.4f}")
    check("lambda_3 = 0 -> punteggi indipendenti", abs(correlation(0.0)) < 1e-6)

    # 2) devig -------------------------------------------------------------
    odds = [2.10, 3.40, 3.60]
    for method in ("shin", "multiplicative", "power"):
        fair = fair_probabilities(odds, method)
        check(f"devig '{method}' somma a 1", abs(sum(fair) - 1) < 1e-8)
        check(f"devig '{method}' sotto le probabilita' lorde",
              all(f < 1 / o for f, o in zip(fair, odds)))

    # 3) modello di lega su dati sintetici ---------------------------------
    rng = random.Random(settings.seed)
    now = dt.datetime.now(dt.timezone.utc)
    matches, names = _synthetic_league(rng, now)
    league = build_league_model("TEST", matches, settings, now)
    check("medie di lega plausibili", 0.8 < league.mu_home < 2.5 and 0.6 < league.mu_away < 2.2,
          f"casa {league.mu_home:.2f} / trasferta {league.mu_away:.2f}")
    check("vantaggio del fattore campo ricostruito", league.mu_home > league.mu_away,
          f"{league.mu_home:.2f} > {league.mu_away:.2f}")
    strong, weak = league.teams[8], league.teams[1]
    check("attacco piu' forte riconosciuto", strong.att_home > weak.att_home,
          f"{strong.att_home:.2f} vs {weak.att_home:.2f}")
    check("difesa piu' forte riconosciuta", strong.def_home < weak.def_home,
          f"{strong.def_home:.2f} vs {weak.def_home:.2f}")
    newcomer = league.teams[99]
    check("squadra con pochi dati tirata verso la media di lega",
          abs(newcomer.att_home - 1.0) < abs(strong.att_home - 1.0),
          f"neopromossa {newcomer.att_home:.2f} vs consolidata {strong.att_home:.2f}")
    check("pochi dati -> incertezza maggiore",
          newcomer.se_att_home > strong.se_att_home,
          f"{newcomer.se_att_home:.3f} vs {strong.se_att_home:.3f}")
    check("incertezza limitata dal prior di popolazione",
          all(t.se_att_home <= 0.26 for t in league.teams.values()),
          f"max {max(t.se_att_home for t in league.teams.values()):.3f}")
    check("squadra senza dati -> forza 1.0 (shrinkage completo)",
          abs(build_league_model("T", [], settings, now).mu_home - 1.45) < 1e-9)

    # 4) pipeline completa sul fixture con la neopromossa -------------------
    kickoff = now + dt.timedelta(hours=6)
    fixture = Fixture(1, "TEST", "Campionato di test", kickoff,
                      99, names[99], 3, names[3])
    event = _synthetic_event(kickoff, names[99], names[3])
    _model, rows = analyze_fixture(fixture, event, league, settings)
    check("righe generate per il fixture", len(rows) >= 5, f"{len(rows)} righe")
    check("neopromossa marcata a bassa affidabilita'",
          all(r.reliability != RELIABILITY_OK for r in rows),
          rows[0].reliability)
    check("nessuna riga esclusa in silenzio",
          all(r.p_model is not None for r in rows))

    priced = [r for r in rows if r.odds]
    check("edge coerente con quota e probabilita'",
          all(abs(r.edge_pct - (r.p_model * r.odds - 1) * 100) < 1e-9 for r in priced))
    check("intervallo di confidenza ordinato",
          all(r.edge_lo <= r.edge_pct + 1e-9 and r.edge_pct <= r.edge_hi + 1e-9
              for r in priced))
    check("edge positivo se e solo se prob. modello > prob. implicita lorda",
          all((r.edge_pct > 0) == (r.p_model > 1 / r.odds) for r in priced))
    # Bet365 quota 2.10 la casa, Pinnacle 2.18: deve vincere la quota migliore.
    home_row = next(r for r in priced if r.market == "1X2" and r.selection.startswith("1"))
    check("viene usata la quota migliore fra i bookmaker",
          abs(home_row.odds - 2.18) < 1e-9 and home_row.book == "Pinnacle",
          f"{home_row.odds} @ {home_row.book}")
    check("consensus calcolato su piu' bookmaker", all(r.n_books == 2 for r in priced),
          f"{priced[0].n_books} book")

    # 5) l'output non deve mai suonare come una certezza --------------------
    fixture2 = Fixture(2, "TEST", "Campionato di test", kickoff, 8, names[8], 1, names[1])
    _m2, rows2 = analyze_fixture(fixture2, _synthetic_event(kickoff, names[8], names[1]),
                                 league, settings)
    all_rows = sorted(rows + rows2, key=lambda r: r.sort_key)
    text = "\n".join([
        render_table(all_rows, settings),
        render_notes(all_rows),
        render_footer({"unmatched": 0, "network_calls": 0, "cache_hits": 0}, settings,
                      sum(1 for r in all_rows if r.reliability != RELIABILITY_OK),
                      len(all_rows)),
    ])
    # spazi normalizzati: il testo dei limiti va a capo su piu' righe
    lowered = " ".join(text.lower().split())
    check("nessun linguaggio da 'pick sicuro' nell'output",
          all(phrase not in lowered for phrase in FORBIDDEN_PHRASES))
    check("ogni riga mostra probabilita' e intervallo",
          all(r.p_model_lo <= r.p_model <= r.p_model_hi for r in all_rows))
    check("i limiti dichiarati sono presenti nell'output",
          "LIMITI DEL MODELLO" in text
          and "formazioni ufficiali" in lowered
          and "non e' un profitto garantito" in lowered)

    print("\n" + SEPARATOR)
    print("ESEMPIO DI OUTPUT (dati sintetici, quote inventate)")
    print(SEPARATOR)
    print(text)

    print(SEPARATOR)
    if failures:
        print(f"SELF-TEST FALLITO: {len(failures)} controlli non superati")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("SELF-TEST SUPERATO: tutti i controlli sono passati.")
    return 0
