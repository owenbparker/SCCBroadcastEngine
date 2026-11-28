"""The CEN Desk Front TV board: in the SCC graphics, reading Global's teams,
logos, tournament and game logo, over the background loop."""

import json
import os
import unittest

from gfxengine import globalcfg
from gfxengine.pack import signature

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "CEN Desk Front TV"


class CenDeskTests(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "starter", "project.json"), encoding="utf-8") as f:
            self.project = json.load(f)
        self.comp = next(c for c in self.project["compositions"] if c["name"] == NAME)

    def test_in_the_pack(self):
        self.assertIn(NAME, self.project["pack_new"])
        self.assertIn(signature(self.comp), self.project["pack_history"][NAME])
        self.assertEqual(self.comp["kind"], "board")
        for l in self.comp["layers"]:
            src = l.get("src") or ""
            if src and "{{" not in src:
                self.assertTrue(os.path.isfile(os.path.join(ROOT, "starter", src)), src)

    def test_reads_global(self):
        used = json.dumps(self.comp["layers"])
        for token in ("{{Global!BG loop}}", "{{Global!Left color}}", "{{Global!Right color}}", "{{Global!Left logo}}",
                      "{{Global!Right logo}}", "{{Global!Tournament logo}}", "{{Global!Game logo}}",
                      "{{Global!Left score}}", "{{Global!Stage}}", "{{Global!Right name big high}}"):
            self.assertIn(token, used)
        self.assertEqual([l["type"] for l in self.comp["layers"][:2]], ["image", "video"])

    def test_name_lines(self):
        self.assertEqual(globalcfg.name_lines("St. Clair Saints"), ("St. Clair", "Saints", "", ""))
        self.assertEqual(globalcfg.name_lines("Fuel Esports"), ("", "", "Fuel", "Esports"))
        self.assertEqual(globalcfg.name_lines("Opponent"), ("", "Opponent", "", ""))
        self.assertEqual(globalcfg.name_lines(""), ("", "", "", ""))

    def test_game_logo(self):
        g = globalcfg.clean({"left": {"game": "VALORANT"}})
        self.assertEqual(globalcfg.game_logo(g), "games/valorant.svg")
        self.assertEqual(globalcfg.game_logo(g, "cod"), "games/cod.png")       # the connected HUD's game first
        self.assertEqual(globalcfg.game_logo(globalcfg.clean({"game_logo": "assets/logos/MW4.png"}), "lol"),
                         "assets/logos/MW4.png")                                 # one set in Global wins
        self.assertEqual(globalcfg.game_logo(globalcfg.clean({})), "")
        rows = dict(globalcfg.rows({"left": {"name": "Fuel Esports"}}, "rl")[1:])
        self.assertEqual((rows["Game logo"], rows["Left name big high"]), ("games/rocketleague.png", "Fuel"))
        for path in globalcfg.GAME_LOGOS.values():
            self.assertTrue(os.path.isfile(os.path.join(ROOT, "web", path)), path)


if __name__ == "__main__":
    unittest.main()
