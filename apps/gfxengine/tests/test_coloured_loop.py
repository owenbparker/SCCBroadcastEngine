"""The background loop coloured once by the engine (media.tint_loop / LoopBaker)
instead of live in every output."""

import os
import subprocess
import tempfile
import time
import unittest

from gfxengine import media


@unittest.skipUnless(media.ffmpeg_path(), "needs FFmpeg")
class ColouredLoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "loop.webm")
        # (a mid-grey clip: grey 128 * brightness 1.5 = 192, times the colour)
        subprocess.run([media.ffmpeg_path(), "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x808080:s=64x36:d=1:r=30",
                        "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", self.src], check=True)

    def pixel(self, path):
        raw = subprocess.run([media.ffmpeg_path(), "-loglevel", "error", "-i", path, "-frames:v", "1",
                              "-vf", "scale=in_color_matrix=bt709:in_range=tv", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, check=True).stdout
        mid = (18 * 64 + 32) * 3
        return tuple(raw[mid:mid + 3])

    def test_tint_matches_the_live_look(self):
        out = media.tint_loop(self.src, os.path.join(self.tmp, "out.mp4"), "#ff8000", 1.5)
        r, g, b = self.pixel(out)
        self.assertLess(abs(r - 192), 8)
        self.assertLess(abs(g - 96), 8)
        self.assertLess(b, 8)

    def test_baker_makes_it_once(self):
        done = []
        baker = media.LoopBaker(os.path.join(self.tmp, "cache"), on_done=lambda: done.append(1))
        self.assertEqual(baker.get(self.src, "#2fa85a", 1.6), {"pending": True})
        self.assertEqual(baker.get(self.src, "#2fa85a", 1.6), {"pending": True})   # (not twice)
        for _ in range(300):
            got = baker.get(self.src, "#2FA85A", 1.6)
            if "file" in got:
                break
            time.sleep(0.1)
        self.assertIn("file", got)
        self.assertTrue(baker.file(got["file"]))
        self.assertEqual(len(done), 1)
        self.assertIsNone(baker.file("../settings.json"))
        self.assertEqual(baker.get(self.src, "not a colour", 1.6), {"error": "Not a colour"})
        self.assertEqual(baker.get(os.path.join(self.tmp, "nope.webm"), "#fff", 1), {"error": "No such video"})


if __name__ == "__main__":
    unittest.main()
