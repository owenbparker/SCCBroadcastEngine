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
