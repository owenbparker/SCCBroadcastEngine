"""Figma .fig import (Composer's Import): a small .fig written here with a kiwi encoder."""

import io
import os
import shutil
import struct
import tempfile
import unittest
from unittest import mock
import zipfile
import zlib

from PIL import Image

from gfxengine.project import Workspace

# --- a tiny kiwi encoder (the format figkiwi reads) ----------------------------------------------
BUILTIN = {"bool": -1, "byte": -2, "int": -3, "uint": -4, "float": -5, "string": -6}
DEFS = [
    ("GUID", "struct", [("sessionID", "uint", False), ("localID", "uint", False)]),
    ("ParentIndex", "message", [("guid", "GUID", False), ("position", "string", False)]),
    ("Color", "struct", [("r", "float", False), ("g", "float", False), ("b", "float", False), ("a", "float", False)]),
    ("Vector", "struct", [("x", "float", False), ("y", "float", False)]),
    ("Matrix", "struct", [(k, "float", False) for k in ("m00", "m01", "m02", "m10", "m11", "m12")]),
    ("Image", "message", [("hash", "byte", True)]),
    ("Paint", "message", [("type", "string", False), ("color", "Color", False), ("opacity", "float", False),
                          ("visible", "bool", False), ("image", "Image", False), ("imageScaleMode", "string", False)]),
    ("FontName", "message", [("family", "string", False), ("style", "string", False), ("postscript", "string", False)]),
    ("TextData", "message", [("characters", "string", False)]),
    ("NodeChange", "message", [("guid", "GUID", False), ("parentIndex", "ParentIndex", False), ("type", "string", False),
                               ("name", "string", False), ("visible", "bool", False), ("opacity", "float", False),
                               ("size", "Vector", False), ("transform", "Matrix", False), ("fillPaints", "Paint", True),
                               ("fontName", "FontName", False), ("fontSize", "float", False), ("textData", "TextData", False),
                               ("mask", "bool", False), ("cornerRadius", "float", False)]),
    ("Message", "message", [("nodeChanges", "NodeChange", True)]),
]
INDEX = {d[0]: i for i, d in enumerate(DEFS)}


def _uint(v):
    out = bytearray()
    while True:
        b = v & 127
        v >>= 7
        out.append(b | (128 if v else 0))
        if not v:
            return bytes(out)


def _sint(v):
    return _uint((v << 1) ^ (v >> 31) if v >= 0 else ((-v - 1) << 1) | 1)


def _str(s):
    return s.encode() + b"\0"


def _float(f):
    if f == 0:
        return b"\0"
    b = struct.unpack("<I", struct.pack("<f", f))[0]
    return struct.pack("<I", ((b >> 23) | (b << 9)) & 0xFFFFFFFF)


def schema():
    out = _uint(len(DEFS))
    for name, kind, fields in DEFS:
        out += _str(name) + bytes([{"enum": 0, "struct": 1, "message": 2}[kind]]) + _uint(len(fields))
        for i, (fname, ftype, arr) in enumerate(fields):
            out += _str(fname) + _sint(BUILTIN.get(ftype, INDEX.get(ftype, 0))) + bytes([arr]) + _uint(i + 1)
    return out


def encode(tname, value):
    if tname in BUILTIN:
        return {"bool": lambda v: bytes([bool(v)]), "uint": _uint, "float": _float, "string": _str}[tname](value)
    name, kind, fields = DEFS[INDEX[tname]]
    out = b""
    for i, (fname, ftype, arr) in enumerate(fields):
        if kind == "struct":
            out += encode(ftype, value.get(fname, 0))
            continue
        if fname not in value:
            continue
        v = value[fname]
        out += _uint(i + 1)
        if arr and ftype == "byte":
            out += _uint(len(v)) + bytes(v)
        elif arr:
            out += _uint(len(v)) + b"".join(encode(ftype, x) for x in v)
        else:
            out += encode(ftype, v)
    return out + (b"\0" if kind == "message" else b"")


def deflate(data):
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    return c.compress(data) + c.flush()


def make_fig(nodes, images):
    s, d = deflate(schema()), deflate(encode("Message", {"nodeChanges": nodes}))
    canvas = b"fig-kiwi" + struct.pack("<I", 15) + struct.pack("<I", len(s)) + s + struct.pack("<I", len(d)) + d
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("canvas.fig", canvas)
        for h, data in images.items():
            z.writestr("images/" + h, data)
    return buf.getvalue()


def node(i, parent, type_, name, w, h, x=0, y=0, **extra):
    n = {"guid": {"sessionID": 1, "localID": i}, "type": type_, "name": name, "visible": True, "opacity": 1.0,
         "size": {"x": w, "y": h}, "transform": {"m00": 1.0, "m01": 0.0, "m02": x, "m10": 0.0, "m11": 1.0, "m12": y}}
    if parent is not None:
        n["parentIndex"] = {"guid": {"sessionID": 1, "localID": parent}, "position": chr(33 + i)}
    n.update(extra)
    return n


def solid(r, g, b, a=1.0):
    return {"type": "SOLID", "color": {"r": r, "g": g, "b": b, "a": a}, "opacity": 1.0, "visible": True}


class FigTests(unittest.TestCase):
    def test_import(self):
        from gfxengine.assets import Assets
        pic = io.BytesIO()
        Image.new("RGBA", (64, 32), (200, 10, 10, 255)).save(pic, "PNG")
        h = "ab" * 20
        image = {"type": "IMAGE", "opacity": 1.0, "visible": True, "image": {"hash": bytes.fromhex(h)}, "imageScaleMode": "FILL"}
        nodes = [
            node(1, None, "DOCUMENT", "Document", 0, 0),
            node(2, 1, "CANVAS", "Page 1", 0, 0),
            node(3, 2, "FRAME", "Scorebug", 1920, 1080, fillPaints=[solid(1, 1, 1)]),
            node(4, 3, "RECTANGLE", "Rectangle 1", 400, 80, 100, 900, fillPaints=[solid(0.1, 0.2, 0.3)]),
            node(5, 3, "TEXT", "TEAM NAME", 200, 40, 120, 920, fillPaints=[solid(1, 1, 1)], fontSize=32.0,
                 fontName={"family": "Inter", "style": "Bold", "postscript": "Inter-Bold"}, textData={"characters": "SCC"}),
            node(6, 3, "ELLIPSE", "Ellipse 2", 50, 50, 600, 900, fillPaints=[solid(0, 1, 0)]),
            node(7, 3, "ROUNDED_RECTANGLE", "Team logo", 64, 64, 700, 900, fillPaints=[image], cornerRadius=8.0),
            node(8, 3, "GROUP", "Masked", 100, 100, 800, 900),
            node(9, 8, "ELLIPSE", "Mask", 100, 100, 0, 0, fillPaints=[solid(0, 0, 0)], mask=True),
            node(10, 8, "RECTANGLE", "Rectangle 3", 200, 100, 0, 0, fillPaints=[solid(1, 0, 0)]),
            node(13, 3, "GROUP", "Score box", 300, 100, 1000, 900),
            node(14, 13, "RECTANGLE", "Rectangle 5", 150, 100, 0, 0, fillPaints=[solid(0, 0, 1)]),
            node(15, 13, "TEXT", "SCORE", 150, 100, 150, 0, fillPaints=[solid(1, 1, 1)], fontSize=32.0,
                 fontName={"family": "Inter", "style": "Bold", "postscript": "Inter-Bold"}, textData={"characters": "0"}),
            node(11, 2, "FRAME", "Lower third", 800, 200, 3000, 0, fillPaints=[]),
            node(12, 11, "RECTANGLE", "Rectangle 4", 800, 200, 0, 0, fillPaints=[solid(0, 0, 0, 0.5)]),
        ]
        tmp = tempfile.mkdtemp()
        try:
            ws = Workspace(os.path.join(tmp, "ws"), starter="")
            assets = Assets(ws, None)
            src = os.path.join(tmp, "upload")
            with open(src, "wb") as f:
                f.write(make_fig(nodes, {h: pic.getvalue()}))
            with mock.patch("gfxengine.sysfonts.font_files", return_value=[]):   # (as on a PC without Inter installed)
                r = assets.add("SCC 2027.fig", src, graphic=True)
            ws.close()
            self.assertFalse(os.path.exists(src))
            self.assertEqual([c["name"] for c in r["comps"]], ["Scorebug", "Lower third"])
            by = {l["name"]: l for l in r["comps"][0]["layers"]}
            bg = by["Scorebug background"]
            self.assertFalse(bg["visible"])              # see-through graphic, background kept
            box = by["Rectangle 1"]
            self.assertEqual((box["type"], box["fill"], box["x"], box["y"], box["w"], box["h"]), ("rect", "#1a334d", 100, 900, 400, 80))
            self.assertEqual(box["field"], "")
            text = by["TEAM NAME"]
            self.assertEqual((text["type"], text["text"], text["font"], text["size"], text["weight"], text["field"]),
                             ("text", "SCC", "Inter-Bold", 32, 700, "TEAM NAME"))
            dot = by["Ellipse 2"]
            self.assertEqual((dot["type"], dot["x"], dot["y"], dot["w"], dot["h"]), ("image", 600, 900, 50, 50))
            self.assertTrue(ws.asset_path(dot["src"]).endswith(".svg"))
            logo = by["Team logo"]
            self.assertTrue(logo["src"].endswith(".png") and os.path.isfile(ws.asset_path(logo["src"])))
            self.assertEqual(logo["field"], "Team logo")
            with Image.open(ws.asset_path(logo["src"])) as im:
                self.assertEqual(im.getpixel((0, 0))[3], 0)     # rounded corner cut
            cut = by["Rectangle 3"]
            self.assertTrue(cut.get("mask"))
            with open(ws.asset_path(cut["mask"])) as f:
                self.assertIn("<mask", f.read())
            self.assertNotIn("Mask", by)                 # the mask itself isn't drawn
            # (a Figma group's layers are a Composer group; a group of one isn't)
            self.assertTrue(by["Rectangle 5"].get("group"))
            self.assertEqual(by["Rectangle 5"]["group"], by["SCORE"]["group"])
            self.assertEqual(by["SCORE"]["groupName"], "Score box")
            self.assertNotIn("group", by["Rectangle 3"])
            self.assertNotIn("group", box)
            lower = r["comps"][1]["layers"][0]
            self.assertEqual((lower["x"], lower["y"], lower["w"], lower["h"]), (560, 440, 800, 200))   # its size, centred
            self.assertEqual(lower["fill"], "#00000080")
            self.assertEqual(r["missing_fonts"], ["Inter-Bold"])
            self.assertTrue(any("background" in n for n in r["notes"]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_tidy_groups(self):
        from gfxengine.project import tidy_groups
        L = lambda i, g=None: dict({"id": i}, **({"group": g, "groupName": g.upper()} if g else {}))
        layers = [L("a", "g1"), L("b"), L("c", "g1"), L("d", "g2"), L("e")]
        tidy_groups(layers)
        # g1 comes together where its top layer was; g2 (one layer) is no group
        self.assertEqual([l["id"] for l in layers], ["b", "a", "c", "d", "e"])
        self.assertNotIn("group", layers[3])
        self.assertEqual(layers[1]["groupName"], "G1")
        split = [L("a", "g1"), L("b"), L("c", "g1"), L("d", "g2"), L("e", "g2")]
        tidy_groups(split, keep_order=True)
        self.assertEqual([l["id"] for l in split], ["a", "b", "c", "d", "e"])   # an import keeps its order
        self.assertEqual([l.get("group") for l in split], [None, None, None, "g2", "g2"])
        everything = [L("a", "g"), L("b", "g")]
        self.assertNotIn("group", tidy_groups(everything)[0])

    def test_not_a_figma_file(self):
        from gfxengine.assets import Assets
        tmp = tempfile.mkdtemp()
        try:
            ws = Workspace(os.path.join(tmp, "ws"), starter="")
            src = os.path.join(tmp, "upload")
            with open(src, "wb") as f:
                f.write(b"nope")
            with self.assertRaisesRegex(ValueError, "Figma"):
                Assets(ws, None).add("x.fig", src, graphic=True)
            ws.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
