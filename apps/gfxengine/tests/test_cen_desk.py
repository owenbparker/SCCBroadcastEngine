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
        for token in ("{{Global!BG loop}}", "{{Desk!Left color}}", "{{Desk!Right color}}", "{{Desk!Left logo}}",
                      "{{Desk!Right logo}}", "{{Global!Tournament logo}}", "{{Desk!Game logo}}",
                      "{{Desk!Left score}}", "{{Global!Stage}}", "{{Desk!Right name big high}}"):
            self.assertIn(token, used)
        self.assertEqual([l["type"] for l in self.comp["layers"][:2]], ["image", "video"])

    def test_desk_teams_and_game(self):
        teams = {"fuel esports": {"name": "Fuel Esports", "short": "FUEL", "logo": "library/teams/fuel.png",
                                  "color": "#ff0000", "game": "VALORANT"}}
        find = lambda n, g=None: teams.get(n.lower())   # noqa: E731
        g = {"left": {"name": "St. Clair Saints", "color": "#00aa00", "logo": "a.png", "score": 2, "game": "VALORANT"},
             "right": {"name": "Away", "color": "#0000ff", "logo": "b.png", "score": 1}}
        # Nothing picked: the same as Global.
        self.assertEqual(globalcfg.desk_rows(g, find), globalcfg.rows(g))
        rows = dict(globalcfg.desk_rows(dict(g, desk={"right": {"name": "Fuel Esports", "game": "VALORANT"}, "game": "cod"}), find)[1:])
        self.assertEqual((rows["Right name"], rows["Right color"], rows["Right logo"], rows["Right score"]),
                         ("Fuel Esports", "#ff0000", "library/teams/fuel.png", "0"))
        self.assertEqual((rows["Right name big high"], rows["Right name small under"]), ("Fuel", "Esports"))
        self.assertEqual((rows["Left name"], rows["Left score"], rows["Game logo"]), ("St. Clair Saints", "2", "games/cod.png"))
        # Global's own team picked keeps its score; a team gone from the Teams tab keeps its name.
        rows = dict(globalcfg.desk_rows(dict(g, desk={"left": {"name": "St. Clair Saints"}, "right": {"name": "Gone"}}), find)[1:])
        self.assertEqual((rows["Left score"], rows["Right name"], rows["Right color"], rows["Right logo"]),
                         ("2", "Gone", "#0000ff", ""))
        # (cleaned: an unknown game is Global's; old Globals have none)
        self.assertEqual(globalcfg.clean({"desk": {"game": "nope"}})["desk"],
                         {"left": {"name": "", "game": ""}, "right": {"name": "", "game": ""}, "game": ""})
        self.assertEqual(globalcfg.clean({})["desk"]["game"], "")

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
