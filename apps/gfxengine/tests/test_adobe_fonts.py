import json
import os
import shutil
import tempfile
import unittest
import urllib.request
from unittest import mock

from gfxengine import adobefonts

ENTITLEMENTS = """<?xml version="1.0" encoding="utf-8"?>
<typekitSyncState>
  <fonts>
    <font><url>https://use.typekit.net/x</url><id>48850</id>
      <properties><fullName>DIN 2014 Bold</fullName><familyName>DIN 2014</familyName><variationName>Bold</variationName>
        <installState>OS</installState></properties></font>
    <font><id>48851</id>
      <properties><fullName>DIN 2014 Light Italic</fullName><familyName>DIN 2014</familyName><variationName>Light Italic</variationName></properties></font>
    <font><id>48852</id>
      <properties><fullName>Gone Regular</fullName><familyName>Gone</familyName><variationName>Regular</variationName>
        <installState>uninstalled</installState></properties></font>
  </fonts>
</typekitSyncState>"""

KIT_CSS = """/*
 * The Typekit service used to deliver this font or fonts for use on websites
 * is provided by Adobe and is subject to these Terms of Use
 * http://www.adobe.com/products/eulas/tou_typekit. For font license
 * information, see the list below.
 *
 * din-2014:
 *   - http://typekit.com/eulas/00000000000000003b9b0f3a
 * tungsten:
 *   - http://typekit.com/eulas/00000000000000007735a0a5
 *
 * © 2009-2026 Adobe Systems Incorporated. All Rights Reserved.
 */
/*{"last_published":"2026-11-23 10:00:00 UTC"}*/

@import url("https://p.typekit.net/p.css?s=1&k=abc1234&ht=tk&f=1&a=2&app=typekit&e=css");

@font-face {
font-family:"din-2014";
src:url("https://use.typekit.net/af/1/l?primer=x&fvd=n7&v=3") format("woff2"),url("https://use.typekit.net/af/1/d?primer=x&fvd=n7&v=3") format("woff");
font-display:auto;font-style:normal;font-weight:700;font-stretch:normal;
}

@font-face {
font-family:"din-2014";
src:url("https://use.typekit.net/af/2/l?fvd=i3&v=3") format("woff2");
font-display:auto;font-style:italic;font-weight:300;font-stretch:normal;
}

@font-face {
font-family:"tungsten";
src:url("https://use.typekit.net/af/3/l?fvd=n6&v=3") format("woff2");
font-display:auto;font-style:normal;font-weight:600;font-stretch:normal;
}

.tk-din-2014 { font-family: "din-2014",sans-serif; }
.tk-tungsten { font-family: "tungsten",sans-serif; }
"""


def names(fonts):
    return {adobefonts.norm(a) for f in fonts for a in f["aliases"]}


class AdobeFontsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        adobefonts._pc_cache.update(key=None, fonts=[])

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_creative_cloud_list(self):
        fonts = adobefonts.parse_entitlements(ENTITLEMENTS)
        self.assertEqual([f["postscript"] for f in fonts], ["DIN2014-Bold", "DIN2014-LightItalic"])   # (not the uninstalled one)
        bold, light = fonts
        self.assertEqual((bold["weight"], bold["italic"], bold["adobe"], bold["path"]), (700, False, "pc", ""))
        self.assertEqual((light["weight"], light["italic"]), (300, True))
        self.assertIn("DIN 2014 Bold", bold["local"])    # (the browser finds the installed font by name)
        self.assertIn("din2014bold", names([bold]))
        self.assertEqual(adobefonts.parse_entitlements("not xml"), [])

    def test_kit_ids(self):
        self.assertEqual(adobefonts.kit_id("abc1234"), "abc1234")
        self.assertEqual(adobefonts.kit_id('<link rel="stylesheet" href="https://use.typekit.net/xyz9876.css">'), "xyz9876")
        self.assertEqual(adobefonts.kit_id('@import url("https://use.typekit.net/xyz9876.css");'), "xyz9876")
        self.assertEqual(adobefonts.kit_id("Typekit.load({ kitId: 'qwe4567' })"), "qwe4567")
        self.assertEqual(adobefonts.kit_id("not a kit at all"), "")

    def test_kit_saved_and_listed(self):
        kit = adobefonts.Kit(self.dir)
        seen = []
        fetch = lambda url: seen.append(url) or KIT_CSS
        data = kit.set('<link rel="stylesheet" href="https://use.typekit.net/abc1234.css">', fetch)
        self.assertEqual(seen, ["https://use.typekit.net/abc1234.css"])
        self.assertEqual(data["id"], "abc1234")
        self.assertEqual(len(data["faces"]), 3)
        fonts = kit.fonts()
        by = {f["kit"]["family"] + str(f["weight"]): f for f in fonts}
        bold = by["din-2014700"]
        self.assertEqual(bold["kit"], {"id": "abc1234", "family": "din-2014", "weight": 700, "style": "normal"})
        # What a .fig / .psd records for it (family + style, or a PostScript name)
        for name in ("DIN2014-Bold", "DIN 2014 Bold", "din-2014-bold"):
            self.assertIn(adobefonts.norm(name), names([bold]))
        self.assertIn("din2014lightitalic", names([by["din-2014300"]]))
        self.assertIn("tungstensemibold", names([by["tungsten600"]]))
        self.assertNotIn("din2014", names([bold]))       # (the bare family is the Regular)
        # Saved for every workspace, and removed again
        self.assertEqual(adobefonts.Kit(self.dir).get()["id"], "abc1234")
        kit.set("")
        self.assertEqual(kit.fonts(), [])
        with self.assertRaises(ValueError):
            kit.set("nope nope")
        with self.assertRaises(ValueError):
            kit.set("abc1234", lambda url: "/* nothing */")

    def test_pc_and_web_together(self):
        path = os.path.join(self.dir, "entitlements.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(ENTITLEMENTS)
        kit = adobefonts.Kit(self.dir)
        kit.set("abc1234", lambda url: KIT_CSS)
        with mock.patch.object(adobefonts, "entitlements_paths", lambda: [path]):
            fonts = adobefonts.all_fonts(kit)
        pcs = [f for f in fonts if f["adobe"] == "pc"]
        webs = [f for f in fonts if f["adobe"] == "web"]
        self.assertEqual(len(pcs), 2)
        # The PC's DIN 2014 Bold also names the web one (other PCs load that)
        self.assertEqual(pcs[0]["kit"]["family"], "din-2014")
        # Only Tungsten is left as web-only (both DIN 2014 faces are on the PC)
        self.assertEqual([f["kit"]["family"] for f in webs], ["tungsten"])

    def test_engine_lists_them_and_imports_find_them(self):
        from gfxengine.app import Engine
        from gfxengine.config import Settings
        engine = Engine(settings=Settings(os.path.join(self.dir, "settings.json")),
                        workspaces_dir=os.path.join(self.dir, "ws"), library_dir=os.path.join(self.dir, "lib"))
        try:
            with mock.patch.object(adobefonts, "_fetch", lambda url: KIT_CSS):
                info = engine.set_adobe_kit("abc1234")
            self.assertEqual((info["kit"], info["kit_fonts"]), ("abc1234", 3))
            st = engine.state()
            self.assertEqual(st["adobe_fonts"]["kit"], "abc1234")
            web = [f for f in st["fonts"] if f.get("adobe") == "web"]
            self.assertEqual(len(web), 3)
            # Not in exports: they aren't files
            self.assertFalse(any(f.get("adobe") for f in engine.assets.fonts()))
        finally:
            engine.stop()


if __name__ == "__main__":
    unittest.main()
