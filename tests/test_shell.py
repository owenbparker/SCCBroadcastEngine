"""SCC Broadcast Engine's own parts: the copies of each app in apps/, the
settings, and every part running together in one process."""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DATA = tempfile.mkdtemp(prefix="sccbe-test-")
os.environ["SCCBE_DATA"] = DATA

from sccbe import config, parts as P  # noqa: E402

P.add_to_path()


def get(url, timeout=8):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read())


class CopiesTests(unittest.TestCase):
    def test_every_part_is_in_apps(self):
        with open(os.path.join(ROOT, "apps", "SOURCES.json"), encoding="utf-8") as f:
            sources = json.load(f)
        for part in P.PARTS:
            self.assertIn(part.folder, sources)
            self.assertTrue(os.path.isdir(os.path.join(ROOT, "apps", part.folder, part.package)), part.folder)
            self.assertTrue(os.path.isdir(os.path.join(ROOT, "apps", part.folder, "web")), part.folder)

    def test_copies_keep_data_in_the_data_folder(self):
        for part in P.PARTS:
            path = os.path.join(ROOT, "apps", part.folder, part.package, "config.py")
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertIn(f'os.path.join(os.environ["SCCBE_DATA"], "{part.folder}")', text, part.folder)
            self.assertIn(f'"apps", "{part.folder}") if FROZEN', text, part.folder)

    def test_copies_dont_update_themselves(self):
        for part in P.PARTS:
            path = os.path.join(ROOT, "apps", part.folder, part.package, "updater.py")
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertRegex(text, r"def check\(self\):\n        return", part.folder)
            self.assertIn("self.can_install = False", text, part.folder)

    def test_data_folder_follows_the_app(self):
        import gfxengine.config
        self.assertEqual(gfxengine.config.DATA_DIR, os.path.join(DATA, "gfxengine"))

    def test_spec_lists_every_part(self):
        with open(os.path.join(ROOT, "SCCBroadcastEngine.spec"), encoding="utf-8") as f:
            spec = f.read()
        for part in P.PARTS:
            self.assertIn(f'("{part.folder}", "{part.package}"', spec)


class SettingsTests(unittest.TestCase):
    def test_control_pc_address(self):
        self.assertEqual(config.control_pc_url("192.168.2.40"), "http://192.168.2.40:8782")
        self.assertEqual(config.control_pc_url("192.168.2.40:9000"), "http://192.168.2.40:9000")
        self.assertEqual(config.control_pc_url("http://gfx-pc:8782/control#home"), "http://gfx-pc:8782")
        self.assertEqual(config.control_pc_url(""), "")
        with self.assertRaises(ValueError):
            config.control_pc_url("ftp://x")

    def test_settings_save_and_merge(self):
        path = os.path.join(DATA, "s", "settings.json")
        s = config.Settings(path)
        self.assertFalse(s.get()["setup_done"])
        s.update({"parts": {"lol": True}, "name": "SCC"})
        again = config.Settings(path).get()
        self.assertTrue(again["parts"]["lol"])
        self.assertTrue(again["parts"]["engine"])   # (the rest stay)
        self.assertEqual(again["name"], "SCC")

    def test_roles(self):
        from sccbe.app import Shell
        shell = Shell(config.Settings(os.path.join(DATA, "roles", "settings.json")))
        shell.windows = None
        for p in shell.parts:   # (nothing actually starts here)
            p.start = lambda windows=None, separate=False, p=p: setattr(p, "status", "on")
            p.stop = lambda p=p: setattr(p, "status", "off")
        try:
            shell.setup({"role": "hud", "parts": {"val": True}, "control_pc": "10.0.0.5"})
            s = shell.settings.get()
            self.assertTrue(s["setup_done"])
            self.assertFalse(s["parts"]["engine"])
            self.assertTrue(s["parts"]["val"])
            self.assertEqual(s["control_pc"], "http://10.0.0.5:8782")
            self.assertEqual(shell.engine_base(), ("http://10.0.0.5:8782", True))
        finally:
            for p in shell.parts:
                del p.start, p.stop
                p.status = "off"


class EverythingTogetherTests(unittest.TestCase):
    """Every part running at once in this process, each on its usual port."""

    @classmethod
    def setUpClass(cls):
        from sccbe.app import Shell, start
        cls.shell = Shell(config.Settings(os.path.join(DATA, "shell", "settings.json")))
        cls.port = start(cls.shell, 8769)
        post(f"http://127.0.0.1:{cls.port}/api/setup",
             {"role": "control", "parts": {k: True for k in P.BY_KEY}, "name": "Test"})
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline and any(p.status == "starting" for p in cls.shell.parts):
            time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.shell.stop()
        shutil.rmtree(DATA, ignore_errors=True)

    def test_every_part_runs(self):
        for part in self.shell.parts:
            self.assertEqual(part.status, "on", f"{part.title}: {part.error}")

    def test_every_part_serves_its_pages(self):
        pages = {"engine": ["/control", "/output"], "lol": ["/start", "/overlay"], "val": ["/start", "/overlay"],
                 "cod": ["/control", "/overlay"], "rl": ["/start", "/overlay"], "smash": ["/control"],
                 "ow": ["/control"], "builder": ["/"], "stream": ["/"]}
        for part in self.shell.parts:
            for path in pages[part.key]:
                status, body = get(f"http://127.0.0.1:{part.port}{path}")
                self.assertEqual(status, 200, f"{part.title} {path}")
                self.assertGreater(len(body), 200, f"{part.title} {path}")

    def test_usual_ports(self):
        ports = {p.key: p.port for p in self.shell.parts}
        self.assertEqual(ports, {"engine": 8782, "lol": 8777, "val": 8778, "cod": 8780, "rl": 8781,
                                 "smash": 8784, "ow": 8785, "builder": 8800, "stream": 8775})

    def test_each_part_keeps_its_data_in_its_folder(self):
        for part in self.shell.parts:
            self.assertTrue(os.path.isdir(os.path.join(DATA, part.folder)), part.folder)

    def test_shell_pages_and_state(self):
        for path in ("/", "/app.js", "/app.css", "/assets/logo.png", "/assets/games/lol.svg"):
            status, _ = get(f"http://127.0.0.1:{self.port}{path}")
            self.assertEqual(status, 200, path)
        self.shell._engine["data"] = None   # (the last look may be from before the engine started)
        status, body = get(f"http://127.0.0.1:{self.port}/api/state")
        s = json.loads(body)
        self.assertEqual(s["app"]["name"], "SCC Broadcast Engine")
        self.assertTrue(s["engine"]["ok"], s["engine"])
        self.assertEqual(s["engine"]["base"], "http://127.0.0.1:8782")
        self.assertIn("left", s["engine"]["match"])
        with self.assertRaises(urllib.error.HTTPError):
            get(f"http://127.0.0.1:{self.port}/../sccbe/config.py")

    def test_engine_pages_follow_the_address_tab(self):
        status, body = get("http://127.0.0.1:8782/control.js")
        self.assertIn(b'addEventListener("hashchange"', body)

    def test_switch_a_part_off_and_on(self):
        state = post(f"http://127.0.0.1:{self.port}/api/part", {"key": "ow", "on": False})
        self.assertFalse(state["settings"]["parts"]["ow"])
        deadline = time.monotonic() + 15
        while P.BY_KEY["ow"].status != "off" and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(P.BY_KEY["ow"].status, "off")
        with self.assertRaises(OSError):
            get("http://127.0.0.1:8785/control", timeout=2)
        post(f"http://127.0.0.1:{self.port}/api/part", {"key": "ow", "on": True})
        deadline = time.monotonic() + 30
        while P.BY_KEY["ow"].status != "on" and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(P.BY_KEY["ow"].status, "on", P.BY_KEY["ow"].error)
        status, _ = get("http://127.0.0.1:8785/control")
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
