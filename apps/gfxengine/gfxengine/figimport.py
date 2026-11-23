"""Figma files (.fig, from Figma's File > Save local copy) as graphics.

Each frame on a page becomes a graphic (a 16:9 frame fills the screen; a
smaller one keeps its size, in the middle). In it:

    text            text layers (font, size, colour, spacing, alignment, line
                    breaks where Figma wrapped), sat on Figma's baseline,
                    and fields that can be changed from Control
    rectangles      plain one-colour boxes stay boxes (colour editable);
                    anything else (gradients, shadows, ellipses, odd corners,
                    outlines outside the box) is drawn exactly as an SVG
    pictures        saved cut to their box (crop, fit, rounded corners)
    vector shapes   SVG pictures; a group made only of shapes (a logo, an
                    icon) is one picture
    masks, frames that clip
                    the layers under them are cut to the mask's shape
                    (layer.mask, an SVG of the shape)

The frame's own background (usually Figma's white) is kept as a hidden layer,
so the graphic is see-through. What can't be drawn (background blur, inner
shadows, a group's own shadow) is left out, and the import says so.
"""

import base64
import io
import math
import os
import re
import zipfile

from . import figkiwi
from .log import log
from .project import ANIM_NONE, blank_comp, new_id, tidy_groups

CONTAINERS = {"FRAME", "GROUP", "SECTION", "SYMBOL", "INSTANCE", "COMPONENT", "COMPONENT_SET"}
VECTORS = {"VECTOR", "STAR", "LINE", "REGULAR_POLYGON", "BOOLEAN_OPERATION", "POLYGON"}
SHAPES = {"RECTANGLE", "ROUNDED_RECTANGLE", "ELLIPSE"}
FRAMES = ("FRAME", "SYMBOL", "COMPONENT", "INSTANCE")
BLENDS = {"MULTIPLY": "multiply", "SCREEN": "screen", "OVERLAY": "overlay", "DARKEN": "darken", "LIGHTEN": "lighten",
          "COLOR_DODGE": "color-dodge", "COLOR_BURN": "color-burn", "HARD_LIGHT": "hard-light",
          "SOFT_LIGHT": "soft-light", "DIFFERENCE": "difference", "EXCLUSION": "exclusion", "HUE": "hue",
          "SATURATION": "saturation", "COLOR": "color", "LUMINOSITY": "luminosity", "LINEAR_DODGE": "plus-lighter"}
WEIGHTS = [("thin", 100), ("hairline", 100), ("extralight", 200), ("ultralight", 200), ("light", 300),
           ("medium", 500), ("semibold", 600), ("demibold", 600), ("extrabold", 800), ("ultrabold", 800),
           ("bold", 700), ("black", 900), ("heavy", 900)]
# Figma's own names for things nobody named: fixed, not fields.
GENERIC = re.compile(r"^(rectangle|ellipse|line|vector|group|frame|image|polygon|star|union|subtract|intersect|exclude|"
                     r"slide|mask|layer|shape|path|component|instance|section|arrow|bg|background|copy)\b|^\d+$", re.I)
SCREEN_W, SCREEN_H = 1920, 1080


# --- reading the file ---------------------------------------------------------------------------
def read(blob):
    """(message, {image hash hex: bytes})."""
    images = {}
    if blob[:2] == b"PK":
        try:
            z = zipfile.ZipFile(io.BytesIO(blob))
        except zipfile.BadZipFile:
            raise ValueError("That Figma file is damaged") from None
        names = z.namelist()
        canvas = next((n for n in names if n.lower().endswith(".fig")), None)
        if not canvas:
            raise ValueError("That zip has no Figma design in it (canvas.fig)")
        for n in names:
            if n.startswith("images/") and not n.endswith("/"):
                images[n[len("images/"):].lower()] = z.read(n)
        canvas = z.read(canvas)
    else:
        canvas = blob
    return figkiwi.read_fig(canvas), images


def _gid(guid):
    return (guid or {}).get("sessionID"), (guid or {}).get("localID")


def _tree(nodes):
    """{parent id: [children, in drawing order (bottom first)]}."""
    kids = {}
    for n in nodes:
        p = n.get("parentIndex")
        if p:
            kids.setdefault(_gid(p.get("guid")), []).append(n)
    for lst in kids.values():
        lst.sort(key=lambda n: n["parentIndex"].get("position") or "")
    return kids


# --- geometry -----------------------------------------------------------------------------------
IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)


def _matrix(t):
    t = t or {}
    return (t.get("m00", 1.0), t.get("m01", 0.0), t.get("m02", 0.0), t.get("m10", 0.0), t.get("m11", 1.0), t.get("m12", 0.0))


def _mul(a, b):
    return (a[0] * b[0] + a[1] * b[3], a[0] * b[1] + a[1] * b[4], a[0] * b[2] + a[1] * b[5] + a[2],
            a[3] * b[0] + a[4] * b[3], a[3] * b[1] + a[4] * b[4], a[3] * b[2] + a[4] * b[5] + a[5])


def _inv(m):
    det = m[0] * m[4] - m[1] * m[3]
    if abs(det) < 1e-12:
        return None
    return (m[4] / det, -m[1] / det, (m[1] * m[5] - m[4] * m[2]) / det,
            -m[3] / det, m[0] / det, (m[3] * m[2] - m[0] * m[5]) / det)


def _apply(m, x, y):
    return m[0] * x + m[1] * y + m[2], m[3] * x + m[4] * y + m[5]


def _svgm(m):
    """An SVG matrix() of ours (x' = m0 x + m1 y + m2, y' = m3 x + m4 y + m5)."""
    return "matrix(" + " ".join(_n(v) for v in (m[0], m[3], m[1], m[4], m[2], m[5])) + ")"


def _n(v):
    return f"{v:.3f}".rstrip("0").rstrip(".") if v == v else "0"


def _scales(m):
    return math.hypot(m[0], m[3]) or 1.0, math.hypot(m[1], m[4]) or 1.0


def _place(m, w, h):
    """The layer's box (x, y, w, h, rotation) for a w x h box under m, and whether it's mirrored."""
    sx, sy = _scales(m)
    flip = m[0] * m[4] - m[1] * m[3] < 0
    s = -1 if flip else 1
    angle = math.degrees(math.atan2(s * m[3], s * m[0]))
    cx, cy = _apply(m, w / 2, h / 2)
    w, h = w * sx, h * sy
    return {"x": round(cx - w / 2, 2), "y": round(cy - h / 2, 2), "w": round(w, 2), "h": round(h, 2),
            "rotation": round(angle, 2) if abs(angle) > 0.01 else 0}, flip


def _path(blob, m=None, pts_out=None):
    """Figma's path commands (0 close, 1 move, 2 line, 3 quad, 4 cubic; float32
    points) as SVG path data. pts_out collects the points (under m) for the bounds."""
    import struct
    out, o, n = [], 0, len(blob)
    counts = {1: 1, 2: 1, 3: 2, 4: 3}
    letters = {1: "M", 2: "L", 3: "Q", 4: "C"}
    while o < n:
        cmd = blob[o]
        o += 1
        if cmd == 0:
            out.append("Z")
            continue
        if cmd not in counts or o + 8 * counts[cmd] > n:
            break
        pts = struct.unpack_from("<" + "f" * (2 * counts[cmd]), blob, o)
        o += 8 * counts[cmd]
        if pts_out is not None:
            for i in range(0, len(pts), 2):
                pts_out.append(_apply(m or IDENTITY, pts[i], pts[i + 1]))
        out.append(letters[cmd] + " ".join(_n(v) for v in pts))
    return " ".join(out)


def _radii(node):
    """[top left, top right, bottom right, bottom left]."""
    if node.get("rectangleCornerRadiiIndependent"):
        return [node.get(f"rectangle{k}CornerRadius", 0) or 0 for k in ("TopLeft", "TopRight", "BottomRight", "BottomLeft")]
    r = node.get("cornerRadius", 0) or 0
    return [r] * 4


def _rect_path(w, h, r=(0, 0, 0, 0), ellipse=False):
    if ellipse:
        # (four curves, so its points give its bounds)
        a, b, k = w / 2, h / 2, 0.5523
        cx, cy = a, b
        return (f"M{_n(cx + a)} {_n(cy)}C{_n(cx + a)} {_n(cy + b * k)} {_n(cx + a * k)} {_n(cy + b)} {_n(cx)} {_n(cy + b)}"
                f"C{_n(cx - a * k)} {_n(cy + b)} {_n(cx - a)} {_n(cy + b * k)} {_n(cx - a)} {_n(cy)}"
                f"C{_n(cx - a)} {_n(cy - b * k)} {_n(cx - a * k)} {_n(cy - b)} {_n(cx)} {_n(cy - b)}"
                f"C{_n(cx + a * k)} {_n(cy - b)} {_n(cx + a)} {_n(cy - b * k)} {_n(cx + a)} {_n(cy)}Z")
    lim = min(w, h) / 2
    tl, tr, br, bl = (max(0, min(lim, v)) for v in r)
    return (f"M{_n(tl)} 0H{_n(w - tr)}" + (f"A{_n(tr)} {_n(tr)} 0 0 1 {_n(w)} {_n(tr)}" if tr else "")
            + f"V{_n(h - br)}" + (f"A{_n(br)} {_n(br)} 0 0 1 {_n(w - br)} {_n(h)}" if br else "")
            + f"H{_n(bl)}" + (f"A{_n(bl)} {_n(bl)} 0 0 1 0 {_n(h - bl)}" if bl else "")
            + f"V{_n(tl)}" + (f"A{_n(tl)} {_n(tl)} 0 0 1 {_n(tl)} 0" if tl else "") + "Z")


# --- paint --------------------------------------------------------------------------------------
def _hex(color, opacity=1.0):
    c = color or {}
    a = max(0.0, min(1.0, c.get("a", 1.0) * opacity))
    rgb = "".join(f"{max(0, min(255, round(c.get(k, 0) * 255))):02x}" for k in "rgb")
    return "#" + rgb + ("" if a >= 0.999 else f"{round(a * 255):02x}")


def _rgb(color):
    c = color or {}
    return "#" + "".join(f"{max(0, min(255, round(c.get(k, 0) * 255))):02x}" for k in "rgb")


def _visible(paints):
    return [p for p in paints or [] if p.get("visible", True) and p.get("opacity", 1.0) > 0]


def _effects(node):
    return [e for e in node.get("effects") or [] if e.get("visible", True)]


def _safe(name, used):
    base = re.sub(r"[^\w\- ]+", "_", name or "").strip()[:60] or "layer"
    out, n = base, 2
    while out.lower() in used:
        out, n = f"{base}-{n}", n + 1
    used.add(out.lower())
    return out


def _field_name(name, taken):
    base = re.sub(r"\s+", " ", name or "").strip()[:40] or "Field"
    out, n = base, 2
    while out.lower() in taken:
        out, n = f"{base} {n}", n + 1
    taken.add(out.lower())
    return out


class _Svg:
    """One SVG picture being drawn: its defs, its body, and the bounds (in the
    graphic's pixels) of everything drawn."""

    def __init__(self, job, prefix=""):
        self.job, self.defs, self.body, self.pts, self.pad, self.n = job, [], [], [], 0.0, 0
        self.prefix = prefix

    def id(self, kind):
        self.n += 1
        return f"{self.prefix}{kind}{self.n}"

    def paint(self, p, w, h, m):
        """An SVG fill for a Figma paint on a w x h box: (fill, fill-opacity), or None."""
        kind = p.get("type", "")
        op = p.get("opacity", 1.0)
        if kind == "SOLID":
            c = p.get("color") or {}
            return _rgb(c), c.get("a", 1.0) * op
        if kind.startswith("GRADIENT"):
            stops = sorted(p.get("stops") or [], key=lambda s: s.get("position", 0))
            if not stops:
                return None
            gid = self.id("g")
            # The paint's transform maps the box (0..1) to gradient space; the
            # gradient runs (0, .5) -> (1, .5), a radial one sits at (.5, .5) radius .5.
            inv = _inv(_matrix(p.get("transform"))) or IDENTITY
            gt = _svgm(_mul((w, 0, 0, 0, h, 0), inv))
            st = "".join(f'<stop offset="{_n(s.get("position", 0))}" stop-color="{_rgb(s.get("color"))}"'
                         f' stop-opacity="{_n((s.get("color") or {}).get("a", 1.0))}"/>' for s in stops)
            if kind == "GRADIENT_LINEAR":
                self.defs.append(f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="0" y1="0.5" x2="1" y2="0.5"'
                                 f' gradientTransform="{gt}">{st}</linearGradient>')
            else:   # radial (angular and diamond drawn as radial)
                self.defs.append(f'<radialGradient id="{gid}" gradientUnits="userSpaceOnUse" cx="0.5" cy="0.5" r="0.5"'
                                 f' gradientTransform="{gt}">{st}</radialGradient>')
            return f"url(#{gid})", op
        if kind == "IMAGE":
            data = self.job.image_bytes(p)
            if not data:
                return None
            pid = self.id("p")
            mime = "image/jpeg" if data[:3] == b"\xff\xd8\xff" else "image/png"
            uri = f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
            fit = "xMidYMid meet" if p.get("imageScaleMode") == "FIT" else "none" if p.get("imageScaleMode") == "STRETCH" else "xMidYMid slice"
            self.defs.append(f'<pattern id="{pid}" patternUnits="userSpaceOnUse" width="{_n(w)}" height="{_n(h)}">'
                             f'<image href="{uri}" width="{_n(w)}" height="{_n(h)}" preserveAspectRatio="{fit}"/></pattern>')
            return f"url(#{pid})", op
        return None

    def filter(self, effects, m):
        """A filter for drop shadows and blur (in the graphic's pixels), its id or None."""
        parts, merge, k = [], [], _scales(m)[0]
        blur = 0
        for e in effects:
            t = e.get("type")
            if t == "DROP_SHADOW":
                r = (e.get("radius", 0) or 0) * k
                off = e.get("offset") or {}
                dx, dy = (off.get("x", 0) or 0) * k, (off.get("y", 0) or 0) * k
                c = e.get("color") or {}
                i = len(merge)
                parts.append(f'<feGaussianBlur in="SourceAlpha" stdDeviation="{_n(r / 2)}"/>'
                             f'<feOffset dx="{_n(dx)}" dy="{_n(dy)}" result="o{i}"/>'
                             f'<feFlood flood-color="{_rgb(c)}" flood-opacity="{_n(c.get("a", 1.0))}"/>'
                             f'<feComposite in2="o{i}" operator="in" result="s{i}"/>')
                merge.append(f"s{i}")
                self.pad = max(self.pad, r * 1.5 + abs(dx) + abs(dy) + abs((e.get("spread") or 0) * k))
            elif t == "FOREGROUND_BLUR" or t == "LAYER_BLUR":
                blur = (e.get("radius", 0) or 0) * k
                self.pad = max(self.pad, blur * 1.5)
        if not parts and not blur:
            return None
        fid = self.id("f")
        src = "SourceGraphic"
        if blur:
            parts.append(f'<feGaussianBlur in="SourceGraphic" stdDeviation="{_n(blur / 2)}" result="b"/>')
            src = "b"
        nodes = "".join(f'<feMergeNode in="{s}"/>' for s in merge) + f'<feMergeNode in="{src}"/>'
        self.defs.append(f'<filter id="{fid}" filterUnits="userSpaceOnUse" x="-100000" y="-100000" width="200000" height="200000"'
                         f' color-interpolation-filters="sRGB">{"".join(parts)}<feMerge>{nodes}</feMerge></filter>')
        return fid

    def shape(self, node, m, fills=True, strokes=True, effects=True, skip_images=False):
        """The node's own fills and outline (not its children), under m. Returns whether anything was drawn."""
        size = node.get("size") or {}
        w, h = size.get("x", 0) or 0, size.get("y", 0) or 0
        geo = self.job.geometry(node, w, h)
        out = []
        if fills:
            for p in _visible(node.get("fillPaints")):
                if skip_images and p.get("type") == "IMAGE":
                    continue
                paint = self.paint(p, w, h, m)
                if not paint:
                    continue
                for d, rule in geo:
                    _path_pts(d, m, self.pts)
                    out.append(f'<path d="{d}" fill="{paint[0]}" fill-opacity="{_n(paint[1])}" fill-rule="{rule}"/>')
        if strokes and (node.get("strokeWeight") or 0) > 0:
            sgeo = self.job.stroke_geometry(node)
            for p in _visible(node.get("strokePaints")):
                paint = self.paint(p, w, h, m)
                if not paint:
                    continue
                for d, rule in sgeo:
                    _path_pts(d, m, self.pts)
                    out.append(f'<path d="{d}" fill="{paint[0]}" fill-opacity="{_n(paint[1])}" fill-rule="{rule}"/>')
        if not out:
            return False
        body = f'<g transform="{_svgm(m)}">' + "".join(out) + "</g>"
        fid = self.filter(_effects(node), m) if effects else None
        if fid:
            body = f'<g filter="url(#{fid})">{body}</g>'
        self.body.append(body)
        return True

    def tree(self, node, m, opacity=1.0):
        """A node and everything in it (shapes only: see _Import.shapes_only)."""
        if not node.get("visible", True) or node.get("internalOnly"):
            return
        mm = _mul(m, _matrix(node.get("transform")))
        t = node.get("type")
        op = node.get("opacity", 1.0)
        start = len(self.body)
        self.shape(node, mm)
        kids = self.job.children(node) if t in CONTAINERS else []
        if kids:
            clip = ""
            if t in FRAMES and not node.get("frameMaskDisabled"):
                cid = self.id("c")
                size = node.get("size") or {}
                geo = self.job.geometry(node, size.get("x", 0) or 0, size.get("y", 0) or 0, fill_only=False)
                self.defs.append(f'<clipPath id="{cid}">' + "".join(
                    f'<path transform="{_svgm(mm)}" d="{d}" clip-rule="{rule}"/>' for d, rule in geo) + "</clipPath>")
                clip = f' clip-path="url(#{cid})"'
            inner = len(self.body)
            for child in kids:
                self.tree(child, mm)
            drawn = self.body[inner:]
            del self.body[inner:]
            if drawn:
                self.body.append(f"<g{clip}>" + "".join(drawn) + "</g>")
        group = self.body[start:]
        del self.body[start:]
        if group:
            style = ""
            blend = BLENDS.get(node.get("blendMode"))
            if blend:
                style = f' style="mix-blend-mode:{blend}"'
            self.body.append(f'<g opacity="{_n(op)}"{style}>' + "".join(group) + "</g>" if op < 1 or style else "".join(group))

    def bounds(self):
        if not self.pts:
            return None
        xs = [p[0] for p in self.pts]
        ys = [p[1] for p in self.pts]
        pad = self.pad
        return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad

    def text(self, box=None):
        b = box or self.bounds()
        x0, y0, x1, y1 = b
        w, h = max(x1 - x0, 1), max(y1 - y0, 1)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{_n(w)}" height="{_n(h)}" viewBox="{_n(x0)} {_n(y0)} {_n(w)} {_n(h)}">'
                + (f"<defs>{''.join(self.defs)}</defs>" if self.defs else "") + "".join(self.body) + "</svg>")


_NUM = re.compile(r"-?\d+(?:\.\d+)?(?:e-?\d+)?")


def _path_pts(d, m, out):
    """Rough bounds of path data (its points and control points) under m."""
    nums = [float(v) for v in _NUM.findall(re.sub(r"A[^A-Za-z]*", " ", d))]
    for i in range(0, len(nums) - 1, 2):
        out.append(_apply(m, nums[i], nums[i + 1]))
    for arc in re.findall(r"A([^A-Za-z]*)", d):
        v = [float(x) for x in _NUM.findall(arc)]
        if len(v) >= 7:
            out.append(_apply(m, v[5], v[6]))


# --- the importer -------------------------------------------------------------------------------
class _Import:
    def __init__(self, blob, workspace, name):
        self.ws, self.name = workspace, name
        self.msg, self.images = read(blob)
        self.blobs = [b.get("bytes", b"") for b in self.msg.get("blobs") or []]
        self.nodes = self.msg.get("nodeChanges") or []
        self.by_id = {_gid(n.get("guid")): n for n in self.nodes}
        self.kids = _tree(self.nodes)
        self.missing_images = 0
        self.left_out = {}
        self.fonts = set()

    # --- the file's parts ---
    def children(self, node):
        kids = self.kids.get(_gid(node.get("guid")), [])
        if not kids and node.get("type") == "INSTANCE":
            # (an instance with no layers of its own shows its component's)
            sym = self.by_id.get(_gid((node.get("symbolData") or {}).get("symbolID")))
            if sym:
                kids = self.kids.get(_gid(sym.get("guid")), [])
        return kids

    def image_bytes(self, paint):
        ref = (paint.get("image") or {}).get("hash")
        data = self.images.get(ref.hex()) if isinstance(ref, (bytes, bytearray)) else None
        if not data:
            self.missing_images += 1
        return data

    def geometry(self, node, w, h, fill_only=True):
        """[(path data, fill rule)] of the node's filled area, in its own pixels."""
        out = []
        for g in node.get("fillGeometry") or []:
            i = g.get("commandsBlob")
            if isinstance(i, int) and i < len(self.blobs):
                d = _path(self.blobs[i])
                if d:
                    out.append((d, "evenodd" if g.get("windingRule") in ("ODD", "EVENODD") else "nonzero"))
        if not out and w > 0 and h > 0 and (node.get("type") in SHAPES or node.get("type") in CONTAINERS):
            out.append((_rect_path(w, h, _radii(node), node.get("type") == "ELLIPSE"), "nonzero"))
        return out

    def stroke_geometry(self, node):
        out = []
        for g in node.get("strokeGeometry") or []:
            i = g.get("commandsBlob")
            if isinstance(i, int) and i < len(self.blobs):
                d = _path(self.blobs[i])
                if d:
                    out.append((d, "nonzero"))
        return out

    def note(self, what):
        self.left_out[what] = self.left_out.get(what, 0) + 1

    def shapes_only(self, node, depth=0):
        """Whether a group holds only shapes (no text, pictures, masks or hidden
        layers): then it's drawn as one picture (a logo, an icon)."""
        for c in self.children(node):
            t = c.get("type")
            if c.get("mask") or not c.get("visible", True) or t == "TEXT":
                return False
            if any(p.get("type") == "IMAGE" for p in _visible(c.get("fillPaints"))):
                return False
            if t in CONTAINERS:
                if depth > 12 or not self.shapes_only(c, depth + 1):
                    return False
            elif t not in VECTORS and t not in SHAPES:
                return False
        return True

    def count_shapes(self, node):
        n = 0
        for c in self.children(node):
            n += 1 + (self.count_shapes(c) if c.get("type") in CONTAINERS else 0)
        return n

    # --- layers ---
    def layer(self, node, place, opacity, kind, **extra):
        out = {"id": new_id("l"), "name": node.get("name") or kind.capitalize(), "type": kind,
               "opacity": round(max(0.0, min(1.0, opacity)), 3), "visible": True,
               "blend": BLENDS.get(node.get("blendMode"), "normal"),
               "field": "", "anim": {"in": dict(ANIM_NONE), "out": dict(ANIM_NONE)}}
        out.update(place)
        out.update(extra)
        return out

    def save(self, stem, ext, data):
        fname = _safe(stem, self.used) + ext
        with open(os.path.join(self.folder, fname), "wb") as f:
            f.write(data)
        return f"{self.rel}/{fname}"

    def svg_layer(self, node, svg, opacity, name=None):
        b = svg.bounds()
        if not b or b[2] - b[0] < 0.01 and b[3] - b[1] < 0.01:
            return None
        src = self.save(name or node.get("name") or "shape", ".svg", svg.text(b).encode("utf-8"))
        place = {"x": round(b[0], 2), "y": round(b[1], 2), "w": round(max(b[2] - b[0], 1), 2),
                 "h": round(max(b[3] - b[1], 1), 2), "rotation": 0}
        return self.layer(node, place, opacity, "image", src=src, fit="fill", loop=True)

    def walk(self, node, m, opacity, visible, clips, out):
        """The layers for one node and what's in it. m: its parent's matrix
        (to the graphic's pixels), clips: shapes that cut what's drawn."""
        if node.get("internalOnly") or node.get("type") in ("CANVAS", "DOCUMENT"):
            return
        vis = visible and node.get("visible", True)
        op = opacity * node.get("opacity", 1.0)
        mm = _mul(m, _matrix(node.get("transform")))
        size = node.get("size") or {}
        w, h = size.get("x", 0) or 0, size.get("y", 0) or 0
        t = node.get("type")
        start = len(out)
        for e in _effects(node):
            if e.get("type") in ("BACKGROUND_BLUR", "INNER_SHADOW"):
                self.note({"BACKGROUND_BLUR": "background blur", "INNER_SHADOW": "inner shadow"}[e["type"]])
            elif e.get("type") == "DROP_SHADOW" and t in ("GROUP", "SECTION"):
                self.note("shadow on a group")
        try:
            if t == "TEXT":
                self.text(node, mm, w, h, op, out)
            elif t in VECTORS:
                if not node.get("fillGeometry") and not node.get("strokeGeometry") and t == "BOOLEAN_OPERATION":
                    for c in self.children(node):
                        self.walk(c, mm, op, vis, clips, out)
                else:
                    svg = _Svg(self)
                    svg.shape(node, mm)
                    layer = self.svg_layer(node, svg, op)
                    if layer:
                        out.append(layer)
            elif t in SHAPES or t in CONTAINERS:
                if t in CONTAINERS and node is not self.top and self.count_shapes(node) >= 2 and self.shapes_only(node):
                    # A logo or icon made of shapes: one picture.
                    svg = _Svg(self)
                    svg.tree(dict(node, transform=None, opacity=1.0, blendMode=None), mm)
                    layer = self.svg_layer(node, svg, op)
                    if layer:
                        out.append(layer)
                    self._finish(out, start, vis, clips)
                    return
                self.box(node, mm, w, h, op, out)
        except Exception as e:
            log(f"{self.name}: left out {node.get('name')!r} ({e})", "warn")
            self.note("layer that couldn't be read")
        if t in CONTAINERS:
            inner = clips
            if t in FRAMES and not node.get("frameMaskDisabled") and w > 0 and h > 0 and node is not self.top:
                inner = clips + [self.clip_of(node, mm, w, h)]
            here = inner
            for child in self.children(node):
                if child.get("mask"):
                    # (a mask cuts the layers above it in the same group)
                    if child.get("visible", True):
                        cm = _mul(mm, _matrix(child.get("transform")))
                        cs = child.get("size") or {}
                        clip = self.clip_of(child, cm, cs.get("x", 0) or 0, cs.get("y", 0) or 0)
                        clip["node"], clip["parent_m"] = child, mm
                        if any(p.get("type") != "SOLID" or (p.get("color") or {}).get("a", 1) < 1 or p.get("opacity", 1) < 1
                               for p in _visible(child.get("fillPaints"))) or child.get("opacity", 1) < 1:
                            clip["plain"] = False
                        here = here + [clip]
                    continue
                self.walk(child, mm, op, vis, here, out)
            if node is not self.top:
                # (a Figma group or frame: its layers are a Composer group,
                # the innermost one they're in)
                gid, gname = new_id("g"), (node.get("name") or "Group").strip()[:80] or "Group"
                for layer in out[start:]:
                    if not layer.get("group"):
                        layer["group"], layer["groupName"] = gid, gname
        self._finish(out, start, vis, clips, own_only=t in CONTAINERS)

    def _finish(self, out, start, vis, clips, own_only=False):
        for layer in out[start:]:
            if not vis:
                layer["visible"] = False
            if clips and not layer.get("_clipped"):
                self.cut(layer, clips)
                layer["_clipped"] = True

    def clip_of(self, node, m, w, h):
        geo = self.geometry(node, w, h, fill_only=False)
        pts = []
        for d, _ in geo:
            _path_pts(d, m, pts)
        box = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)) if pts else (0, 0, 0, 0)
        plain = (node.get("type") in CONTAINERS or node.get("type") in ("RECTANGLE", "ROUNDED_RECTANGLE")) \
            and not any(_radii(node)) and abs(m[1]) < 1e-6 and abs(m[3]) < 1e-6
        return {"geo": geo, "m": m, "box": box, "plain": plain}

    def cut(self, layer, clips):
        """Cuts a layer to the shapes it's inside (an SVG mask), unless it's all inside them anyway."""
        x0, y0, x1, y1 = layer["x"], layer["y"], layer["x"] + layer["w"], layer["y"] + layer["h"]
        need = [c for c in clips if not (c["plain"] and not layer.get("rotation")
                                         and x0 >= c["box"][0] - 0.5 and y0 >= c["box"][1] - 0.5
                                         and x1 <= c["box"][2] + 0.5 and y1 <= c["box"][3] + 0.5)]
        if not need:
            return
        defs, open_, close = [], "", ""
        for i, c in enumerate(need):
            if c.get("node") is not None:
                # A mask layer: what shows is where it's drawn (its alpha: a picture's shape, a gradient's fade).
                drawn = _Svg(self, f"k{i}_")
                drawn.tree(dict(c["node"], mask=False), c["parent_m"])
                if drawn.body:
                    defs += drawn.defs
                    defs.append(f'<mask id="k{i}" style="mask-type:alpha" maskUnits="userSpaceOnUse" x="-100000" y="-100000"'
                                f' width="200000" height="200000">{"".join(drawn.body)}</mask>')
                    open_ += f'<g mask="url(#k{i})">'
                    close += "</g>"
                    continue
            defs.append(f'<clipPath id="k{i}">' + "".join(
                f'<path transform="{_svgm(c["m"])}" d="{d}" clip-rule="{rule}"/>' for d, rule in c["geo"]) + "</clipPath>")
            open_ += f'<g clip-path="url(#k{i})">'
            close += "</g>"
        w, h = layer["w"], layer["h"]
        rot = layer.get("rotation") or 0
        turn = f'<g transform="rotate({_n(-rot)} {_n(x0 + w / 2)} {_n(y0 + h / 2)})">' if rot else ""
        body = (f'{open_}<rect x="{_n(x0 - w)}" y="{_n(y0 - h)}" width="{_n(w * 3)}" height="{_n(h * 3)}" fill="#fff"/>{close}')
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{_n(w)}" height="{_n(h)}" viewBox="{_n(x0)} {_n(y0)} {_n(w)} {_n(h)}"'
               f' preserveAspectRatio="none"><defs>{"".join(defs)}</defs>{turn}{body}{"</g>" if rot else ""}</svg>')
        layer["mask"] = self.save((layer.get("name") or "layer") + " mask", ".svg", svg.encode("utf-8"))

    def box(self, node, m, w, h, op, out):
        """A rectangle, ellipse or frame's own look: a plain box when it is one,
        pictures cut to it, otherwise drawn as an SVG."""
        if w <= 0 or h <= 0:
            return
        fills = _visible(node.get("fillPaints"))
        strokes = _visible(node.get("strokePaints")) if (node.get("strokeWeight") or 0) > 0 else []
        effects = [e for e in _effects(node) if e.get("type") in ("DROP_SHADOW", "FOREGROUND_BLUR", "LAYER_BLUR")]
        if not fills and not strokes:
            return
        place, flip = _place(m, w, h)
        ellipse = node.get("type") == "ELLIPSE"
        radii = _radii(node)
        top_bg = node is self.top
        sx, _ = _scales(m)
        borders = {node.get(f"border{s}Weight") for s in ("Top", "Right", "Bottom", "Left")} - {None}
        plain = (not ellipse and len(set(radii)) == 1 and not effects and len(fills) == 1 and fills[0].get("type") == "SOLID"
                 and (not strokes or (len(strokes) == 1 and strokes[0].get("type") == "SOLID" and node.get("strokeAlign", "INSIDE") == "INSIDE"
                                      and len(borders) <= 1 and not node.get("borderStrokeWeightsIndependent")))
                 and abs(_scales(m)[0] - _scales(m)[1]) < 1e-3 and not flip and not node.get("arcData", {}).get("innerRadius"))
        made = []
        if plain:
            extra = {"fill": _hex(fills[0].get("color"), fills[0].get("opacity", 1.0)), "radius": round(radii[0] * sx, 2),
                     "stroke": "#ffffff", "strokeWidth": 0}
            if strokes:
                extra.update(stroke=_hex(strokes[0].get("color"), strokes[0].get("opacity", 1.0)),
                             strokeWidth=round((node.get("strokeWeight") or 0) * sx, 2))
            made.append(self.layer(node, place, op, "rect", **extra))
        else:
            images = [p for p in fills if p.get("type") == "IMAGE"]
            if images:
                # Under the picture: its shadow and other fills; over it: the outline.
                under = _Svg(self)
                if any(p.get("type") != "IMAGE" for p in fills) or effects:
                    under.shape(node, m, strokes=False, skip_images=True)
                    if not under.body and effects:
                        # (a shadow only: the shape drawn with the shadow, then cut away by the picture on top)
                        under.shape(dict(node, fillPaints=[{"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0, "a": 1}}]), m, strokes=False)
                    layer = self.svg_layer(node, under, op)
                    if layer:
                        made.append(layer)
                for p in images:
                    src = self.picture(node, p, w, h, place, flip, ellipse, radii)
                    if src:
                        made.append(self.layer(node, place, op, "image", src=src, fit="fill", loop=True))
                if strokes:
                    over = _Svg(self)
                    over.shape(node, m, fills=False, effects=False)
                    layer = self.svg_layer(node, over, op, (node.get("name") or "shape") + " outline")
                    if layer:
                        layer["name"] += " outline"
                        made.append(layer)
            else:
                svg = _Svg(self)
                svg.shape(node, m)
                layer = self.svg_layer(node, svg, op)
                if layer:
                    made.append(layer)
        if top_bg:
            for layer in made:
                layer["name"] = (node.get("name") or "Frame") + " background"
                layer["visible"] = False
                layer["field"] = ""
                layer["_bg"] = True
        elif node.get("type") in CONTAINERS:
            for layer in made:
                if not layer["name"].endswith(" outline"):
                    layer["name"] = (node.get("name") or "Frame") + " background"
        out.extend(made)

    def picture(self, node, paint, w, h, place, flip, ellipse, radii):
        """An image fill drawn as it shows in Figma, saved as a PNG; its asset path."""
        from PIL import Image, ImageDraw, ImageOps
        data = self.image_bytes(paint)
        if not data:
            return None
        img = Image.open(io.BytesIO(data))
        img.load()
        img = img.convert("RGBA")
        lw, lh = place["w"], place["h"]
        k = max(1.0, min(2.0, img.width / lw if lw else 1))
        ow, oh = max(1, round(lw * k)), max(1, round(lh * k))
        mode = paint.get("imageScaleMode", "FILL")
        rot = round((paint.get("rotation") or 0) / 90) % 4
        if rot:
            img = img.rotate(-90 * rot, expand=True)
        canvas = Image.new("RGBA", (ow, oh), (0, 0, 0, 0))
        if mode == "FIT":
            s = min(ow / img.width, oh / img.height)
            fit = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
            canvas.paste(fit, ((ow - fit.width) // 2, (oh - fit.height) // 2))
        elif mode == "TILE":
            s = (paint.get("scale") or 1) * k * (lw / w if w else 1)
            tile = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
            for ty in range(0, oh, tile.height):
                for tx in range(0, ow, tile.width):
                    canvas.paste(tile, (tx, ty))
        elif mode in ("STRETCH", "CROP"):
            # The paint's transform maps the box (0..1) to the part of the picture it
            # shows (which can reach past the picture: see-through there).
            t = _matrix(paint.get("transform"))
            iw, ih = img.width, img.height
            canvas = img.transform((ow, oh), Image.AFFINE, (iw * t[0] / ow, iw * t[1] / oh, iw * t[2],
                                                            ih * t[3] / ow, ih * t[4] / oh, ih * t[5]),
                                   resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0))
        else:   # FILL: cover, centred
            canvas = ImageOps.fit(img, (ow, oh), Image.LANCZOS)
        if flip:
            canvas = ImageOps.mirror(canvas)
        op = paint.get("opacity", 1.0)
        if op < 1:
            canvas.putalpha(canvas.getchannel("A").point(lambda v: round(v * op)))
        if ellipse or any(radii):
            mask = Image.new("L", (ow, oh), 0)
            d = ImageDraw.Draw(mask)
            if ellipse:
                d.ellipse((0, 0, ow - 1, oh - 1), fill=255)
            else:
                d.rounded_rectangle((0, 0, ow - 1, oh - 1), radius=max(radii) * k * (lw / w if w else 1), fill=255)
            cut = Image.new("L", (ow, oh), 0)
            cut.paste(canvas.getchannel("A"), mask=mask)
            canvas.putalpha(cut)
        buf = io.BytesIO()
        canvas.save(buf, "PNG", optimize=True)
        return self.save(node.get("name") or "picture", ".png", buf.getvalue())

    def text(self, node, m, w, h, op, out):
        td = node.get("textData") or {}
        chars = td.get("characters") or ""
        if not chars.strip():
            return
        derived = node.get("derivedTextData") or {}
        lines = derived.get("baselines") or []
        # Line breaks where Figma wrapped the text (the graphic doesn't wrap).
        if len(lines) > 1:
            parts, last = [], 0
            for b in lines[1:]:
                i = b.get("firstCharacter")
                if not isinstance(i, int) or i <= last or i > len(chars):
                    continue
                piece = chars[last:i]
                parts.append(piece if piece.endswith("\n") else piece.rstrip(" ") + "\n")
                last = i
            chars = "".join(parts) + chars[last:]
        font = node.get("fontName") or {}
        style = (font.get("style") or "").lower().replace(" ", "")
        family = font.get("family") or "Inter"
        name = font.get("postscript") or (family + ("-" + font.get("style", "").replace(" ", "") if font.get("style") else ""))
        meta = (derived.get("fontMetaData") or [{}])[0]
        weight = meta.get("fontWeight") or next((v for k, v in WEIGHTS if k in style), 400)
        self.fonts.add(name)
        sx, sy = _scales(m)
        size = (node.get("fontSize") or 24)
        fills = [p for p in _visible(node.get("fillPaints")) if p.get("type") in ("SOLID",) or p.get("type", "").startswith("GRADIENT")]
        if fills:
            p = fills[-1]
            colour = _hex(p.get("color") if p.get("type") == "SOLID" else (sorted(p.get("stops") or [{}], key=lambda s: s.get("position", 0))[0].get("color")),
                          p.get("opacity", 1.0))
            if p.get("type") != "SOLID":
                self.note("gradient on text (its first colour used)")
        else:
            colour = "#ffffff"
        ls = node.get("letterSpacing") or {}
        tracking = ls.get("value", 0) * 10 if ls.get("units") == "PERCENT" else (ls.get("value", 0) / size * 1000 if size else 0)
        if lines and lines[0].get("lineHeight"):
            line_height = lines[0]["lineHeight"] / size
        else:
            lh = node.get("lineHeight") or {}
            line_height = {"PERCENT": lh.get("value", 100) / 100, "PIXELS": lh.get("value", size) / size if size else 1.2,
                           "RAW": lh.get("value", 1.2)}.get(lh.get("units"), 1.2)
        n_lines = chars.count("\n") + 1
        align = {"CENTER": "center", "RIGHT": "right", "JUSTIFIED": "left"}.get(node.get("textAlignHorizontal"), "left")
        # The box: at least its lines' height (Figma can trim it to the capitals),
        # and a little wider, so another font's spacing doesn't shrink it.
        bw = w
        bh = max(h, size * line_height * n_lines)
        slack = size * 0.5 if node.get("textAutoResize") == "WIDTH_AND_HEIGHT" else 0
        ox = {"left": 0, "center": -slack / 2, "right": -slack}[align]
        local = _mul(m, (1, 0, ox, 0, 1, 0))
        place, _ = _place(local, bw + slack, bh)
        layer = self.layer(node, place, op, "text",
                           text=chars.rstrip("\n"), font=name, size=round(size * sy, 2), color=colour, align=align,
                           valign="top" if lines else {"CENTER": "middle", "BOTTOM": "bottom"}.get(node.get("textAlignVertical"), "top"),
                           tracking=round(tracking, 1), caps=node.get("textCase") == "UPPER",
                           smallCaps=node.get("textCase") in ("SMALL_CAPS", "SMALL_CAPS_FORCED"),
                           lineHeight=round(line_height or 1.2, 3), fit="shrink", weight=weight,
                           italic="italic" in style or "oblique" in style, scroll=0)
        if lines:
            # (where Figma put the first line's baseline, from the top of its box)
            layer["baseline"] = round(((lines[0].get("position") or {}).get("y", 0)) * sy, 2)
        if (_visible(node.get("strokePaints")) and (node.get("strokeWeight") or 0) > 0):
            self.note("outline on text")
        if any(e.get("type") == "DROP_SHADOW" for e in _effects(node)):
            layer["shadow"] = True
        out.append(layer)

    # --- the frames ---
    def frames(self):
        """The top frames of every page, and any loose layers (as one more graphic)."""
        pages = [n for n in self.nodes if n.get("type") == "CANVAS" and not n.get("internalOnly")]
        frames, loose = [], []
        for page in pages:
            for top in self.kids.get(_gid(page.get("guid")), []):
                if top.get("internalOnly"):
                    continue
                if top.get("type") in FRAMES and (top.get("size") or {}).get("x"):
                    frames.append(top)
                elif top.get("type") == "SECTION":
                    frames += [c for c in self.kids.get(_gid(top.get("guid")), [])
                               if c.get("type") in FRAMES and (c.get("size") or {}).get("x")]
                else:
                    loose.append(top)
        return frames, loose

    def comp(self, title, nodes, w, h, top=None, at=None):
        """One graphic of the nodes (a frame's own look and what's in it, or loose layers)."""
        if abs(w / h - SCREEN_W / SCREEN_H) < 0.01 if h else False:
            k = SCREEN_W / w
        else:
            k = min(1.0, SCREEN_W / w, SCREEN_H / h) if w and h else 1.0
        ox, oy = (SCREEN_W - w * k) / 2, (SCREEN_H - h * k) / 2
        if at:
            ox, oy = ox - at[0] * k, oy - at[1] * k
        root = (k, 0, ox, 0, k, oy)
        comp = blank_comp(title)
        self.rel, self.folder = self.ws.unique_asset(title)
        os.makedirs(self.folder, exist_ok=True)
        self.used, self.top = set(), top
        layers = []
        for n in nodes:
            if top is not None:
                # (the frame where the graphic is: its own place doesn't count)
                self.top = dict(n, transform=None)
                self.walk(self.top, root, 1.0, True, [], layers)
            else:
                self.walk(n, root, 1.0, True, [], layers)
        taken = set()
        for layer in layers:
            layer.pop("_clipped", None)
            bg = layer.pop("_bg", False)
            if not bg and (layer["type"] == "text" or (layer["type"] == "image" and not GENERIC.match(layer["name"].strip())
                                                      and not layer["name"].endswith((" outline", " background")))):
                layer["field"] = _field_name(layer["name"], taken)
        comp["layers"] = tidy_groups(layers, keep_order=True)
        if not os.listdir(self.folder):
            os.rmdir(self.folder)
        return comp

    def run(self):
        frames, loose = self.frames()
        comps = []
        many = len(frames) + (1 if loose else 0) > 1
        for f in frames:
            size = f.get("size") or {}
            title = (f.get("name") or self.name) if many else self.name
            comps.append(self.comp(title, [f], size.get("x") or SCREEN_W, size.get("y") or SCREEN_H, top=f))
        if loose:
            # Loose layers (not in a frame): their bounds as the frame.
            pts = []
            for n in loose:
                m = _matrix(n.get("transform"))
                s = n.get("size") or {}
                for x, y in ((0, 0), (s.get("x", 0), 0), (0, s.get("y", 0)), (s.get("x", 0), s.get("y", 0))):
                    pts.append(_apply(m, x, y))
            if pts:
                x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
                x1, y1 = max(p[0] for p in pts), max(p[1] for p in pts)
                comps.append(self.comp(self.name + (" (outside frames)" if frames else ""), loose,
                                       max(x1 - x0, 1), max(y1 - y0, 1), at=(x0, y0)))
        return [c for c in comps if c["layers"]]


def import_fig(path, workspace, name):
    """Graphics from a Figma file: ([compositions], [fonts], [notes])."""
    from .psdimport import auto_animate, guess_kind
    with open(path, "rb") as f:
        blob = f.read()
    try:
        job = _Import(blob, workspace, name)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"{name} can't be read as a Figma file ({e})") from None
    comps = job.run()
    if not comps:
        raise ValueError(f"{name} has nothing in it to make a graphic of (its frames are empty)")
    for comp in comps:
        auto_animate(comp["layers"])
        comp["kind"] = guess_kind([l for l in comp["layers"] if l.get("visible", True)])
        log(f"Imported {comp['name']} from Figma: {len(comp['layers'])} layers")
    notes = []
    if any(l.get("visible") is False and l["name"].endswith(" background") for c in comps for l in c["layers"]):
        notes.append("the frame's background is a hidden layer (turn it on if you want it)")
    if job.missing_images:
        notes.append(f"{job.missing_images} picture{'s' if job.missing_images != 1 else ''} weren't in the file")
    if job.left_out:
        notes.append("left out: " + ", ".join(f"{what} ({n})" for what, n in sorted(job.left_out.items())))
    return comps, sorted(job.fonts), notes
