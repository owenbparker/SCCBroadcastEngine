"""A whole workspace exported as a .sccws file and imported on another PC."""

import io
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.request
import zipfile

from PIL import Image

from gfxengine import wsshare
from gfxengine.config import ROOT, Settings


def _png(colour):
    buf = io.BytesIO()
    Image.new("RGBA", (4, 4), colour).save(buf, "PNG")
    return buf.getvalue()


class WorkspaceShareTests(unittest.TestCase):
    def setUp(self):
        wsshare.EXTRAS.clear()
        self.addCleanup(wsshare.EXTRAS.clear)

    def _engine(self, name="Main"):
        from gfxengine.app import Engine
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        engine = Engine(Settings(os.path.join(tmp, "settings.json")), os.path.join(tmp, "workspaces"),
                        starter=None, library_dir=os.path.join(tmp, "library"), legacy_dir=os.path.join(tmp, "none"))
        engine.rename_workspace(engine.workspace_id, name)
        return engine

    def _add(self, engine, name, blob):
        return engine.upload(name, io.BytesIO(blob), len(blob))

    def _sakura(self):
        """PC A: the Sakura Fest workspace (open), with files, a font, a team, a tournament."""
        a = self._engine("Other show")
        wid = a.create_workspace("Sakura Fest 2027", "empty")
        logo = self._add(a, "logo.png", _png((255, 0, 0, 255)))["assets"][0]
        with open(os.path.join(ROOT, "web", "fonts", "Anton-Regular.ttf"), "rb") as f:
            font = self._add(a, "Anton-Regular.ttf", f.read())["assets"][0]
        ps = next(x for x in a.assets.fonts() if x["path"] == font)["postscript"]
        a.ws.add_comp({"name": "Caster card", "layers": [
            {"id": "l1", "type": "image", "src": logo, "x": 0, "y": 0, "w": 4, "h": 4},
            {"id": "l2", "type": "text", "text": "Hi", "font": ps, "x": 0, "y": 0, "w": 9, "h": 9}]})
        a.ws.add_comp({"name": "Scorebug", "layers": []})
        team_logo = a.save_team_logo("Sakura Saints", "saints.png", _png((0, 255, 0, 255)), "VALORANT")
        a.new_tournament("Spring cup")
        a.set_workspace_picture(wid, "cover.png", _png((0, 0, 255, 255)))
        return a, wid, logo, font, team_logo

    def _export(self, engine, wid):
        path, name = engine.export_workspace(wid)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path, name

    def _import(self, engine, path):
        with open(path, "rb") as f:
            blob = f.read()
        return engine.import_workspace("x.sccws", io.BytesIO(blob), len(blob))

    def test_round_trip_adds_a_new_workspace_and_changes_nothing_here(self):
        a, wid, logo, font, team_logo = self._sakura()
        path, name = self._export(a, wid)
        self.assertEqual(name, "Sakura Fest 2027")
        names = set(zipfile.ZipFile(path).namelist())
        self.assertIn("workspace/project.json", names)
        self.assertIn("workspace/" + logo, names)
        self.assertIn("workspace/cover.png", names)
        self.assertIn(font, names)
        self.assertIn(team_logo, names)

        b = self._engine("Tonight")
        before_id = b.workspace_id
        before = b.ws.get()
        r = self._import(b, path)
        self.assertEqual(r["name"], "Sakura Fest 2027")
        self.assertEqual(r["graphics"], 2)
        self.assertEqual(r["teams"], ["Sakura Saints"])
        # Not opened, and the open workspace is as it was.
        self.assertEqual(b.workspace_id, before_id)
        self.assertEqual(b.settings.get()["workspace"], before_id)
        self.assertEqual(b.ws.get()["compositions"], before["compositions"])
        listed = {w["id"]: w for w in b.workspaces.list()}
        self.assertIn(r["id"], listed)
        self.assertTrue(listed[r["id"]]["picture"])
        # Everything there when it's opened.
        b.open(r["id"])
        p = b.ws.get()
        self.assertEqual([c["name"] for c in p["compositions"]], ["Caster card", "Scorebug"])
        self.assertTrue(os.path.isfile(b.ws.asset_path(logo)))
        self.assertIn("Spring cup", [t["name"] for t in b.tournaments_info()["tournaments"]])
        self.assertTrue(os.path.isfile(b.assets.path_of(font)))
        t = b.teams.find("Sakura Saints", "VALORANT")
        self.assertTrue(t and os.path.isfile(b.assets.path_of(t["logo"])))

        # Again: a second copy, "Sakura Fest 2027 2"; the team isn't doubled.
        r2 = self._import(b, path)
        self.assertEqual(r2["name"], "Sakura Fest 2027 2")
        self.assertNotEqual(r2["id"], r["id"])
        self.assertEqual(r2["teams"], [])
        self.assertEqual(len([x for x in b.teams.list() if x["name"] == "Sakura Saints"]), 1)

    def test_teams_and_shared_files_here_are_never_replaced(self):
        a, wid, logo, font, team_logo = self._sakura()
        path, _ = self._export(a, wid)
        b = self._engine("Tonight")
        # B has its own Sakura Saints with a different logo of the same file name.
        mine = b.save_team_logo("Sakura Saints", "saints.png", _png((9, 9, 9, 255)), "VALORANT")
        self.assertEqual(mine, team_logo)
        with open(b.assets.path_of(mine), "rb") as f:
            my_bytes = f.read()
        # And a different file where the font goes.
        os.makedirs(os.path.dirname(b.assets.path_of(font)), exist_ok=True)
        with open(b.assets.path_of(font), "wb") as f:
            f.write(b"not the same font")
        r = self._import(b, path)
        with open(b.assets.path_of(mine), "rb") as f:
            self.assertEqual(f.read(), my_bytes)
        self.assertEqual(b.teams.find("Sakura Saints", "VALORANT")["logo"], mine)
        self.assertEqual(r["teams"], [])
        with open(b.assets.path_of(font), "rb") as f:
            self.assertEqual(f.read(), b"not the same font")
        # The font comes in under a new file name (text finds fonts by name).
        new_font = font[:-4] + "-2" + font[-4:]
        self.assertIn(new_font, r["files"])
        self.assertTrue(os.path.isfile(b.assets.path_of(new_font)))
        # A second import reuses that file.
        r2 = self._import(b, path)
        self.assertEqual(r2["files"], [])

    def test_a_workspace_that_is_not_open_exports_too(self):
        a, wid, *_ = self._sakura()
        other = next(w["id"] for w in a.workspaces.list() if w["id"] != wid)
        path, name = self._export(a, other)
        self.assertEqual(name, "Other show")
        b = self._engine("Tonight")
        r = self._import(b, path)
        self.assertEqual(r["name"], "Other show")

    def test_extras_go_along(self):
        got = []
        wsshare.EXTRAS["run_of_show"] = (lambda: {"templates": [{"name": "VAL night"}]},
                                         lambda data: got.append(data) or {"added": ["VAL night"]})
        a, wid, *_ = self._sakura()
        path, _ = self._export(a, wid)
        b = self._engine("Tonight")
        r = self._import(b, path)
        self.assertEqual(got, [{"templates": [{"name": "VAL night"}]}])
        self.assertEqual(r["extras"]["run_of_show"], {"added": ["VAL night"]})

    def test_bad_files_are_refused_and_leave_nothing(self):
        b = self._engine("Tonight")
        n = len(b.workspaces.list())
        for blob in (b"not a zip", self._zip({"scc-gfx.json": "{}"}),
                     self._zip({"scc-ws.json": json.dumps({"format": "scc-ws", "version": 1})})):
            with self.assertRaises(ValueError):
                b.import_workspace("x.sccws", io.BytesIO(blob), len(blob))
        self.assertEqual(len(b.workspaces.list()), n)
        self.assertEqual([x for x in os.listdir(b.workspaces.root) if x.startswith(".import")], [])

    def test_paths_out_of_the_folder_are_skipped(self):
        b = self._engine("Tonight")
        blob = self._zip({"scc-ws.json": json.dumps({"format": "scc-ws", "version": 1, "library": ["library/../../evil.txt"]}),
                          "workspace/project.json": json.dumps({"name": "Evil", "compositions": []}),
                          "workspace/../../evil.txt": "x", "library/../../evil.txt": "x"})
        r = b.import_workspace("x.sccws", io.BytesIO(blob), len(blob))
        self.assertEqual(r["name"], "Evil")
        root = os.path.dirname(b.workspaces.root)
        self.assertFalse(os.path.exists(os.path.join(root, "evil.txt")))
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(root), "evil.txt")))

    def test_send_to_another_engine_over_http(self):
        from gfxengine.app import make_handler, _HTTPServer
        a, wid, *_ = self._sakura()
        b = self._engine("Tonight")
        httpd = _HTTPServer(("127.0.0.1", 0), make_handler(b))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        url = f"http://127.0.0.1:{httpd.server_address[1]}"
        got = a.send_workspace(wid, url)
        self.assertEqual(got["name"], "Sakura Fest 2027")
        self.assertIn(got["id"], [w["id"] for w in b.workspaces.list()])
        # And the download.
        with urllib.request.urlopen(f"{url}/api/workspaces/export?id={got['id']}") as r:
            self.assertIn("Sakura Fest 2027.sccws", r.headers["Content-Disposition"])
            self.assertTrue(zipfile.ZipFile(io.BytesIO(r.read())).namelist())

    @staticmethod
    def _zip(members):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for k, v in members.items():
                z.writestr(k, v)
        return buf.getvalue()


if __name__ == "__main__":
    unittest.main()
