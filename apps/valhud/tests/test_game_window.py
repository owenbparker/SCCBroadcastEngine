"""Which window the reader reads: VALORANT on any screen, or the one picked
under Live Game > Game window (reader.PICK / _find_window), in real pixels
whatever the display scaling (scc_shared/dpi.py)."""

import json
import os
import sys
import tempfile
import unittest
import urllib.request

from valhud import reader


def win(title, exe="", w=1920, h=1080, screen=1, valorant=None, minimised=False):
    return {"hwnd": hash((title, exe, w)), "title": title, "exe": exe, "width": w, "height": h, "x": 0, "y": 0,
            "screen": screen, "minimised": minimised,
            "valorant": valorant if valorant is not None else (exe.lower() == reader.VALORANT_EXE or title == "VALORANT")}


class FindWindowTests(unittest.TestCase):
    def setUp(self):
        self._real = reader.game_windows
        reader.set_pick({})

    def tearDown(self):
        reader.game_windows = self._real
        reader.set_pick({})

    def use(self, *wins):
        reader.game_windows = lambda: list(wins)
        reader._found.update(key=None, win=None, at=0.0)   # (looked for again)

    def test_finds_valorant_by_its_program_on_any_screen(self):
        self.use(win("Google Chrome", "chrome.exe", 2560, 1440, 1),
                 win("VALORANT  ", "VALORANT-Win64-Shipping.exe", 3840, 2160, 3))
        found, reason = reader._find_window()
        self.assertIsNone(reason)
        self.assertEqual(found["screen"], 3)

    def test_biggest_valorant_window_beats_a_small_helper(self):
        self.use(win("VALORANT", "VALORANT-Win64-Shipping.exe", 300, 200, 1),
                 win("VALORANT", "VALORANT-Win64-Shipping.exe", 3840, 2160, 3))
        self.assertEqual(reader._find_window()[0]["width"], 3840)

    def test_not_found_says_where_to_pick_it(self):
        self.use(win("Google Chrome", "chrome.exe"))
        found, reason = reader._find_window()
        self.assertIsNone(found)
        self.assertIn("Game window", reason)

    def test_picked_window_is_read_even_if_not_valorant(self):
        self.use(win("VALORANT", "VALORANT-Win64-Shipping.exe", 1920, 1080, 1),
                 win("Observer feed", "obs64.exe", 1920, 1080, 2))
        reader.set_pick({"title": "Observer feed", "exe": "obs64.exe"})
        self.assertEqual(reader._find_window()[0]["exe"], "obs64.exe")

    def test_picked_window_closed_says_so(self):
        self.use(win("VALORANT", "VALORANT-Win64-Shipping.exe"))
        reader.set_pick({"title": "Observer feed", "exe": "obs64.exe"})
        found, reason = reader._find_window()
        self.assertIsNone(found)
        self.assertIn("Observer feed", reason)

    def test_pick_survives_a_changed_title_tail(self):
        self.use(win("VALORANT - spectating", "VALORANT-Win64-Shipping.exe"))
        reader.set_pick({"title": "VALORANT", "exe": "other.exe"})
        self.assertIsNotNone(reader._find_window()[0])


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class RealPixelsTests(unittest.TestCase):
    def test_thread_is_per_monitor_aware_inside_even_after_pywebview(self):
        import ctypes
        from scc_shared import dpi
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()   # what pywebview does at start
        user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        with dpi.real_pixels():
            inside = user32.GetAwarenessFromDpiAwarenessContext(user32.GetThreadDpiAwarenessContext())
        self.assertEqual(inside, 2)   # DPI_AWARENESS_PER_MONITOR_AWARE
        self.assertGreaterEqual(len(dpi.monitors()), 1)

    def test_lists_windows_and_reports_valorant_missing(self):
        wins = reader.game_windows()
        self.assertIsInstance(wins, list)
        image, reason = reader.capture_valorant()
        self.assertIsNone(image)
        self.assertIn("VALORANT", reason)


class WindowsApiTests(unittest.TestCase):
    def test_lists_windows_and_saves_the_pick(self):
        from valhud.app import HudApp, start
        from valhud.config import Config
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(os.path.join(tmp, "config.json"))
            cfg.update({"http_port": 8794, "output_dir": os.path.join(tmp, "out")})
            app = HudApp(cfg)
            app.updater.check_in_background = lambda: None
            start(app)
            try:
                base = "http://127.0.0.1:8794"
                with urllib.request.urlopen(base + "/api/reader/windows", timeout=5) as r:
                    data = json.loads(r.read())
                self.assertIn("windows", data)
                self.assertIn("screens", data)
                req = urllib.request.Request(base + "/api/config", method="POST",
                                             data=json.dumps({"capture": {"title": "", "exe": "", "screen": 3}}).encode(),
                                             headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5).read()
                self.assertEqual(reader.PICK["screen"], 3)
                self.assertEqual(cfg.get()["capture"]["screen"], 3)
            finally:
                app.stop()
                reader.set_pick({})


if __name__ == "__main__":
    unittest.main()


class KeptWindowTests(unittest.TestCase):
    """The window found is kept for a moment (going through every window on
    the PC for each of twenty captures a second was slow): only checked."""

    def setUp(self):
        self._real = (reader.game_windows, reader._window_now)
        reader.set_pick({})
        reader._found.update(key=None, win=None, at=0.0)

    def tearDown(self):
        reader.game_windows, reader._window_now = self._real
        reader._found.update(key=None, win=None, at=0.0)

    def test_looks_once_then_checks(self):
        looks = []
        reader.game_windows = lambda: looks.append(1) or [win("VALORANT", "VALORANT-Win64-Shipping.exe")]
        reader._window_now = lambda w: dict(w, x=5)
        for _ in range(5):
            found, _ = reader._find_window()
        self.assertEqual(len(looks), 1)
        self.assertEqual(found["x"], 5)

    def test_looks_again_when_gone_or_another_is_picked(self):
        looks = []
        reader.game_windows = lambda: looks.append(1) or [win("VALORANT", "VALORANT-Win64-Shipping.exe"),
                                                          win("OBS", "obs64.exe")]
        reader._window_now = lambda w: None   # (closed)
        reader._find_window()
        reader._find_window()
        self.assertEqual(len(looks), 2)
        reader._window_now = lambda w: w
        reader.set_pick({"title": "OBS", "exe": "obs64.exe"})
        self.assertEqual(reader._find_window()[0]["exe"], "obs64.exe")
        self.assertEqual(len(looks), 3)

    def test_not_open_is_kept_for_a_moment_too(self):
        looks = []
        reader.game_windows = lambda: looks.append(1) or []
        for _ in range(3):
            found, reason = reader._find_window()
        self.assertIsNone(found)
        self.assertIn("not found", reason)
        self.assertEqual(len(looks), 1)


@unittest.skipUnless(sys.platform == "win32", "Windows screen copy")
class AreaGrabTests(unittest.TestCase):
    def test_same_as_imagegrab(self):
        from PIL import ImageChops, ImageGrab
        from scc_shared import dpi
        with dpi.real_pixels():
            l, t, r, b = dpi.monitors()[0]
            box = (l + 10, t + 20, min(r, l + 410), min(b, t + 320))
            mine = reader._gdi_grab(box)
            theirs = ImageGrab.grab(box, all_screens=True)
        self.assertIsNotNone(mine)
        self.assertEqual(mine.size, theirs.size)
        self.assertEqual(mine.mode, "RGB")
        # (the screen can change between the two copies: nearly all the same)
        diff = ImageChops.difference(mine, theirs).convert("L")
        same = sum(1 for v in diff.getdata() if v < 8) / (mine.width * mine.height)
        self.assertGreater(same, 0.95)
