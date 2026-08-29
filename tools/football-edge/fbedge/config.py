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
    name: str               # etichetta per l'output
    short_name: str         # nome del campionato, per il matching coi provider
    country: str            # paese, per disambiguare omonimie ("Serie A")
    odds_sport_key: str     # sport key di The Odds API
    free_tier: bool         # incluso nel piano free di football-data.org
    tier: int               # 1 = prima divisione, 2 = seconda divisione
    #: id del campionato lato SharpAPI. None = da mappare: gli id di SharpAPI
    #: sono slug propri (es. "nfl"), da scoprire con --list-leagues e passare
    #: con --league-map.
    sharpapi_league: Optional[str] = None

    def league_key(self, provider: str) -> Optional[str]:
        if provider == "sharpapi":
            return self.sharpapi_league
        return self.odds_sport_key


def _c(code, name, short_name, country, odds_key, free_tier, tier):
    return Competition(code, name, short_name, country, odds_key, free_tier, tier)


COMPETITIONS: Dict[str, Competition] = {
    c.code: c
    for c in [
        # --- prime divisioni (tutte nel piano free di football-data.org) ---
        _c("SA",  "Serie A (ITA)",        "Serie A",        "Italy",       "soccer_italy_serie_a",          True, 1),
        _c("PL",  "Premier League (ENG)", "Premier League", "England",     "soccer_epl",                    True, 1),
        _c("BL1", "Bundesliga (GER)",     "Bundesliga",     "Germany",     "soccer_germany_bundesliga",     True, 1),
        _c("PD",  "La Liga (ESP)",        "LaLiga",         "Spain",       "soccer_spain_la_liga",          True, 1),
        _c("FL1", "Ligue 1 (FRA)",        "Ligue 1",        "France",      "soccer_france_ligue_one",       True, 1),
        # --- extra utili, sempre nel piano free ---
        _c("DED", "Eredivisie (NED)",     "Eredivisie",     "Netherlands", "soccer_netherlands_eredivisie", True, 1),
        _c("PPL", "Primeira Liga (POR)",  "Primeira Liga",  "Portugal",    "soccer_portugal_primeira_liga", True, 1),
        _c("CL",  "Champions League",     "Champions League", "Europe",    "soccer_uefa_champs_league",     True, 1),
        # --- seconde divisioni ---
        _c("ELC", "Championship (ENG)",   "Championship",   "England",     "soccer_efl_champ",              True, 2),
        _c("SB",  "Serie B (ITA)",        "Serie B",        "Italy",       "soccer_italy_serie_b",         False, 2),
        _c("BL2", "2. Bundesliga (GER)",  "2. Bundesliga",  "Germany",     "soccer_germany_bundesliga2",   False, 2),
        _c("SD",  "LaLiga2 (ESP)",        "LaLiga 2",       "Spain",       "soccer_spain_segunda_division", False, 2),
        _c("FL2", "Ligue 2 (FRA)",        "Ligue 2",        "France",      "soccer_france_ligue_two",      False, 2),
    ]
}

#: come ogni paese puo' comparire nell'id o nel nome di un provider.
#: Serve a riconoscere "English Premier League" come inglese e a scartare
#: "Russia Premier League".
COUNTRY_ALIASES: Dict[str, List[str]] = {
    "italy": ["italy", "italia", "italian", "ita", "seriea"],
    "england": ["england", "english", "britain", "british", "uk", "eng", "efl", "epl"],
    "germany": ["germany", "german", "deutschland", "ger", "dfb"],
    "spain": ["spain", "spanish", "espana", "esp"],
    "france": ["france", "french", "fra"],
    "netherlands": ["netherlands", "dutch", "holland", "ned", "nl"],
    "portugal": ["portugal", "portuguese", "por"],
    "europe": ["uefa", "europe", "european", "champions"],
}

#: token che, se presenti in un campionato del provider ma non nel nostro
#: nome, indicano che NON e' la stessa competizione. Una corrispondenza
#: sbagliata qui non da' errore: analizza in silenzio il campionato sbagliato.
DISQUALIFYING_TOKENS = {
    # mercati derivati, non campionati
    "offside", "offsides", "corner", "corners", "card", "cards", "booking",
    "bookings", "shot", "shots", "minute", "minutes", "total", "totals",
    "player", "players", "prop", "props", "special", "specials", "outright",
    "outrights", "winner", "halftime", "half", "handicap", "score", "scorer",
    "scorers", "team", "goalscorer", "goalscorers", "correct", "exact",
    "double", "chance", "draw", "clean", "sheet", "sheets", "first", "last",
    "method", "combo", "combos", "insurance", "boost", "boosts", "goal",
    "race", "sending", "off",
    # competizioni diverse
    "women", "womens", "ladies", "femminile", "feminine", "feminina",
    "u23", "u21", "u20", "u19", "u18", "u17", "u16", "youth", "junior",
    "juniors", "reserve", "reserves", "amateur", "futsal", "beach", "esports",
    "cup", "coppa", "copa", "pokal", "trophy", "supercup", "supercoppa",
    "playoff", "playoffs", "qualification", "qualifying", "friendly",
    "friendlies", "preseason", "relegation", "promotion",
    # ritagli regionali
    "southern", "northern", "eastern", "western", "north", "south", "east",
    "west", "central", "regional",
}

#: paesi usati per penalizzare gli omonimi ("Serie A" esiste in Italia e in
#: Brasile, "Premier League" in mezza Europa).
COUNTRY_HINTS = [
    "italy", "italia", "england", "english", "germany", "deutschland", "spain",
    "espana", "france", "netherlands", "holland", "portugal", "brazil", "brasil",
    "argentina", "usa", "united states", "mexico", "japan", "china", "korea",
    "russia", "ukraine", "turkey", "greece", "belgium", "austria", "switzerland",
    "scotland", "ireland", "denmark", "sweden", "norway", "finland", "poland",
    "czech", "croatia", "serbia", "romania", "bulgaria", "israel", "egypt",
    "australia", "india", "chile", "colombia", "peru", "uruguay", "paraguay",
    "ecuador", "bolivia", "venezuela", "saudi", "qatar", "emirates", "morocco",
]

# Tutte le competizioni del piano gratuito di football-data.org, non solo le
# cinque principali: la specifica chiede esplicitamente le seconde divisioni
# quando il piano free le copre, ed e' il caso della Championship inglese.
# Le seconde divisioni a pagamento (SB, BL2, SD, FL2) restano fuori dal
# default: senza un piano superiore, football-data.org le rifiuta con 403 a
# ogni corsa, e includerle di default vorrebbe dire stampare quel rifiuto a
# chi non le ha mai chieste. Restano raggiungibili con --competitions all
# o elencandole esplicitamente.
DEFAULT_COMPETITIONS: List[str] = [
    code for code, comp in COMPETITIONS.items() if comp.free_tier
]


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
