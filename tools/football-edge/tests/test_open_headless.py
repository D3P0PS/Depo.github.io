"""Test del rilevamento di sessione senza schermo per --open.

Il flag lancia un browser sulla macchina che esegue lo script: su una
connessione SSH/Termius quella macchina e' il server remoto, non il telefono
o il computer dell'utente. Aprire un browser li' non serve a nessuno, e prima
falliva in silenzio. Questi test bloccano sia il rilevamento sia il messaggio
di aiuto che lo sostituisce.
"""

from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fbedge.cli import is_headless_session  # noqa: E402


class HeadlessDetectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {k: os.environ.get(k) for k in
                      ("SSH_CONNECTION", "SSH_TTY", "DISPLAY", "WAYLAND_DISPLAY")}
        for key in self._saved:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_ssh_connection_is_detected_as_headless(self) -> None:
        os.environ["SSH_CONNECTION"] = "1.2.3.4 1 5.6.7.8 22"
        os.environ["DISPLAY"] = ":0"      # anche con DISPLAY, l'SSH vince
        self.assertTrue(is_headless_session())

    def test_no_display_no_ssh_is_headless(self) -> None:
        self.assertTrue(is_headless_session())

    def test_display_present_without_ssh_is_not_headless(self) -> None:
        os.environ["DISPLAY"] = ":0"
        self.assertFalse(is_headless_session())

    def test_wayland_counts_as_a_display(self) -> None:
        os.environ["WAYLAND_DISPLAY"] = "wayland-0"
        self.assertFalse(is_headless_session())


class OpenOverSshTest(unittest.TestCase):
    """Pipeline completa: --open su una sessione SSH stampa la guida, non fallisce muto."""

    def setUp(self) -> None:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "tests"))
        import tests.test_offline_pipeline as offline
        self.offline = offline
        self.case = offline.OfflinePipelineTest("test_pipeline_end_to_end")
        self.case.setUp()
        self._saved_ssh = os.environ.get("SSH_CONNECTION")
        os.environ["SSH_CONNECTION"] = "1.2.3.4 1 5.6.7.8 22"

    def tearDown(self) -> None:
        self.case.tearDown()
        if self._saved_ssh is None:
            os.environ.pop("SSH_CONNECTION", None)
        else:
            os.environ["SSH_CONNECTION"] = self._saved_ssh

    def test_open_prints_guidance_instead_of_trying_a_browser(self) -> None:
        from fbedge import cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main([
                "--competitions", "SA", "--date", self.case.date.isoformat(),
                "--offline", "--cache-dir", self.case.cache_dir,
                "--football-data-key", "TEST", "--odds-key", "TEST",
                "--odds-provider", "theoddsapi", "--mc-draws", "50", "--open",
            ])
        out = buf.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("non ha uno schermo collegato", out)
        self.assertIn("scp ", out)
        self.assertIn("SFTP", out)
        self.assertIn("HTML scritto in", out)

    def test_default_temp_file_is_in_its_own_directory(self) -> None:
        """Non deve finire condiviso in /tmp: altrimenti servirlo espone tutto."""
        from fbedge import cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main([
                "--competitions", "SA", "--date", self.case.date.isoformat(),
                "--offline", "--cache-dir", self.case.cache_dir,
                "--football-data-key", "TEST", "--odds-key", "TEST",
                "--odds-provider", "theoddsapi", "--mc-draws", "50", "--open",
            ])
        out = buf.getvalue()
        line = next(l for l in out.splitlines() if l.startswith("HTML scritto in"))
        path = line.split("HTML scritto in ", 1)[1]
        self.assertTrue(os.path.dirname(path).startswith(("/tmp/football-edge-",
                                                           os.environ.get("TMPDIR", "/tmp"))))
        self.assertEqual(len(os.listdir(os.path.dirname(path))), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
