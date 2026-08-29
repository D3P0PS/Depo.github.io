#!/usr/bin/env python3
"""Punto di ingresso: analisi edge sui mercati calcio.

Esempi:
    python3 edge_scan.py --self-test
    python3 edge_scan.py --competitions SA,PL --date today
    python3 edge_scan.py --date 2026-09-01 --days 2 --min-edge 3 --csv edge.csv

Richiede due chiavi gratuite (vedi --help):
    export FOOTBALL_DATA_API_KEY="..."
    export ODDS_API_KEY="..."
"""

import sys

from fbedge.cli import main

if __name__ == "__main__":
    sys.exit(main())
