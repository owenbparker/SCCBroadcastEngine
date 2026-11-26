"""The main window's own title bar (no Windows title bar): sccbe/winframe.py + web/winframe.js."""
import os
import unittest

from sccbe import winframe

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeWindow:
    def __init__(self):
        self.calls = []
        self.native = None

        class Ev:
            def __iadd__(s, fn):
                return s
        self.events = type("E", (), {"shown": Ev()})()

    def __getattr__(self, name):
        return lambda *a: self.calls.append((name, a))


class WinFrameTest(unittest.TestCase):
    def test_min_size(self):
        self.assertEqual(winframe.clamp_rect(10, 20, 500, 300, 1100, 680), (10, 20, 1100, 680))
        self.assertEqual(winframe.clamp_rect(10, 20, 1500, 900, 1100, 680), (10, 20, 1500, 900))

    def test_drag_out_of_maximised_keeps_cursor_on_bar(self):
        x, y, w, h = winframe.restore_rect_for_drag((300, 200, 1600, 940), 1000, 30, 0.5)
        self.assertEqual((x, w, h), (200, 1600, 940))
        self.assertLessEqual(y, 30)

    def test_only_win_methods_are_exposed(self):
        api = winframe.WindowApi()
        public = [n for n in dir(api) if not n.startswith("_")]
        self.assertTrue(public and all(n.startswith("win_") for n in public), public)

    def test_buttons_work_without_win32(self):
        api = winframe.WindowApi()
        w = FakeWindow()
        api._attach(w)
        api._hwnd = lambda: None
        self.assertTrue(api.win_state()["native"])
        self.assertTrue(api.win_toggle_max()["maximized"])
        self.assertFalse(api.win_toggle_max()["maximized"])
        api.win_minimize()
        api.win_close()
        self.assertEqual([c[0] for c in w.calls], ["maximize", "restore", "minimize", "destroy"])

    def test_page_has_the_capsule(self):
        with open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8") as f:
            html = f.read()
        self.assertIn('id="wincaps"', html)
        self.assertIn("winframe.js", html)
        self.assertTrue(os.path.exists(os.path.join(ROOT, "web", "winframe.js")))

    def test_window_is_frameless(self):
        with open(os.path.join(ROOT, "sccbe", "gui.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("frameless=True", src)
        self.assertIn("js_api=frame", src)


if __name__ == "__main__":
    unittest.main()


class SnapTests(unittest.TestCase):
    """Windows Snap: drags are handed to Windows' own move / size loop."""

    def test_hit_codes(self):
        self.assertEqual(winframe.hit_code("caption"), 2)
        self.assertEqual(winframe.hit_code(""), 2)
        self.assertEqual(winframe.hit_code("n"), 12)
        self.assertEqual(winframe.hit_code("se"), 17)
        self.assertEqual(winframe.hit_code("w"), 10)
        self.assertIsNone(winframe.hit_code("bogus"))

    def test_points_lparam_handles_monitors_left_of_main(self):
        lp = winframe.points_lparam(-100, 50)
        self.assertEqual(lp & 0xFFFF, (-100) & 0xFFFF)
        self.assertEqual(lp >> 16, 50)

    def test_snap_styles_include_frame_and_maximise_box(self):
        self.assertTrue(winframe.SNAP_STYLES & winframe.WS_THICKFRAME)
        self.assertTrue(winframe.SNAP_STYLES & winframe.WS_MAXIMIZEBOX)
        self.assertTrue(winframe.SNAP_STYLES & winframe.WS_CAPTION)

    def test_no_snap_without_win32_falls_back(self):
        api = winframe.WindowApi()
        api._attach(FakeWindow())
        api._hwnd = lambda: None
        self.assertFalse(api.win_state()["snap"])
        self.assertFalse(api.win_begin("caption"))

    def test_page_hands_drags_to_windows(self):
        with open(os.path.join(ROOT, "web", "winframe.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn('native("caption")', js)
        self.assertIn("native(edge)", js)
        self.assertIn('addEventListener("resize", syncState)', js)
