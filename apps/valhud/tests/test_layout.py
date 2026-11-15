"""Finding the game's picture (black bars on 16:10 and 4:3 screens), and the
reader's plain status line."""

import os
import unittest

from PIL import Image

from valhud import reader

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.shot = Image.open(os.path.join(FIX, "tab_scoreboard_rifles.png")).convert("RGB")
        self.plain = reader.read_frame(self.shot)

    def boxed(self, w, h):
        img = Image.new("RGB", (w, h))
        pic = self.shot.resize((w, round(w * 9 / 16)))
        img.paste(pic, (0, (h - pic.height) // 2))
        return img

    def test_no_bars_on_16_9(self):
        self.assertEqual(reader.letterbox(self.shot), (0, 0))

    def test_bars(self):
        self.assertEqual(reader.letterbox(self.boxed(1920, 1200)), (60, 60))
        self.assertEqual(reader.letterbox(self.boxed(1440, 1080)), (135, 135))
        got = reader.read_frame(self.boxed(1920, 1200))
        self.assertEqual([p.get("agent") for p in got["players"]], [p.get("agent") for p in self.plain["players"]])
        self.assertTrue(reader.in_match(reader.Frame(self.boxed(1920, 1200))))

    def test_dark_scene_isnt_bars(self):
        # A 16:10 picture with something on its top rows: no bars.
        img = self.boxed(1920, 1200)
        img.paste((90, 90, 90), (0, 0, 1920, 10))
        self.assertEqual(reader.letterbox(img), (0, 0))

    def test_status_line(self):
        r = reader.ScreenReader(lambda u: None)
        line = r._describe(reader.Frame(self.shot), {"match": {"score": {"left": 3, "right": 2},
                                                               "score_shape": {"left": 3, "right": 2}}, "players": []})
        self.assertIn("score 3-2 (digit shapes agree)", line)
        self.assertIn("Tab scoreboard closed", line)
        self.assertIn("digits learned: score 0/10", line)


if __name__ == "__main__":
    unittest.main()
