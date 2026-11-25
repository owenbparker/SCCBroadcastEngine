"""Round win bug picker (Control > Round win bug, 2026-11-25)."""
import json
import os
import tempfile
import unittest

from valhud.config import Config, DEFAULTS

WEB = os.path.join(os.path.dirname(__file__), "..", "web", "scc2027")


class RoundWinBugTests(unittest.TestCase):
    def test_default_keeps_the_hud_own(self):
        self.assertEqual(DEFAULTS["round_win"], {"bug": "own", "intro": "", "outro": "", "test": 0})

    def test_old_config_gets_the_default(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"hud_design": "scc2027", "left": {"name": "Kept"}}, f)
            cfg = Config(path).get()
            self.assertEqual(cfg["round_win"]["bug"], "own")
            self.assertEqual(cfg["left"]["name"], "Kept")

    def test_partial_update_keeps_the_rest(self):
        with tempfile.TemporaryDirectory() as d:
            c = Config(os.path.join(d, "config.json"))
            c.update({"round_win": {"bug": "cen"}})
            c.update({"round_win": {"intro": "#00ff88"}})
            self.assertEqual(c.get()["round_win"], {"bug": "cen", "intro": "#00ff88", "outro": "", "test": 0})

    def test_cen_assets_and_bugs(self):
        for f in ("roundwin-cen-bg.png", "roundwin-cen-logo.png"):
            self.assertTrue(os.path.exists(os.path.join(WEB, "assets", f)), f)
        js = open(os.path.join(WEB, "scc2027.js"), encoding="utf-8").read()
        for bug in ("own:", "scc2027:", "cen:"):
            self.assertIn(bug, js)


if __name__ == "__main__":
    unittest.main()
