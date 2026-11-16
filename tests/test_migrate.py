"""Bringing in the old GFX Engine / HUDs' data (sccbe/migrate.py): it only adds."""

import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sccbe import migrate, parts as P  # noqa: E402

P.add_to_path()


def Teams(lib):
    from gfxengine.teams import Teams as T
    return T(lib)


def write(path, text, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        f.write(text)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class MigrateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.had = set(sys.modules)

    @classmethod
    def tearDownClass(cls):
        # gfxengine (imported here) reads SCCBE_DATA once: let the other tests import it afresh.
        for m in [m for m in sys.modules if m.startswith("gfxengine") and m not in cls.had]:
            del sys.modules[m]
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sccbe-migrate-")
        self.old = os.path.join(self.tmp, "SCC GFX Engine")
        self.data = os.path.join(self.tmp, "SCC Broadcast Engine", "data")
        o = self.old
        # The old engine: 100 teams, two workspaces (one with the same id as the new app's), one deleted.
        rows = ["Name,Short name,Logo,Colour,Game,Player 1 name,Player 1 headshot"]
        rows += [f"Team {i},T{i},library/teams/t{i}.png,#112233,VALORANT,P{i},library/teams/p{i}.png" for i in range(100)]
        rows.append("Keep Me,OLD,library/teams/keep.png,#000000,VALORANT,,")
        write(os.path.join(o, "library", "teams.csv"), "\n".join(rows) + "\n")
        for i in range(100):
            write(os.path.join(o, "library", "teams", f"t{i}.png"), b"old%d" % i, "wb")
        write(os.path.join(o, "library", "teams", "keep.png"), b"OLD LOGO", "wb")
        write(os.path.join(o, "library", "fonts", "Barlow.ttf"), b"font", "wb")
        write(os.path.join(o, "workspaces", "scc-broadcast", "project.json"), json.dumps({"name": "SCC Broadcast", "compositions": [1, 2, 3]}))
        write(os.path.join(o, "workspaces", "scc-broadcast", "assets", "a.png"), b"a", "wb")
        write(os.path.join(o, "workspaces", "lotd", "project.json"), json.dumps({"name": "LOTD"}))
        write(os.path.join(o, "workspaces", ".deleted", "esm-1", "project.json"), json.dumps({"name": "ESM"}))
        write(os.path.join(o, "settings.json"), json.dumps({"workspace": "scc-broadcast", "name": "Owen GFX",
                                                            "engine_id": "oldid", "camera_looks": [{"name": "Day"}]}))
        write(os.path.join(o, "GFXEngine.exe"), b"exe", "wb")
        write(os.path.join(o, "_internal", "x.dll"), b"dll", "wb")
        # The new app after its first start: the starter workspace, one team of its own, a different keep.png.
        n = os.path.join(self.data, "gfxengine")
        write(os.path.join(n, "workspaces", "scc-broadcast", "project.json"), json.dumps({"name": "SCC Broadcast"}))
        write(os.path.join(n, "settings.json"), json.dumps({"workspace": "scc-broadcast", "name": "", "engine_id": "newid",
                                                            "camera_looks": []}))
        write(os.path.join(n, "library", "teams.csv"), "Name,Short name,Logo,Colour,Game\nKeep Me,NEW,library/teams/keep.png,#ffffff,VALORANT\n")
        write(os.path.join(n, "library", "teams", "keep.png"), b"NEW LOGO", "wb")
        # An old League HUD.
        self.lol = os.path.join(self.tmp, "SCC LoL HUD")
        write(os.path.join(self.lol, "config.json"), json.dumps({"riot_id": "abc", "port": 1}))
        write(os.path.join(self.lol, "logos", "x.png"), b"x", "wb")
        write(os.path.join(self.data, "lolhud", "config.json"), json.dumps({"port": 2}))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_import(self, again=False):
        return migrate.run(self.data, [self.old, self.lol], again=again)

    def test_imports_and_only_adds(self):
        before = {}
        for root, _, files in os.walk(self.old):
            for f in files:
                p = os.path.join(root, f)
                with open(p, "rb") as fh:
                    before[p] = fh.read()
        r = self.run_import()
        self.assertEqual(r["teams"], 100)
        n = os.path.join(self.data, "gfxengine")
        teams = Teams(os.path.join(n, "library")).list()
        self.assertEqual(len(teams), 101)
        keep = next(t for t in teams if t["name"] == "Keep Me")
        self.assertEqual(keep["short"], "NEW")                                 # the one here kept
        t5 = next(t for t in teams if t["name"] == "Team 5")
        self.assertEqual(t5["logo"], "library/teams/t5.png")
        self.assertEqual(t5["players"][0]["photo"], "library/teams/p5.png")
        with open(os.path.join(n, "library", "teams", "keep.png"), "rb") as f:
            self.assertEqual(f.read(), b"NEW LOGO")                            # not replaced
        with open(os.path.join(n, "library", "teams", "keep-old.png"), "rb") as f:
            self.assertEqual(f.read(), b"OLD LOGO")                            # old one beside it
        self.assertTrue(os.path.isfile(os.path.join(n, "library", "fonts", "Barlow.ttf")))
        # Workspaces: the new one untouched, the old one beside it, deleted ones not brought back.
        self.assertEqual(read_json(os.path.join(n, "workspaces", "scc-broadcast", "project.json")), {"name": "SCC Broadcast"})
        old_ws = read_json(os.path.join(n, "workspaces", "scc-broadcast-2", "project.json"))
        self.assertEqual(old_ws["name"], "SCC Broadcast (old GFX Engine)")
        self.assertEqual(len(old_ws["compositions"]), 3)
        self.assertTrue(os.path.isfile(os.path.join(n, "workspaces", "scc-broadcast-2", "assets", "a.png")))
        self.assertTrue(os.path.isfile(os.path.join(n, "workspaces", "lotd", "project.json")))
        self.assertFalse(os.path.exists(os.path.join(n, "workspaces", ".deleted")))
        # Settings: filled in, own engine ID kept, the old open workspace opened.
        s = read_json(os.path.join(n, "settings.json"))
        self.assertEqual(s["engine_id"], "newid")
        self.assertEqual(s["name"], "Owen GFX")
        self.assertEqual(s["camera_looks"], [{"name": "Day"}])
        self.assertEqual(s["workspace"], "scc-broadcast-2")
        # Program files not copied.
        self.assertFalse(os.path.exists(os.path.join(n, "GFXEngine.exe")))
        self.assertFalse(os.path.exists(os.path.join(n, "_internal")))
        # HUD: missing settings added, its own kept.
        c = read_json(os.path.join(self.data, "lolhud", "config.json"))
        self.assertEqual(c, {"port": 2, "riot_id": "abc"})
        self.assertTrue(os.path.isfile(os.path.join(self.data, "lolhud", "logos", "x.png")))
        # The old folders are exactly as they were.
        for p, data in before.items():
            with open(p, "rb") as fh:
                self.assertEqual(fh.read(), data, p)

    def test_runs_once_and_again_adds_nothing_twice(self):
        self.run_import()
        r = self.run_import()
        self.assertEqual(r["sources"], [])                                     # done before
        r = self.run_import(again=True)
        self.assertEqual(r["teams"], 0)
        self.assertEqual(r["workspaces"], [])
        self.assertEqual(r["files"], 0)
        n = os.path.join(self.data, "gfxengine", "workspaces")
        self.assertEqual(sorted(os.listdir(n)), ["lotd", "scc-broadcast", "scc-broadcast-2"])
        self.assertEqual(len(migrate.last(self.data)["folders"]), 2)

    def test_empty_new_app(self):
        shutil.rmtree(os.path.join(self.data, "gfxengine"))
        r = self.run_import()
        self.assertEqual(r["teams"], 101)
        n = os.path.join(self.data, "gfxengine")
        self.assertTrue(os.path.isfile(os.path.join(n, "workspaces", "scc-broadcast", "assets", "a.png")))
        self.assertEqual(read_json(os.path.join(n, "settings.json"))["workspace"], "scc-broadcast")


if __name__ == "__main__":
    unittest.main()
