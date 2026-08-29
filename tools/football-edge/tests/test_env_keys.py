"""Test del caricamento delle chiavi da file .env e da variabili d'ambiente."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fbedge.cli import _mask, load_env_file  # noqa: E402

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
