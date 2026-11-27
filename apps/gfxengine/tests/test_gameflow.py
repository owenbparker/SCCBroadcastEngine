"""Game Flow: the CoD HUD's Hardpoint / Hijack score over time -> the "Game flow" data and graphic."""

import json
import os
import shutil
import tempfile
import unittest

from gfxengine.gameflow import GameFlow, rows

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HP = {"mode": "hardpoint", "map": "Reactor U92", "map_no": 1, "state": "final", "score": [153, 250], "hills": 5,
      "marks": [[0, 0], [29, 8], [153, 250]], "labels": ["P1", "P2"], "per_hill": [[40, 43], [27, 45], [49, 39], [31, 60], [6, 63]]}
HJ = {"mode": "hijack", "map": "", "map_no": 3, "state": "halftime", "score": [39, 167], "halves": [[39, 167], None],
      "stats": [{"throws": 2, "dunks": 0, "runoff": 9, "avg": 19.5}, {"throws": 1, "dunks": 3, "runoff": 62, "avg": 41.8}],
      "line": [[0, 0, 0, 1]], "drives": []}


class GameFlowTests(unittest.TestCase):
    def test_rows(self):
        t = dict(rows(HP)[1:])
        self.assertEqual((t["Title"], t["Subtitle"], t["Panel title"], t["Status"]),
                         ("HARDPOINT // REACTOR U92", "GAME FLOW / MAP 1", "POINTS PER HILL", "FINAL"))
        self.assertEqual((t["P1 left"], t["P5 right"], t["P6 left"], t["Right score"]), ("40", "63", "", "250"))
        self.assertEqual(json.loads(t["Data"])["marks"][-1], [153, 250])
        j = dict(rows(HJ)[1:])
        self.assertEqual((j["Title"], j["Panel title"], j["Status"], j["1st half right"], j["2nd half left"], j["Right avg"]),
                         ("HIJACK", "POINTS PER HALF", "HALFTIME", "167", "", "41.8"))
        none = dict(rows({})[1:])
        self.assertEqual((none["Title"], none["Data"]), ("", ""))

    def test_kept_until_the_next_game(self):
        tmp = tempfile.mkdtemp()
        try:
            g = GameFlow(tmp)
            self.assertTrue(g.update(HP))
            self.assertFalse(g.update(HP))
            self.assertFalse(g.update({}))                    # (no game yet in the HUD: the last one stays)
            self.assertFalse(g.update({"mode": "search"}))
            self.assertEqual(dict(GameFlow(tmp).rows()[1:])["Right score"], "250")    # (an engine restart)
            self.assertTrue(g.update(HJ))
            g.clear()
            self.assertEqual(dict(GameFlow(tmp).rows()[1:])["Mode"], "")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_in_the_pack(self):
        with open(os.path.join(ROOT, "starter", "project.json"), encoding="utf-8") as f:
            data = json.load(f)
        comp = next(c for c in data["compositions"] if c["name"] == "Game flow")
        self.assertIn("Game flow", data["pack_new"])
        self.assertIn("Game flow", data["pack_history"])
        parts = sorted(l["part"] for l in comp["layers"] if l["type"] == "gameflow")
        self.assertEqual(parts, ["chart", "panel"])
        for l in comp["layers"]:
            src = l.get("src") or ""
            if src and "{{" not in src:
                self.assertTrue(os.path.isfile(os.path.join(ROOT, "starter", src)), src)

    def test_ingest(self):
        """A HUD's gameflow goes into the "Game flow" table (and an empty one doesn't wipe it)."""
        from gfxengine.app import Engine
        from gfxengine.config import Settings
        tmp = tempfile.mkdtemp()
        try:
            engine = Engine(Settings(os.path.join(tmp, "settings.json")), os.path.join(tmp, "workspaces"),
                            starter=os.path.join(ROOT, "starter"), library_dir=os.path.join(tmp, "library"),
                            legacy_dir=os.path.join(tmp, "none"))
            self.assertTrue(any(c["name"] == "Game flow" for c in engine.ws.snapshot()["compositions"]))
            engine.ingest({"source": "Call of Duty HUD", "game": "cod", "fields": {}, "gameflow": HP}, "127.0.0.1")
            engine.ingest({"source": "Call of Duty HUD", "game": "cod", "fields": {}, "gameflow": {}}, "127.0.0.1")
            t = dict(engine.data_snapshot()["tables"]["Game flow"][1:])
            self.assertEqual(t["Title"], "HARDPOINT // REACTOR U92")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
