"""Digits by shape (glyphbank.py): learned from the text recognition's
readings, then read without it."""

import os
import tempfile
import unittest

from PIL import Image, ImageDraw, ImageFont

from valhud.config import WEB_DIR
from valhud.glyphbank import GlyphBank, pieces


def cell(text, size=34, w=60, h=44, shift=0):
    """White digits on the game's dark bar, as the top bar's score box."""
    font = ImageFont.truetype(os.path.join(WEB_DIR, "fonts", "Inter.ttf"), size)
    img = Image.new("RGB", (w, h), (18, 22, 30))
    ImageDraw.Draw(img).text((w // 2 + shift, h // 2), text, fill=(240, 240, 240), font=font, anchor="mm")
    return img


class GlyphBankTests(unittest.TestCase):
    def test_learns_then_reads(self):
        bank = GlyphBank()
        self.assertIsNone(bank.read("score", cell("7")))   # (knows nothing yet)
        # The text recognition reads each the same twice running: learned.
        for n in range(10):
            self.assertFalse(bank.offer("score", "left", cell(str(n)), n))
            self.assertTrue(bank.offer("score", "left", cell(str(n)), n))
        self.assertEqual(bank.known("score"), list("0123456789"))
        for n in (0, 1, 7, 10, 12, 13, 21):
            self.assertEqual(bank.read("score", cell(str(n), shift=2)), n)
        self.assertIsNone(bank.read("kda", cell("7")))   # (another kind of cell: its own digits)

    def test_turns_away_misreads(self):
        bank = GlyphBank()
        for n in range(10):
            bank.learn("score", cell(str(n)), str(n))
        # "12" read as "1": two pieces, one digit: not learned from.
        self.assertFalse(bank.learn("score", cell("12"), "1"))
        # An 8 read as 3: it looks like the 8 already known, so it isn't kept as a 3.
        self.assertFalse(bank.learn("score", cell("8", size=30), "3"))
        self.assertGreaterEqual(bank.clashes, 1)
        self.assertEqual(bank.read("score", cell("8", size=30)), 8)

    def test_kept_between_runs(self):
        path = os.path.join(tempfile.mkdtemp(), "glyphs.json")
        bank = GlyphBank(path)
        for n in range(10):
            bank.learn("score", cell(str(n)), str(n))
        bank.save()
        again = GlyphBank(path)
        self.assertEqual(again.read("score", cell("19")), 19)

    def test_real_scoreboard(self):
        """The Tab scoreboard at the start of a match (everyone 0/0/0): two
        rows' zeros learned, every row read by shape, and the score too."""
        from valhud import reader
        img = Image.open(os.path.join(os.path.dirname(__file__), "fixtures", "tab_scoreboard.png")).convert("RGB")
        frame = reader.Frame(img)
        bank = GlyphBank()
        for side in ("left", "right"):
            for col in "kda":
                bank.learn("kda", reader.row_cell(frame, side, 0, col, 3), "0")
            bank.learn("score", frame.crop(*reader.SCORE_BOX[side]), "0", 170)
        update = reader.read_frame(img, None, bank=bank)
        self.assertEqual([p.get("kda_shape") for p in update["players"]], [[0, 0, 0]] * 10)
        self.assertEqual(update["match"]["score_shape"], {"left": 0, "right": 0})
        reader._drop_shadow_fields(update)
        self.assertNotIn("score_shape", update["match"])

    def test_pieces(self):
        self.assertEqual(len(pieces(cell("13"))), 2)
        self.assertEqual(pieces(Image.new("RGB", (40, 40))), [])


if __name__ == "__main__":
    unittest.main()
