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
def leagues(count):
    return {"data": [{"id": "serie_a", "display_name": "Serie A",
                      "sport": "soccer", "event_count": count}]}


META = {"tier": {"name": "free", "books": ["draftkings", "fanduel"]},
        "books": {"in_scope": ["draftkings", "fanduel"]}}
EMPTY = {"data": [], "pagination": {"count": 0}, "meta": META}


def payload(*events):
    return {"data": list(events), "pagination": {"count": len(events)}, "meta": META}


class DiagnoseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cache = tempfile.mkdtemp(prefix="fbedge-diag-")
        self.client = HttpClient(cache_dir=self.cache)
        self._seed_catalogue(all_books=380, plan_books=380)

    def _seed_catalogue(self, all_books, plan_books) -> None:
        """event_count con tutti i book e con i soli book del piano.

        plan_books=None significa campionato del tutto assente dall'elenco
        filtrato, che e' come il provider segnala "nessuna quota da quei book".
        """
        self._seed(LEAGUES_PATH, {"sport": "soccer"}, leagues(all_books))
        self._seed(LEAGUES_PATH,
                   {"sport": "soccer", "sportsbook": "draftkings,fanduel"},
                   leagues(plan_books) if plan_books is not None
                   else {"data": []})

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
        self.assertIn("ma nessuno di 'serie_a'", out)
        self.assertIn("nfl", out)
        self.assertIn("theoddsapi", out)          # indica la via d'uscita

    def test_events_of_another_sport_are_not_counted_as_success(self) -> None:
        """Caso reale: 50 eventi di golf in risposta a league=serie_a.

        Il filtro campionato non viene applicato, e contare gli eventi senza
        guardare a che campionato appartengono produceva il verdetto sbagliato
        ("colpa dei nomi dei mercati") su un caso che era invece copertura
        mancante dei bookmaker.
        """
        golf = [dict(EVENT, id=f"g{n}", league="pga") for n in range(50)]
        self._seed_catalogue(all_books=20, plan_books=None)   # assente col filtro
        out = self._run(EMPTY, payload(*golf), payload(*golf))
        self.assertIn("pga", out)
        self.assertIn("Il filtro campionato non e' stato applicato", out)
        self.assertNotIn("spariscono col filtro mercati", out)   # il vecchio errore
        self.assertIn("Confermato", out)
        self.assertIn("draftkings", out)

    def test_plan_books_do_not_cover_the_league(self) -> None:
        # 380 eventi quotati in generale, 0 con draftkings+fanduel
        self._seed_catalogue(all_books=380, plan_books=0)
        out = self._run(EMPTY, EMPTY, EMPTY)
        self.assertIn("Confermato", out)
        self.assertIn("draftkings", out)
        self.assertIn("theoddsapi", out)

    def test_league_out_of_season_is_distinguished(self) -> None:
        # nessuna quota nemmeno su tutti i book: non e' colpa del piano
        self._seed_catalogue(all_books=0, plan_books=0)
        out = self._run(EMPTY, EMPTY, EMPTY)
        self.assertIn("fuori stagione", out)
        self.assertNotIn("Confermato", out)

    def test_odds_present_means_no_problem(self) -> None:
        out = self._run(payload(EVENT), payload(EVENT), payload(EVENT))
        self.assertIn("Le quote arrivano", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
