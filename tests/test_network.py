"""Settings > Network: PCs on other networks (VLANs) are found, game HUDs are
opened to other PCs once, and Check another PC says what's in the way."""

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# (all the shell's tests run in one Python: another test module may have set this first)
if not os.environ.get("SCCBE_DATA"):
    os.environ["SCCBE_DATA"] = tempfile.mkdtemp(prefix="sccbe-net-test-")

from sccbe import config, parts as P  # noqa: E402

P.add_to_path()

from scc_shared import netpeers  # noqa: E402
from sccbe import network  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ParseTests(unittest.TestCase):
    def test_what_can_be_typed(self):
        self.assertEqual(netpeers.parse("10.230.2.0/24"), "10.230.2.0/24")
        self.assertEqual(netpeers.parse(" 10.230.2.77/24 "), "10.230.2.0/24")
        self.assertEqual(netpeers.parse("10.230.2.*"), "10.230.2.0/24")
        self.assertEqual(netpeers.parse("10.230.2.x"), "10.230.2.0/24")
        self.assertEqual(netpeers.parse("10.230.2.15"), "10.230.2.15")
        self.assertEqual(netpeers.parse("http://10.230.2.15:8782/control"), "10.230.2.15")
        self.assertEqual(netpeers.parse("10.230.2.15:8778"), "10.230.2.15")
        self.assertEqual(netpeers.parse("HUD-PC-3"), "HUD-PC-3")
        self.assertEqual(netpeers.parse("10.230.0.0/22"), "10.230.0.0/22")

    def test_what_is_refused(self):
        for bad in ("", "10.0.0.0/8", "10.230.0.0/16", "8.8.8.0/24", "not a pc!"):
            with self.assertRaises(ValueError, msg=bad):
                netpeers.parse(bad)


class CandidatesTests(unittest.TestCase):
    def tearDown(self):
        netpeers.use(None)

    def test_own_network_then_saved_ones(self):
        netpeers.use(["10.230.2.0/24", "10.230.9.15", "127.0.0.1"])
        c = netpeers.candidates(["10.230.5.138"])
        self.assertIn("10.230.5.1", c)            # this PC's own /24
        self.assertNotIn("10.230.5.138", c)       # not itself
        self.assertIn("10.230.2.1", c)            # the other VLAN
        self.assertIn("10.230.2.254", c)
        self.assertIn("10.230.9.15", c)           # a single PC
        self.assertIn("127.0.0.1", c)
        self.assertEqual(len(c), len(set(c)))
        self.assertLess(c.index("10.230.5.1"), c.index("10.230.2.1"))

    def test_saved_in_the_shell_settings(self):
        path = netpeers.settings_path()   # (where every part reads them)
        backup = open(path, "rb").read() if os.path.exists(path) else None
        self.addCleanup(lambda: _put_back(path, backup))
        s = config.Settings(path)
        network.add_other(s, "10.230.2.x")
        network.add_other(s, "10.230.2.0/24")    # (not twice)
        network.add_other(s, "STREAM-PC")
        self.assertEqual(s.get()["other_networks"], ["10.230.2.0/24", "STREAM-PC"])
        self.assertEqual(netpeers.entries(), ["10.230.2.0/24", "STREAM-PC"])   # (what every part reads)
        network.remove_other(s, "STREAM-PC")
        self.assertEqual(netpeers.entries(), ["10.230.2.0/24"])
        with self.assertRaises(ValueError):
            network.add_other(s, "10.0.0.0/8")

    def test_every_scan_looks_at_the_saved_networks(self):
        """HUD -> engine, engine -> engines, observer -> GFX PC, run of show: one list."""
        import inspect
        from gfxengine import discover as gd
        from valhud import discover as vd
        from lolhud import discover as ld
        from rlhud import discover as rd
        from scc_shared import enginelink
        from sccbe import rosnet
        for fn in (gd.scan, vd.find_huds, ld.find_huds, rd.find_huds, enginelink.scan, rosnet.find):
            self.assertIn("netpeers.candidates", inspect.getsource(fn), fn.__module__)

    def test_a_saved_pc_is_found(self):
        """An engine at an address only the saved list has (127.0.0.1 standing in for another VLAN)."""
        from valhud import discover as vd
        port = free_port()

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps({"app": {"role": "gfx"}}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            netpeers.use([])
            self.assertEqual(vd.find_huds(port, lambda s: True, addresses=["192.0.2.10"]), [])
            netpeers.use(["127.0.0.1"])
            found = vd.find_huds(port, lambda s: True, addresses=["192.0.2.10"])
            self.assertEqual([f["ip"] for f in found], ["127.0.0.1"])
        finally:
            httpd.shutdown()
            httpd.server_close()


class ProbeTests(unittest.TestCase):
    def test_open_and_refused(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen()
            self.assertEqual(netpeers.probe("127.0.0.1", s.getsockname()[1])["state"], "open")
        self.assertEqual(netpeers.probe("127.0.0.1", free_port())["state"], "refused")

    def test_unknown_name(self):
        self.assertEqual(netpeers.probe("no-such-pc.invalid", 80, timeout=0.5)["state"], "noname")

    def test_check_another_pc_says_what_is_wrong(self):
        r = network.check("127.0.0.1")
        self.assertEqual(len(r["results"]), len(network.PORTS))
        self.assertIn(r["verdict"], ("ok", "not_running", "partly", "blocked"))
        self.assertTrue(r["summary"])
        with self.assertRaises(ValueError):
            network.check("10.230.2.0/24")

    def test_ports_for_it(self):
        text = network.ports_text()
        for p in (8771, 8782, 8778, 8788, 8783):
            self.assertIn(str(p), text)


class OpenOnceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sccbe-net-open-")
        self.s = config.Settings(os.path.join(self.tmp, "settings.json"))
        self.folder = os.path.join(self.tmp, "valhud")
        self._data = network.DATA_DIR
        network.DATA_DIR = self.tmp
        os.makedirs(self.folder, exist_ok=True)
        self.path = os.path.join(self.folder, "config.json")

    def tearDown(self):
        network.DATA_DIR = self._data
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_game_hud_is_opened_once_keeping_its_settings(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"allow_network": False, "left": {"name": "SCC"}, "http_port": 8778}, f)
        val = P.BY_KEY["val"]
        self.assertTrue(network.open_once(self.s, val))
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data, {"allow_network": True, "left": {"name": "SCC"}, "http_port": 8778})
        # Switched back to this PC only: it stays that way.
        data["allow_network"] = False
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        self.assertFalse(network.open_once(self.s, val))
        with open(self.path, encoding="utf-8") as f:
            self.assertFalse(json.load(f)["allow_network"])
        self.assertEqual(self.s.get()["network_opened"], ["val"])

    def test_not_the_engine_or_tools_and_a_broken_file_is_left_alone(self):
        self.assertFalse(network.open_once(self.s, P.BY_KEY["engine"]))
        self.assertFalse(network.open_once(self.s, P.BY_KEY["builder"]))
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{broken")
        self.assertFalse(network.open_once(self.s, P.BY_KEY["val"]))
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "{broken")

    def test_a_new_hud_gets_it_too(self):
        self.assertTrue(network.open_once(self.s, P.BY_KEY["val"]))
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"allow_network": True})
        from valhud.config import Config
        self.assertTrue(Config(self.path).get()["allow_network"])


def _put_back(path, data):
    if data is None:
        if os.path.exists(path):
            os.remove(path)
    else:
        with open(path, "wb") as f:
            f.write(data)


if __name__ == "__main__":
    unittest.main()
