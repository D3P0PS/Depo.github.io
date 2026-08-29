"""Test del controllo di calibrazione sull'insieme della corsa.

Il caso che ha motivato questo modulo: un output di 80 righe quasi tutte con
edge positivo e grande, dove ogni riga sembrava un'occasione e nessuna nota
diceva che era il modello a essere sbagliato.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fbedge.analysis import EdgeRow  # noqa: E402
from fbedge.calibration import assess, render  # noqa: E402


def row(p_model, p_market, odds, reliability="OK"):
    edge = (p_model * odds - 1) * 100
    price = (p_market * odds - 1) * 100
    return EdgeRow(
        dt.datetime.now(dt.timezone.utc), "SA", "x - y", "1X2", "1", odds, "Book",
        8, 0.05, p_model, p_model * 0.7, p_model * 1.3, p_market,
        edge, edge - 40, edge + 40, (p_model - p_market) * 100,
        reliability, "", 1.5, 1.2, 9, 9, "", price, edge - price,
    )


class CalibrationTest(unittest.TestCase):
    def test_model_agreeing_with_market_is_not_flagged(self) -> None:
        # scarti piccoli e quote in linea col consenso: corsa plausibile
        rows = [row(0.50, 0.49, 2.00), row(0.30, 0.31, 3.20),
                row(0.22, 0.20, 4.80), row(0.62, 0.60, 1.62)]
        result = assess(rows)
        self.assertFalse(result.suspect, result.warnings)
        self.assertLess(result.mean_deviation, 0.05)
        self.assertIn("CONTROLLO DI CALIBRAZIONE", render(result))

    def test_flat_model_inflating_longshots_is_flagged(self) -> None:
        """I numeri sono quelli reali della corsa che ha motivato il modulo."""
        rows = [row(0.490, 0.201, 5.00, "INSUFF."), row(0.532, 0.228, 4.50),
                row(0.411, 0.209, 5.46, "INSUFF."), row(0.129, 0.061, 16.00),
                row(0.299, 0.148, 6.60), row(0.245, 0.134, 7.50)]
        result = assess(rows)
        self.assertTrue(result.suspect)
        self.assertGreater(result.longshot_bias, 0.04)
        text = render(result)
        self.assertIn("NON E' UTILIZZABILE", text)
        self.assertIn("troppo piatto", text)
        self.assertIn("--market-blend", text)

    def test_edge_from_price_dispersion_is_separated_from_the_model(self) -> None:
        # il modello concorda col mercato, l'edge viene tutto dalla quota
        r = row(0.471, 0.476, 2.75)
        self.assertAlmostEqual(r.edge_pct, 29.5, places=1)
        self.assertAlmostEqual(r.edge_price_pct, 30.9, places=1)
        self.assertLess(abs(r.edge_model_pct), 2.0)
        result = assess([r] * 4)
        self.assertEqual(result.price_driven_rows, 4)
        self.assertEqual(result.model_driven_rows, 0)
        self.assertIn("stantie", render(result))

    def test_edge_from_model_disagreement_is_separated_from_the_price(self) -> None:
        # quota in linea col mercato, edge tutto dal disaccordo del modello
        r = row(0.129, 0.061, 16.00)
        self.assertLess(r.edge_price_pct, 0)
        self.assertGreater(r.edge_model_pct, 100)
        result = assess([r] * 4)
        self.assertEqual(result.model_driven_rows, 4)

    def test_rows_without_market_probability_are_ignored(self) -> None:
        r = row(0.5, 0.5, 2.0)
        r.p_market = None
        self.assertEqual(assess([r]).rows, 0)
        self.assertEqual(render(assess([r])), "")

    def test_verdict_survives_a_single_row(self) -> None:
        result = assess([row(0.50, 0.20, 5.00)])
        self.assertEqual(result.rows, 1)
        self.assertIsNone(result.correlation)      # non calcolabile
        self.assertTrue(render(result))


if __name__ == "__main__":
    unittest.main(verbosity=2)
