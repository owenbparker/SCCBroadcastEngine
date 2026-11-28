"""Map bans and picks: the CDL veto, the picks board and the HUD's routes."""

import copy
import json
import os
import tempfile
import unittest
import urllib.request

from codhud import mapbans
from codhud.config import DEFAULTS, Config, _merge


def cfg(**map_bans):
    return _merge(DEFAULTS, {"map_bans": map_bans})


class VetoTests(unittest.TestCase):
    def test_current_pool_is_cdl_2027(self):
        pools = mapbans.pools(cfg())
        self.assertEqual(pools["hp"], ["Lotus", "Lithium", "Munition", "Reactor U92", "Rooftops", "Sentry"])
        self.assertEqual(pools["snd"], ["Coal", "Lotus", "Munition", "Reactor U92", "Rooftops", "Silkworm"])
        self.assertEqual(pools["hij"], ["Lotus", "Lithium", "Munition"])
        self.assertEqual(mapbans.mode_name(cfg(), "hij"), "Hijack")
        self.assertEqual(mapbans.mode_name(cfg(game="bo7"), "hij"), "Overload")

    def test_bo5_order(self):
        steps = mapbans.steps(cfg(team_a="right"), 5)
        self.assertEqual([(s["action"], s["team"], s["mode"], s["game"]) for s in steps], [
            ("ban", "right", "hp", None), ("ban", "left", "hp", None), ("pick", "right", "hp", 1), ("pick", "left", "hp", 4),
            ("ban", "left", "snd", None), ("ban", "right", "snd", None), ("pick", "left", "snd", 2), ("pick", "right", "snd", 5),
            ("ban", "right", "hij", None), ("ban", "left", "hij", None), ("decider", None, "hij", 3)])
        self.assertEqual([s["side_team"] for s in steps if s["game"]], ["left", "right", "right", "left", "left"])

    def test_bo3_and_bo7_decide_every_game(self):
        for n in (3, 7):
            got = sorted(s["game"] for s in mapbans.steps(cfg(), n) if s["game"])
            self.assertEqual(got, list(range(1, n + 1)))
            modes = {s["game"]: s["mode"] for s in mapbans.steps(cfg(), n) if s["game"]}
            self.assertEqual([modes[i] for i in range(1, n + 1)], mapbans.MODE_ORDER[n])

    def test_hijack_decider_is_the_map_left(self):
        steps = [{}] * 8 + [{"map": "Lotus"}, {"map": "Munition"}]
        st = mapbans.steps(cfg(bo5={"steps": steps}), 5)
        self.assertEqual((st[10]["map"], st[10].get("auto")), ("Lithium", True))
        g = mapbans.games(cfg(bo5={"steps": steps}), 5)
        self.assertEqual(g[2]["map"], "Lithium")
        self.assertTrue(g[2]["decider"])

    def test_unknown_maps_are_dropped_and_custom_ones_kept(self):
        st = mapbans.steps(cfg(bo5={"steps": [{"map": "Nuketown"}, {"map": "Rust"}]}, custom=["Rust"]), 5)
        self.assertEqual(st[0]["map"], "")
        self.assertEqual(st[1]["map"], "Rust")

    def test_results_pick_the_winner(self):
        c = cfg(results={"1": {"left": 250, "right": 201}, "2": {"left": 3, "right": 6},
                         "3": {"left": 1, "right": 1, "winner": "right"}, "4": {"left": "x"}})
        g = mapbans.games(c, 5)
        self.assertEqual([x["winner"] for x in g], ["left", "right", "right", None, None])
        self.assertEqual(g[3]["score"], {"left": None, "right": None})

    def test_view_puts_team_a_on_top(self):
        v = mapbans.view(cfg(team_a="right", bo5={"steps": [{"map": "Lotus"}, {"map": "Sentry"}]}), 5)
        self.assertEqual((v["team_a"], v["team_b"]), ("right", "left"))
        self.assertEqual(v["bans"][0]["team"], "right")
        self.assertEqual(v["bans"][0]["cells"][0]["map"], "Lotus")
        self.assertEqual(v["bans"][1]["cells"][0]["map"], "Sentry")
        self.assertEqual(len(v["games"]), 5)
        # A best of 7 has no Team B bans.
        v7 = mapbans.view(cfg(), 7)
        self.assertTrue(all(c["none"] for c in v7["bans"][1]["cells"]))

    def test_old_config_gets_map_bans(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "config.json")
        old = copy.deepcopy(DEFAULTS)
        old.pop("map_bans")
        with open(path, "w") as f:
            json.dump(old, f)
        c = Config(path).get()
        self.assertEqual(c["map_bans"]["game"], "mw4")
        self.assertIsNone(c["map_bans"]["pools"])


class ArtTests(unittest.TestCase):
    def test_add_and_remove_a_picture(self):
        tmp = tempfile.mkdtemp()
        old = mapbans.ART_DIR
        mapbans.ART_DIR = tmp
        try:
            png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
            url = mapbans.save_art("Reactor U92", png)
            self.assertTrue(url.startswith("/map-art/reactor-u92?v="))
            self.assertTrue(os.path.isfile(os.path.join(tmp, "reactor-u92.png")))
            self.assertEqual(mapbans.art_by_slug("reactor-u92"), os.path.join(tmp, "reactor-u92.png"))
            mapbans.save_art("Reactor U92", "")
            self.assertFalse(os.path.exists(os.path.join(tmp, "reactor-u92.png")))
            # The pictures that come with the HUD stay.
            self.assertTrue(mapbans.art_path("Den"))
        finally:
            mapbans.ART_DIR = old


class RouteTests(unittest.TestCase):
    def test_graphic_and_api(self):
        from codhud.app import HudApp, start
        tmp = tempfile.mkdtemp()
        config = Config(os.path.join(tmp, "config.json"))
        config.update({"http_port": 8797})
        app = HudApp(config, demo=True)
        start(app)
        try:
            base = "http://127.0.0.1:8797"
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            v = json.loads(opener.open(base + "/api/map-bans?bo=3").read())
            self.assertEqual(v["format"], 3)
            page = opener.open(base + "/map-bans?show=bans").read().decode()
            self.assertIn("MAP BANS", page.upper())
            self.assertEqual(opener.open(base + "/mapbans/bans-under.png").status, 200)
            self.assertEqual(opener.open(base + "/map-art/den").status, 200)
            snap = app._engine_snapshot()
            self.assertEqual([g["path"] for g in snap["hud"]["graphics"]], ["/map-bans", "/map-bans?show=picks", "/map-bans?show=bans"])
            self.assertIn("map_bans", app.info())
        finally:
            app.stop()


if __name__ == "__main__":
    unittest.main()
