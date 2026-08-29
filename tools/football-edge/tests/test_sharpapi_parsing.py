"""Test del parser SharpAPI su piu' forme plausibili della risposta.

La mappatura dei campi e' stata ricostruita senza accesso alla documentazione,
quindi il parser accetta piu' varianti. Questi test bloccano le varianti
supportate: se la risposta reale non rientra in nessuna, --dump-odds lo mostra
e la mappatura va estesa qui insieme al codice.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fbedge.sharpapi import (  # noqa: E402
    SharpApiClient,
    _to_decimal_odds,
    summarize_structure,
)

KICKOFF = "2026-08-29T18:45:00Z"


def client() -> SharpApiClient:
    return SharpApiClient("TEST", http=None)


# --- variante A: struttura simile a The Odds API ---------------------------
SHAPE_A = {
    "data": [{
        "id": "evt-1",
        "league": "italy-serie-a",
        "commence_time": KICKOFF,
        "home_team": "Inter Milan",
        "away_team": "Napoli",
        "bookmakers": [{
            "key": "bet365", "title": "Bet365",
            "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "Inter Milan", "price": 2.05},
                    {"name": "Draw", "price": 3.50},
                    {"name": "Napoli", "price": 3.70}]},
                {"key": "totals", "outcomes": [
                    {"name": "Over", "price": 1.90, "point": 2.5},
                    {"name": "Under", "price": 1.92, "point": 2.5}]},
            ],
        }],
    }]
}

# --- variante B: nomi diversi, squadre come oggetti, mercati come dizionario
SHAPE_B = {
    "events": [{
        "event_id": "evt-1",
        "start_time": KICKOFF,
        "home": {"name": "Inter Milan"},
        "away": {"name": "Napoli"},
        "sportsbooks": [{
            "book": "bet365", "name": "Bet365",
            "markets": {
                "moneyline": {"selections": [
                    {"team": "Inter Milan", "decimal_odds": 2.05},
                    {"team": "Draw", "decimal_odds": 3.50},
                    {"team": "Napoli", "decimal_odds": 3.70}]},
                "over_under": {"line": 2.5, "selections": [
                    {"team": "Over", "decimal_odds": 1.90},
                    {"team": "Under", "decimal_odds": 1.92}]},
            },
        }],
    }]
}

# --- variante C: quote americane, linea sul mercato, lista squadre ---------
SHAPE_C = [{
    "uuid": "evt-1",
    "starts_at": KICKOFF,
    "teams": ["Inter Milan", "Napoli"],
    "books": [{
        "id": "pinnacle", "display_name": "Pinnacle",
        "lines": [
            {"market_type": "total", "line": 2.5, "prices": [
                {"label": "Over", "odds": -111},
                {"label": "Under", "odds": 109}]},
            {"market_type": "both_teams_to_score", "prices": [
                {"label": "Yes", "odds": -125},
                {"label": "No", "odds": 105}]},
        ],
    }],
}]


class SharpApiParsingTest(unittest.TestCase):
    def _events(self, payload):
        from fbedge.sharpapi import _as_list
        parser = client()
        return [parser._parse_event(raw, "italy-serie-a") for raw in _as_list(payload)]

    def test_shape_a(self) -> None:
        (event,) = self._events(SHAPE_A)
        self.assertEqual(event.home_team, "Inter Milan")
        self.assertEqual(event.away_team, "Napoli")
        self.assertEqual(event.commence_time.hour, 18)
        self.assertIn("h2h", event.markets)
        self.assertIn("totals", event.markets)
        prices = [o.price for o in event.markets["h2h"][0].outcomes]
        self.assertEqual(prices, [2.05, 3.50, 3.70])
        totals = event.markets["totals"][0].outcomes
        self.assertTrue(all(o.point == 2.5 for o in totals))

    def test_shape_b_alternative_names(self) -> None:
        (event,) = self._events(SHAPE_B)
        self.assertEqual((event.home_team, event.away_team), ("Inter Milan", "Napoli"))
        self.assertEqual(event.markets["h2h"][0].book_title, "Bet365")
        self.assertEqual([o.price for o in event.markets["h2h"][0].outcomes],
                         [2.05, 3.50, 3.70])
        # la linea sta sul mercato, non sull'esito: va propagata
        self.assertTrue(all(o.point == 2.5 for o in event.markets["totals"][0].outcomes))

    def test_shape_c_american_odds(self) -> None:
        (event,) = self._events(SHAPE_C)
        self.assertEqual((event.home_team, event.away_team), ("Inter Milan", "Napoli"))
        over, under = event.markets["totals"][0].outcomes
        self.assertAlmostEqual(over.price, 1.9009, places=3)   # -111
        self.assertAlmostEqual(under.price, 2.09, places=3)    # +109
        self.assertEqual(over.point, 2.5)
        self.assertIn("btts", event.markets)

    def test_unknown_market_is_reported_not_silently_dropped(self) -> None:
        parser = client()
        payload = {"data": [{
            "id": "x", "commence_time": KICKOFF,
            "home_team": "A", "away_team": "B",
            "bookmakers": [{"key": "b", "markets": [
                {"key": "asian_handicap", "outcomes": [{"name": "A", "price": 1.9}]}]}],
        }]}
        from fbedge.sharpapi import _as_list
        for raw in _as_list(payload):
            parser._parse_event(raw, "l")
        self.assertIn("asian_handicap", parser.unknown_fields)

    def test_odds_format_conversion(self) -> None:
        self.assertAlmostEqual(_to_decimal_odds(2.05, "decimal"), 2.05)
        self.assertAlmostEqual(_to_decimal_odds(-200, "american"), 1.5)
        self.assertAlmostEqual(_to_decimal_odds(150, "american"), 2.5)
        self.assertAlmostEqual(_to_decimal_odds(-200, "auto"), 1.5)
        self.assertAlmostEqual(_to_decimal_odds(2.05, "auto"), 2.05)
        # una quota decimale >= 100 e' implausibile ma non va letta come americana
        self.assertIsNone(_to_decimal_odds("non-un-numero"))
        self.assertIsNone(_to_decimal_odds(0.5, "decimal"))

    def test_malformed_event_is_skipped_without_raising(self) -> None:
        parser = client()
        self.assertIsNone(parser._parse_event({"id": "x"}, "l"))
        self.assertIsNone(parser._parse_event("stringa", "l"))
        self.assertIsNone(parser._parse_event({"commence_time": "non-una-data",
                                               "home_team": "A", "away_team": "B"}, "l"))

    def test_structure_summary_is_readable(self) -> None:
        text = summarize_structure(SHAPE_A)
        self.assertIn("data", text)
        self.assertIn("home_team", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
