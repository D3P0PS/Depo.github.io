"""Esportazione HTML: la stessa analisi, come pagina apribile nel browser.

File singolo, nessuna dipendenza esterna (niente CDN, niente JS di terze
parti): deve aprirsi con un doppio clic anche senza connessione. Il contenuto
e i limiti sono identici alla tabella da terminale — questo e' solo un altro
modo di leggerli, non un'altra fonte di verita'.
"""

from __future__ import annotations

import datetime as dt
import html
from typing import Dict, List, Optional, Sequence

from .analysis import EdgeRow, RELIABILITY_LOW, RELIABILITY_NONE, RELIABILITY_OK
from .calibration import Calibration
from .config import Settings
from .report import LIMITS

_RELIABILITY_CLASS = {
    RELIABILITY_OK: "ok",
    RELIABILITY_LOW: "low",
    RELIABILITY_NONE: "none",
}


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _edge_class(edge: Optional[float]) -> str:
    if edge is None:
        return "edge-na"
    if abs(edge) > 15.0:
        return "edge-implausible"
    return "edge-pos" if edge > 0 else "edge-neg"


def _row_html(r: EdgeRow) -> str:
    ci = (
        f"{r.edge_lo:+.1f}% ; {r.edge_hi:+.1f}%"
        if r.edge_lo is not None and r.edge_hi is not None
        else f"p {r.p_model_lo * 100:.0f}–{r.p_model_hi * 100:.0f}%"
    )
    odds = f"{r.odds:.2f}" if r.odds else "–"
    market_p = f"{r.p_market * 100:.1f}%" if r.p_market is not None else "–"
    edge = f"{r.edge_pct:+.1f}%" if r.edge_pct is not None else "–"
    rel_class = _RELIABILITY_CLASS.get(r.reliability, "low")
    note = f'<div class="note">{_esc(r.note)}</div>' if r.note else ""
    return f"""
      <tr class="{_edge_class(r.edge_pct)}">
        <td class="match">{_esc(r.match_label)}<span class="comp">{_esc(r.competition)}</span></td>
        <td>{_esc(r.market)}</td>
        <td>{_esc(r.selection)}</td>
        <td class="num">{odds}</td>
        <td class="num">{r.p_model * 100:.1f}%</td>
        <td class="num">{market_p}</td>
        <td class="num edge-cell">{edge}</td>
        <td class="ci">{_esc(ci)}{note}</td>
        <td><span class="badge {rel_class}">{_esc(r.reliability)}</span>
            {f'<div class="note">{_esc(r.reliability_note)}</div>' if r.reliability_note else ""}</td>
      </tr>"""


def _table_html(rows: Sequence[EdgeRow], caption: str) -> str:
    if not rows:
        return ""

    # Raggruppa per match (kickoff, competition, match_label)
    from collections import defaultdict
    groups: Dict[tuple, List[EdgeRow]] = defaultdict(list)
    for row in rows:
        key = (row.kickoff, row.competition, row.match_label)
        groups[key].append(row)

    # Ordina i mercati dentro ogni match per edge decrescente
    body_lines = []
    for (kickoff, competition, match_label), market_rows in sorted(groups.items()):
        sorted_markets = sorted(
            market_rows,
            key=lambda r: (0, -r.edge_pct) if r.edge_pct is not None else (1, 0.0),
            reverse=False
        )

        # Aggiungi riga header per il match
        body_lines.append(f"""
      <tr class="match-header">
        <td colspan="9" class="match-name">{_esc(match_label)} <span class="comp-badge">{_esc(competition)}</span></td>
      </tr>""")

        # Aggiungi le righe dei mercati (senza il nome della partita ripetuto)
        for row in sorted_markets:
            # Modifica la row per non mostrare il match_label (vuoto)
            ci = (
                f"{row.edge_lo:+.1f}% ; {row.edge_hi:+.1f}%"
                if row.edge_lo is not None and row.edge_hi is not None
                else f"p {row.p_model_lo * 100:.0f}–{row.p_model_hi * 100:.0f}%"
            )
            odds = f"{row.odds:.2f}" if row.odds else "–"
            market_p = f"{row.p_market * 100:.1f}%" if row.p_market is not None else "–"
            edge = f"{row.edge_pct:+.1f}%" if row.edge_pct is not None else "–"
            rel_class = _RELIABILITY_CLASS.get(row.reliability, "low")
            note = f'<div class="note">{_esc(row.note)}</div>' if row.note else ""
            body_lines.append(f"""
      <tr class="{_edge_class(row.edge_pct)}">
        <td></td>
        <td>{_esc(row.market)}</td>
        <td>{_esc(row.selection)}</td>
        <td class="num">{odds}</td>
        <td class="num">{row.p_model * 100:.1f}%</td>
        <td class="num">{market_p}</td>
        <td class="num edge-cell">{edge}</td>
        <td class="ci">{_esc(ci)}{note}</td>
        <td><span class="badge {rel_class}">{_esc(row.reliability)}</span>
            {f'<div class="note">{_esc(row.reliability_note)}</div>' if row.reliability_note else ""}</td>
      </tr>""")

    body = "\n".join(body_lines)
    return f"""
    <h2>{_esc(caption)}</h2>
    <div class="table-wrap">
    <table>
      <thead><tr>
        <th>Partita</th><th>Mercato</th><th>Selezione</th><th>Quota</th>
        <th>P. modello</th><th>P. mercato</th><th>Edge</th>
        <th>Intervallo (90%)</th><th>Affidabilità</th>
      </tr></thead>
      <tbody>{body}</tbody>
    </table>
    </div>"""


def _calibration_html(c: Calibration) -> str:
    if not c.rows:
        return ""
    corr = f"{c.correlation:.2f}" if c.correlation is not None else "n/d"
    stats = f"""
      <div class="cal-stats">
        <div><span>{c.rows}</span>righe confrontate col mercato</div>
        <div><span>{c.mean_deviation * 100:.1f} pt</span>scostamento medio</div>
        <div><span>{corr}</span>correlazione col mercato</div>
        <div><span>{c.implausible_share:.0%}</span>righe con |edge| &gt; 15%</div>
      </div>"""
    if c.suspect:
        warnings = "".join(f"<li>{_esc(w)}</li>" for w in c.warnings)
        return f"""
    <div class="banner banner-bad">
      <h2>⚠ Questa corsa non è utilizzabile come lista di occasioni</h2>
      {stats}
      <ul class="warnings">{warnings}</ul>
      <p class="hint">Prova <code>--market-blend 0.3</code> per avvicinare le stime
      al mercato, o guarda le righe marcate INSUFF. qui sotto: sono la causa più
      comune.</p>
    </div>"""
    return f"""
    <div class="banner banner-ok">
      <h2>Controllo di calibrazione: nella norma</h2>
      {stats}
    </div>"""


CSS = """
:root {
  color-scheme: light;
  --bg: #f6f5f2; --panel: #ffffff; --ink: #1b1b1d; --muted: #6b6b70;
  --line: #e4e2dc; --accent: #2f6f4f; --bad-bg: #fdeeee; --bad-line: #d98a8a;
  --bad-ink: #7a2020; --ok-bg: #eef6f0; --ok-line: #a9cdb4;
  --pos: #1f7a4d; --neg: #8a2b2b; --warn-bg: #fff6e0; --warn-ink: #7a5b00;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  padding: 24px 16px 64px;
}
.wrap { max-width: 1180px; margin: 0 auto; }
header { margin-bottom: 20px; }
header h1 { font-size: 1.5rem; margin: 0 0 4px; }
header .meta { color: var(--muted); font-size: 0.92rem; }
.disclaimer {
  background: var(--warn-bg); color: var(--warn-ink); border-radius: 10px;
  padding: 12px 16px; margin: 16px 0; font-size: 0.9rem;
}
.banner { border-radius: 12px; padding: 18px 20px; margin: 20px 0; }
.banner-bad { background: var(--bad-bg); border: 1px solid var(--bad-line); color: var(--bad-ink); }
.banner-ok { background: var(--ok-bg); border: 1px solid var(--ok-line); }
.banner h2 { margin: 0 0 10px; font-size: 1.05rem; }
.cal-stats { display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 10px; }
.cal-stats div { font-size: 0.85rem; color: inherit; opacity: 0.85; }
.cal-stats span { display: block; font-size: 1.15rem; font-weight: 600; opacity: 1; }
.warnings { margin: 8px 0; padding-left: 20px; }
.warnings li { margin-bottom: 6px; }
.hint { margin: 10px 0 0; font-size: 0.88rem; }
.hint code { background: rgba(0,0,0,0.08); padding: 1px 5px; border-radius: 4px; }
h2 { font-size: 1.1rem; margin: 28px 0 10px; }
.table-wrap { overflow-x: auto; border-radius: 12px; border: 1px solid var(--line); background: var(--panel); }
table { border-collapse: collapse; width: 100%; font-size: 0.88rem; white-space: nowrap; }
thead th {
  text-align: left; padding: 10px 12px; background: #efede8; color: var(--muted);
  font-weight: 600; font-size: 0.76rem; text-transform: uppercase; letter-spacing: 0.03em;
  position: sticky; top: 0;
}
tbody td { padding: 9px 12px; border-top: 1px solid var(--line); vertical-align: top; }
tbody tr:hover { background: #faf9f6; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
td.match { white-space: normal; min-width: 200px; }
td.match .comp { display: block; color: var(--muted); font-size: 0.76rem; }
td.ci { white-space: normal; color: var(--muted); font-size: 0.82rem; min-width: 160px; }
.note { color: var(--muted); font-size: 0.78rem; margin-top: 2px; white-space: normal; }
.edge-cell { font-weight: 600; }
tr.match-header { background: #f0ede8; border: 1px solid var(--line); }
tr.match-header td { padding: 12px; font-weight: 600; color: var(--ink); }
.match-name { font-size: 0.98rem; }
.comp-badge { display: inline-block; margin-left: 8px; padding: 2px 8px; background: var(--accent); color: white; border-radius: 4px; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; }
tr.edge-pos .edge-cell { color: var(--pos); }
tr.edge-neg .edge-cell { color: var(--neg); }
tr.edge-implausible { background: var(--bad-bg); }
tr.edge-implausible .edge-cell { color: var(--bad-ink); }
.badge {
  display: inline-block; padding: 2px 8px; border-radius: 999px;
  font-size: 0.74rem; font-weight: 600;
}
.badge.ok { background: var(--ok-bg); color: var(--pos); border: 1px solid var(--ok-line); }
.badge.low { background: var(--warn-bg); color: var(--warn-ink); border: 1px solid #e8d180; }
.badge.none { background: var(--bad-bg); color: var(--bad-ink); border: 1px solid var(--bad-line); }
footer {
  margin-top: 32px; padding: 18px 20px; background: var(--panel);
  border: 1px solid var(--line); border-radius: 12px; font-size: 0.85rem; color: var(--muted);
}
footer h2 { color: var(--ink); font-size: 0.95rem; margin-top: 0; }
footer ol { padding-left: 20px; }
footer li { margin-bottom: 8px; }
.summary-line { color: var(--muted); font-size: 0.85rem; margin: 4px 0; }
"""


def render_html(
    rows: Sequence[EdgeRow],
    unpriced: Sequence[EdgeRow],
    calibration: Calibration,
    stats: Dict[str, object],
    settings: Settings,
    date_from: dt.date,
    date_to: dt.date,
    competitions: Sequence[str],
    odds_provider: str,
    generated_at: dt.datetime,
) -> str:
    limits_html = "".join(
        f"<li>{_esc(line.strip())}</li>"
        for block in LIMITS.strip().split("\n\n")[1:]
        for line in [" ".join(block.split())]
        if line
    )
    notes_html = "".join(f"<li>{_esc(n)}</li>" for n in (stats.get("api_notes") or []))
    notes_block = (
        f'<div class="disclaimer"><strong>Note di raccolta dati</strong><ul>{notes_html}</ul></div>'
        if notes_html else ""
    )

    return f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<title>Edge calcio {_esc(date_from.isoformat())}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Analisi edge calcio — stima statistica, non un pronostico</h1>
    <div class="meta">
      Generato il {generated_at:%Y-%m-%d %H:%M} UTC &middot;
      finestra {date_from} → {date_to} &middot;
      campionati {_esc(', '.join(competitions))} &middot;
      quote: {_esc(odds_provider)}
    </div>
    <div class="summary-line">
      {len(rows)} righe con quota &middot; {len(unpriced)} solo probabilità di
      modello &middot; {stats.get('unmatched', 0)} partite senza quote abbinate
    </div>
  </header>

  {notes_block}
  {_calibration_html(calibration)}
  {_table_html(rows, "Mercati con quota, per edge decrescente")}
  {_table_html(unpriced, "Mercati senza quota abbinata (solo probabilità di modello)")}

  <footer>
    <h2>Limiti del modello — leggere prima di usare questi numeri</h2>
    <ol>{limits_html}</ol>
  </footer>
</div>
</body>
</html>
"""
