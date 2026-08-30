#!/usr/bin/env python3
"""Invia notifiche Telegram con i top edge opportunities."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError


def extract_top_edges_from_html(html_path: Path, limit: int = 10) -> List[dict]:
    """Estrae i top edge dal report HTML."""
    try:
        content = html_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Errore lettura {html_path}: {e}")
        return []

    edges = []

    # Regex per estrarre le righe con edge dal HTML
    # Cerchiamo: match_header (match name) -> righe di mercati con edge
    current_match = None
    for line in content.split("\n"):
        # Riga di header del match
        if 'class="match-header"' in line:
            match = re.search(r'<td[^>]*>([^<]+?)\s+<span class="comp-badge">([^<]+)</span>', line)
            if match:
                current_match = f"{match.group(1)} ({match.group(2)})"

        # Riga di mercato con edge
        if current_match and '<td class="num edge-cell">' in line:
            match = re.search(r'<td class="num edge-cell">([^<]+)</td>', line)
            if match:
                edge_str = match.group(1)
                try:
                    edge_pct = float(edge_str.replace("+", "").replace("%", ""))
                    # Estrai mercato e selezione dalla riga (approssimativo)
                    market_match = re.search(r'<td>([^<]+)</td>\s+<td>([^<]+)</td>', line)
                    if market_match:
                        market = market_match.group(1).strip()
                        selection = market_match.group(2).strip()
                        edges.append({
                            "match": current_match,
                            "market": market,
                            "selection": selection,
                            "edge": edge_pct,
                        })
                except (ValueError, AttributeError):
                    pass

    # Ordina per edge decrescente e limita
    edges.sort(key=lambda x: x["edge"], reverse=True)
    return edges[:limit]


def format_telegram_message(html_path: Path, limit: int = 10) -> str:
    """Formatta i top edge per Telegram."""
    edges = extract_top_edges_from_html(html_path, limit)

    if not edges:
        return "📊 Analisi edge di oggi — Nessun edge positivo trovato."

    # Header
    date_str = html_path.name.replace("report_", "").replace(".html", "")
    msg = f"📊 *Edge Analysis — {date_str}*\n\n"

    # Top opportunities
    msg += "🎯 *Top Opportunities*\n"
    for i, edge in enumerate(edges[:5], 1):
        msg += f"\n{i}. {edge['match']}\n"
        msg += f"   Market: {edge['market']} ({edge['selection']})\n"
        msg += f"   Edge: *+{edge['edge']:.1f}%*"

    # Footer con link
    msg += f"\n\n📄 Report completo: [Apri](file://{html_path.absolute()})"
    msg += "\n\n_Ricorda: queste sono stime statistiche, non pronostici._"

    return msg


def send_telegram(bot_token: str, chat_id: str, message: str) -> bool:
    """Invia messaggio su Telegram."""
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = json.dumps({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }).encode("utf-8")

        req = Request(url, data=data, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode())
            if result.get("ok"):
                print(f"✓ Notifica Telegram inviata (chat_id: {chat_id})")
                return True
            else:
                print(f"✗ Errore Telegram: {result.get('description')}")
                return False
    except URLError as e:
        print(f"✗ Errore rete Telegram: {e}")
        return False
    except Exception as e:
        print(f"✗ Errore durante invio Telegram: {e}")
        return False


def main():
    import argparse
    p = argparse.ArgumentParser(description="Invia notifiche Telegram con top edge")
    p.add_argument("--report", required=True, help="Path al report HTML")
    p.add_argument("--bot-token", help="Telegram bot token (o env TELEGRAM_BOT_TOKEN)")
    p.add_argument("--chat-id", help="Telegram chat ID (o env TELEGRAM_CHAT_ID)")
    p.add_argument("--limit", type=int, default=10, help="Top edge da mostrare")
    p.add_argument("--test", action="store_true", help="Mostra messaggio senza inviarlo")
    args = p.parse_args()

    # Carica credenziali
    import os
    bot_token = args.bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = args.chat_id or os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("⚠ Credenziali Telegram non configurate. Configura:")
        print("  export TELEGRAM_BOT_TOKEN='...'")
        print("  export TELEGRAM_CHAT_ID='...'")
        print("\n  O passa: --bot-token ... --chat-id ...")
        sys.exit(1)

    # Formatta messaggio
    report_path = Path(args.report)
    if not report_path.exists():
        print(f"✗ Report non trovato: {report_path}")
        sys.exit(1)

    message = format_telegram_message(report_path, args.limit)
    print(message)

    if args.test:
        print("\n[TEST MODE - messaggio non inviato]")
        return

    # Invia
    if send_telegram(bot_token, chat_id, message):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
