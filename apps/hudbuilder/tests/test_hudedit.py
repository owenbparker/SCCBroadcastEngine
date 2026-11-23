"""Game HUDs (hudedit.py): saving, versions, conflicts, uploads and cleaning."""

import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from hudbuilder import hudedit


class HudEditStore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_blank_until_saved(self):
        self.assertEqual(hudedit.load(self.dir, "val-scc2027")["rev"], 0)
        self.assertEqual(hudedit.load(self.dir, "val-scc2027")["rules"], {})

    def test_save_keeps_every_earlier_version(self):
        a = hudedit.save(self.dir, "lol-overlay:scc-2026", {"rules": {"#a": {"x": 10}}})
        b = hudedit.save(self.dir, "lol-overlay:scc-2026", {"rules": {"#a": {"x": 20}}}, base_rev=a["rev"])
        self.assertEqual(b["rev"], 2)
        self.assertEqual(hudedit.load(self.dir, "lol-overlay:scc-2026")["rules"]["#a"]["x"], 20)
        hist = hudedit.history(self.dir, "lol-overlay:scc-2026")
        self.assertEqual([v["version"] for v in hist], [1])
        back = hudedit.restore(self.dir, "lol-overlay:scc-2026", 1)
        self.assertEqual(back["rev"], 3)
        self.assertEqual(back["rules"]["#a"]["x"], 10)
        self.assertEqual([v["version"] for v in hudedit.history(self.dir, "lol-overlay:scc-2026")], [2, 1])

    def test_conflict(self):
        hudedit.save(self.dir, "cod-overlay", {})
        with self.assertRaises(hudedit.Conflict):
            hudedit.save(self.dir, "cod-overlay", {}, base_rev=0)

    def test_cleaning_keeps_css_safe(self):
        doc = hudedit.clean({"rules": {
            "#ok": {"x": 5, "color": "#ff0000", "font": "DIN 2014", "bogus": 1, "case": "upper"},
            "#bad{}": {"x": 1},
            "#evil": {"color": "red;} body{display:none", "font": "a\";}", "img": "../../x.png"},
        }, "added": [{"id": "abc", "type": "text", "text": "Hi", "x": 1}, {"id": "BAD!", "type": "box"}],
           "fonts": [{"family": "My Font", "file": "0123456789abcdef.ttf"}, {"family": "x", "file": "../a.ttf"}]})
        self.assertEqual(doc["rules"], {"#ok": {"x": 5.0, "color": "#ff0000", "font": "DIN 2014", "case": "upper"}})
        self.assertEqual([a["id"] for a in doc["added"]], ["abc"])
        self.assertEqual(len(doc["fonts"]), 1)

    def test_locks_kept(self):
        doc = hudedit.clean({"rules": {"#logo": {"lock": True}, "#x": {"lock": "yes"}},
                             "added": [{"id": "a1", "type": "text", "text": "Hi", "lock": True}]})
        self.assertEqual(doc["rules"], {"#logo": {"lock": True}})
        self.assertTrue(doc["added"][0]["lock"])

    def test_deleted_parts_and_shapes_kept(self):
        doc = hudedit.clean({"rules": {"#logo": {"del": True}, "#x": {"del": "yes"}},
            "added": [{"id": "s1", "type": "shape", "shape": "slant", "fill": "#ff0000", "fill2": "#0000ff", "angle": 45,
                       "stroke": "#fff", "strokeWidth": 2, "slant": -20, "x": 1, "y": 2, "w": 300, "h": 70},
                      {"id": "s2", "type": "shape", "shape": "hexagon<script>", "fill": "red;}"},
                      {"id": "t1", "type": "text", "text": "Hi", "italic": True, "shadow": True}]})
        self.assertEqual(doc["rules"], {"#logo": {"del": True}})
        s1, s2, t1 = doc["added"]
        self.assertEqual((s1["shape"], s1["fill2"], s1["slant"], s1["strokeWidth"]), ("slant", "#0000ff", -20.0, 2.0))
        self.assertNotIn("shape", s2)
        self.assertNotIn("fill", s2)
        self.assertTrue(t1["italic"] and t1["shadow"])

    def test_bad_design_names(self):
        for bad in ("../x", "", "A B", "x/y"):
            with self.assertRaises(ValueError):
                hudedit.save(self.dir, bad, {})

    def test_upload(self):
        name = hudedit.store_upload(self.dir, "logo.PNG", b"\x89PNG....")
        self.assertRegex(name, r"^[0-9a-f]{16}\.png$")
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "hud-edits", "assets", name)))
        with self.assertRaises(ValueError):
            hudedit.store_upload(self.dir, "x.exe", b"MZ")


class HudEditHttp(unittest.TestCase):
    """handle() on a real server, as each HUD app uses it."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        data_dir = cls.dir

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if not hudedit.handle(self, "GET", self.path.split("?")[0], data_dir):
                    self.send_error(404)

            def do_POST(self):
                if not hudedit.handle(self, "POST", self.path.split("?")[0], data_dir):
                    self.send_error(404)

        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def req(self, path, body=None):
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        r = urllib.request.Request(self.base + path, data=data, headers={"Content-Type": "text/plain"})
        try:
            with urllib.request.urlopen(r) as res:
                return res.status, res.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_round_trip(self):
        st, js = self.req("/hudedit.js")
        self.assertEqual(st, 200)
        self.assertIn(b"HudEdit", js)
        st, body = self.req("/hudedit/save", {"design": "rl-newgerrit", "edits": {"rules": {"#x": {"op": 0.5}}}, "base_rev": None})
        self.assertEqual(st, 200, body)
        rev = json.loads(body)["rev"]
        st, body = self.req(f"/hudedit/edits?design=rl-newgerrit&rev={rev}")
        self.assertEqual(json.loads(body), {"rev": rev, "same": True})
        st, body = self.req("/hudedit/edits?design=rl-newgerrit")
        self.assertEqual(json.loads(body)["rules"], {"#x": {"op": 0.5}})
        st, body = self.req("/hudedit/save", {"design": "rl-newgerrit", "edits": {}, "base_rev": 0})
        self.assertEqual(st, 409)
        st, body = self.req("/hudedit/upload?name=a.png", b"\x89PNGdata")
        name = json.loads(body)["name"]
        st, got = self.req("/hudedit/asset/" + name)
        self.assertEqual(got, b"\x89PNGdata")


class Catalog(unittest.TestCase):
    def test_every_game_and_design(self):
        games = {g["game"]: g for g in hudedit.catalog()}
        self.assertEqual(set(games), {"lol", "valorant", "cod", "rl", "smash", "overwatch"})
        keys = {d["key"] for g in games.values() for d in g["designs"]}
        for k in ("lol-overlay:scc-2026", "val-scc2027", "val-default2026-hud", "cod-overlay", "rl-newgerrit",
                  "rl-gerrit2026", "smash-scoreboard", "ow-overlay"):
            self.assertIn(k, keys)

    def test_pages_load_the_script_with_their_key(self):
        apps = os.path.join(os.path.dirname(__file__), "..", "..")
        if not os.path.isdir(os.path.join(apps, "valhud")):
            self.skipTest("not inside SCC Broadcast Engine")
        found = set()
        for root, _dirs, files in os.walk(apps):
            for f in files:
                if f.endswith(".html"):
                    with open(os.path.join(root, f), encoding="utf-8", errors="replace") as fh:
                        for m in __import__("re").finditer(r'src="/hudedit\.js" data-design="([^"]+)"', fh.read()):
                            found.add(m.group(1))
        for _g, key, *_ in hudedit.DESIGNS:
            self.assertIn(key, found)
        self.assertIn("lol-overlay", found)


if __name__ == "__main__":
    unittest.main()
