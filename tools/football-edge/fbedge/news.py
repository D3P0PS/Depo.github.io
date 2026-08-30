"""Raccolta notizie da fonti pubbliche per avvertimenti di ultima ora."""

from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional, Set
from urllib.request import urlopen
from urllib.error import URLError

from .analysis import EdgeRow


def extract_team_names(rows: List[EdgeRow]) -> Set[str]:
    """Estrae nomi di squadre uniche dal report."""
    teams: Set[str] = set()
    for row in rows:
        # Estrae da "Home Team vs Away Team"
        if " vs " in row.match_label:
            parts = row.match_label.split(" vs ")
            if len(parts) == 2:
                teams.add(parts[0].strip())
                teams.add(parts[1].strip())
    return teams


def fetch_bbc_football_feed() -> List[Dict[str, str]]:
    """Fetcha i titoli da BBC Sport (calcio).

    Ritorna una lista di {"title": str, "url": str}.
    Fallback a lista vuota se unavailable.
    """
    try:
        # Usa un RSS feed pubblico di BBC Sport
        url = "https://feeds.bbc.co.uk/sport/football/rss.xml"
        with urlopen(url, timeout=3) as response:
            content = response.read().decode("utf-8")

        # Parsing XML minimalista (no dipendenze esterne)
        news = []
        for item in re.finditer(r"<item>(.*?)</item>", content, re.DOTALL):
            item_text = item.group(1)
            title_match = re.search(r"<title>(.*?)</title>", item_text)
            link_match = re.search(r"<link>(.*?)</link>", item_text)
            if title_match and link_match:
                news.append({
                    "title": title_match.group(1),
                    "url": link_match.group(1),
                })
        return news[:10]  # Limita ai 10 titoli più recenti
    except (URLError, Exception):
        return []


def filter_news_for_teams(news: List[Dict[str, str]], teams: Set[str]) -> List[str]:
    """Filtra le notizie per squadre rilevanti al report."""
    relevant = []
    teams_lower = {t.lower() for t in teams}

    for item in news:
        title = item.get("title", "").lower()
        # Controlla se il titolo contiene una squadra del report
        if any(team in title for team in teams_lower):
            relevant.append(item["title"])

    return relevant


def get_news_alerts(rows: List[EdgeRow]) -> str:
    """Ritorna un avvertimento HTML con notizie recenti pertinenti.

    Se nessuna notizia è disponibile, ritorna un disclaimer generico.
    """
    teams = extract_team_names(rows)
    if not teams:
        return ""

    news = fetch_bbc_football_feed()
    relevant = filter_news_for_teams(news, teams)

    if relevant:
        alerts_html = "<ul>"
        for article in relevant[:5]:  # Mostra max 5 notizie
            alerts_html += f"<li>{article}</li>"
        alerts_html += "</ul>"
        return f"""
    <div class="banner banner-warn">
      <h2>📰 Notizie recenti</h2>
      <p>Notizie rilevanti dalle fonti pubbliche:</p>
      {alerts_html}
      <p class="hint">Verifica le formazioni ufficiali su <a href="https://www.espn.com/soccer/">ESPN</a>,
      <a href="https://www.bbc.com/sport/football">BBC Sport</a>, o
      <a href="https://www.transfermarkt.com/">Transfermarkt</a> prima di scommettere.</p>
    </div>"""

    # Fallback: disclaimer generico se nessuna notizia disponibile
    return f"""
    <div class="disclaimer">
      <strong>⚠️ Controllare le ultime notizie prima di scommettere</strong>
      <p>Il modello NON conosce formazioni ufficiali, infortuni dell'ultimo minuto,
      o cambi tattici annunciati dopo l'ultima analisi.
      Verifica sempre:</p>
      <ul>
        <li><a href="https://www.espn.com/soccer/">ESPN</a> — formazioni e notizie</li>
        <li><a href="https://www.bbc.com/sport/football">BBC Sport</a> — ultimi aggiornamenti</li>
        <li><a href="https://www.transfermarkt.com/">Transfermarkt</a> — infortuni e assenze</li>
      </ul>
    </div>"""
