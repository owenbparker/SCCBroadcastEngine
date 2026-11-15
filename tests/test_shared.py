"""One copy of shared code: every part's engine link is scc_shared's."""

import filecmp
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HUDS = ["codhud", "lolhud", "owhud", "rlhud", "smashhud", "valhud"]


class SharedCodeTests(unittest.TestCase):
    def test_every_hud_uses_the_one_engine_link(self):
        import importlib
        from scc_shared import enginelink
        for hud in HUDS:
            mod = importlib.import_module(f"{hud}.enginelink")
            self.assertIs(mod, enginelink, hud)

    def test_engine_link_pages_are_the_same_file(self):
        """The browser half (web/enginelink.js) is served by each HUD from its
        own web folder: each must be an exact copy of scc_shared's."""
        src = os.path.join(ROOT, "scc_shared", "enginelink.js")
        for hud in HUDS:
            copy = os.path.join(ROOT, "apps", hud, "web", "enginelink.js")
            self.assertTrue(filecmp.cmp(src, copy, shallow=False),
                            f"apps/{hud}/web/enginelink.js differs from scc_shared/enginelink.js: copy it over")


if __name__ == "__main__":
    unittest.main()
