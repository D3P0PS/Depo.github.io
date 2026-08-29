"""Test del caricamento delle chiavi da file .env e da variabili d'ambiente."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fbedge.cli import _mask, load_env_file  # noqa: E402
from fbedge.httpcache import HttpClient, redact  # noqa: E402

SAMPLE = """\
# commento da ignorare

FOOTBALL_DATA_API_KEY=chiave-dati-123
export SHARPAPI_KEY="sk_live_abc"
ODDS_API_KEY='quotata-singolarmente'
RIGA_SENZA_UGUALE
"""


class EnvFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = {k: os.environ.get(k) for k in
                      ("FOOTBALL_DATA_API_KEY", "SHARPAPI_KEY", "ODDS_API_KEY")}
        for key in self.saved:
            os.environ.pop(key, None)
        fd, self.path = tempfile.mkstemp(suffix=".env")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(SAMPLE)

    def tearDown(self) -> None:
        os.unlink(self.path)
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_parses_exports_quotes_and_comments(self) -> None:
        applied = load_env_file(self.path)
        self.assertEqual(os.environ["FOOTBALL_DATA_API_KEY"], "chiave-dati-123")
        self.assertEqual(os.environ["SHARPAPI_KEY"], "sk_live_abc")   # export + virgolette
        self.assertEqual(os.environ["ODDS_API_KEY"], "quotata-singolarmente")
        self.assertEqual(sorted(applied),
                         ["FOOTBALL_DATA_API_KEY", "ODDS_API_KEY", "SHARPAPI_KEY"])
        self.assertNotIn("RIGA_SENZA_UGUALE", os.environ)

    def test_environment_wins_over_file(self) -> None:
        os.environ["SHARPAPI_KEY"] = "gia-impostata"
        applied = load_env_file(self.path)
        self.assertEqual(os.environ["SHARPAPI_KEY"], "gia-impostata")
        self.assertNotIn("SHARPAPI_KEY", applied)

    def test_mask_never_exposes_the_key(self) -> None:
        secret = "sk_live_0123456789abcdef"
        masked = _mask(secret)
        self.assertNotIn(secret, masked)
        self.assertNotIn(secret[:8], masked)
        self.assertTrue(masked.endswith(f"({len(secret)} caratteri)"))
        self.assertIn("cdef", masked)          # solo la coda, per riconoscerla


class RedactionTest(unittest.TestCase):
    """La stessa funzione maschera i log e calcola la chiave di cache."""

    def test_secrets_are_masked(self) -> None:
        for url in ("https://a/b?apiKey=SEGRETO&x=1", "https://a/b?api_key=SEGRETO",
                    "https://a/b?token=SEGRETO", "https://a/b?secret=SEGRETO"):
            self.assertNotIn("SEGRETO", redact(url))
            self.assertIn("***", redact(url))

    def test_ordinary_params_are_untouched(self) -> None:
        url = "https://a/b?league=serie-a&markets=h2h&key=premier"
        self.assertEqual(redact(url), url)

    def test_cache_keys_do_not_collide_on_ordinary_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = HttpClient(cache_dir=tmp)
            self.assertNotEqual(client._cache_path("https://a/b?key=serie-a"),
                                client._cache_path("https://a/b?key=premier"))
            # due chiavi API diverse devono invece condividere la cache
            self.assertEqual(client._cache_path("https://a/b?apiKey=K1&l=sa"),
                             client._cache_path("https://a/b?apiKey=K2&l=sa"))


class TableWidthTest(unittest.TestCase):
    """La tabella deve entrare nel terminale, non andare a capo."""

    def _row(self, reliability="OK"):
        import datetime as dt
        from fbedge.analysis import EdgeRow
        return EdgeRow(
            dt.datetime.now(dt.timezone.utc), "SA", "Real Sociedad - Espanyol",
            "Over/Under 2.5", "Over 2.5", 2.05, "Pinnacle", 4, 0.045,
            0.69, 0.45, 0.87, 0.52, 41.4, -7.8, 78.3, 17.0, reliability, "",
            1.7, 1.1, 9, 8,
        )

    def test_every_line_fits_the_requested_width(self) -> None:
        from fbedge.config import Settings
        from fbedge.report import render_table
        for width in (140, 120, 110, 100, 90, 80):
            table = render_table([self._row()], Settings(), width=width)
            for line in table.splitlines():
                self.assertLessEqual(len(line), width,
                                     f"riga troppo lunga a {width} colonne: {line!r}")

    def test_essential_columns_are_never_dropped(self) -> None:
        from fbedge.report import _fit_columns
        for width in (140, 120, 100, 80, 60):
            names = [n for n, _w in _fit_columns(width)]
            for essential in ("PARTITA", "MERCATO", "SELEZIONE", "QUOTA",
                              "P.MOD", "EDGE", "AFFID."):
                self.assertIn(essential, names, f"{essential} tolta a {width}")

    def test_reliability_is_still_visible_when_narrow(self) -> None:
        from fbedge.config import Settings
        from fbedge.report import render_table
        table = render_table([self._row("INSUFF.")], Settings(), width=80)
        self.assertIn("INSUFF.", table)


class FooterTest(unittest.TestCase):
    def test_credits_are_labelled_with_the_provider(self) -> None:
        from fbedge.config import Settings
        from fbedge.report import render_footer
        text = render_footer({"odds_provider": "sharpapi",
                              "odds_requests_remaining": "431",
                              "odds_requests_used": "69"}, Settings(), 0, 3)
        self.assertIn("sharpapi", text)
        self.assertIn("431 rimasti", text)
        self.assertIn("69 usati", text)

    def test_missing_usage_counter_is_omitted_not_printed_as_none(self) -> None:
        from fbedge.config import Settings
        from fbedge.report import render_footer
        text = render_footer({"odds_provider": "sharpapi",
                              "odds_requests_remaining": "11"}, Settings(), 0, 0)
        self.assertNotIn("None", text)
        self.assertIn("Crediti quasi esauriti", text)   # 11 <= 50


if __name__ == "__main__":
    unittest.main(verbosity=2)
