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

    def test_shipped_sakura_recolour_only_touches_the_sakura_copy(self):
        d = self.dir
        sak = hudedit.make_copy(d, "val-scc2027", "/scc2027/index.html", "Sakura Class Broadcast HUD Val")
        other = hudedit.make_copy(d, "val-scc2027", "/scc2027/index.html", "Other look")
        key = hudedit.copy_key("val-scc2027", sak["id"])
        cur = hudedit.load(d, key)
        hudedit.save(d, key, {"rules": {"#event": {"x": 5, "bg": "#000"}, "#keep": {"op": 0.5}}}, cur["rev"])
        done = hudedit.apply_presets(d)
        self.assertEqual(done, [("sakura-val-2026-11-24", sak["id"])])
        rules = hudedit.load(d, key)["rules"]
        self.assertEqual(rules["#event"], {"x": 5.0, "bg": "#4A1F36"})       # its own change kept, colour set
        self.assertEqual(rules["#keep"], {"op": 0.5})
        self.assertEqual(rules["#rwin > div:nth-of-type(6)"], {"color": "#FFF7FA"})
        pic = rules["#board > div:nth-of-type(1)"]["img"]
        self.assertTrue(os.path.isfile(os.path.join(hudedit.folder(d), "assets", pic)))
        self.assertTrue(pic.endswith(".svg"))
        # SCC 2027 itself and the other copy untouched; the earlier version kept
        self.assertFalse(os.path.exists(hudedit._path(d, "val-scc2027")))
        self.assertEqual(hudedit.load(d, hudedit.copy_key("val-scc2027", other["id"]))["rules"], {})
        self.assertTrue(hudedit.history(d, key))
        # only once: a later change by hand stays
        rev = hudedit.load(d, key)["rev"]
        self.assertEqual(hudedit.apply_presets(d), [])
        self.assertEqual(hudedit.load(d, key)["rev"], rev)

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

    def test_copies(self):
        st, body = self.req("/hudedit/copies", {"action": "make", "base": "rl-classic", "path": "/overlay-classic", "name": "Copy"})
        self.assertEqual(st, 200, body)
        cid = json.loads(body)["copy"]["id"]
        st, body = self.req("/hudedit/copies")
        self.assertIn(cid, [c["id"] for c in json.loads(body)["copies"]])
        st, body = self.req("/hudedit/copies", {"action": "delete", "id": cid, "confirm": "nope"})
        self.assertEqual(st, 400)
        st, body = self.req("/hudedit/copies", {"action": "rename", "id": "00000000", "name": "x"})
        self.assertEqual(st, 404)
        # live: the edits a page gets on air follow the live copy; /overlay follows a My HUD
        self.req("/hudedit/copies", {"action": "live", "base": "rl-classic", "id": cid})
        st, body = self.req("/hudedit/edits?design=rl-classic&live=1")
        doc = json.loads(body)
        self.assertEqual(doc["served"], "rl-classic.c" + cid)
        st, body = self.req(f"/hudedit/edits?design=rl-classic&live=1&rev={doc['rev']}&served=rl-classic")
        self.assertNotIn("same", json.loads(body))   # (another version than the page has)
        st, js = self.req("/hudedit/picker.js")
        self.assertIn(b"HudPicker", js)
        self.req("/hudedit/copies", {"action": "live", "custom": {"src": "builder", "id": "habcdef1234", "port": 8800}})

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        with self.assertRaises(urllib.error.HTTPError) as e:
            opener.open(self.base + "/overlay")
        self.assertEqual(e.exception.code, 302)
        self.assertTrue(e.exception.headers["Location"].endswith(":8800/hud/habcdef1234"))
        self.req("/hudedit/copies", {"action": "live", "custom": None})


class Copies(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_copy_starts_from_the_original_and_is_its_own(self):
        hudedit.save(self.dir, "val-scc2027", {"rules": {"#a": {"x": 10}}, "settings": {"top.mode": "full"}})
        c = hudedit.make_copy(self.dir, "val-scc2027", "/overlay?design=scc2027", "Finals")
        key = hudedit.copy_key("val-scc2027", c["id"])
        self.assertEqual(key, "val-scc2027.c" + c["id"])
        self.assertEqual(hudedit.load(self.dir, key)["rules"], {"#a": {"x": 10.0}})
        hudedit.save(self.dir, key, {"rules": {"#a": {"x": 99}}})
        self.assertEqual(hudedit.load(self.dir, "val-scc2027")["rules"]["#a"]["x"], 10)
        # a copy of the copy starts from the copy's changes
        c2 = hudedit.make_copy(self.dir, "val-scc2027", "/overlay?design=scc2027", "Finals 2", c["id"])
        self.assertEqual(hudedit.load(self.dir, hudedit.copy_key("val-scc2027", c2["id"]))["rules"]["#a"]["x"], 99)
        hudedit.rename_copy(self.dir, c["id"], "  Grand   final ")
        self.assertEqual([x["name"] for x in hudedit.list_copies(self.dir)], ["Grand final", "Finals 2"])
        # use on the original: the original's old changes stay in its versions
        hudedit.apply_copy(self.dir, c["id"])
        self.assertEqual(hudedit.load(self.dir, "val-scc2027")["rules"]["#a"]["x"], 99)
        self.assertEqual(len(hudedit.history(self.dir, "val-scc2027")), 1)

    def test_league_profile_keys(self):
        c = hudedit.make_copy(self.dir, "lol-overlay:scc-2026", "/overlay?profile=scc-2026", "B")
        hudedit.save(self.dir, hudedit.copy_key("lol-overlay:scc-2026", c["id"]), {})
        self.assertTrue(os.path.exists(os.path.join(self.dir, "hud-edits", f"lol-overlay~scc-2026.c{c['id']}.json")))

    def test_delete_needs_the_name_and_keeps_it(self):
        c = hudedit.make_copy(self.dir, "cod-overlay", "/overlay", "Side B")
        key = hudedit.copy_key("cod-overlay", c["id"])
        hudedit.save(self.dir, key, {"rules": {"#b": {"op": 0.5}}})   # (rev 2: one version kept)
        with self.assertRaises(ValueError):
            hudedit.delete_copy(self.dir, c["id"], "side")
        hudedit.delete_copy(self.dir, c["id"], "side b")
        self.assertEqual(hudedit.list_copies(self.dir), [])
        self.assertEqual(hudedit.load(self.dir, key)["rev"], 0)
        gone = hudedit.deleted_copies(self.dir)
        self.assertEqual([g["name"] for g in gone], ["Side B"])
        hudedit.undelete_copy(self.dir, gone[0]["tid"])
        self.assertEqual([x["name"] for x in hudedit.list_copies(self.dir)], ["Side B"])
        self.assertEqual(hudedit.load(self.dir, key)["rules"], {"#b": {"op": 0.5}})
        self.assertEqual(len(hudedit.history(self.dir, key)), 1)
        self.assertEqual(hudedit.deleted_copies(self.dir), [])

    def test_live_copy_and_custom(self):
        hudedit.save(self.dir, "val-scc2027", {"rules": {"#a": {"x": 1}}})
        c = hudedit.make_copy(self.dir, "val-scc2027", "/overlay?design=scc2027", "Sakura")
        hudedit.save(self.dir, hudedit.copy_key("val-scc2027", c["id"]), {"rules": {"#a": {"x": 2}}})
        doc, served = hudedit.live_edits(self.dir, "val-scc2027")
        self.assertEqual((doc["rules"]["#a"]["x"], served), (1, "val-scc2027"))
        hudedit.set_live(self.dir, {"base": "val-scc2027", "id": c["id"]})
        doc, served = hudedit.live_edits(self.dir, "val-scc2027")
        self.assertEqual((doc["rules"]["#a"]["x"], served), (2, hudedit.copy_key("val-scc2027", c["id"])))
        # a My HUD on /overlay, then back to a design (which clears it)
        live = hudedit.set_live(self.dir, {"custom": {"src": "builder", "id": "h0123456789", "name": "Mine", "port": 8800}})
        self.assertEqual(live["custom"]["id"], "h0123456789")
        self.assertEqual(live["active"], {"val-scc2027": c["id"]})
        live = hudedit.set_live(self.dir, {"base": "val-scc2027", "id": ""})
        self.assertEqual((live["custom"], live["active"]), (None, {}))
        with self.assertRaises(ValueError):
            hudedit.set_live(self.dir, {"custom": {"src": "web", "id": "x", "port": 1}})
        # deleting a live copy puts the original back on air
        hudedit.set_live(self.dir, {"base": "val-scc2027", "id": c["id"]})
        hudedit.delete_copy(self.dir, c["id"], "Sakura")
        self.assertEqual(hudedit.live_edits(self.dir, "val-scc2027")[1], "val-scc2027")
        gone = hudedit.deleted_copies(self.dir)[0]
        hudedit.undelete_copy(self.dir, gone["tid"])
        self.assertEqual(hudedit.get_live(self.dir)["active"], {})

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            hudedit.make_copy(self.dir, "BAD KEY", "/overlay", "x")
        with self.assertRaises(ValueError):
            hudedit.make_copy(self.dir, "cod-overlay", "javascript:alert(1)", "x")
        with self.assertRaises(KeyError):
            hudedit.rename_copy(self.dir, "deadbeef", "x")
        with self.assertRaises(KeyError):
            hudedit.undelete_copy(self.dir, "../x")


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
