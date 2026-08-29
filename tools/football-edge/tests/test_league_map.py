"""Test della compatibilita' fra --league-map e il provider attivo.

Il bug che ha motivato questo file: una mappa scritta per SharpAPI (id come
"germany_-_bundesliga") veniva applicata senza controlli a una corsa con The
Odds API, che si aspetta sport key come "soccer_germany_bundesliga". Il
campionato interrogato con il codice sbagliato risultava "non offerto in
questo momento", un messaggio plausibile che nascondeva un errore di mappatura
invece di segnalarlo.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fbedge.cli import load_league_map  # noqa: E402


class LeagueMapProviderTaggingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="fbedge-leaguemap-")

    def _write(self, name: str, payload) -> str:
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    def test_matching_provider_is_applied(self) -> None:
        path = self._write("m.json", {
            "provider": "sharpapi",
            "leagues": {"BL1": "germany_-_bundesliga"},
        })
        result = load_league_map(path, "sharpapi")
        self.assertEqual(result, {"BL1": "germany_-_bundesliga"})

    def test_mismatched_provider_is_rejected_not_silently_applied(self) -> None:
        """Il caso reale: mappa SharpAPI usata con The Odds API."""
        path = self._write("m.json", {
            "provider": "sharpapi",
            "leagues": {"BL1": "germany_-_bundesliga", "FL1": "france_-_ligue_1"},
        })
        buf = io.StringIO()
        with redirect_stderr(buf):
            result = load_league_map(path, "theoddsapi")
        self.assertEqual(result, {})                # nessun codice sbagliato applicato
        err = buf.getvalue()
        self.assertIn("sharpapi", err)
        self.assertIn("theoddsapi", err)
        self.assertIn("ignorata", err)

    def test_untagged_flat_file_is_accepted_as_before(self) -> None:
        """File scritto a mano, senza tag: retrocompatibilita'."""
        path = self._write("m.json", {"SA": "italy_-_serie_a"})
        for provider in ("sharpapi", "theoddsapi"):    # nessun tag = nessun controllo
            self.assertEqual(load_league_map(path, provider), {"SA": "italy_-_serie_a"})

    def test_no_path_returns_empty(self) -> None:
        self.assertEqual(load_league_map(None, "sharpapi"), {})


class ListLeaguesWritesTaggedMapTest(unittest.TestCase):
    """--leagues-out deve scrivere il formato taggato, non piu' il dizionario piatto."""

    def test_output_file_is_tagged_with_the_provider(self) -> None:
        import fbedge.cli as cli

        tmp = tempfile.mkdtemp(prefix="fbedge-leaguesout-")
        out_path = os.path.join(tmp, "leghe.json")

        class FakeClient:
            base = "https://api.sharpapi.io"

            def list_leagues(self, ttl, sport):
                return [{"id": "italy_-_serie_a", "name": "Italy - Serie A",
                         "sport": "soccer", "events": 133}]

        args = cli.parse_args([
            "--odds-provider", "sharpapi", "--list-leagues",
            "--leagues-out", out_path,
        ])
        orig_build = cli.build_odds_client
        cli.build_odds_client = lambda *a, **k: FakeClient()
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli.cmd_list_leagues(args, "sharpapi", "K", None, ["SA"], 0)
        finally:
            cli.build_odds_client = orig_build

        with open(out_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["provider"], "sharpapi")
        self.assertIn("SA", data["leagues"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
