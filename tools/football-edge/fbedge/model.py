"""Modello statistico: forza attacco/difesa pesata + Poisson bivariato.

Passi:
 1. media pesata dei gol fatti/subiti nelle ultime N partite, separando casa e
    trasferta, con decadimento esponenziale (mezza vita configurabile);
 2. shrinkage bayesiano verso la media di lega, cosi' le squadre con poche
    partite (neopromosse, inizio stagione) tendono al valore medio invece di
    produrre stime instabili;
 3. gol attesi (lambda) per le due squadre;
 4. Poisson bivariato (Karlis-Ntzoufras) con componente comune lambda_3 per la
    correlazione fra i due punteggi;
 5. probabilita' di 1X2, Over/Under e BTTS dalla griglia congiunta;
 6. incertezza via Monte Carlo sui lambda stimati.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

import datetime as dt

from .config import Settings
from .football_data import PlayedMatch

# Pavimento sulla deviazione standard log-lambda: tiene conto, in modo
# grossolano, dell'errore di specificazione del modello (non solo campionario).
SIGMA_FLOOR = 0.10

# Dispersione tipica delle forze di attacco/difesa attorno alla media di lega.
# Fa da prior: una squadra senza dati non ha incertezza infinita, ha quella
# di una squadra qualunque estratta dal campionato.
PRIOR_STRENGTH_SD = 0.25


# --------------------------------------------------------------------- forma
@dataclass
class VenueForm:
    """Forma di una squadra in un singolo contesto (casa oppure trasferta)."""

    played: int = 0
    weight: float = 0.0          # somma dei pesi
    weight_sq: float = 0.0       # somma dei pesi al quadrato
    goals_for: float = 0.0       # gol fatti, pesati
    goals_against: float = 0.0   # gol subiti, pesati

    @property
    def n_eff(self) -> float:
        """Numero efficace di partite: (sum w)^2 / sum w^2."""
        return (self.weight ** 2 / self.weight_sq) if self.weight_sq > 0 else 0.0


@dataclass
class TeamStrength:
    team_id: int
    team_name: str
    home: VenueForm = field(default_factory=VenueForm)
    away: VenueForm = field(default_factory=VenueForm)
    att_home: float = 1.0
    def_home: float = 1.0
    att_away: float = 1.0
    def_away: float = 1.0
    se_att_home: float = PRIOR_STRENGTH_SD
    se_def_home: float = PRIOR_STRENGTH_SD
    se_att_away: float = PRIOR_STRENGTH_SD
    se_def_away: float = PRIOR_STRENGTH_SD


@dataclass
class LeagueModel:
    competition: str
    mu_home: float
    mu_away: float
    teams: Dict[int, TeamStrength]
    matches_used: int
    season_span_days: float


def _decay_weight(match_date: dt.datetime, ref: dt.datetime, half_life: float) -> float:
    age_days = max(0.0, (ref - match_date).total_seconds() / 86400.0)
    return 0.5 ** (age_days / half_life) if half_life > 0 else 1.0


def _venue_factor(
    goals: float,
    weight: float,
    baseline: float,
    overall_factor: float,
    prior_venue: float,
    pooled_info: float,
) -> Tuple[float, float]:
    """Fattore casa/trasferta con pooling a due livelli.

    Il valore specifico del contesto (es. attacco in casa) viene tirato verso
    il valore complessivo della squadra, che a sua volta e' tirato verso la
    media di lega. In questo modo un parametro non dipende solo dalle 6-10
    partite del singolo split.

    Ritorna (fattore, errore standard relativo). L'errore combina
    l'informazione del prior di popolazione, quella dell'altro split e quella
    delle partite osservate nello split.
    """
    posterior_w = weight + prior_venue
    factor = (goals + prior_venue * overall_factor * baseline) / (posterior_w * baseline)
    factor = max(factor, 1e-3)
    rate = max(factor * baseline, 1e-3)
    information = 1.0 / (PRIOR_STRENGTH_SD ** 2) + rate * (weight + pooled_info)
    return factor, 1.0 / math.sqrt(information)


def build_league_model(
    competition: str,
    matches: Sequence[PlayedMatch],
    settings: Settings,
    reference: dt.datetime,
) -> LeagueModel:
    past = [m for m in matches if m.date < reference]
    if not past:
        return LeagueModel(competition, 1.45, 1.15, {}, 0, 0.0)

    # --- medie di lega (pesate) --------------------------------------------
    tot_w = tot_hg = tot_ag = 0.0
    for m in past:
        w = _decay_weight(m.date, reference, settings.half_life_days)
        tot_w += w
        tot_hg += w * m.home_goals
        tot_ag += w * m.away_goals
    mu_home = max(tot_hg / tot_w, 0.2) if tot_w else 1.45
    mu_away = max(tot_ag / tot_w, 0.2) if tot_w else 1.15

    # --- partite per squadra, divise casa/trasferta, piu' recenti prima ----
    by_team_home: Dict[int, List[PlayedMatch]] = {}
    by_team_away: Dict[int, List[PlayedMatch]] = {}
    names: Dict[int, str] = {}
    for m in sorted(past, key=lambda x: x.date, reverse=True):
        by_team_home.setdefault(m.home_id, []).append(m)
        by_team_away.setdefault(m.away_id, []).append(m)
        names.setdefault(m.home_id, m.home_name)
        names.setdefault(m.away_id, m.away_name)

    teams: Dict[int, TeamStrength] = {}
    for team_id, name in names.items():
        strength = TeamStrength(team_id=team_id, team_name=name)

        for venue, subset, is_home in (
            (strength.home, by_team_home.get(team_id, []), True),
            (strength.away, by_team_away.get(team_id, []), False),
        ):
            for m in subset[: settings.form_matches]:
                w = _decay_weight(m.date, reference, settings.half_life_days)
                venue.played += 1
                venue.weight += w
                venue.weight_sq += w * w
                gf, ga = (m.home_goals, m.away_goals) if is_home else (m.away_goals, m.home_goals)
                venue.goals_for += w * gf
                venue.goals_against += w * ga

        k, kv = settings.prior_matches, settings.prior_venue
        home_form, away_form = strength.home, strength.away
        w_all = home_form.weight + away_form.weight

        # Livello 1: forza complessiva della squadra, rapporto fra gol reali e
        # gol attesi da una squadra media nello stesso mix casa/trasferta.
        exp_scored = home_form.weight * mu_home + away_form.weight * mu_away
        exp_conceded = home_form.weight * mu_away + away_form.weight * mu_home
        att_all = (home_form.goals_for + away_form.goals_for + k) / (exp_scored + k)
        def_all = (home_form.goals_against + away_form.goals_against + k) / (exp_conceded + k)

        # Quanta informazione l'altro split presta a questo (0 se non c'e' storia).
        pooled = kv * (w_all / (w_all + k)) if (w_all + k) > 0 else 0.0

        # Livello 2: specializzazione casa/trasferta.
        strength.att_home, strength.se_att_home = _venue_factor(
            home_form.goals_for, home_form.weight, mu_home, att_all, kv, pooled)
        strength.def_home, strength.se_def_home = _venue_factor(
            home_form.goals_against, home_form.weight, mu_away, def_all, kv, pooled)
        strength.att_away, strength.se_att_away = _venue_factor(
            away_form.goals_for, away_form.weight, mu_away, att_all, kv, pooled)
        strength.def_away, strength.se_def_away = _venue_factor(
            away_form.goals_against, away_form.weight, mu_home, def_all, kv, pooled)

        teams[team_id] = strength

    span = (max(m.date for m in past) - min(m.date for m in past)).days if past else 0
    return LeagueModel(competition, mu_home, mu_away, teams, len(past), float(span))


# ------------------------------------------------------------- gol attesi
@dataclass
class ExpectedGoals:
    home: float
    away: float
    sigma_home: float
    sigma_away: float
    home_matches: int
    away_matches: int
    home_n_eff: float
    away_n_eff: float


def expected_goals(
    league: LeagueModel,
    home_id: int,
    away_id: int,
    settings: Settings,
) -> ExpectedGoals:
    home = league.teams.get(home_id) or TeamStrength(home_id, "?")
    away = league.teams.get(away_id) or TeamStrength(away_id, "?")

    lam_home = league.mu_home * home.att_home * away.def_away
    lam_away = league.mu_away * away.att_away * home.def_home
    lam_home = min(max(lam_home, settings.lambda_floor), settings.lambda_ceiling)
    lam_away = min(max(lam_away, settings.lambda_floor), settings.lambda_ceiling)

    sigma_home = math.sqrt(home.se_att_home ** 2 + away.se_def_away ** 2 + SIGMA_FLOOR ** 2)
    sigma_away = math.sqrt(away.se_att_away ** 2 + home.se_def_home ** 2 + SIGMA_FLOOR ** 2)

    return ExpectedGoals(
        home=lam_home,
        away=lam_away,
        sigma_home=sigma_home,
        sigma_away=sigma_away,
        home_matches=home.home.played,
        away_matches=away.away.played,
        home_n_eff=home.home.n_eff,
        away_n_eff=away.away.n_eff,
    )


# -------------------------------------------------------- Poisson bivariato
def poisson_pmf(lam: float, n: int) -> List[float]:
    """Vettore [P(0), ..., P(n)] calcolato per ricorrenza."""
    lam = max(lam, 0.0)
    out = [math.exp(-lam)]
    for k in range(1, n + 1):
        out.append(out[-1] * lam / k)
    return out


def joint_score_matrix(
    lam_home: float, lam_away: float, lam_cov: float, max_goals: int
) -> List[List[float]]:
    """P(X=x, Y=y) con X = W1+W3, Y = W2+W3 (Poisson bivariato)."""
    l3 = max(0.0, min(lam_cov, 0.9 * min(lam_home, lam_away)))
    p1 = poisson_pmf(lam_home - l3, max_goals)
    p2 = poisson_pmf(lam_away - l3, max_goals)
    p3 = poisson_pmf(l3, max_goals) if l3 > 0 else None

    matrix = [[0.0] * (max_goals + 1) for _ in range(max_goals + 1)]
    total = 0.0
    for x in range(max_goals + 1):
        row = matrix[x]
        for y in range(max_goals + 1):
            if p3 is None:
                value = p1[x] * p2[y]
            else:
                value = 0.0
                for k in range(min(x, y) + 1):
                    value += p3[k] * p1[x - k] * p2[y - k]
            row[y] = value
            total += value
    if total > 0:                     # rinormalizza la coda troncata
        inv = 1.0 / total
        for row in matrix:
            for y in range(max_goals + 1):
                row[y] *= inv
    return matrix


# ------------------------------------------------------------- probabilita'
def market_probabilities(
    matrix: List[List[float]], totals_lines: Sequence[float]
) -> Dict[str, float]:
    n = len(matrix) - 1
    p_home = p_draw = p_away = 0.0
    p_btts = 0.0
    totals: Dict[float, List[float]] = {line: [0.0, 0.0, 0.0] for line in totals_lines}

    for x in range(n + 1):
        row = matrix[x]
        for y in range(n + 1):
            p = row[y]
            if not p:
                continue
            if x > y:
                p_home += p
            elif x == y:
                p_draw += p
            else:
                p_away += p
            if x >= 1 and y >= 1:
                p_btts += p
            total_goals = x + y
            for line, acc in totals.items():
                if total_goals > line:
                    acc[0] += p
                elif total_goals < line:
                    acc[1] += p
                else:                      # linea intera: rimborso
                    acc[2] += p

    probs: Dict[str, float] = {
        "1X2:home": p_home,
        "1X2:draw": p_draw,
        "1X2:away": p_away,
        "BTTS:yes": p_btts,
        "BTTS:no": 1.0 - p_btts,
    }
    for line, (over, under, push) in totals.items():
        tag = f"{line:g}"
        probs[f"OU{tag}:over"] = over
        probs[f"OU{tag}:under"] = under
        if push > 1e-9:
            probs[f"OU{tag}:push"] = push
    return probs


@dataclass
class FixtureModel:
    xg: ExpectedGoals
    probs: Dict[str, float]
    #: market_id -> (percentile basso, percentile alto) della probabilita'
    prob_ci: Dict[str, Tuple[float, float]]
    draws: int


def simulate_fixture(
    xg: ExpectedGoals, settings: Settings
) -> FixtureModel:
    """Probabilita' puntuali + intervallo di credibilita' via Monte Carlo.

    L'incertezza simulata e' quella sulla stima dei gol attesi. NON copre
    l'errore di specificazione del modello ne' le notizie dell'ultimo minuto:
    gli intervalli sono quindi ottimisti, non conservativi.
    """
    base_matrix = joint_score_matrix(xg.home, xg.away, settings.lambda_cov, settings.max_goals)
    point = market_probabilities(base_matrix, settings.totals_lines)

    rng = random.Random(settings.seed)
    samples: Dict[str, List[float]] = {key: [] for key in point}
    for _ in range(max(0, settings.mc_draws)):
        # lognormale con correzione di mediana: E[lambda] resta la stima puntuale
        lam_h = xg.home * math.exp(rng.gauss(0.0, xg.sigma_home) - 0.5 * xg.sigma_home ** 2)
        lam_a = xg.away * math.exp(rng.gauss(0.0, xg.sigma_away) - 0.5 * xg.sigma_away ** 2)
        lam_h = min(max(lam_h, settings.lambda_floor), settings.lambda_ceiling)
        lam_a = min(max(lam_a, settings.lambda_floor), settings.lambda_ceiling)
        matrix = joint_score_matrix(lam_h, lam_a, settings.lambda_cov, settings.max_goals)
        for key, value in market_probabilities(matrix, settings.totals_lines).items():
            if key in samples:
                samples[key].append(value)

    alpha = (1.0 - settings.ci_level) / 2.0
    ci: Dict[str, Tuple[float, float]] = {}
    for key, values in samples.items():
        if len(values) < 20:
            ci[key] = (point[key], point[key])
            continue
        values.sort()
        ci[key] = (percentile(values, alpha), percentile(values, 1.0 - alpha))

    return FixtureModel(xg=xg, probs=point, prob_ci=ci, draws=settings.mc_draws)


def percentile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac
