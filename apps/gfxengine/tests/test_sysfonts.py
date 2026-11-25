"""Fonts installed on this PC: read from their files, served only from the font folders."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from gfxengine import sysfonts

WEB_FONTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "fonts")


def _a_ttf():
    """A real TrueType / OpenType font to install (from the system, if any)."""
    for d in sysfonts.font_dirs():
        for folder, _, files in os.walk(d):
            for f in sorted(files):
                if f.lower().endswith((".ttf", ".otf")):
                    return os.path.join(folder, f)
    return None


class SystemFontsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fonts_dir = os.path.join(self.tmp, "Fonts")
        self.lib = os.path.join(self.tmp, "library")
        os.makedirs(self.fonts_dir)
        os.makedirs(self.lib)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_installed_fonts_are_listed_by_every_name_and_served(self):
        src = _a_ttf()
        if not src:
            self.skipTest("no TrueType font on this machine to install")
        shutil.copy(src, os.path.join(self.fonts_dir, "My Font.ttf"))
        with open(os.path.join(self.fonts_dir, "notes.txt"), "w") as f:
            f.write("not a font")
        with mock.patch.object(sysfonts, "font_dirs", return_value=[self.fonts_dir]), \
                mock.patch.object(sysfonts, "_registry_files", return_value=[]):
            sf = sysfonts.SystemFonts(self.lib)
            fonts = sf.fonts()
            self.assertEqual(len(fonts), 1)
            f = fonts[0]
            self.assertTrue(f["system"])
            self.assertTrue(f["family"] and f["postscript"])
            self.assertIn(f["postscript"], f["aliases"])
            self.assertIn(f["postscript"], f["local"])
            self.assertIn(f["weight"], range(100, 1000, 100))
            self.assertEqual(f["path"], "sysfonts/0/My Font.ttf")
            self.assertEqual(sf.file(f["path"]), os.path.join(self.fonts_dir, "My Font.ttf"))
            # Only the listed files: not other names, numbers or paths out of the folder.
            for bad in ["sysfonts/0/other.ttf", "sysfonts/1/My Font.ttf", "sysfonts/../../etc/passwd",
                        "sysfonts/x/My Font.ttf", "assets/My Font.ttf"]:
                self.assertIsNone(sf.file(bad), bad)
            names = sysfonts.known_names(fonts)
            self.assertIn(f["family"].lower(), names)
            self.assertIn(f["postscript"].lower(), names)
            # Read once: the names are kept in the library, by size and time.
            self.assertTrue(os.path.isfile(os.path.join(self.lib, sysfonts.CACHE_FILE)))
            with mock.patch.object(sysfonts, "read_faces", side_effect=AssertionError("read again")):
                self.assertEqual(sysfonts.SystemFonts(self.lib).fonts(), fonts)

    def test_a_font_installed_later_is_found(self):
        src = _a_ttf()
        if not src:
            self.skipTest("no TrueType font on this machine to install")
        with mock.patch.object(sysfonts, "font_dirs", return_value=[self.fonts_dir]), \
                mock.patch.object(sysfonts, "_registry_files", return_value=[]):
            sf = sysfonts.SystemFonts(self.lib)
            self.assertEqual(sf.fonts(), [])
            shutil.copy(src, os.path.join(self.fonts_dir, "New.ttf"))
            os.utime(self.fonts_dir, (1, 1))   # (the folder's time changes when a font is installed)
            self.assertEqual(len(sf.fonts()), 1)

    def test_broken_font_files_are_skipped(self):
        with open(os.path.join(self.fonts_dir, "broken.ttf"), "wb") as f:
            f.write(b"\x00\x01\x00\x00garbage")
        with mock.patch.object(sysfonts, "font_dirs", return_value=[self.fonts_dir]), \
                mock.patch.object(sysfonts, "_registry_files", return_value=[]):
            self.assertEqual(sysfonts.SystemFonts(self.lib).fonts(), [])


if __name__ == "__main__":
    unittest.main()
