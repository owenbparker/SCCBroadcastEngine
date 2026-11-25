"""Text layers are outlined by their letters (TextInk), like Figma: the same
code in the Composer, HUD Builder and the Game HUDs editor (hudedit.js)."""

import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APPS = os.path.dirname(os.path.dirname(HERE))
START = "  // --- text ink ---"
END = "  // --- end text ink ---"


def read(*parts):
    with open(os.path.join(APPS, *parts), encoding="utf-8") as f:
        return f.read()


def block(text):
    a = text.index(START)
    return text[a:text.index(END, a) + len(END)]


class TextInkTest(unittest.TestCase):
    def test_same_file_in_both_apps(self):
        self.assertEqual(read("gfxengine", "web", "textink.js"), read("hudbuilder", "web", "textink.js"))

    def test_same_code_in_hudedit(self):
        self.assertEqual(block(read("gfxengine", "web", "textink.js")), block(read("hudbuilder", "web", "hudedit.js")))

    def test_pages_load_it_before_the_editor(self):
        for app, page, editor in (("gfxengine", "control.html", "composer.js"), ("hudbuilder", "app.html", "editor.js")):
            html = read(app, "web", page)
            self.assertIn("textink.js", html)
            self.assertLess(html.index("textink.js"), html.index(editor))

    def test_runtimes_dont_use_it(self):
        # (it only measures for the editors: what's drawn on air is unchanged)
        for app in ("gfxengine", "hudbuilder"):
            self.assertNotIn("TextInk", read(app, "web", "runtime.js"))


class TextSizingTest(unittest.TestCase):
    """Figma's Auto width / Auto height / Truncate: the same in both runtimes, and opt-in."""

    def sizing(self, app):
        text = read(app, "web", "runtime.js")
        a = text.index("  // --- text sizing:")
        return text[a:text.index("  // --- end text sizing ---", a)]

    def test_same_in_both_runtimes(self):
        self.assertEqual(self.sizing("gfxengine"), self.sizing("hudbuilder"))

    def test_only_layers_that_ask_for_it(self):
        block = self.sizing("gfxengine")
        self.assertIn('(layer.sizing !== "autoW" && layer.sizing !== "autoH")) return;', block)
        self.assertIn('layer.fit === "truncate"', block)


if __name__ == "__main__":
    unittest.main()
