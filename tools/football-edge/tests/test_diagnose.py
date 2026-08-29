"""Test della diagnosi per la risposta quote vuota.

Una 200 con zero eventi ha cause diverse che si distinguono solo variando un
filtro alla volta. Questi test fissano il verdetto per ciascuna.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fbedge import cli  # noqa: E402
from fbedge.httpcache import HttpClient, Response, build_url  # noqa: E402
from fbedge.sharpapi import DEFAULT_BASE, DEFAULT_ODDS_PATH, LEAGUES_PATH  # noqa: E402

EVENT = {
    "id": "e1", "commence_time": "2026-08-29T18:45:00Z",
    "home_team": "Inter", "away_team": "Napoli", "league": "serie_a",
    "bookmakers": [{"key": "draftkings", "title": "DraftKings", "markets": [
        {"key": "h2h", "outcomes": [
            {"name": "Inter", "price": 2.0}, {"name": "Draw", "price": 3.4},
            {"name": "Napoli", "price": 3.8}]}]}],
}
LEAGUES = {"data": [{"id": "serie_a", "display_name": "Serie A",
                     "sport": "soccer", "event_count": 380}]}
EMPTY = {"data": [], "pagination": {"count": 0}}


def payload(*events):
    return {"data": list(events), "pagination": {"count": len(events)}}


class DiagnoseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cache = tempfile.mkdtemp(prefix="fbedge-diag-")
        self.client = HttpClient(cache_dir=self.cache)
        self._seed(LEAGUES_PATH, None, LEAGUES)

    def tearDown(self) -> None:
        shutil.rmtree(self.cache, ignore_errors=True)

    def _seed(self, path, params, body) -> None:
        self.client._write_cache(
            build_url(f"{DEFAULT_BASE}{path}", params or {}),
            Response(200, {}, json.dumps(body), from_cache=False),
        )

    def _run(self, with_markets, without_markets, no_filter) -> str:
        self._seed(DEFAULT_ODDS_PATH,
                   {"league": "serie_a", "markets": "h2h,totals"}, with_markets)
        self._seed(DEFAULT_ODDS_PATH, {"league": "serie_a"}, without_markets)
        self._seed(DEFAULT_ODDS_PATH, {}, no_filter)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main([
                "--odds-provider", "sharpapi", "--sharpapi-key", "T",
                "--diagnose-odds", "--league", "serie_a", "--offline",
                "--cache-dir", self.cache, "--football-data-key", "X",
            ])
        self.assertEqual(code, 0)
        return buf.getvalue()

    def test_market_filter_is_the_culprit(self) -> None:
        out = self._run(EMPTY, payload(EVENT), payload(EVENT))
        self.assertIn("spariscono col filtro mercati", out)
        self.assertIn("MARKET_SYNONYMS", out)

    def test_plan_serves_only_other_sports(self) -> None:
        out = self._run(EMPTY, EMPTY,
                        payload(dict(EVENT, league="nfl"), dict(EVENT, league="nba")))
        self.assertIn("nessuno di questo campionato", out)
        self.assertIn("nfl", out)
        self.assertIn("theoddsapi", out)          # indica la via d'uscita

    def test_catalogue_lists_it_but_no_odds_anywhere(self) -> None:
        out = self._run(EMPTY, EMPTY, EMPTY)
        self.assertIn("380 eventi dichiarati", out)
        self.assertIn("serve le quote solo per", out)

    def test_odds_present_means_no_problem(self) -> None:
        out = self._run(payload(EVENT), payload(EVENT), payload(EVENT))
        self.assertIn("Le quote arrivano", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
