"""Formattazione dell'output: tabella testuale, CSV, JSON e avvertenze."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
from typing import Dict, List, Optional, Sequence, Tuple

from .analysis import EdgeRow, RELIABILITY_OK
from .config import Settings

SEPARATOR = "=" * 118


def _fmt_pct(value: Optional[float], digits: int = 1) -> str:
    return "n/d" if value is None else f"{value:.{digits}f}%"


def _fmt_odds(value: Optional[float]) -> str:
    return "n/d" if value is None else f"{value:.2f}"


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


#: larghezze piene delle colonne
FULL_COLUMNS: List[Tuple[str, int]] = [
    ("PARTITA", 28),
    ("MERCATO", 14),
    ("SELEZIONE", 13),
    ("BOOK", 10),
    ("QUOTA", 6),
    ("P.MOD", 6),
    ("P.MKT", 6),
    ("EDGE", 7),
    ("IC EDGE", 16),
    ("AFFID.", 7),
]

#: come restringere la tabella, un passo alla volta, quando il terminale e'
#: stretto. Si accorciano prima i nomi delle squadre, poi si tolgono le colonne
#: meno essenziali. Edge, probabilita' di modello e affidabilita' non si
#: tolgono mai: sono il minimo per leggere una riga senza fraintenderla.
NARROW_STEPS = [
    ("shrink", "PARTITA", 22),
    ("drop", "BOOK", 0),
    ("shrink", "PARTITA", 18),
    ("drop", "P.MKT", 0),
    ("drop", "IC EDGE", 0),
    ("shrink", "PARTITA", 14),
]


def terminal_width(default: int = 132) -> int:
    try:
        import shutil
        width = shutil.get_terminal_size(fallback=(default, 24)).columns
    except Exception:
        return default
    return width if width >= 60 else default


def _table_width(columns: Sequence[Tuple[str, int]]) -> int:
    return sum(w for _n, w in columns) + 2 * (len(columns) - 1)


def _fit_columns(width: int) -> List[Tuple[str, int]]:
    """Applica i passi di riduzione finche' la tabella non entra."""
    columns = list(FULL_COLUMNS)
    for action, name, value in NARROW_STEPS:
        if _table_width(columns) <= width:
            break
        if action == "drop":
            columns = [c for c in columns if c[0] != name]
        else:
            columns = [(n, min(w, value) if n == name else w) for n, w in columns]
    return columns


def render_table(rows: Sequence[EdgeRow], settings: Settings,
                 width: Optional[int] = None) -> str:
    columns = _fit_columns(width or terminal_width())
    names = [name for name, _w in columns]
    header = [
        (f"IC {int(settings.ci_level * 100)}%" if name == "IC EDGE" else name, w)
        for name, w in columns
    ]
    lines = [
        "  ".join(name[:w].ljust(w) for name, w in header),
        "  ".join("-" * w for _name, w in columns),
    ]
    for row in rows:
        ci = (
            f"[{row.edge_lo:+.1f};{row.edge_hi:+.1f}]"
            if row.edge_lo is not None and row.edge_hi is not None
            else f"[p {row.p_model_lo * 100:.0f}-{row.p_model_hi * 100:.0f}%]"
        )
        values = {
            "PARTITA": (row.match_label, "<"),
            "MERCATO": (row.market, "<"),
            "SELEZIONE": (row.selection, "<"),
            "BOOK": (row.book, "<"),
            "QUOTA": (_fmt_odds(row.odds), ">"),
            "P.MOD": (f"{row.p_model * 100:.1f}%", ">"),
            "P.MKT": (_fmt_pct(row.p_market * 100 if row.p_market is not None else None), ">"),
            "EDGE": (f"{row.edge_pct:+.1f}%" if row.edge_pct is not None else "n/d", ">"),
            "IC EDGE": (ci, "<"),
            "AFFID.": (row.reliability, "<"),
        }
        cells = []
        for name, w in columns:
            text, align = values[name]
            text = _truncate(text, w)
            cells.append(text.rjust(w) if align == ">" else text.ljust(w))
        lines.append("  ".join(cells))
    return "\n".join(lines)


def render_notes(rows: Sequence[EdgeRow]) -> str:
    """Dettaglio delle righe a bassa affidabilita': mai escluse in silenzio."""
    seen: Dict[str, str] = {}
    for row in rows:
        if row.reliability != RELIABILITY_OK and row.match_label not in seen:
            seen[row.match_label] = (
                f"[{row.reliability}] {row.match_label}: {row.reliability_note} "
                f"(partite usate: casa {row.home_matches}, trasferta {row.away_matches})"
            )
    extra = {r.note for r in rows if r.note}
    out: List[str] = []
    if seen:
        out.append("AFFIDABILITA' DEI DATI DI FORMA")
        out.extend("  - " + v for v in seen.values())
    if extra:
        out.append("")
        out.append("NOTE SUI MERCATI")
        out.extend("  - " + n for n in sorted(extra))
    return "\n".join(out)


def render_header(
    day_from: dt.date,
    day_to: dt.date,
    competitions: Sequence[str],
    settings: Settings,
    generated_at: dt.datetime,
    odds_provider: str = "",
) -> str:
    return "\n".join(
        [
            SEPARATOR,
            "ANALISI EDGE CALCIO - stima statistica, non un pronostico",
            SEPARATOR,
            f"Generato il      : {generated_at:%Y-%m-%d %H:%M} UTC",
            f"Finestra partite : {day_from} -> {day_to}",
            f"Campionati       : {', '.join(competitions)}",
            f"Fonte quote      : {odds_provider or 'n/d'}",
            f"Modello          : Poisson bivariato (lambda3={settings.lambda_cov:g}), "
            f"forma su {settings.form_matches} partite per split, "
            f"mezza vita {settings.half_life_days:g} giorni",
            f"Devig            : {settings.devig_method}"
            + (f", blend col mercato {settings.market_blend:.0%}" if settings.market_blend else ""),
            f"Incertezza       : Monte Carlo, {settings.mc_draws} estrazioni, "
            f"intervallo al {settings.ci_level:.0%}",
            SEPARATOR,
        ]
    )


LIMITS = """\
LIMITI DEL MODELLO - LEGGERE PRIMA DI USARE QUESTI NUMERI

 1. Nessuna notizia dell'ultimo minuto. Il modello NON conosce formazioni
    ufficiali, infortuni, squalifiche, turnover, motivazioni di classifica,
    meteo o cambi di allenatore. Le formazioni escono circa un'ora prima del
    fischio d'inizio: eseguito prima di quel momento, il modello ignora
    informazioni che il mercato ha gia' incorporato nelle quote.
 2. Un edge positivo NON e' un profitto garantito. E' la differenza fra due
    stime, entrambe incerte. L'intervallo di confidenza mostrato copre solo
    l'errore di stima dei gol attesi: non copre l'errore di specificazione del
    modello (il calcio non e' esattamente Poisson), i cambi di rosa, ne' il
    fatto che il mercato e' mediamente ben calibrato. L'incertezza reale e'
    quindi PIU' AMPIA di quella riportata.
 3. Dati scarsi = stime fragili. Neopromosse, inizio stagione, campionati
    minori e squadre con meno di 5 partite nello split casa/trasferta sono
    marcati "BASSA" o "INSUFF.": su quelle righe l'edge e' rumore quanto
    segnale. Non sono state escluse, ma vanno lette come tali.
 4. Il mercato e' un concorrente forte. Nei campionati principali le quote
    incorporano molte piu' informazioni di questo modello. Un edge molto
    grande (>15%) e' quasi sempre un errore nostro, non un'occasione: quota
    stantia, mercato con poca liquidita', o squadre abbinate male fra le fonti.
 5. Nessuna riga di questo output e' un consiglio. Non esistono qui pick
    "sicuri", "garantiti" o "banco": ogni riga e' una probabilita' con un
    margine d'errore. Le scommesse sono un intrattenimento a valore atteso
    negativo per la stragrande maggioranza dei giocatori.
"""


def render_footer(
    stats: Dict[str, object], settings: Settings, low_reliability: int, total_rows: int
) -> str:
    parts = [
        SEPARATOR,
        "RIEPILOGO",
        f"  Righe con quota (edge)     : {total_rows}",
        f"  di cui bassa affidabilita' : {low_reliability}",
        f"  Righe senza quota          : {stats.get('unpriced_rows', 0)} "
        "(solo probabilita' di modello)",
        f"  Partite senza quote        : {stats.get('unmatched', 0)}",
        f"  Chiamate di rete           : {stats.get('network_calls', 0)} "
        f"(cache: {stats.get('cache_hits', 0)})",
    ]

    remaining = stats.get("odds_requests_remaining")
    if remaining is not None:
        provider = stats.get("odds_provider") or "provider quote"
        used = stats.get("odds_requests_used")
        line = f"  Crediti {provider:<19}: {remaining} rimasti"
        if used is not None:
            line += f", {used} usati"
        parts.append(line)
        try:
            if int(str(remaining)) <= 50:
                parts.append("  ! Crediti quasi esauriti: alza --cache-ttl o riduci "
                             "il numero di campionati per far durare il piano.")
        except (TypeError, ValueError):
            pass

    for note in stats.get("api_notes", []) or []:
        parts.append(f"  ! {note}")
    parts += [SEPARATOR, "", LIMITS, SEPARATOR]
    return "\n".join(parts)


# ------------------------------------------------------------------ export
def rows_to_dicts(rows: Sequence[EdgeRow]) -> List[dict]:
    out = []
    for r in rows:
        out.append(
            {
                "kickoff_utc": r.kickoff.isoformat(),
                "competizione": r.competition,
                "partita": r.match_label,
                "mercato": r.market,
                "selezione": r.selection,
                "bookmaker_migliore": r.book,
                "quota": r.odds,
                "n_bookmaker": r.n_books,
                "overround_medio_pct": (
                    round(r.avg_overround * 100, 2) if r.avg_overround is not None else None
                ),
                "prob_modello_pct": round(r.p_model * 100, 2),
                "prob_modello_ic_basso_pct": round(r.p_model_lo * 100, 2),
                "prob_modello_ic_alto_pct": round(r.p_model_hi * 100, 2),
                "prob_mercato_equa_pct": (
                    round(r.p_market * 100, 2) if r.p_market is not None else None
                ),
                "edge_pct": round(r.edge_pct, 2) if r.edge_pct is not None else None,
                "edge_ic_basso_pct": round(r.edge_lo, 2) if r.edge_lo is not None else None,
                "edge_ic_alto_pct": round(r.edge_hi, 2) if r.edge_hi is not None else None,
                "differenza_prob_punti": (
                    round(r.delta_pp, 2) if r.delta_pp is not None else None
                ),
                "affidabilita": r.reliability,
                "affidabilita_nota": r.reliability_note,
                "xg_casa": round(r.lam_home, 3),
                "xg_trasferta": round(r.lam_away, 3),
                "partite_casa_usate": r.home_matches,
                "partite_trasferta_usate": r.away_matches,
                "nota": r.note,
            }
        )
    return out


def to_csv(rows: Sequence[EdgeRow]) -> str:
    data = rows_to_dicts(rows)
    if not data:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(data[0].keys()))
    writer.writeheader()
    writer.writerows(data)
    return buf.getvalue()


def to_json(rows: Sequence[EdgeRow], stats: Dict[str, object], settings: Settings) -> str:
    return json.dumps(
        {
            "avvertenza": (
                "Stime statistiche con incertezza rilevante. Nessuna riga e' un "
                "pronostico sicuro o garantito."
            ),
            "parametri": {
                "form_matches": settings.form_matches,
                "half_life_days": settings.half_life_days,
                "prior_matches": settings.prior_matches,
                "lambda_cov": settings.lambda_cov,
                "devig_method": settings.devig_method,
                "market_blend": settings.market_blend,
                "mc_draws": settings.mc_draws,
                "ci_level": settings.ci_level,
            },
            "limiti": [l.strip() for l in LIMITS.strip().split("\n\n")[1:]],
            "statistiche": stats,
            "righe": rows_to_dicts(rows),
        },
        ensure_ascii=False,
        indent=2,
    )
