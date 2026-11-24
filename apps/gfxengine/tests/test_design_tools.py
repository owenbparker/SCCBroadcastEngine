"""The Figma / Photoshop design tools' drawing (paths, masks, effects) is the
same in the GFX Engine's runtime.js and HUD Builder's, so a HUD Builder design
sent to the engine draws the same."""

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APPS = os.path.dirname(os.path.dirname(HERE))
START = "  // --- design tools: vector paths, flips, effects and masks"
END = "  GFX.clipMasks = clipMasks;"


def block(app):
    with open(os.path.join(APPS, app, "web", "runtime.js"), encoding="utf-8") as f:
        text = f.read()
    a = text.index(START)
    return text[a:text.index(END, a) + len(END)]


class DesignToolsTest(unittest.TestCase):
    def test_same_in_both_runtimes(self):
        self.assertEqual(block("gfxengine"), block("hudbuilder"))

    def test_runtimes_use_it(self):
        for app in ("gfxengine", "hudbuilder"):
            with open(os.path.join(APPS, app, "web", "runtime.js"), encoding="utf-8") as f:
                text = f.read()
            self.assertIn('if (t === "path") return pathBox(layer, value);', text)
            self.assertIn("design(layer, inner, content);", text)
            # (masks set after a graphic is built and after every update)
            self.assertEqual(len(re.findall(r"^    clipMasks\(root\);$", text, re.M)), 2)
            self.assertIn('layer.type === "rect" || layer.type === "path" ? layer.fill : layer.src', text)


if __name__ == "__main__":
    unittest.main()
