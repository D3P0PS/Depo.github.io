"""Esportazione HTML: la stessa analisi, come pagina apribile nel browser.

File singolo, nessuna dipendenza esterna (niente CDN, niente JS di terze
parti): deve aprirsi con un doppio clic anche senza connessione. Il contenuto
e i limiti sono identici alla tabella da terminale — questo e' solo un altro
modo di leggerli, non un'altra fonte di verita'.

Include una "schedina" virtuale lato client (solo JS/localStorage, nessun
dato lascia la pagina): serve a comporre piu' selezioni, vedere la quota
combinata e copiare il tutto per riportarlo manualmente sul sito del
bookmaker. Non piazza scommesse, non parla con nessuna API esterna.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

from .analysis import EdgeRow, RELIABILITY_LOW, RELIABILITY_NONE, RELIABILITY_OK
from .calibration import Calibration
from .combos import ComboSuggestion, suggest_combos
from .config import Settings
from .news import get_news_alerts
from .report import LIMITS
from .sofascore_history import MatchCardCheck

_RELIABILITY_CLASS = {
    RELIABILITY_OK: "ok",
    RELIABILITY_LOW: "low",
    RELIABILITY_NONE: "none",
}


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _slip_key(match_label: str, market: str, selection: str) -> str:
    raw = f"{match_label}|{market}|{selection}"
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")


def _edge_class(edge: Optional[float]) -> str:
    if edge is None:
        return "edge-na"
    if abs(edge) > 15.0:
        return "edge-implausible"
    return "edge-pos" if edge > 0 else "edge-neg"


def _slip_button(row: EdgeRow) -> str:
    if row.odds is None:
        return '<span class="slip-na">–</span>'
    key = _slip_key(row.match_label, row.market, row.selection)
    return (
        f'<button type="button" class="slip-add" '
        f'data-key="{_esc(key)}" data-match="{_esc(row.match_label)}" '
        f'data-market="{_esc(row.market)}" data-selection="{_esc(row.selection)}" '
        f'data-odds="{row.odds:.2f}">+ Schedina</button>'
    )


def _market_row_html(row: EdgeRow, allow_slip: bool, group: str) -> str:
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
    rel_note = (
        f'<div class="note">{_esc(row.reliability_note)}</div>' if row.reliability_note else ""
    )
    slip_cell = f'<td data-label="Schedina" class="slip-cell">{_slip_button(row)}</td>' if allow_slip else ""
    return f"""
      <tr class="{_edge_class(row.edge_pct)} market-row" data-group="{group}" hidden>
        <td data-label="Mercato">{_esc(row.market)}</td>
        <td data-label="Selezione">{_esc(row.selection)}</td>
        <td data-label="Quota" class="num">{odds}</td>
        <td data-label="P. modello" class="num">{row.p_model * 100:.1f}%</td>
        <td data-label="P. mercato" class="num">{market_p}</td>
        <td data-label="Edge" class="num edge-cell">{edge}</td>
        <td data-label="Intervallo (90%)" class="ci">{_esc(ci)}{note}</td>
        <td data-label="Affidabilità"><span class="badge {rel_class}">{_esc(row.reliability)}</span>{rel_note}</td>
        {slip_cell}
      </tr>"""


def _combo_row_html(combos: Sequence[ComboSuggestion], group: str, n_cols: int) -> str:
    if not combos:
        return ""
    items = []
    for c in combos:
        a, b = c.legs
        items.append(f"""
        <div class="combo-item">
          <div class="combo-legs">{_esc(a.market)} — {_esc(a.selection)}
            <span class="combo-plus">+</span> {_esc(b.market)} — {_esc(b.selection)}</div>
          <div class="combo-stats">
            <span>Prob. congiunta modello: <strong>{c.joint_prob * 100:.1f}%</strong></span>
            <span>Quota equa: <strong>{c.fair_odds:.2f}</strong></span>
          </div>
        </div>""")
    body = "".join(items)
    return f"""
      <tr class="combo-row market-row" data-group="{group}" hidden>
        <td colspan="{n_cols}">
          <div class="combo-box">
            <div class="combo-title">🧩 Combo suggerite (solo mercati-gol, calcolate dal modello)</div>
            {body}
            <p class="combo-hint">Quota equa stimata dalla probabilità congiunta reale del modello,
            non dal semplice prodotto delle due quote singole: 1X2, Over/Under e BTTS sullo stesso
            match sono correlati. Non è la quota vera del bet builder: confrontala con quella del
            tuo bookmaker prima di puntare. Copre solo mercati-gol: corner, cartellini, tiri e primo
            tempo non sono stimati da questo strumento.</p>
          </div>
        </td>
      </tr>"""


def _table_html(
    rows: Sequence[EdgeRow], caption: str, allow_slip: bool = False,
    settings: Optional[Settings] = None,
) -> str:
    if not rows:
        return ""

    groups: Dict[Tuple[dt.datetime, str, str], List[EdgeRow]] = defaultdict(list)
    for row in rows:
        groups[(row.kickoff, row.competition, row.match_label)].append(row)

    n_cols = 9 if allow_slip else 8
    table_id = "priced" if allow_slip else "unpriced"
    body_lines = []
    for i, ((kickoff, competition, match_label), market_rows) in enumerate(sorted(groups.items())):
        sorted_markets = sorted(
            market_rows,
            key=lambda r: (0, -r.edge_pct) if r.edge_pct is not None else (1, 0.0),
        )
        kickoff_str = kickoff.strftime("%H:%M UTC") if kickoff else ""
        gid = f"{table_id}-{i}"

        best = sorted_markets[0]
        if allow_slip and best.edge_pct is not None:
            summary = f"{len(sorted_markets)} mercati &middot; top edge {best.edge_pct:+.1f}%"
        else:
            summary = f"{len(sorted_markets)} mercati"

        body_lines.append(f"""
      <tr class="match-header" data-group="{gid}" role="button" tabindex="0" aria-expanded="false">
        <td colspan="{n_cols}">
          <div class="match-name">
            <span class="match-title">{_esc(match_label)}
              <span class="comp-badge">{_esc(competition)}</span>
              <span class="kickoff-badge">{_esc(kickoff_str)}</span>
            </span>
            <span class="match-right">
              <span class="match-summary">{summary}</span>
              <span class="match-toggle-icon">▾</span>
            </span>
          </div>
        </td>
      </tr>""")
        for row in sorted_markets:
            body_lines.append(_market_row_html(row, allow_slip, group=gid))

        if allow_slip and settings is not None:
            combos = suggest_combos(sorted_markets, settings)
            body_lines.append(_combo_row_html(combos, gid, n_cols))

    body = "\n".join(body_lines)
    slip_header = "<th>Schedina</th>" if allow_slip else ""
    return f"""
    <h2>{_esc(caption)}</h2>
    <div class="table-toolbar">
      <button type="button" class="toolbar-btn" data-expand-all="{table_id}">Espandi tutte</button>
      <button type="button" class="toolbar-btn" data-collapse-all="{table_id}">Comprimi tutte</button>
    </div>
    <div class="table-wrap">
    <table class="{'with-slip' if allow_slip else ''}" data-table-id="{table_id}">
      <thead><tr>
        <th>Mercato</th><th>Selezione</th><th>Quota</th>
        <th>P. modello</th><th>P. mercato</th><th>Edge</th>
        <th>Intervallo (90%)</th><th>Affidabilità</th>{slip_header}
      </tr></thead>
      <tbody>{body}</tbody>
    </table>
    </div>"""


def _season_start_warning(rows: Sequence[EdgeRow]) -> str:
    """Avvertenza se il campionato è appena iniziato (pochi dati storici)."""
    if not rows:
        return ""

    low_data = sum(1 for r in rows if r.home_matches < 3 or r.away_matches < 3)
    total = len(rows)

    if low_data > total * 0.3:
        return f"""
    <div class="banner banner-warn">
      <h2>⚠ Stagione appena iniziata — dati storici limitati</h2>
      <p>{low_data}/{total} righe (~{low_data * 100 // total}%) hanno meno di 3 partite per split
      casa/trasferta. Per campionati all'inizio della stagione, i suggerimenti sono:</p>
      <ul>
        <li><code>--form-matches 5</code> (default: 10) — meno dati recenti, più peso alla storia</li>
        <li><code>--half-life 30</code> (default: 60) — attualizza più velocemente ai nuovi risultati</li>
        <li><code>--market-blend 0.5</code> — ancora più vicino al mercato quando i dati sono pochi</li>
      </ul>
    </div>"""
    return ""


def _freshness_badge(stats) -> str:
    age = stats.age_days()
    if age < 1:
        label = "aggiornato oggi"
    elif age < 2:
        label = "aggiornato ieri"
    else:
        label = f"aggiornato {int(age)} giorni fa"
    cls = "stale" if stats.is_stale() else "fresh"
    if stats.is_stale():
        label += " — potrebbe non riflettere la forma recente"
    return f'<span class="freshness {cls}">{_esc(label)}</span>'


def _card_check_team_html(name: str, stats) -> str:
    if stats is None:
        return f'<div class="card-check-team"><span class="card-check-name">{_esc(name)}</span>' \
               f'<span class="card-check-stats">dati non disponibili</span></div>'
    return f"""
        <div class="card-check-team">
          <span class="card-check-name">{_esc(stats.team_name)}</span>
          <span class="card-check-stats">{stats.yellow_avg:.1f} gialli/partita &middot;
          {stats.red_avg:.1f} rossi/partita ({stats.matches_used} partite)</span>
          {_freshness_badge(stats)}
        </div>"""


def _card_checks_html(card_checks: Dict[str, MatchCardCheck]) -> str:
    if not card_checks:
        return ""
    items = []
    for match_label, check in card_checks.items():
        if check.note and check.home is None and check.away is None:
            items.append(f"""
      <div class="card-check-item">
        <div class="card-check-match">{_esc(match_label)}</div>
        <div class="card-check-unavailable">{_esc(check.note)}</div>
      </div>""")
            continue
        note_html = f'<div class="card-check-note">{_esc(check.note)}</div>' if check.note else ""
        home_label, _, away_label = match_label.partition(" - ")
        items.append(f"""
      <div class="card-check-item">
        <div class="card-check-match">{_esc(match_label)}</div>
        {_card_check_team_html(home_label, check.home)}
        {_card_check_team_html(away_label, check.away)}
        {note_html}
      </div>""")
    body = "".join(items)
    return f"""
    <h2>🃏 Verifica statistica — cartellini sulle top partite</h2>
    <p class="section-hint">Media sulle ultime partite giocate da ciascuna squadra (fonte: SofaScore).
    Non è un edge calcolato, è un riscontro aggiuntivo da leggere insieme alla stima sui gol qui sotto.</p>
    <div class="card-check-grid">{body}</div>"""


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
  color-scheme: light dark;
  --bg: #f6f5f2; --panel: #ffffff; --ink: #1b1b1d; --muted: #6b6b70;
  --line: #e4e2dc; --accent: #2f6f4f; --accent-ink: #ffffff;
  --bad-bg: #fdeeee; --bad-line: #d98a8a; --bad-ink: #7a2020;
  --ok-bg: #eef6f0; --ok-line: #a9cdb4;
  --pos: #1f7a4d; --neg: #8a2b2b; --warn-bg: #fff6e0; --warn-ink: #7a5b00;
  --shadow: 0 10px 30px rgba(20, 20, 20, 0.12);
  --head-bg: #efede8;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #15161a; --panel: #1e2025; --ink: #eceef1; --muted: #9498a1;
    --line: #2c2f36; --accent: #3fa571; --accent-ink: #06120b;
    --bad-bg: #3a1d1d; --bad-line: #6e2f2f; --bad-ink: #f3a3a3;
    --ok-bg: #16301f; --ok-line: #2c5c3c;
    --pos: #4fce8d; --neg: #f08787; --warn-bg: #3a2f0d; --warn-ink: #eecb6b;
    --shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
    --head-bg: #24262c;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  padding: 20px 16px 96px;
  -webkit-text-size-adjust: 100%;
}
.wrap { max-width: 1180px; margin: 0 auto; }
header { margin-bottom: 20px; }
header h1 { font-size: 1.35rem; margin: 0 0 6px; line-height: 1.3; }
header .meta { color: var(--muted); font-size: 0.86rem; }
header .summary-line { color: var(--muted); font-size: 0.86rem; margin: 6px 0 0; }
.disclaimer {
  background: var(--warn-bg); color: var(--warn-ink); border-radius: 12px;
  padding: 12px 16px; margin: 16px 0; font-size: 0.9rem;
}
.disclaimer ul { margin: 6px 0 0; padding-left: 20px; }
.banner { border-radius: 14px; padding: 16px 18px; margin: 16px 0; box-shadow: var(--shadow); }
.banner-bad { background: var(--bad-bg); border: 1px solid var(--bad-line); color: var(--bad-ink); }
.banner-ok { background: var(--ok-bg); border: 1px solid var(--ok-line); }
.banner-warn { background: var(--warn-bg); border: 1px solid #e8d180; color: var(--warn-ink); }
.banner h2 { margin: 0 0 10px; font-size: 1.02rem; }
.banner a { color: inherit; text-decoration: underline; }
.banner a:hover { opacity: 0.8; }
.cal-stats { display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 10px; }
.cal-stats div { font-size: 0.82rem; color: inherit; opacity: 0.85; }
.cal-stats span { display: block; font-size: 1.15rem; font-weight: 700; opacity: 1; }
.warnings { margin: 8px 0; padding-left: 20px; }
.warnings li { margin-bottom: 6px; }
.hint { margin: 10px 0 0; font-size: 0.86rem; }
.hint code { background: rgba(127,127,127,0.18); padding: 1px 5px; border-radius: 4px; }
h2 { font-size: 1.05rem; margin: 26px 0 10px; }
[hidden] { display: none !important; }
.table-toolbar {
  display: flex; justify-content: flex-end; gap: 8px; padding: 8px 4px; margin-bottom: 6px;
}
.toolbar-btn {
  border: 1px solid var(--line); background: var(--panel); color: var(--ink);
  padding: 6px 12px; border-radius: 8px; font-size: 0.76rem; cursor: pointer; font-family: inherit;
}
.toolbar-btn:hover { background: var(--head-bg); }
.table-wrap {
  overflow-x: auto; border-radius: 14px; border: 1px solid var(--line);
  background: var(--panel); box-shadow: var(--shadow);
  -webkit-overflow-scrolling: touch;
}
table { border-collapse: collapse; width: 100%; font-size: 0.86rem; }
thead th {
  text-align: left; padding: 10px 12px; background: var(--head-bg); color: var(--muted);
  font-weight: 700; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.03em;
  white-space: nowrap;
}
tbody td { padding: 10px 12px; border-top: 1px solid var(--line); vertical-align: top; }
tbody tr:not(.match-header):hover { background: rgba(127,127,127,0.06); }
td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.ci { color: var(--muted); font-size: 0.8rem; min-width: 150px; }
.note { color: var(--muted); font-size: 0.76rem; margin-top: 2px; }
.edge-cell { font-weight: 700; }
tr.match-header { background: var(--head-bg); cursor: pointer; }
tr.match-header:hover { background: rgba(127,127,127,0.14); }
tr.match-header td { padding: 12px; font-weight: 700; color: var(--ink); }
.match-name {
  font-size: 0.95rem; display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 8px 14px;
}
.match-title { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.match-right { display: flex; align-items: center; gap: 10px; margin-left: auto; }
.match-summary { color: var(--muted); font-size: 0.78rem; font-weight: 500; white-space: nowrap; }
.match-toggle-icon {
  color: var(--muted); font-size: 0.85rem; transition: transform 0.2s ease; display: inline-block;
}
tr.match-header[aria-expanded="true"] .match-toggle-icon { transform: rotate(180deg); }
.comp-badge {
  display: inline-block; padding: 2px 9px; background: var(--accent); color: var(--accent-ink);
  border-radius: 999px; font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
}
.kickoff-badge { color: var(--muted); font-size: 0.76rem; font-weight: 500; }
tr.edge-pos .edge-cell { color: var(--pos); }
tr.edge-neg .edge-cell { color: var(--neg); }
tr.edge-implausible { background: rgba(220, 80, 80, 0.08); }
tr.edge-implausible .edge-cell { color: var(--bad-ink); }
.badge {
  display: inline-block; padding: 2px 9px; border-radius: 999px;
  font-size: 0.72rem; font-weight: 700;
}
.badge.ok { background: var(--ok-bg); color: var(--pos); border: 1px solid var(--ok-line); }
.badge.low { background: var(--warn-bg); color: var(--warn-ink); border: 1px solid #e8d180; }
.badge.none { background: var(--bad-bg); color: var(--bad-ink); border: 1px solid var(--bad-line); }

/* --- combo "bet builder" suggerite (solo mercati-gol) --- */
.combo-box {
  background: rgba(47, 111, 79, 0.07); border: 1px dashed var(--accent);
  border-radius: 10px; padding: 12px 14px; margin: 4px 0;
}
.combo-title { font-weight: 700; font-size: 0.82rem; margin-bottom: 8px; }
.combo-item { padding: 8px 0; border-top: 1px dashed var(--line); }
.combo-item:first-of-type { border-top: none; padding-top: 0; }
.combo-legs { font-size: 0.86rem; font-weight: 600; margin-bottom: 4px; }
.combo-plus { color: var(--muted); margin: 0 4px; font-weight: 400; }
.combo-stats { display: flex; gap: 16px; flex-wrap: wrap; font-size: 0.8rem; color: var(--muted); }
.combo-stats strong { color: var(--ink); font-variant-numeric: tabular-nums; }
.combo-hint { margin: 10px 0 0; font-size: 0.72rem; color: var(--muted); }

/* --- verifica statistica cartellini (top partite) --- */
.section-hint { color: var(--muted); font-size: 0.84rem; margin: -6px 0 12px; }
.card-check-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px; margin-bottom: 20px;
}
.card-check-item {
  background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
  padding: 14px 16px; box-shadow: var(--shadow);
}
.card-check-match { font-weight: 700; font-size: 0.9rem; margin-bottom: 10px; }
.card-check-team { padding: 8px 0; border-top: 1px dashed var(--line); }
.card-check-team:first-of-type { border-top: none; padding-top: 0; }
.card-check-name { display: block; font-weight: 600; font-size: 0.85rem; }
.card-check-stats { display: block; color: var(--muted); font-size: 0.8rem; margin: 2px 0; }
.card-check-unavailable { color: var(--muted); font-size: 0.82rem; font-style: italic; }
.card-check-note { margin-top: 8px; font-size: 0.76rem; color: var(--warn-ink); }
.freshness { font-size: 0.72rem; font-weight: 600; }
.freshness.fresh { color: var(--pos); }
.freshness.stale { color: var(--warn-ink); }

footer {
  margin-top: 28px; padding: 16px 18px; background: var(--panel);
  border: 1px solid var(--line); border-radius: 14px; font-size: 0.84rem; color: var(--muted);
}
footer h2 { color: var(--ink); font-size: 0.92rem; margin-top: 0; }
footer ol { padding-left: 20px; }
footer li { margin-bottom: 8px; }

/* --- pulsante "aggiungi a schedina" --- */
.slip-add {
  border: 1px solid var(--accent); background: transparent; color: var(--accent);
  padding: 5px 11px; border-radius: 999px; font-size: 0.74rem; font-weight: 700;
  cursor: pointer; white-space: nowrap; font-family: inherit;
}
.slip-add.active { background: var(--accent); color: var(--accent-ink); }
.slip-na { color: var(--muted); }

/* --- pulsante flottante + pannello schedina --- */
.slip-fab {
  position: fixed; bottom: 20px; right: 20px; z-index: 40;
  width: 58px; height: 58px; border-radius: 50%; border: none;
  background: var(--accent); color: var(--accent-ink); font-size: 1.5rem;
  box-shadow: var(--shadow); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
}
.slip-badge {
  position: absolute; top: -4px; right: -4px; background: var(--neg); color: white;
  border-radius: 999px; font-size: 0.7rem; min-width: 20px; height: 20px;
  display: flex; align-items: center; justify-content: center; padding: 0 5px;
  font-weight: 700; border: 2px solid var(--bg);
}
.slip-panel {
  position: fixed; z-index: 50; background: var(--panel); border: 1px solid var(--line);
  box-shadow: var(--shadow); display: flex; flex-direction: column;
  transition: transform 0.22s ease, opacity 0.22s ease;
  left: 0; right: 0; bottom: 0; max-height: 78vh; border-radius: 18px 18px 0 0;
  transform: translateY(110%);
}
.slip-panel.open { transform: translateY(0); }
@media (min-width: 640px) {
  .slip-panel {
    left: auto; right: 20px; bottom: 92px; width: 400px; max-width: calc(100vw - 40px);
    border-radius: 16px; max-height: 72vh;
    transform: translateY(16px) scale(0.97); opacity: 0; pointer-events: none;
  }
  .slip-panel.open { transform: translateY(0) scale(1); opacity: 1; pointer-events: auto; }
}
.slip-panel-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 16px; border-bottom: 1px solid var(--line);
}
.slip-panel-header h3 { margin: 0; font-size: 1rem; }
.slip-close {
  border: none; background: none; color: var(--muted); font-size: 1.4rem;
  cursor: pointer; line-height: 1; padding: 2px 6px;
}
.slip-panel-body { overflow-y: auto; padding: 8px 16px; flex: 1; }
.slip-empty { color: var(--muted); font-size: 0.86rem; text-align: center; padding: 26px 8px; }
.slip-list { list-style: none; margin: 0; padding: 0; }
.slip-item {
  display: flex; align-items: flex-start; gap: 10px; padding: 10px 0;
  border-bottom: 1px solid var(--line);
}
.slip-item:last-child { border-bottom: none; }
.slip-item-main { flex: 1; min-width: 0; }
.slip-item-match { font-weight: 700; font-size: 0.85rem; }
.slip-item-sel { color: var(--muted); font-size: 0.78rem; margin-top: 2px; }
.slip-item-odds { font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; }
.slip-remove {
  border: none; background: none; color: var(--muted); font-size: 1.3rem;
  cursor: pointer; line-height: 1; padding: 0 2px;
}
.slip-remove:hover { color: var(--bad-ink); }
.slip-panel-footer { padding: 14px 16px; border-top: 1px solid var(--line); }
.slip-totals { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; font-size: 0.88rem; }
.slip-totals .slip-row { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.slip-totals strong { font-variant-numeric: tabular-nums; }
.slip-totals input {
  width: 90px; padding: 6px 8px; border: 1px solid var(--line); border-radius: 8px;
  font-size: 0.9rem; background: var(--bg); color: var(--ink); font-family: inherit;
}
.slip-actions { display: flex; gap: 8px; }
.btn-primary {
  flex: 1; background: var(--accent); color: var(--accent-ink); border: none;
  padding: 11px; border-radius: 10px; font-weight: 700; cursor: pointer;
  font-size: 0.88rem; font-family: inherit;
}
.btn-secondary {
  background: none; border: 1px solid var(--line); padding: 11px 14px; border-radius: 10px;
  cursor: pointer; font-size: 0.88rem; color: var(--ink); font-family: inherit;
}
.slip-hint { margin: 10px 0 0; font-size: 0.72rem; color: var(--muted); }

/* --- layout a card sotto i 720px: la tabella diventa una lista di righe --- */
@media (max-width: 720px) {
  header h1 { font-size: 1.15rem; }
  table.with-slip, table:not(.with-slip) { font-size: 0.88rem; }
  thead { display: none; }
  table, tbody, tr, td { display: block; width: 100%; }
  tbody tr:not(.match-header) {
    border: 1px solid var(--line); border-radius: 12px; margin: 10px 8px;
    padding: 4px 0; background: var(--panel);
  }
  tr.match-header { border-radius: 0; margin: 0; padding: 0; }
  tr.match-header td { padding: 12px 12px 8px; }
  tbody td {
    display: flex; justify-content: space-between; align-items: center; gap: 12px;
    border-top: none; border-bottom: 1px solid var(--line); padding: 9px 12px;
    text-align: right;
  }
  tbody tr:not(.match-header) td:last-child { border-bottom: none; }
  tbody td::before {
    content: attr(data-label); font-weight: 700; color: var(--muted);
    text-align: left; font-size: 0.7rem; text-transform: uppercase;
    letter-spacing: 0.02em; flex-shrink: 0;
  }
  td.ci { text-align: right; }
  td.ci .note { text-align: right; }
  tr.combo-row td {
    display: block; text-align: left; padding: 10px 12px;
  }
  tr.combo-row td::before { content: none; }
  .slip-fab { bottom: 16px; right: 16px; }
}
"""

JS = """
(function(){
  var STORAGE_KEY = 'fbedge_slip_v1';
  var slip = [];
  try { slip = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'); } catch (e) { slip = []; }

  function save(){
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(slip)); } catch (e) {}
  }
  function fmt(v){ return Number(v).toFixed(2); }
  function totalOdds(){ return slip.reduce(function(acc, it){ return acc * it.odds; }, 1); }

  function render(){
    var badge = document.getElementById('slip-badge');
    var list = document.getElementById('slip-list');
    var empty = document.getElementById('slip-empty');
    var totalEl = document.getElementById('slip-total-odds');

    badge.textContent = slip.length;
    badge.hidden = slip.length === 0;

    list.innerHTML = '';
    empty.hidden = slip.length !== 0;

    slip.forEach(function(item, idx){
      var li = document.createElement('li');
      li.className = 'slip-item';
      var main = document.createElement('div');
      main.className = 'slip-item-main';
      var m = document.createElement('div');
      m.className = 'slip-item-match';
      m.textContent = item.match;
      var s = document.createElement('div');
      s.className = 'slip-item-sel';
      s.textContent = item.market + ' \\u2014 ' + item.selection;
      main.appendChild(m);
      main.appendChild(s);
      var odds = document.createElement('div');
      odds.className = 'slip-item-odds';
      odds.textContent = fmt(item.odds);
      var rm = document.createElement('button');
      rm.className = 'slip-remove';
      rm.type = 'button';
      rm.setAttribute('aria-label', 'Rimuovi');
      rm.dataset.idx = idx;
      rm.textContent = '\\u00d7';
      li.appendChild(main);
      li.appendChild(odds);
      li.appendChild(rm);
      list.appendChild(li);
    });

    totalEl.textContent = slip.length ? fmt(totalOdds()) : '\\u2013';
    updatePayout();

    document.querySelectorAll('.slip-add').forEach(function(btn){
      var active = slip.some(function(it){ return it.key === btn.dataset.key; });
      btn.classList.toggle('active', active);
      btn.textContent = active ? '\\u2713 In schedina' : '+ Schedina';
    });

    save();
  }

  function updatePayout(){
    var stakeInput = document.getElementById('slip-stake');
    var payoutEl = document.getElementById('slip-payout');
    var stake = parseFloat(stakeInput.value) || 0;
    payoutEl.textContent = (stake * totalOdds()).toFixed(2) + ' \\u20ac';
  }

  function toggleItem(btn){
    var key = btn.dataset.key;
    var idx = -1;
    for (var i = 0; i < slip.length; i++) { if (slip[i].key === key) { idx = i; break; } }
    if (idx >= 0) {
      slip.splice(idx, 1);
    } else {
      slip.push({
        key: key, match: btn.dataset.match, market: btn.dataset.market,
        selection: btn.dataset.selection, odds: parseFloat(btn.dataset.odds)
      });
    }
    render();
  }

  function fallbackCopy(text, cb){
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); if (cb) cb(); } catch (e) {}
    document.body.removeChild(ta);
  }

  function copySlip(){
    if (!slip.length) return;
    var lines = slip.map(function(it){
      return it.match + ' \\u2014 ' + it.market + ' (' + it.selection + ') @ ' + fmt(it.odds);
    });
    var stake = parseFloat(document.getElementById('slip-stake').value) || 0;
    lines.push('');
    lines.push('Quota totale: ' + fmt(totalOdds()));
    if (stake > 0) {
      lines.push('Puntata: ' + stake.toFixed(2) + ' \\u20ac \\u2192 Vincita potenziale: ' +
        (stake * totalOdds()).toFixed(2) + ' \\u20ac');
    }
    var text = lines.join('\\n');
    var btn = document.getElementById('slip-copy');
    var old = btn.textContent;
    var done = function(){ btn.textContent = 'Copiato \\u2713'; setTimeout(function(){ btn.textContent = old; }, 1500); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function(){ fallbackCopy(text, done); });
    } else {
      fallbackCopy(text, done);
    }
  }

  document.addEventListener('click', function(e){
    var addBtn = e.target.closest('.slip-add');
    if (addBtn) { toggleItem(addBtn); return; }

    var rmBtn = e.target.closest('.slip-remove');
    if (rmBtn) { slip.splice(parseInt(rmBtn.dataset.idx, 10), 1); render(); return; }

    if (e.target.closest('#slip-clear')) { slip = []; render(); return; }
    if (e.target.closest('#slip-copy')) { copySlip(); return; }
    if (e.target.closest('#slip-toggle')) { document.getElementById('slip-panel').classList.toggle('open'); return; }
    if (e.target.closest('#slip-close')) { document.getElementById('slip-panel').classList.remove('open'); return; }
  });

  document.addEventListener('input', function(e){
    if (e.target.id === 'slip-stake') updatePayout();
  });

  render();

  // --- accordion: match compressi di default, un click li espande ---
  function setGroupOpen(header, open){
    var gid = header.dataset.group;
    header.setAttribute('aria-expanded', open ? 'true' : 'false');
    document.querySelectorAll('tr.market-row[data-group="' + CSS.escape(gid) + '"]').forEach(function(row){
      row.hidden = !open;
    });
  }
  function toggleGroup(header){
    setGroupOpen(header, header.getAttribute('aria-expanded') !== 'true');
  }

  document.addEventListener('click', function(e){
    if (e.target.closest('.slip-add') || e.target.closest('.slip-remove')) return;

    var header = e.target.closest('tr.match-header');
    if (header) { toggleGroup(header); return; }

    var expandBtn = e.target.closest('[data-expand-all]');
    if (expandBtn) {
      var tid = expandBtn.dataset.expandAll;
      document.querySelectorAll('table[data-table-id="' + CSS.escape(tid) + '"] tr.match-header')
        .forEach(function(h){ setGroupOpen(h, true); });
      return;
    }
    var collapseBtn = e.target.closest('[data-collapse-all]');
    if (collapseBtn) {
      var tid2 = collapseBtn.dataset.collapseAll;
      document.querySelectorAll('table[data-table-id="' + CSS.escape(tid2) + '"] tr.match-header')
        .forEach(function(h){ setGroupOpen(h, false); });
      return;
    }
  });

  document.addEventListener('keydown', function(e){
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var header = e.target.closest('tr.match-header');
    if (!header) return;
    e.preventDefault();
    toggleGroup(header);
  });
})();
"""

SLIP_PANEL = """
<button id="slip-toggle" class="slip-fab" type="button" aria-label="Apri la schedina">
  \U0001f3ab<span id="slip-badge" class="slip-badge" hidden>0</span>
</button>
<div id="slip-panel" class="slip-panel">
  <div class="slip-panel-header">
    <h3>La tua schedina</h3>
    <button id="slip-close" class="slip-close" type="button" aria-label="Chiudi">&times;</button>
  </div>
  <div class="slip-panel-body">
    <p id="slip-empty" class="slip-empty">Nessuna selezione. Tocca "+ Schedina" su una riga con quota per aggiungerla.</p>
    <ul id="slip-list" class="slip-list"></ul>
  </div>
  <div class="slip-panel-footer">
    <div class="slip-totals">
      <div class="slip-row">Quota totale <strong id="slip-total-odds">–</strong></div>
      <div class="slip-row"><label for="slip-stake">Puntata (€)</label>
        <input type="number" id="slip-stake" min="0" step="1" value="10" inputmode="decimal"></div>
      <div class="slip-row">Vincita potenziale <strong id="slip-payout">0.00 €</strong></div>
    </div>
    <div class="slip-actions">
      <button id="slip-copy" class="btn-primary" type="button">\U0001f4cb Copia schedina</button>
      <button id="slip-clear" class="btn-secondary" type="button">Svuota</button>
    </div>
    <p class="slip-hint">Composizione locale, nessun dato lascia questa pagina. Copia il
    testo e incollalo sul tuo bookmaker: questa non è una scommessa piazzata né un
    consiglio.</p>
  </div>
</div>
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
    card_checks: Optional[Dict[str, MatchCardCheck]] = None,
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
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
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
  {get_news_alerts(list(rows))}
  {_season_start_warning(list(rows))}
  {_card_checks_html(card_checks or {})}
  {_calibration_html(calibration)}
  {_table_html(rows, "Mercati con quota, per edge decrescente", allow_slip=True, settings=settings)}
  {_table_html(unpriced, "Mercati senza quota abbinata (solo probabilità di modello)")}

  <footer>
    <h2>Limiti del modello — leggere prima di usare questi numeri</h2>
    <ol>{limits_html}</ol>
  </footer>
</div>

{SLIP_PANEL}
<script>{JS}</script>
</body>
</html>
"""
