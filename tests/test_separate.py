"""Game HUDs as programs of their own (Settings > Run game HUDs as separate
programs): the child starts, serves its pages, is started again when it
crashes, and stops with the app."""

import os
import shutil
import tempfile
import time
import unittest
import urllib.request

from sccbe import parts as P


def wait_for(cond, secs=60):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


class SeparateHudTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._data = os.environ.get("SCCBE_DATA")
        os.environ["SCCBE_DATA"] = self.tmp

    def tearDown(self):
        if self._data is None:
            os.environ.pop("SCCBE_DATA", None)
        else:
            os.environ["SCCBE_DATA"] = self._data
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_runs_restarts_and_stops(self):
        part = P.Part("smash", "Smash Ultimate", "game", "smashhud", "smashhud", "/control", 8784, "smash.png")
        part.start(None, separate=True)
        self.addCleanup(part.stop)
        self.assertTrue(wait_for(lambda: part.status == "on"), f"{part.status} {part.error}\n{part._log_tail()}")
        self.assertTrue(part.info()["separate"])
        with urllib.request.urlopen(f"http://127.0.0.1:{part.port}/control", timeout=10) as r:
            self.assertEqual(r.status, 200)
        self.assertIsNone(part.busy())
        first = part.proc.pid
        self.assertNotEqual(first, os.getpid())

        # It crashes: started again by itself.
        part.proc.kill()
        self.assertTrue(wait_for(lambda: part.status == "on" and part.proc is not None and part.proc.pid != first, 90),
                        f"{part.status} {part.error}")
        self.assertEqual(part.info()["restarts"], 1)

        # Stopping it stops the program.
        proc = part.proc
        part.stop()
        self.assertEqual(part.status, "off")
        self.assertIsNotNone(proc.poll())
        self.assertIsNone(part.proc)

    def test_gives_up_after_too_many_crashes(self):
        part = P.Part("smash", "Smash Ultimate", "game", "smashhud", "smashhud", "/control", 8784, "smash.png")
        part.RESTARTS = 0
        part.start(None, separate=True)
        self.addCleanup(part.stop)
        self.assertTrue(wait_for(lambda: part.status == "on"), part._log_tail())
        part.proc.kill()
        self.assertTrue(wait_for(lambda: part.status == "error"))
        self.assertIn("left off", part.error)


if __name__ == "__main__":
    unittest.main()
