"""Interfaccia a riga di comando."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from typing import Dict, List, Optional, Sequence, Tuple

from .analysis import EdgeRow, RELIABILITY_OK, analyze_fixture
from .config import COMPETITIONS, DEFAULT_COMPETITIONS, Settings
from .football_data import FootballDataClient, current_season_start_year
from .httpcache import (
    DEFAULT_CACHE_DIR,
    HttpClient,
    HttpError,
    RateLimiter,
    build_url,
)
from .matching import match_fixtures
from .model import build_league_model
from .odds_api import OddsApiClient
from .odds_types import MARKET_BTTS, MARKET_H2H, MARKET_TOTALS
from .sharpapi import DEFAULT_BASE as SHARP_BASE
from .sharpapi import DEFAULT_ODDS_PATH as SHARP_ODDS_PATH
from .sharpapi import SharpApiClient, summarize_structure
from .report import (
    SEPARATOR,
    render_footer,
    render_header,
    render_notes,
    render_table,
    to_csv,
    to_json,
)

KEYS_HELP = """\
Serve una chiave per i dati storici e una per le quote.

Il modo piu' comodo: un file .env nella cartella dello script (viene caricato
da solo, ed e' gia' in .gitignore).

    FOOTBALL_DATA_API_KEY=...
    SHARPAPI_KEY=...

Verifica con:  python3 edge_scan.py --check-keys

  1) Dati storici - football-data.org
     https://www.football-data.org/client/register
     export FOOTBALL_DATA_API_KEY="la-tua-chiave"

  2) Quote - uno fra questi due provider (--odds-provider):
     a) SharpAPI            export SHARPAPI_KEY="la-tua-chiave"
     b) The Odds API        export ODDS_API_KEY="la-tua-chiave"
     Se e' impostata una sola delle due chiavi, il provider viene scelto
     automaticamente.

In alternativa: --football-data-key / --odds-key / --sharpapi-key, oppure un
file con le variabili passato con --env-file.
Senza chiave quote si puo' comunque usare --model-only (probabilita' del
modello, nessun edge: senza quote reali l'edge non e' calcolabile).
"""


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="edge_scan",
        description=(
            "Confronta le probabilita' di un modello Poisson bivariato con le "
            "quote di mercato de-viggate e stima un edge, con intervallo di "
            "incertezza. Strumento informativo: non produce pronostici sicuri."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=KEYS_HELP,
    )
    p.add_argument("--competitions", default=",".join(DEFAULT_COMPETITIONS),
                   help="codici football-data separati da virgola, oppure 'all' "
                        f"(disponibili: {', '.join(COMPETITIONS)})")
    p.add_argument("--date", default="today",
                   help="today | tomorrow | YYYY-MM-DD (default: today)")
    p.add_argument("--days", type=int, default=1,
                   help="numero di giorni da includere a partire da --date")

    m = p.add_argument_group("modello")
    m.add_argument("--form-matches", type=int, default=10,
                   help="partite per split casa/trasferta (consigliato 6-10)")
    m.add_argument("--min-matches", type=int, default=5,
                   help="sotto questa soglia la riga e' marcata bassa affidabilita'")
    m.add_argument("--half-life", type=float, default=60.0,
                   help="mezza vita in giorni del decadimento esponenziale")
    m.add_argument("--prior-matches", type=float, default=4.0,
                   help="shrinkage della forza complessiva verso la media di lega")
    m.add_argument("--prior-venue", type=float, default=4.0,
                   help="shrinkage dello split casa/trasferta verso la forza "
                        "complessiva della squadra")
    m.add_argument("--lambda-cov", type=float, default=0.12,
                   help="componente comune del Poisson bivariato (0 = indipendente)")
    m.add_argument("--no-previous-season", action="store_true",
                   help="usa solo la stagione in corso")
    m.add_argument("--totals-lines", default="2.5",
                   help="linee Over/Under da valutare, separate da virgola")

    k = p.add_argument_group("mercato")
    k.add_argument("--devig", default="shin", choices=["shin", "multiplicative", "power"],
                   help="metodo di rimozione del margine bookmaker")
    k.add_argument("--market-blend", type=float, default=0.0,
                   help="0 = solo modello, 1 = solo mercato. Valori 0.2-0.4 "
                        "riducono l'eccesso di fiducia nel modello")
    k.add_argument("--min-edge", type=float, default=None,
                   help="filtro opzionale: mostra solo le righe con edge stimato >= "
                        "questa soglia (%%). Senza filtro vengono mostrate anche le "
                        "righe con edge negativo, che sono la maggioranza")
    k.add_argument("--odds-provider", default="auto",
                   choices=["auto", "sharpapi", "theoddsapi"],
                   help="fonte delle quote. 'auto' sceglie in base alle chiavi presenti")
    k.add_argument("--regions", default="eu",
                   help="regioni bookmaker, solo The Odds API (eu, uk, us, au)")
    k.add_argument("--bookmakers", default=None,
                   help="lista di bookmaker specifici (es. bet365,pinnacle)")
    k.add_argument("--btts", action="store_true",
                   help="prova a richiedere anche il mercato BTTS (piano a pagamento)")

    u = p.add_argument_group("incertezza")
    u.add_argument("--mc-draws", type=int, default=800, help="estrazioni Monte Carlo")
    u.add_argument("--ci", type=float, default=0.90, help="livello dell'intervallo")
    u.add_argument("--seed", type=int, default=12345)

    o = p.add_argument_group("output e rete")
    o.add_argument("--csv", metavar="FILE", help="salva la tabella in CSV")
    o.add_argument("--json", metavar="FILE", help="salva il risultato completo in JSON")
    o.add_argument("--model-only", action="store_true",
                   help="niente quote: solo probabilita' del modello")
    o.add_argument("--offline", action="store_true",
                   help="usa solo la cache locale, nessuna chiamata di rete")
    o.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    o.add_argument("--football-data-key", default=None)
    o.add_argument("--odds-key", default=None, help="chiave The Odds API")
    o.add_argument("--sharpapi-key", default=None, help="chiave SharpAPI")
    o.add_argument("--env-file", default=None,
                   help="file KEY=VALUE con le chiavi. Se omesso viene cercato "
                        "un .env nella cartella corrente e in quella dello script")
    o.add_argument("--verbose", action="store_true")
    o.add_argument("--self-test", action="store_true",
                   help="verifica il modello su dati sintetici, senza rete")
    o.add_argument("--check-keys", action="store_true",
                   help="mostra quali chiavi sono state trovate e da dove, "
                        "senza chiamare le API")

    sh = p.add_argument_group(
        "SharpAPI (mappatura dei campi ricostruita: verificare con --dump-odds)")
    sh.add_argument("--sharpapi-base", default=SHARP_BASE, help="URL base")
    sh.add_argument("--sharpapi-odds-path", default=SHARP_ODDS_PATH,
                    help="percorso dell'endpoint quote")
    sh.add_argument("--sharpapi-auth", default="bearer",
                    choices=["bearer", "x-api-key", "query"],
                    help="come viene inviata la chiave")
    sh.add_argument("--sharpapi-league-param", default="league",
                    help="nome del parametro con cui si filtra il campionato")
    sh.add_argument("--sharpapi-odds-format", default="auto",
                    choices=["auto", "decimal", "american"],
                    help="formato delle quote restituite")
    sh.add_argument("--league-map", default=None,
                    help="file JSON {\"SA\": \"codice-del-provider\"} per "
                         "correggere i codici campionato")
    sh.add_argument("--list-leagues", action="store_true",
                    help="elenca i campionati come li chiama il provider ed esce")
    sh.add_argument("--dump-odds", action="store_true",
                    help="stampa la risposta grezza delle quote e la sua struttura, "
                         "per verificare la mappatura dei campi")
    return p.parse_args(argv)


#: cartella dello script, dove si cerca un .env se non ne viene passato uno
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEY_VARIABLES = [
    ("FOOTBALL_DATA_API_KEY", "dati storici (football-data.org)", True),
    ("SHARPAPI_KEY", "quote (SharpAPI)", False),
    ("ODDS_API_KEY", "quote (The Odds API)", False),
]


def load_env_file(path: str) -> List[str]:
    """Legge un file KEY=VALUE. Le variabili d'ambiente gia' presenti vincono.

    Ritorna i nomi effettivamente impostati dal file, per poter dire poi da
    dove arriva ciascuna chiave.
    """
    applied: List[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key not in os.environ:
                os.environ[key] = value.strip().strip("'\"")
                applied.append(key)
    return applied


def autoload_env(explicit: Optional[str]) -> Tuple[Optional[str], List[str]]:
    """Carica il file indicato, oppure il primo .env trovato.

    Ritorna (file usato, nomi impostati da quel file).
    """
    if explicit:
        return explicit, load_env_file(explicit)
    for candidate in (os.path.join(os.getcwd(), ".env"),
                      os.path.join(SCRIPT_DIR, ".env")):
        if os.path.isfile(candidate):
            return candidate, load_env_file(candidate)
    return None, []


def _mask(value: str) -> str:
    """Mostra solo la coda della chiave: quel tanto che basta a riconoscerla."""
    return f"{'.' * 6}{value[-4:]} ({len(value)} caratteri)" if len(value) > 8 else "(molto corta)"


def cmd_check_keys(args: argparse.Namespace, env_file: Optional[str],
                   from_file: Sequence[str]) -> int:
    """Dice quali chiavi sono state trovate e da dove, senza chiamare le API."""
    print("Chiavi trovate\n")
    print(f"  File .env letto : {env_file or 'nessuno'}")
    print(f"  Cartella script : {SCRIPT_DIR}\n")

    overrides = {
        "FOOTBALL_DATA_API_KEY": args.football_data_key,
        "SHARPAPI_KEY": args.sharpapi_key,
        "ODDS_API_KEY": args.odds_key,
    }
    problems: List[str] = []
    for name, description, required in KEY_VARIABLES:
        from_flag = overrides.get(name)
        value = from_flag or os.environ.get(name, "")
        if from_flag:
            origin = "opzione da riga di comando"
        elif name in from_file:
            origin = f"file {os.path.basename(env_file or '.env')}"
        else:
            origin = "variabile d'ambiente" if value else "-"
        if value:
            print(f"  [ok]      {name:24} {_mask(value):28} {description}  [{origin}]")
            if value != value.strip() or " " in value:
                problems.append(f"{name} contiene spazi: probabile errore di copia")
            if value[0] in "\"'" or value[-1] in "\"'":
                problems.append(f"{name} inizia o finisce con una virgoletta")
        else:
            marker = "MANCA" if required else "-"
            print(f"  [{marker:5}]   {name:24} {'':28} {description}")

    provider, key = resolve_provider(args)
    print()
    if not os.environ.get("FOOTBALL_DATA_API_KEY") and not args.football_data_key:
        print("  Senza FOOTBALL_DATA_API_KEY non si puo' stimare niente: e' obbligatoria.")
    if key:
        print(f"  Provider quote che verrebbe usato: {provider}")
    else:
        print("  Nessuna chiave per le quote: si puo' usare solo --model-only "
              "(probabilita' del modello, nessun edge).")
    for problem in problems:
        print(f"  ! {problem}")
    print("\n  Nota: le chiavi non vengono mai stampate per intero ne' inviate "
          "altrove che alle rispettive API.")
    return 0


def resolve_date_range(spec: str, days: int) -> tuple[dt.date, dt.date]:
    today = dt.date.today()
    if spec == "today":
        start = today
    elif spec == "tomorrow":
        start = today + dt.timedelta(days=1)
    else:
        start = dt.date.fromisoformat(spec)
    return start, start + dt.timedelta(days=max(1, days) - 1)


def settings_from_args(args: argparse.Namespace) -> Settings:
    lines = [float(x) for x in args.totals_lines.split(",") if x.strip()]
    return Settings(
        form_matches=args.form_matches,
        min_matches=args.min_matches,
        half_life_days=args.half_life,
        prior_matches=args.prior_matches,
        prior_venue=args.prior_venue,
        include_previous_season=not args.no_previous_season,
        lambda_cov=args.lambda_cov,
        totals_lines=lines or [2.5],
        devig_method=args.devig,
        market_blend=max(0.0, min(1.0, args.market_blend)),
        min_edge_pct=args.min_edge,
        mc_draws=args.mc_draws,
        ci_level=args.ci,
        seed=args.seed,
        offline=args.offline,
    )


def resolve_provider(args: argparse.Namespace) -> tuple[str, str]:
    """Sceglie il provider di quote. Ritorna (nome, chiave); ('', '') se assente."""
    sharp_key = args.sharpapi_key or os.environ.get("SHARPAPI_KEY", "")
    odds_key = args.odds_key or os.environ.get("ODDS_API_KEY", "")
    choice = args.odds_provider
    if choice == "sharpapi":
        return ("sharpapi", sharp_key)
    if choice == "theoddsapi":
        return ("theoddsapi", odds_key)
    if sharp_key:
        return ("sharpapi", sharp_key)
    if odds_key:
        return ("theoddsapi", odds_key)
    return ("", "")


def build_odds_client(args: argparse.Namespace, provider: str, key: str, http: HttpClient):
    if provider == "sharpapi":
        return SharpApiClient(
            key, http,
            base=args.sharpapi_base,
            odds_path=args.sharpapi_odds_path,
            auth_style=args.sharpapi_auth,
            league_param=args.sharpapi_league_param,
            odds_format=args.sharpapi_odds_format,
        )
    return OddsApiClient(key, http, regions=args.regions)


def load_league_map(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return {str(k).upper(): str(v) for k, v in data.items()}


def league_key_for(comp, provider: str, overrides: Dict[str, str]) -> str:
    return overrides.get(comp.code, comp.league_key(provider))


def cmd_list_leagues(args: argparse.Namespace, provider: str, key: str,
                     http: HttpClient, ttl: int) -> int:
    """Elenca i campionati come li chiama il provider."""
    if provider == "sharpapi":
        client = build_odds_client(args, provider, key, http)
        print(f"Endpoint di scoperta provati su {client.base}:\n")
        for path, payload in client.discover_leagues(ttl):
            print(f"--- {path} ---")
            if isinstance(payload, str):
                print(f"  {payload}\n")
                continue
            print(summarize_structure(payload))
            print()
        print("Metti i codici trovati in un file JSON e passalo con --league-map,\n"
              'ad esempio: {"SA": "italy-serie-a", "PL": "england-premier-league"}')
        return 0

    from .odds_api import BASE as ODDS_BASE
    url = build_url(f"{ODDS_BASE}/sports", {"apiKey": key})
    payload = http.get(url, ttl=ttl).json()
    for sport in payload:
        if str(sport.get("group", "")).lower().startswith("soccer") or \
                str(sport.get("key", "")).startswith("soccer"):
            print(f"  {sport.get('key'):40} {sport.get('title')}")
    return 0


def cmd_dump_odds(args: argparse.Namespace, provider: str, key: str, http: HttpClient,
                  codes: List[str], overrides: Dict[str, str], ttl: int) -> int:
    """Stampa la risposta grezza delle quote, per verificare la mappatura."""
    comp = COMPETITIONS[codes[0]]
    league = league_key_for(comp, provider, overrides)
    markets = [MARKET_H2H, MARKET_TOTALS] + ([MARKET_BTTS] if args.btts else [])
    client = build_odds_client(args, provider, key, http)
    if provider == "sharpapi":
        url, payload = client.dump_raw(league, markets, ttl)
    else:
        result = client.fetch(comp.odds_sport_key, markets, ttl)
        url, payload = "(The Odds API)", [e.__dict__ for e in result.events[:2]]
    print(f"Campionato richiesto : {comp.name} -> '{league}'")
    print(f"URL                  : {url}\n")
    print("--- struttura riconosciuta ---")
    print(summarize_structure(payload))
    print("\n--- primi 4000 caratteri del JSON grezzo ---")
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str)[:4000])
    return 0


def run(args: argparse.Namespace) -> int:
    env_file, from_file = autoload_env(args.env_file)
    if args.check_keys:
        return cmd_check_keys(args, env_file, from_file)

    fd_key = args.football_data_key or os.environ.get("FOOTBALL_DATA_API_KEY", "")
    provider, odds_key = resolve_provider(args)

    if not fd_key and not (args.list_leagues or args.dump_odds):
        print("Manca la chiave di football-data.org: senza risultati storici il "
              "modello non puo' stimare nulla.\n", file=sys.stderr)
        print(KEYS_HELP, file=sys.stderr)
        return 2
    if not odds_key and not args.model_only:
        missing = {
            "sharpapi": "SHARPAPI_KEY",
            "theoddsapi": "ODDS_API_KEY",
        }.get(provider, "SHARPAPI_KEY oppure ODDS_API_KEY")
        print(f"Manca la chiave per le quote ({missing}): senza quote reali l'edge "
              "non e' calcolabile.\nUsa --model-only per le sole probabilita' del "
              "modello, oppure imposta la chiave.\n", file=sys.stderr)
        print(KEYS_HELP, file=sys.stderr)
        return 2

    settings = settings_from_args(args)
    date_from, date_to = resolve_date_range(args.date, args.days)
    now = dt.datetime.now(dt.timezone.utc)

    codes = (
        list(COMPETITIONS)
        if args.competitions.strip().lower() == "all"
        else [c.strip().upper() for c in args.competitions.split(",") if c.strip()]
    )
    unknown = [c for c in codes if c not in COMPETITIONS]
    if unknown:
        print(f"Codici competizione sconosciuti: {', '.join(unknown)}", file=sys.stderr)
        print(f"Disponibili: {', '.join(COMPETITIONS)}", file=sys.stderr)
        return 2

    http = HttpClient(
        cache_dir=args.cache_dir,
        offline=args.offline,
        rate_limiter=RateLimiter(10, 60.0),
        verbose=args.verbose,
    )
    try:
        overrides = load_league_map(args.league_map)
    except (OSError, ValueError) as exc:
        print(f"--league-map non leggibile: {exc}", file=sys.stderr)
        return 2

    if args.list_leagues:
        return cmd_list_leagues(args, provider, odds_key, http, settings.cache_ttl_odds)
    if args.dump_odds:
        return cmd_dump_odds(args, provider, odds_key, http, codes, overrides,
                             settings.cache_ttl_odds)

    fd = FootballDataClient(fd_key, http)
    odds_client = (
        build_odds_client(args, provider, odds_key, http)
        if odds_key and not args.model_only
        else None
    )

    seasons = [current_season_start_year(date_from)]
    if settings.include_previous_season:
        seasons.append(seasons[0] - 1)

    api_notes: List[str] = []
    rows: List[EdgeRow] = []
    unmatched_total = 0

    for code in codes:
        comp = COMPETITIONS[code]
        if not comp.free_tier:
            api_notes.append(
                f"[{code}] {comp.name}: non inclusa nel piano gratuito di "
                "football-data.org, verra' tentata comunque e saltata in caso di 403."
            )
        try:
            fixtures = fd.fixtures(comp, date_from, date_to, settings.cache_ttl_fixtures)
        except HttpError as exc:
            api_notes.append(f"[{code}] calendario non disponibile: {exc}")
            continue
        if not fixtures:
            continue

        history, skip_reason = fd.load_history(comp, seasons, settings.cache_ttl_history)
        if skip_reason:
            api_notes.append(f"[{code}] {comp.name}: {skip_reason}; partite saltate.")
            continue

        league = build_league_model(code, history, settings, now)

        events = []
        if odds_client:
            markets = [MARKET_H2H, MARKET_TOTALS] + ([MARKET_BTTS] if args.btts else [])
            try:
                result = odds_client.fetch(
                    league_key_for(comp, provider, overrides),
                    markets, settings.cache_ttl_odds,
                    bookmakers=args.bookmakers,
                )
                events = result.events
                api_notes.extend(result.notes)
            except HttpError as exc:
                api_notes.append(f"[{code}] quote non disponibili: {exc}")

        matched, unmatched = match_fixtures(
            fixtures, events, settings.name_match_threshold,
            settings.kickoff_tolerance_minutes,
        )
        unmatched_total += len(unmatched) if odds_client else 0
        for fixture in unmatched:
            if odds_client:
                api_notes.append(
                    f"[{code}] {fixture.home_name} - {fixture.away_name}: nessun "
                    "evento quote abbinato (nome squadra o orario non corrispondenti)."
                )

        for fixture in fixtures:
            _model, fixture_rows = analyze_fixture(
                fixture, matched.get(fixture.match_id), league, settings
            )
            rows.extend(fixture_rows)

    priced = [r for r in rows if r.edge_pct is not None]
    unpriced = [r for r in rows if r.edge_pct is None]
    threshold = settings.min_edge_pct
    kept = priced if threshold is None else [r for r in priced if r.edge_pct >= threshold]
    shown = sorted(kept, key=lambda r: r.sort_key)
    hidden = len(priced) - len(shown)

    stats: Dict[str, object] = {
        "network_calls": http.network_calls,
        "cache_hits": http.cache_hits,
        "unmatched": unmatched_total,
        "api_notes": api_notes,
        "righe_nascoste_dal_filtro": hidden,
        "odds_requests_remaining": odds_client.requests_remaining if odds_client else None,
        "odds_requests_used": odds_client.requests_used if odds_client else None,
    }

    print(render_header(date_from, date_to, codes, settings, now,
                        provider if odds_client else "nessuno (--model-only)"))
    if shown:
        print(render_table(shown, settings))
    else:
        print("Nessuna riga con quote disponibili per i criteri scelti.")
    if hidden:
        print(f"\n({hidden} righe con edge sotto la soglia --min-edge "
              f"{threshold:g}% non sono mostrate; restano nel CSV/JSON solo se "
              "la soglia viene abbassata.)")

    if unpriced:
        print("\n" + SEPARATOR)
        print("MERCATI SENZA QUOTA ABBINATA - solo probabilita' di modello, "
              "nessun edge calcolabile")
        print(SEPARATOR)
        print(render_table(sorted(unpriced, key=lambda r: (r.kickoff, r.match_label)), settings))

    notes = render_notes(rows)
    if notes:
        print("\n" + notes)

    low = sum(1 for r in shown if r.reliability != RELIABILITY_OK)
    print("\n" + render_footer(stats, settings, low, len(shown)))

    if args.csv:
        with open(args.csv, "w", encoding="utf-8", newline="") as fh:
            fh.write(to_csv(shown + unpriced))
        print(f"CSV scritto in {args.csv}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(to_json(shown + unpriced, stats, settings))
        print(f"JSON scritto in {args.json}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        from .selftest import run_self_test
        return run_self_test(settings_from_args(args))
    try:
        return run(args)
    except HttpError as exc:
        print(f"Errore API: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
