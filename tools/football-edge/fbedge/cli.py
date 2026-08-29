"""Interfaccia a riga di comando."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from typing import Dict, List, Optional, Sequence

from .analysis import EdgeRow, RELIABILITY_OK, analyze_fixture
from .config import COMPETITIONS, DEFAULT_COMPETITIONS, Settings
from .football_data import FootballDataClient, current_season_start_year
from .httpcache import DEFAULT_CACHE_DIR, HttpClient, HttpError, RateLimiter
from .matching import match_fixtures
from .model import build_league_model
from .odds_api import MARKET_BTTS, MARKET_H2H, MARKET_TOTALS, OddsApiClient
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
Servono due chiavi API gratuite:

  1) football-data.org  -> https://www.football-data.org/client/register
     Piano free: 10 richieste/minuto, prime divisioni europee + Championship.
     export FOOTBALL_DATA_API_KEY="la-tua-chiave"

  2) The Odds API       -> https://the-odds-api.com/#get-access
     Piano free: ~500 crediti/mese (1 credito per mercato x regione).
     export ODDS_API_KEY="la-tua-chiave"

In alternativa: --football-data-key / --odds-key, oppure un file con
FOOTBALL_DATA_API_KEY=... e ODDS_API_KEY=... passato con --env-file.
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
    k.add_argument("--regions", default="eu", help="regioni bookmaker (eu, uk, us, au)")
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
    o.add_argument("--odds-key", default=None)
    o.add_argument("--env-file", default=None, help="file con le variabili delle chiavi")
    o.add_argument("--verbose", action="store_true")
    o.add_argument("--self-test", action="store_true",
                   help="verifica il modello su dati sintetici, senza rete")
    return p.parse_args(argv)


def load_env_file(path: str) -> None:
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


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


def run(args: argparse.Namespace) -> int:
    if args.env_file:
        load_env_file(args.env_file)

    fd_key = args.football_data_key or os.environ.get("FOOTBALL_DATA_API_KEY", "")
    odds_key = args.odds_key or os.environ.get("ODDS_API_KEY", "")

    if not fd_key:
        print("Manca la chiave di football-data.org: senza risultati storici il "
              "modello non puo' stimare nulla.\n", file=sys.stderr)
        print(KEYS_HELP, file=sys.stderr)
        return 2
    if not odds_key and not args.model_only:
        print("Manca la chiave di The Odds API: senza quote reali l'edge non e' "
              "calcolabile.\nUsa --model-only per le sole probabilita' del "
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
    fd = FootballDataClient(fd_key, http)
    odds_client = (
        OddsApiClient(odds_key, http, regions=args.regions)
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
                    comp.odds_sport_key, markets, settings.cache_ttl_odds,
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

    print(render_header(date_from, date_to, codes, settings, now))
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
