#!/usr/bin/env python3
"""Dashboard web che mostra gli ultimi report di edge analysis."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import List, Dict, Any


def find_reports(report_dir: str) -> List[tuple[dt.date, Path]]:
    """Trova tutti i report HTML nella directory, ordinati per data (più recenti first)."""
    reports: List[tuple[dt.date, Path]] = []
    for file in Path(report_dir).glob("report_*.html"):
        # Formato: report_YYYY-MM-DD.html
        match = re.match(r"report_(\d{4})-(\d{2})-(\d{2})\.html", file.name)
        if match:
            year, month, day = map(int, match.groups())
            date = dt.date(year, month, day)
            reports.append((date, file))
    return sorted(reports, reverse=True)


def extract_summary_from_html(html_path: Path) -> Dict[str, Any]:
    """Estrae summary dal report HTML (numero righe, top edge, ecc.)."""
    try:
        content = html_path.read_text(encoding="utf-8")

        # Estrai numero righe con quota
        match = re.search(r"(\d+)\s+righe con quota", content)
        rows_with_quotes = int(match.group(1)) if match else 0

        # Estrai numero righe solo modello
        match = re.search(r"(\d+)\s+solo probabilità di modello", content)
        rows_model_only = int(match.group(1)) if match else 0

        # Estrai numero partite senza quote
        match = re.search(r"(\d+)\s+partite senza quote", content)
        unmatched = int(match.group(1)) if match else 0

        # Estrai top edge (prima riga con edge positivo)
        match = re.search(r"<td class=\"num edge-cell\">\+(\d+\.?\d*)%</td>", content)
        top_edge = float(match.group(1)) if match else 0

        # Controlla se calibrazione è sospetta
        suspect = "banner-bad" in content and "Questa corsa non è utilizzabile" in content

        return {
            "rows_with_quotes": rows_with_quotes,
            "rows_model_only": rows_model_only,
            "unmatched": unmatched,
            "top_edge": top_edge,
            "suspect": suspect,
        }
    except Exception as e:
        print(f"Errore durante estrazione summary da {html_path}: {e}")
        return {}


def generate_dashboard_html(report_dir: str, output_path: str) -> None:
    """Genera una pagina HTML che mostra i report disponibili."""
    reports = find_reports(report_dir)

    # Prepara righe della tabella
    rows_html = ""
    for date, report_path in reports[:30]:  # Ultimi 30 giorni
        summary = extract_summary_from_html(report_path)
        date_str = date.strftime("%Y-%m-%d")
        relative_path = report_path.name

        suspect_badge = (
            '<span class="badge-suspect">⚠ Sospetta</span>'
            if summary.get("suspect") else
            '<span class="badge-ok">✓ OK</span>'
        )

        rows_html += f"""
      <tr>
        <td>{date_str}</td>
        <td class="num">{summary.get('rows_with_quotes', 0)}</td>
        <td class="num">{summary.get('rows_model_only', 0)}</td>
        <td class="num">{summary.get('top_edge', 0):.1f}%</td>
        <td>{suspect_badge}</td>
        <td><a href="{relative_path}" class="btn-open">Apri</a></td>
      </tr>"""

    # HTML template
    html = f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Edge Analysis Dashboard</title>
<style>
:root {{
  --bg: #f6f5f2; --panel: #ffffff; --ink: #1b1b1d; --muted: #6b6b70;
  --line: #e4e2dc; --accent: #2f6f4f; --ok: #1f7a4d; --bad: #8a2b2b;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 20px; background: var(--bg); color: var(--ink);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}}
.container {{ max-width: 900px; margin: 0 auto; }}
header {{ margin-bottom: 30px; }}
header h1 {{ margin: 0 0 8px; font-size: 1.8rem; }}
header p {{ color: var(--muted); margin: 0; }}
.summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin: 20px 0; }}
.card {{
  background: var(--panel); padding: 16px; border-radius: 8px;
  border: 1px solid var(--line);
}}
.card-title {{ color: var(--muted); font-size: 0.85rem; text-transform: uppercase; margin-bottom: 8px; }}
.card-value {{ font-size: 1.8rem; font-weight: 600; }}
.table-wrap {{ overflow-x: auto; border-radius: 8px; border: 1px solid var(--line); background: var(--panel); margin-top: 20px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
thead th {{
  text-align: left; padding: 12px; background: #efede8; color: var(--muted);
  font-weight: 600; font-size: 0.8rem; text-transform: uppercase;
}}
tbody td {{ padding: 12px; border-top: 1px solid var(--line); }}
tbody tr:hover {{ background: #faf9f6; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.badge-ok {{ display: inline-block; padding: 3px 8px; background: #eef6f0; color: var(--ok); border-radius: 4px; font-size: 0.8rem; font-weight: 600; }}
.badge-suspect {{ display: inline-block; padding: 3px 8px; background: #fdeeee; color: var(--bad); border-radius: 4px; font-size: 0.8rem; font-weight: 600; }}
.btn-open {{ display: inline-block; padding: 6px 12px; background: var(--accent); color: white; text-decoration: none; border-radius: 4px; font-size: 0.85rem; font-weight: 600; }}
.btn-open:hover {{ opacity: 0.9; }}
footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--line); color: var(--muted); font-size: 0.85rem; }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>📊 Edge Analysis Dashboard</h1>
    <p>Ultimi report di analisi edge calcio — aggiornato ogni giorno</p>
    <p>Ultima analisi: <strong>{reports[0][0].strftime('%Y-%m-%d') if reports else 'Nessun report disponibile'}</strong></p>
  </header>

  <div class="summary">
    <div class="card">
      <div class="card-title">Report disponibili</div>
      <div class="card-value">{len(reports)}</div>
    </div>
    <div class="card">
      <div class="card-title">Ultimi 7 giorni</div>
      <div class="card-value">{len([r for r in reports[:7]])}</div>
    </div>
    <div class="card">
      <div class="card-title">Ultima analisi</div>
      <div class="card-value">{reports[0][0].strftime('%a %d') if reports else 'N/A'}</div>
    </div>
  </div>

  <div class="table-wrap">
  <table>
    <thead><tr>
      <th>Data</th>
      <th>Righe con quota</th>
      <th>Solo modello</th>
      <th>Top edge</th>
      <th>Stato</th>
      <th></th>
    </tr></thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
  </div>

  <footer>
    <p>Dashboard auto-aggiornato ogni giorno.
    <a href="javascript:location.reload()" style="color: var(--accent); text-decoration: none;">Ricarica</a></p>
  </footer>
</div>
</body>
</html>"""

    Path(output_path).write_text(html, encoding="utf-8")
    print(f"✓ Dashboard generata: {output_path}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Genera dashboard HTML per i report")
    p.add_argument("--report-dir", default=".", help="Directory con i report (default: .)")
    p.add_argument("--output", default="index.html", help="File HTML di output (default: index.html)")
    args = p.parse_args()

    generate_dashboard_html(args.report_dir, args.output)
