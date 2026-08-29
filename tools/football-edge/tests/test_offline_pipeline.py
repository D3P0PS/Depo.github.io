"""Test di integrazione senza rete.

Pre-carica la cache HTTP con payload nella forma reale di football-data.org
(v4) e The Odds API (v4), poi esegue la CLI in modalita' --offline. Copre le
parti che il --self-test non tocca: parsing delle risposte, abbinamento fra
le due fonti, filtro sull'edge, export CSV/JSON.

Esecuzione:  python3 -m tests.test_offline_pipeline   (dalla cartella dello script)
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import random
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fbedge import cli  # noqa: E402
from fbedge.football_data import BASE as FD_BASE  # noqa: E402
from fbedge.httpcache import HttpClient, Response, build_url  # noqa: E402
from fbedge.odds_api import BASE as ODDS_BASE  # noqa: E402

TEAMS = [
    (100, "Internazionale"), (101, "Milan"), (102, "Juventus"), (103, "Napoli"),
    (104, "Roma"), (105, "Lazio"), (106, "Atalanta"), (107, "Fiorentina"),
]
ODDS_NAMES = {100: "Inter Milan", 101: "AC Milan", 102: "Juventus", 103: "Napoli"}


def _finished_matches(season_start: int, count: int, rng: random.Random) -> list:
    """Risultati finti nella forma esatta restituita da football-data.org."""
    matches = []
    day = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    for i in range(count):
        home = TEAMS[i % len(TEAMS)]
        away = TEAMS[(i + 1 + i // len(TEAMS)) % len(TEAMS)]
        if home[0] == away[0]:
            away = TEAMS[(i + 3) % len(TEAMS)]
        matches.append({
            "id": 900000 + i,
            "utcDate": (day - dt.timedelta(days=3 * i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "FINISHED",
            "matchday": 1 + i // 4,
            "homeTeam": {"id": home[0], "name": f"{home[1]} FC", "shortName": home[1]},
            "awayTeam": {"id": away[0], "name": f"{away[1]} FC", "shortName": away[1]},
            "score": {"fullTime": {"home": rng.randint(0, 4), "away": rng.randint(0, 3)}},
        })
    return matches


def _scheduled(kickoff: dt.datetime) -> list:
    return [
        {
            "id": 800001,
            "utcDate": kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "TIMED",
            "matchday": 5,
            "homeTeam": {"id": 100, "name": "FC Internazionale Milano",
                         "shortName": "Internazionale"},
            "awayTeam": {"id": 103, "name": "SSC Napoli", "shortName": "Napoli"},
        },
        {
            "id": 800002,
            "utcDate": (kickoff + dt.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "TIMED",
            "matchday": 5,
            "homeTeam": {"id": 102, "name": "Juventus FC", "shortName": "Juventus"},
            "awayTeam": {"id": 101, "name": "AC Milan", "shortName": "Milan"},
        },
    ]


def _odds_payload(kickoff: dt.datetime) -> list:
    def event(eid, start, home, away, prices, totals):
        return {
            "id": eid,
            "sport_key": "soccer_italy_serie_a",
            "commence_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "home_team": home,
            "away_team": away,
            "bookmakers": [
                {
                    "key": book, "title": title,
                    "last_update": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "markets": [
                        {"key": "h2h", "outcomes": [
                            {"name": home, "price": p[0]},
                            {"name": "Draw", "price": p[1]},
                            {"name": away, "price": p[2]}]},
                        {"key": "totals", "outcomes": [
                            {"name": "Over", "price": t[0], "point": 2.5},
                            {"name": "Under", "price": t[1], "point": 2.5}]},
                    ],
                }
                for (book, title), p, t in zip(
                    [("bet365", "Bet365"), ("pinnacle", "Pinnacle")], prices, totals
                )
            ],
        }

    return [
        event("evt1", kickoff, "Inter Milan", "Napoli",
              [[2.05, 3.50, 3.70], [2.12, 3.55, 3.60]],
              [[1.90, 1.92], [1.95, 1.95]]),
        event("evt2", kickoff + dt.timedelta(hours=2), "Juventus", "AC Milan",
              [[2.40, 3.20, 3.10], [2.45, 3.25, 3.05]],
              [[2.05, 1.80], [2.10, 1.83]]),
    ]


class OfflinePipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cache_dir = tempfile.mkdtemp(prefix="fbedge-test-")
        self.date = dt.date.today()
        kickoff = dt.datetime.combine(
            self.date, dt.time(18, 45), tzinfo=dt.timezone.utc
        )
        rng = random.Random(7)
        client = HttpClient(cache_dir=self.cache_dir)

        def seed(url: str, payload) -> None:
            client._write_cache(
                url, Response(200, {"x-requests-remaining": "431",
                                    "x-requests-used": "69"},
                              json.dumps(payload), from_cache=False)
            )

        seed(
            build_url(f"{FD_BASE}/competitions/SA/matches",
                      {"dateFrom": self.date.isoformat(),
                       "dateTo": self.date.isoformat(),
                       "status": "SCHEDULED,TIMED"}),
            {"matches": _scheduled(kickoff)},
        )
        season = kickoff.year if kickoff.month >= 7 else kickoff.year - 1
        seed(
            build_url(f"{FD_BASE}/competitions/SA/matches",
                      {"season": season, "status": "FINISHED"}),
            {"matches": _finished_matches(season, 60, rng)},
        )
        seed(
            build_url(f"{FD_BASE}/competitions/SA/matches",
                      {"season": season - 1, "status": "FINISHED"}),
            {"matches": _finished_matches(season - 1, 40, rng)},
        )
        seed(
            build_url(f"{ODDS_BASE}/sports/soccer_italy_serie_a/odds",
                      {"apiKey": "TEST", "regions": "eu", "markets": "h2h,totals",
                       "oddsFormat": "decimal", "dateFormat": "iso"}),
            _odds_payload(kickoff),
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.cache_dir, ignore_errors=True)

    def _run(self, *extra: str):
        csv_path = os.path.join(self.cache_dir, "out.csv")
        json_path = os.path.join(self.cache_dir, "out.json")
        argv = [
            "--competitions", "SA", "--date", self.date.isoformat(),
            "--offline", "--cache-dir", self.cache_dir,
            "--football-data-key", "TEST", "--odds-key", "TEST",
            "--mc-draws", "150", "--csv", csv_path, "--json", json_path, *extra,
        ]
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(argv)
        return code, buf.getvalue(), csv_path, json_path

    def test_pipeline_end_to_end(self) -> None:
        code, out, csv_path, json_path = self._run()
        self.assertEqual(code, 0, out)

        # entrambi i fixture sono stati abbinati alle quote nonostante i nomi diversi
        self.assertIn("Internazionale - Napoli", out)
        self.assertIn("Juventus - Milan", out)
        self.assertNotIn("nessun evento quote abbinato", out)

        # i mercati richiesti compaiono tutti
        for expected in ("1X2", "Over/Under 2.5", "BTTS"):
            self.assertIn(expected, out)

        # i limiti sono sempre dichiarati
        flat = " ".join(out.lower().split())
        self.assertIn("limiti del modello", flat)
        self.assertIn("formazioni ufficiali", flat)
        self.assertIn("non e' un profitto garantito", flat)

        # nessun linguaggio da esito certo
        for phrase in ("pick sicuro", "scommessa sicura", "vincita garantita"):
            self.assertNotIn(phrase, flat)

        # i crediti residui di The Odds API vengono riportati
        self.assertIn("431", out)

        with open(json_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertTrue(data["righe"])
        for row in data["righe"]:
            self.assertIsNotNone(row["prob_modello_pct"])
            self.assertLessEqual(row["prob_modello_ic_basso_pct"], row["prob_modello_pct"] + 1e-6)
            self.assertGreaterEqual(row["prob_modello_ic_alto_pct"], row["prob_modello_pct"] - 1e-6)
            if row["quota"]:
                atteso = (row["prob_modello_pct"] / 100 * row["quota"] - 1) * 100
                self.assertAlmostEqual(row["edge_pct"], atteso, places=1)

        with open(csv_path, encoding="utf-8") as fh:
            self.assertIn("edge_pct", fh.readline())

        # le probabilita' 1X2 di un incontro sommano a 1
        h2h = [r for r in data["righe"]
               if r["mercato"] == "1X2" and r["partita"] == "Internazionale - Napoli"]
        self.assertEqual(len(h2h), 3)
        self.assertAlmostEqual(sum(r["prob_modello_pct"] for r in h2h), 100.0, places=6)

    def test_min_edge_filter_keeps_rows_visible(self) -> None:
        _code, out, _csv, json_path = self._run("--min-edge", "500")
        # nessuna riga passa il filtro, ma il conteggio resta esplicito
        self.assertIn("non sono mostrate", out)
        # e i mercati senza quota non spariscono mai
        with open(json_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertTrue(any(r["quota"] is None for r in data["righe"]))

    def test_market_blend_moves_towards_market(self) -> None:
        _c1, _o1, _csv1, j1 = self._run("--market-blend", "0")
        with open(j1, encoding="utf-8") as fh:
            pure = {(r["partita"], r["selezione"]): r for r in json.load(fh)["righe"]}
        _c2, _o2, _csv2, j2 = self._run("--market-blend", "1")
        with open(j2, encoding="utf-8") as fh:
            blended = {(r["partita"], r["selezione"]): r for r in json.load(fh)["righe"]}
        checked = 0
        for key, row in blended.items():
            if row["prob_mercato_equa_pct"] is None:
                continue
            self.assertAlmostEqual(row["prob_modello_pct"], row["prob_mercato_equa_pct"], places=1)
            self.assertNotAlmostEqual(row["prob_modello_pct"],
                                      pure[key]["prob_modello_pct"], places=3)
            checked += 1
        self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
