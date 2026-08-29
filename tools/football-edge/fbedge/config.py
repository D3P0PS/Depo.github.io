"""Catalogo campionati e parametri di default.

Mappa i codici competizione di football-data.org con le sport-key di
The Odds API. `free_tier` indica se la competizione e' inclusa nel piano
gratuito di football-data.org (v4): le seconde divisioni, tranne la
Championship inglese, richiedono un piano a pagamento e vengono saltate
con un messaggio esplicito invece che silenziosamente.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Competition:
    code: str               # codice football-data.org
    name: str
    odds_sport_key: str     # sport key di The Odds API
    free_tier: bool         # incluso nel piano free di football-data.org
    tier: int               # 1 = prima divisione, 2 = seconda divisione
    #: codice del campionato lato SharpAPI. None = si riusa odds_sport_key,
    #: che e' solo un'ipotesi: verificare con --list-leagues e correggere con
    #: --league-map (file JSON {"SA": "codice-sharpapi", ...}).
    sharpapi_league: Optional[str] = None

    def league_key(self, provider: str) -> str:
        if provider == "sharpapi":
            return self.sharpapi_league or self.odds_sport_key
        return self.odds_sport_key


COMPETITIONS: Dict[str, Competition] = {
    c.code: c
    for c in [
        # --- prime divisioni (tutte nel piano free di football-data.org) ---
        Competition("SA",   "Serie A (ITA)",        "soccer_italy_serie_a",         True,  1),
        Competition("PL",   "Premier League (ENG)", "soccer_epl",                   True,  1),
        Competition("BL1",  "Bundesliga (GER)",     "soccer_germany_bundesliga",    True,  1),
        Competition("PD",   "La Liga (ESP)",        "soccer_spain_la_liga",         True,  1),
        Competition("FL1",  "Ligue 1 (FRA)",        "soccer_france_ligue_one",      True,  1),
        # --- extra utili, sempre nel piano free ---
        Competition("DED",  "Eredivisie (NED)",     "soccer_netherlands_eredivisie", True, 1),
        Competition("PPL",  "Primeira Liga (POR)",  "soccer_portugal_primeira_liga", True, 1),
        Competition("CL",   "Champions League",     "soccer_uefa_champs_league",    True,  1),
        # --- seconde divisioni ---
        Competition("ELC",  "Championship (ENG)",   "soccer_efl_champ",             True,  2),
        Competition("SB",   "Serie B (ITA)",        "soccer_italy_serie_b",         False, 2),
        Competition("BL2",  "2. Bundesliga (GER)",  "soccer_germany_bundesliga2",   False, 2),
        Competition("SD",   "LaLiga2 (ESP)",        "soccer_spain_segunda_division", False, 2),
        Competition("FL2",  "Ligue 2 (FRA)",        "soccer_france_ligue_two",      False, 2),
    ]
}

DEFAULT_COMPETITIONS: List[str] = ["SA", "PL", "BL1", "PD", "FL1"]


@dataclass
class Settings:
    """Parametri del modello. Tutti sovrascrivibili da riga di comando."""

    # --- forma / pesi ---
    form_matches: int = 10          # max partite per split (casa/trasferta)
    min_matches: int = 5            # sotto questa soglia -> bassa affidabilita'
    half_life_days: float = 60.0    # decadimento esponenziale dei pesi
    prior_matches: float = 4.0      # shrinkage della forza complessiva verso la lega
    prior_venue: float = 4.0        # shrinkage dello split casa/trasferta verso la
                                    # forza complessiva della squadra
    include_previous_season: bool = True

    # --- Poisson bivariato ---
    max_goals: int = 12             # troncamento della griglia dei risultati
    lambda_cov: float = 0.12        # componente comune (covarianza) lambda_3
    lambda_floor: float = 0.15
    lambda_ceiling: float = 5.0

    # --- mercati ---
    totals_lines: List[float] = field(default_factory=lambda: [2.5])

    # --- confronto con il mercato ---
    devig_method: str = "shin"      # shin | multiplicative | power
    market_blend: float = 0.0       # 0 = solo modello, 1 = solo mercato
    min_edge_pct: Optional[float] = None   # filtro opzionale sull'edge mostrato

    # --- incertezza ---
    mc_draws: int = 800
    ci_level: float = 0.90
    seed: int = 12345

    # --- rete ---
    cache_ttl_fixtures: int = 3600      # 1 h
    cache_ttl_history: int = 21600      # 6 h
    cache_ttl_odds: int = 900           # 15 min (risparmia il budget mensile)
    offline: bool = False

    # --- matching squadre ---
    name_match_threshold: float = 0.62
    kickoff_tolerance_minutes: int = 240


# Alias per il matching dei nomi squadra fra le due API.
# Chiave: nome normalizzato lato The Odds API -> nome normalizzato football-data.
TEAM_ALIASES: Dict[str, str] = {
    "inter milan": "internazionale",
    "internazionale milano": "internazionale",
    "ac milan": "milan",
    "as roma": "roma",
    "ss lazio": "lazio",
    "hellas verona": "verona",
    "juventus turin": "juventus",
    "napoli ssc": "napoli",
    "atalanta bc": "atalanta",
    "manchester utd": "manchester united",
    "man united": "manchester united",
    "man city": "manchester city",
    "spurs": "tottenham hotspur",
    "wolves": "wolverhampton wanderers",
    "nottm forest": "nottingham forest",
    "brighton and hove albion": "brighton hove albion",
    "west ham": "west ham united",
    "newcastle": "newcastle united",
    "leeds": "leeds united",
    "bayern munich": "bayern munchen",
    "bayern muenchen": "bayern munchen",
    "borussia monchengladbach": "borussia monchengladbach",
    "borussia moenchengladbach": "borussia monchengladbach",
    "bayer leverkusen": "bayer 04 leverkusen",
    "eintracht frankfurt": "eintracht frankfurt",
    "fc koln": "1 fc koln",
    "koln": "1 fc koln",
    "mainz": "1 fsv mainz 05",
    "union berlin": "1 fc union berlin",
    "rb leipzig": "rb leipzig",
    "atletico madrid": "atletico madrid",
    "athletic bilbao": "athletic club",
    "real betis": "real betis balompie",
    "celta vigo": "rc celta de vigo",
    "deportivo alaves": "deportivo alaves",
    "paris saint germain": "paris saint germain",
    "psg": "paris saint germain",
    "olympique marseille": "olympique de marseille",
    "marseille": "olympique de marseille",
    "olympique lyonnais": "olympique lyonnais",
    "lyon": "olympique lyonnais",
    "saint etienne": "as saint etienne",
    "sporting cp": "sporting clube de portugal",
    "sporting lisbon": "sporting clube de portugal",
    "fc porto": "fc porto",
    "psv eindhoven": "psv",
    "ajax amsterdam": "ajax",
}

# Parole da rimuovere quando si normalizza un nome squadra.
NOISE_TOKENS = {
    "fc", "afc", "cf", "ac", "as", "ss", "ssc", "sc", "bc", "bk", "cd", "rc",
    "rcd", "ud", "sd", "club", "calcio", "de", "di", "the", "1899", "1900",
    "1904", "1905", "1907", "1909", "1913", "vfl", "vfb", "tsg", "sv", "fsv",
    "spvgg", "ev", "ag", "srl", "spa", "cp", "sad", "aa", "usl", "us",
}
