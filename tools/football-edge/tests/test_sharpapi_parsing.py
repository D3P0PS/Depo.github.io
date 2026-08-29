"""Test del parser SharpAPI su piu' forme plausibili della risposta.

La mappatura dei campi e' stata ricostruita senza accesso alla documentazione,
quindi il parser accetta piu' varianti. Questi test bloccano le varianti
supportate: se la risposta reale non rientra in nessuna, --dump-odds lo mostra
e la mappatura va estesa qui insieme al codice.
"""

from __future__ import annotations

import json
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


# Forma reale di /api/v1/leagues, osservata sulla risposta del provider.
LEAGUES_PAYLOAD = {
    "data": [
        {"id": "nfl", "display_name": "NFL", "numerical_id": 376,
         "sport": "football", "event_count": 1449, "live_count": 0},
        {"id": "serie_a", "display_name": "Serie A", "sport": "soccer",
         "event_count": 380},
        {"id": "brazil_serie_a", "display_name": "Brazil Serie A",
         "sport": "soccer", "event_count": 380},
        {"id": "serie_b", "display_name": "Serie B", "sport": "soccer",
         "event_count": 380},
        {"id": "epl", "display_name": "English Premier League",
         "sport": "soccer", "event_count": 380},
        {"id": "russia_premier_league", "display_name": "Russia Premier League",
         "sport": "soccer", "event_count": 240},
        {"id": "efl_championship", "display_name": "EFL Championship",
         "sport": "soccer", "event_count": 552},
        {"id": "bundesliga", "display_name": "Bundesliga", "sport": "soccer",
         "event_count": 306},
        {"id": "bundesliga_2", "display_name": "2. Bundesliga",
         "sport": "soccer", "event_count": 306},
        {"id": "laliga", "display_name": "LaLiga", "sport": "soccer",
         "event_count": 380},
        {"id": "laliga_2", "display_name": "LaLiga 2", "sport": "soccer",
         "event_count": 462},
        {"id": "ligue_1", "display_name": "Ligue 1", "sport": "soccer",
         "event_count": 306},
        {"id": "ligue_2", "display_name": "Ligue 2", "sport": "soccer",
         "event_count": 380},
        {"id": "eredivisie", "display_name": "Eredivisie", "sport": "soccer",
         "event_count": 306},
        {"id": "primeira_liga", "display_name": "Primeira Liga",
         "sport": "soccer", "event_count": 306},
        {"id": "ucl", "display_name": "UEFA Champions League",
         "sport": "soccer", "event_count": 189},
    ],
    "updated_at": "2026-08-29T12:59:18.813568864Z",
}

#: cosa deve uscire per ciascun campionato che ci interessa
EXPECTED = {
    "SA": "serie_a", "PL": "epl", "BL1": "bundesliga", "PD": "laliga",
    "FL1": "ligue_1", "DED": "eredivisie", "PPL": "primeira_liga", "CL": "ucl",
    "ELC": "efl_championship", "SB": "serie_b", "BL2": "bundesliga_2",
    "SD": "laliga_2", "FL2": "ligue_2",
}


class LeagueMatchingTest(unittest.TestCase):
    """Gli id SharpAPI sono slug propri: vanno indovinati fra centinaia."""

    def setUp(self) -> None:
        from fbedge.sharpapi import _as_list
        self.leagues = [
            {"id": r["id"], "name": r["display_name"], "sport": r["sport"],
             "events": r.get("event_count", 0)}
            for r in _as_list(LEAGUES_PAYLOAD) if r["sport"] == "soccer"
        ]

    def test_every_competition_matches_the_right_league(self) -> None:
        from fbedge.config import COMPETITIONS
        from fbedge.matching import league_candidates
        for code, expected in EXPECTED.items():
            comp = COMPETITIONS[code]
            candidates = league_candidates(comp.short_name, comp.country, self.leagues)
            self.assertTrue(candidates, code)
            score, best = candidates[0]
            self.assertEqual(best["id"], expected, f"{code}: atteso {expected}")
            self.assertGreaterEqual(score, 0.80, f"{code}: punteggio troppo basso")

    def test_homonyms_from_other_countries_are_ranked_below(self) -> None:
        from fbedge.config import COMPETITIONS
        from fbedge.matching import league_candidates
        # "Serie A" esiste anche in Brasile, "Premier League" anche in Russia
        for code, intruder in (("SA", "brazil_serie_a"), ("PL", "russia_premier_league")):
            comp = COMPETITIONS[code]
            ranked = league_candidates(comp.short_name, comp.country, self.leagues, limit=99)
            ids = [r["id"] for _s, r in ranked]
            self.assertLess(ids.index(EXPECTED[code]), ids.index(intruder), code)

    def test_list_leagues_parses_the_real_envelope(self) -> None:
        parser = client()
        parser._get = lambda path, params, ttl: ("url", LEAGUES_PAYLOAD)  # type: ignore
        rows = parser.list_leagues(ttl=0, sport="soccer")
        self.assertEqual(len(rows), 15)                    # l'NFL viene escluso
        self.assertNotIn("nfl", [r["id"] for r in rows])
        serie_a = next(r for r in rows if r["id"] == "serie_a")
        self.assertEqual(serie_a["name"], "Serie A")
        self.assertEqual(serie_a["events"], 380)

    def test_server_side_filter_is_re_verified_locally(self) -> None:
        # un provider che ignorasse ?sport=soccer restituirebbe anche l'NFL:
        # il filtro locale deve toglierlo comunque
        parser = client()
        parser._get = lambda path, params, ttl: ("url", LEAGUES_PAYLOAD)  # type: ignore
        rows = parser.list_leagues(ttl=0, sport="soccer")
        self.assertNotIn("nfl", [r["id"] for r in rows])

    def test_unknown_sport_falls_back_instead_of_returning_nothing(self) -> None:
        parser = client()
        parser._get = lambda path, params, ttl: ("url", LEAGUES_PAYLOAD)  # type: ignore
        rows = parser.list_leagues(ttl=0, sport="pallanuoto")
        self.assertEqual(len(rows), 16)   # nessun filtro applicabile: li mostra tutti


ERROR_BODY = (
    '{"error":{"code":"invalid_filter","details":{"did_you_mean":'
    '[{"field":"league","try":{"league":"serie_a"},"value":"serie-a"}],'
    '"fields":{"league":["serie-a"]},"reference":{"league":"/api/v1/leagues"}},'
    '"message":"invalid filter values: league=[serie-a]"}}'
)


class FakeHttp:
    """Accetta solo il codice campionato corretto, come fa il provider vero."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, headers=None, ttl=0):
        from fbedge.httpcache import HttpError, Response
        self.calls.append(url)
        if "league=serie_a" in url:
            return Response(200, {}, json.dumps(self.payload), from_cache=False)
        raise HttpError(400, url, ERROR_BODY)


class LeagueSuggestionTest(unittest.TestCase):
    """Un trattino al posto di un underscore non deve fermare l'analisi."""

    def setUp(self) -> None:
        self.http = FakeHttp({"data": [SHAPE_A["data"][0]]})
        self.client = SharpApiClient("TEST", self.http)

    def test_wrong_code_is_corrected_and_retried(self) -> None:
        result = self.client.fetch("serie-a", ["h2h"], ttl=0)
        self.assertEqual(len(result.events), 1)
        self.assertEqual(self.client.league_corrections, {"serie-a": "serie_a"})
        self.assertEqual(len(self.http.calls), 2)          # un solo nuovo tentativo
        self.assertTrue(any("corretto dal provider" in n for n in result.notes))
        self.assertTrue(any("serie_a" in n for n in result.notes))

    def test_correct_code_does_not_trigger_a_retry(self) -> None:
        result = self.client.fetch("serie_a", ["h2h"], ttl=0)
        self.assertEqual(len(result.events), 1)
        self.assertEqual(self.client.league_corrections, {})
        self.assertEqual(len(self.http.calls), 1)

    def test_error_without_suggestion_is_propagated(self) -> None:
        from fbedge.httpcache import HttpError

        class NoSuggestion(FakeHttp):
            def get(self, url, headers=None, ttl=0):
                self.calls.append(url)
                raise HttpError(400, url, '{"error":{"message":"boom"}}')

        client_ = SharpApiClient("TEST", NoSuggestion({}))
        with self.assertRaises(HttpError):
            client_.fetch("qualsiasi", ["h2h"], ttl=0)

    def test_suggestion_parsing_is_defensive(self) -> None:
        from fbedge.sharpapi import suggested_value
        self.assertEqual(suggested_value(ERROR_BODY, "league"), "serie_a")
        self.assertIsNone(suggested_value(ERROR_BODY, "sport"))
        self.assertIsNone(suggested_value("<html>502</html>", "league"))
        self.assertIsNone(suggested_value("null", "league"))


META_FREE = {
    "tier": {"name": "free", "data_delay_seconds": 60, "requests_per_minute": 12,
             "books": ["a", "b"],
             "note": "free-tier responses are delayed 60s and limited to 2 sports"},
    "books": {"in_scope": ["pinnacle", "bet365"]},
}


class PagedHttp:
    """Serve pagine diverse a seconda dell'offset, come il provider vero."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, headers=None, ttl=0):
        from fbedge.httpcache import Response
        self.calls.append(url)
        offset = 0
        if "offset=" in url:
            offset = int(url.split("offset=")[1].split("&")[0])
        return Response(200, {}, json.dumps(self.pages[offset]), from_cache=False)


class EmptyAndPagedResponseTest(unittest.TestCase):
    """Una risposta valida ma vuota non e' un errore di mappatura."""

    def test_empty_data_is_not_reported_as_unknown_structure(self) -> None:
        http = PagedHttp({0: {"data": [], "pagination": {"count": 0, "has_more": False},
                              "meta": META_FREE}})
        result = SharpApiClient("TEST", http).fetch("serie_a", ["h2h"], ttl=0)
        joined = " ".join(result.notes)
        self.assertIn("0 eventi", joined)
        self.assertNotIn("nessuna lista di eventi riconosciuta", joined)
        self.assertEqual(result.events, [])

    def test_plan_limits_are_surfaced(self) -> None:
        http = PagedHttp({0: {"data": [], "pagination": {"has_more": False},
                              "meta": META_FREE}})
        joined = " ".join(SharpApiClient("TEST", http).fetch("serie_a", ["h2h"], 0).notes)
        self.assertIn("piano 'free'", joined)
        self.assertIn("limited to 2 sports", joined)      # la nota non va troncata
        self.assertIn("pinnacle", joined)
        self.assertIn("ritardati di 60s", joined)

    def test_unknown_structure_is_still_reported_as_such(self) -> None:
        http = PagedHttp({0: {"qualcosa": {"di": "inatteso"}}})
        joined = " ".join(SharpApiClient("TEST", http).fetch("serie_a", ["h2h"], 0).notes)
        self.assertIn("nessuna lista di eventi riconosciuta", joined)

    def test_pagination_is_followed(self) -> None:
        event = SHAPE_A["data"][0]
        http = PagedHttp({
            0: {"data": [event], "pagination": {"has_more": True, "next_offset": 50}},
            50: {"data": [dict(event, id="evt-2")],
                 "pagination": {"has_more": False, "next_offset": None}},
        })
        result = SharpApiClient("TEST", http).fetch("serie_a", ["h2h"], ttl=0)
        self.assertEqual(len(result.events), 2)
        self.assertEqual(len(http.calls), 2)

    def test_pagination_stops_at_the_page_limit(self) -> None:
        event = SHAPE_A["data"][0]
        pages = {n * 50: {"data": [dict(event, id=f"evt-{n}")],
                          "pagination": {"has_more": True, "next_offset": (n + 1) * 50}}
                 for n in range(10)}
        http = PagedHttp(pages)
        client_ = SharpApiClient("TEST", http, max_pages=3)
        result = client_.fetch("serie_a", ["h2h"], ttl=0)
        self.assertEqual(len(http.calls), 3)
        self.assertEqual(len(result.events), 3)
        self.assertTrue(any("fermato dopo 3 pagine" in n for n in result.notes))

    def test_diagnostic_notes_are_not_truncated(self) -> None:
        from fbedge.sharpapi import summarize_structure
        long_note = "x" * 300
        text = summarize_structure({"note": long_note, "altro": "y" * 300})
        self.assertIn("x" * 300, text)        # le note si vedono per intero
        self.assertNotIn("y" * 300, text)     # il resto resta troncato


if __name__ == "__main__":
    unittest.main(verbosity=2)
