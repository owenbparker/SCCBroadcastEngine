"""Builds the SCC 2026 graphics (owen's PSDs) into the engine's starter pack,
linked to live data, and adds them to every workspace made from the pack
(starter/project.json "pack_new"; see apps/gfxengine/gfxengine/pack.py).

    python tools/build_psd_graphics.py <folder with the PSDs>

Each PSD goes through the engine's own Photoshop import (psdimport.py), then
its layers are linked up here: team logos and scores from Global, sponsors,
the run of show and its countdown, casters, the spotlight player, head to
head stats, a team's past results. Running it again replaces the graphics
(and records the old versions in pack_history, so untouched copies in
workspaces are brought up to date).
"""

import copy
import io
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GFX = os.path.join(ROOT, "apps", "gfxengine")
sys.path[:0] = [GFX, ROOT]

from gfxengine import pack  # noqa: E402
from gfxengine.project import Workspace, new_id  # noqa: E402
from gfxengine.psdimport import import_psd  # noqa: E402

STARTER = os.path.join(GFX, "starter")
FONT_BOLD, FONT_LIGHT = "OpenSauceOne-Bold", "OpenSauceOne-Light"


# --- helpers -------------------------------------------------------------------------

class G:
    """A graphic being linked up."""

    def __init__(self, comp, folder):
        self.c = comp
        self.layers = comp["layers"]
        self.folder = folder    # its assets on disk
        # (Photoshop's hidden layers - the white "Layer 0" - aren't wanted)
        self.layers[:] = [l for l in self.layers if l.get("visible", True)]
        # Duplicated groups (the Footer's artboard and its copies outside it) once.
        seen, keep = set(), []
        for l in self.layers:
            k = (l["type"], l["x"], l["y"], l["w"], l["h"], l.get("text", ""))
            if k in seen:
                continue
            seen.add(k)
            keep.append(l)
        self.layers[:] = keep
        for l in self.layers:
            l["field"] = ""    # (fields only where set below)

    def all(self, name):
        return [l for l in self.layers if l["name"] == name]

    def one(self, name, n=0, key=None):
        found = self.all(name)
        if key:
            found.sort(key=key)
        return found[n]

    def text(self, l, value, x=None, w=None, align=None, field="", **kw):
        l["text"] = value
        l["field"] = field
        if x is not None:
            l["x"] = round(x)
        if w is not None:
            l["w"] = round(w)
        if align:
            l["align"] = align
        l.update(kw)
        return l

    def picture(self, l, src, fit="contain", **kw):
        l["src"] = src
        l["fit"] = fit
        l.update(kw)
        return l

    def add(self, after, layer):
        self.layers.insert(self.layers.index(after) + 1, layer)
        return layer

    def copy(self, l, **kw):
        out = copy.deepcopy(l)
        out["id"] = new_id("l")
        out.update(kw)
        return out

    def new_picture(self, name, x, y, w, h, src, after, **kw):
        return self.add(after, dict({"id": new_id("l"), "name": name, "type": "image", "x": round(x), "y": round(y),
                                     "w": round(w), "h": round(h), "opacity": 1, "rotation": 0, "visible": True,
                                     "blend": "normal", "field": "", "anim": copy.deepcopy(after["anim"]),
                                     "src": src, "fit": "contain", "loop": True}, **kw))

    def drop(self, l):
        self.layers.remove(l)
        path = os.path.join(self.folder, os.path.basename(l.get("src", "")))
        if l.get("src", "").startswith("assets/") and os.path.isfile(path):
            os.remove(path)


def when(value, op="has"):
    return [{"value": value, "op": op}]


def backdrop(g):
    """The full-page boards' backdrop and the Global background loop (as the
    other SCC boards have), under everything."""
    sp = json.load(open(os.path.join(STARTER, "project.json"), encoding="utf-8"))
    board = next(c for c in sp["compositions"] if c["name"] == "Sponsor board")
    under = [copy.deepcopy(l) for l in board["layers"] if l["name"] in ("Backdrop", "Background loop")]
    for l in under:
        l["id"] = new_id("l")
    g.layers[:0] = under


def smart_object_without(psd_path, layer_name, hide):
    """A smart object's picture rendered without some of its own layers (a
    background with the design's logos baked in), and how to map its
    coordinates to the canvas. Returns (PIL image, (dx, dy), {name: [bboxes]})."""
    from psd_tools import PSDImage
    psd = PSDImage.open(psd_path)
    outer = next(l for l in psd.descendants() if l.name == layer_name and l.kind == "smartobject")
    inner = PSDImage.open(io.BytesIO(outer.smart_object.data))
    boxes = {}
    for l in inner.descendants():
        if l.name in hide:
            boxes.setdefault(l.name, []).append(l.bbox)
            l.visible = False
    content = [l for l in inner if l.visible]
    left = min(l.bbox[0] for l in content)
    top = min(l.bbox[1] for l in content)
    image = inner.composite(force=True)
    ox, oy, ox2, oy2 = outer.bbox
    image = image.crop((left, top, left + (ox2 - ox), top + (oy2 - oy)))
    return image, (ox - left, oy - top), boxes


# --- the graphics --------------------------------------------------------------------

def footer(g):
    # Sponsors in turn in the sponsor box.
    sp = g.one("Subway-Logo")
    g.picture(sp, "{{Sponsors}}", x=58, y=896, w=229, h=126, name="Sponsor")
    # The teams and the series score.
    holder_l, logo_l = sorted(g.all("left-logo"), key=lambda l: l["w"], reverse=True)
    holder_r, logo_r = sorted(g.all("right-logo"), key=lambda l: l["w"], reverse=True)
    holder_l["name"], holder_r["name"] = "Left logo box", "Right logo box"
    g.picture(logo_l, "{{Global!Left logo}}", name="Left logo")
    g.picture(logo_r, "{{Global!Right logo}}", name="Right logo")
    g.text(g.one("0-0"), "{{Global!Left score}}-{{Global!Right score}}", name="Score", fit="squeeze")
    # Now / next / later from tonight's run of show (with each one's start time under it).
    for name, key, x, w in (("now - break", "Now", 752, 280), ("next - map 2", "Next", 1050, 290), ("later - map 3", "Later", 1354, 285)):
        l = g.text(g.one(name), "{{Run of show!%s text}}" % key, x=x, w=w, align="left", name=key, show="{{Run of show!Shown}}")
        t = g.add(l, g.copy(l, name=key + " time", text="{{Run of show!%s time}}" % key, font=FONT_LIGHT,
                            size=round(l["size"] * 1.35, 2), y=l["y"] + 52, h=round(l["h"] * 1.35)))
        t["anim"]["in"]["delay"] += 60
    g.one("lines")["show"] = "{{Run of show!Shown}}"
    # No run of show: the event's name across the middle.
    now = g.one("Now")
    g.add(g.one("Later time"), g.copy(now, name="Event", text="{{Global!Event}}", x=760, w=862, align="center",
                                      size=44, y=930, h=60, show="", when=when("{{Run of show!Shown}}", "empty")))
    # The countdown to the next map ("MAP 2 IN"), else Global's clock.
    label, clock = g.one("map 2 in"), g.one("00:00")
    g.text(label, "{{Run of show!Next map in}}", name="Next map in", when=when("{{Run of show!Next map}}"),
           x=1668, w=196, fit="squeeze")
    g.text(clock, "{{countdown:Run of show!Next map at}}", name="Countdown", fit="squeeze",
           when=when("{{Run of show!Next map}}"))
    g.add(clock, g.copy(label, name="Clock label", text="{{Global!Clock label}}", when=when("{{Run of show!Next map}}", "empty")))
    g.add(g.one("Clock label"), g.copy(clock, name="Clock", text="{{clock}}", when=when("{{Run of show!Next map}}", "empty")))


def back_in(g, psd):
    from PIL import Image, ImageFilter
    bg = g.one("bg")
    bg["name"] = "Background (design)"
    image, (dx, dy), boxes = smart_object_without(psd, "bg", {"SCS_WHITEBORDER"})
    image.save(os.path.join(g.folder, "bg.png"), optimize=True)
    bg["w"], bg["h"] = image.size
    # The bug's own shapes (inner coordinates): the three boxes side by side, and the two tabs.
    from psd_tools import PSDImage
    outer = next(l for l in PSDImage.open(psd).descendants() if l.name == "bg" and l.kind == "smartobject")
    inner = PSDImage.open(io.BytesIO(outer.smart_object.data))
    shapes = [l for l in inner.descendants() if l.name in ("Rectangle 7", "Rectangle 10") and l.visible]
    boxes7 = sorted((l for l in shapes if l.name == "Rectangle 7"), key=lambda l: l.bbox[0])
    left_box, middle_box, right_box = boxes7
    tabs = [l for l in shapes if l.name == "Rectangle 10"]
    # Where the background loop shows: the middle box and the tabs, inside their gold edges.
    mask = Image.new("L", image.size, 0)
    for l in [middle_box] + tabs:
        alpha = l.composite().getchannel("A")
        mask.paste(alpha, (l.bbox[0] + dx - bg["x"], l.bbox[1] + dy - bg["y"]), alpha)
    mask = mask.filter(ImageFilter.MinFilter(5))   # (2px in: the edges stay gold)
    white = Image.new("RGBA", image.size, (255, 255, 255, 0))
    white.putalpha(mask)
    white.save(os.path.join(g.folder, "loop-mask.png"), optimize=True)
    under_loop = g.add(bg, {"id": new_id("l"), "name": "Background loop base", "type": "rect", "x": bg["x"], "y": bg["y"],
                            "w": bg["w"], "h": bg["h"], "opacity": 1, "rotation": 0, "visible": True, "blend": "normal",
                            "field": "", "anim": copy.deepcopy(bg["anim"]), "fill": "#0a0a0c", "radius": 0,
                            "stroke": "#f5c518", "strokeWidth": 0, "mask": f"assets/{g.c['name']}/loop-mask.png",
                            "show": "{{Global!Bug loop}}"})
    sp = json.load(open(os.path.join(STARTER, "project.json"), encoding="utf-8"))
    board = next(c for c in sp["compositions"] if c["name"] == "Sponsor board")
    loop = copy.deepcopy(next(l for l in board["layers"] if l["name"] == "Background loop"))
    loop.update(id=new_id("l"), name="Background loop", x=bg["x"], y=bg["y"], w=bg["w"], h=bg["h"], blend="screen",
                mask=f"assets/{g.c['name']}/loop-mask.png", show="{{Global!Bug loop}}", zoom="{{Global!Bug loop zoom}}",
                anim=copy.deepcopy(bg["anim"]))
    after = g.add(under_loop, loop)
    # The boxes behind the logos: each team's colour (inside the gold edge).
    for side, l in (("Left", left_box), ("Right", right_box)):
        x1, y1, x2, y2 = l.bbox
        after = g.add(after, {"id": new_id("l"), "name": f"{side} colour", "type": "rect", "x": x1 + dx + 2, "y": y1 + dy + 2,
                              "w": x2 - x1 - 4, "h": y2 - y1 - 4, "opacity": 1, "rotation": 0, "visible": True,
                              "blend": "normal", "field": "", "anim": copy.deepcopy(bg["anim"]),
                              "fill": "{{Global!%s color}}" % side, "radius": 0, "stroke": "#f5c518", "strokeWidth": 0})
    for side, (x1, y1, x2, y2) in zip(("Left", "Right"), sorted(boxes["SCS_WHITEBORDER"])):
        after = g.new_picture(f"{side} logo", x1 + dx, y1 + dy, x2 - x1, y2 - y1, "{{Global!%s logo}}" % side, after,
                              anim={"in": {"type": "scale", "dur": 450, "delay": 120}, "out": {"type": "fade", "dur": 250, "delay": 0}})
    g.text(g.one("back in"), "BACK IN", x=1500, w=104, align="left", field="Title", name="Title")
    g.text(g.one("00:00"), "{{clock}}", x=1760, w=122, align="center", name="Clock", fit="squeeze")
    g.one("vs")["name"] = "VS"


def back_soon(g):
    g.one("logo")["name"] = "Logo"
    g.text(g.one("back soon"), "BACK SOON", x=180, w=272, align="left", field="Title", name="Title")
    g.text(g.one("00:00"), "{{clock}}", x=180, w=200, align="left", name="Clock", fit="squeeze")


def head_chicklet(g):
    photo = g.one("woddy (1) copy 4")
    g.picture(photo, "{{Spotlight!Headshot}}", name="Headshot", position="bottom", show="{{Spotlight!Headshot}}")
    # (no headshot: the player's team logo instead)
    g.new_picture("Team logo", 30, 870, 170, 105, "{{Spotlight!Team logo}}", photo,
                  when=when("{{Spotlight!Headshot}}", "empty"))
    g.text(g.one("woddy"), "{{Spotlight!Name}}", x=234, w=360, align="left", name="Name")
    g.text(g.one("scc valorant"), "{{Spotlight!Line}}", x=236, w=290, align="left", name="Team and game")


def casters(g, count):
    names = sorted([l for l in g.layers if l["type"] == "text" and l["size"] > 33], key=lambda l: l["x"])
    handles = sorted([l for l in g.layers if l["type"] == "text" and l["size"] <= 33], key=lambda l: l["x"])
    if count == 1:
        places = [(212, 330, "left", 212, 272, "left")]
    else:
        places = [(218, 330, "left", 218, 260, "left"), (790, 455, "center", 818, 400, "center"),
                  (1482, 342, "right", 1530, 294, "right")]
    for i, (n, h, (nx, nw, na, hx, hw, ha)) in enumerate(zip(names, handles, places), 1):
        g.text(n, "CASTER NAME", x=nx, w=nw, align=na, field=f"Caster {i}", name=f"Caster {i}")
        g.text(h, "@HANDLE", x=hx, w=hw, align=ha, field=f"Caster {i} handle", name=f"Caster {i} handle")
    g.one("SCS_WHITEBORDER")["name"] = "Logo"


def head_to_head(g):
    backdrop(g)
    texts = [l for l in g.layers if l["type"] == "text"]
    band = lambda l: round((l["y"] - 355) / 122) + 1   # noqa: E731  (the four rows of numbers)
    for r in range(1, 5):
        left, title, right = sorted([l for l in texts if 340 <= l["y"] <= 740 and band(l) == r], key=lambda l: l["x"])
        g.text(left, "{{Head to head!Left row %d}}" % r, name=f"Left row {r}", fit="squeeze", x=640, w=200)
        g.text(right, "{{Head to head!Right row %d}}" % r, name=f"Right row {r}", fit="squeeze", x=1082, w=200)
        g.text(title, "{{Head to head!Row %d title}}" % r, name=f"Row {r} title", fit="squeeze", x=880, w=160)
    g.text(g.one("head to head"), "HEAD TO HEAD", field="Title", name="Title")
    # The two players.
    for name, side in (("Jazii", "Left"), ("Cale", "Right")):
        l = g.picture(g.one(name), "{{Head to head!%s headshot}}" % side, name=f"{side} headshot", position="bottom",
                      show="{{Head to head!%s headshot}}" % side)
        g.new_picture(f"{side} logo (no headshot)", l["x"] + 40, 380, l["w"] - 80, 340, "{{Head to head!%s team logo}}" % side, l,
                      when=when("{{Head to head!%s headshot}}" % side, "empty"))
    g.text(g.one("jazii"), "{{Head to head!Left name}}", x=188, w=350, align="left", name="Left name")
    g.text(g.one("kale"), "{{Head to head!Right name}}", x=1385, w=345, align="right", name="Right name")
    g.text(g.one("dps"), "{{Head to head!Left role}}", x=500, w=118, align="right", name="Left role", fit="squeeze")
    g.text(g.one("flex"), "{{Head to head!Right role}}", x=1302, w=118, align="left", name="Right role", fit="squeeze")
    right_team, left_team = sorted(g.all("st. clair"), key=lambda l: -l["x"])
    g.text(left_team, "{{Head to head!Left team short}}", x=66, w=420, align="left", name="Left team")
    g.text(right_team, "{{Head to head!Right team short}}", x=1432, w=420, align="right", name="Right team")
    # The team boxes: the left one had its logo baked in (clipped to it): the plain box, and the logo on top.
    boxes = sorted(g.all("Rectangle 16 copy"), key=lambda l: l["x"])
    plain = boxes[1]["src"]
    old = boxes[0]["src"]
    boxes[0]["src"] = plain
    if os.path.isfile(os.path.join(g.folder, os.path.basename(old))):
        os.remove(os.path.join(g.folder, os.path.basename(old)))
    boxes[0]["name"], boxes[1]["name"] = "Left team box", "Right team box"
    right_logo = g.one("SCS_COLOUR")
    g.picture(right_logo, "{{Head to head!Right team logo}}", name="Right team logo")
    g.add(boxes[0], g.copy(right_logo, name="Left team logo", src="{{Head to head!Left team logo}}",
                           x=right_logo["x"] - (1778 - 85), y=right_logo["y"] - 1))
    g.c["kind"] = "board"


def recent_results(g):
    backdrop(g)
    # Four past matches down the left: (row by its top edge) team v opponent, score, label.
    tops = [29, 285, 541, 797]
    row_of = lambda l: max((i for i, t in enumerate(tops, 1) if l["y"] >= t - 8), default=0) if l["x"] < 540 else 0   # noqa: E731
    labels = sorted([l for l in g.layers if l["type"] == "text" and l["text"].lower().startswith("week")], key=lambda l: l["y"])
    for i, l in enumerate(labels, 1):
        g.text(l, "{{Results!Match %d label}}" % i, x=40, w=482, align="center", name=f"Match {i} label")
    for l in list(g.layers):
        r = row_of(l)
        if l in labels:
            l["show"] = "{{Results!Match %d show}}" % (labels.index(l) + 1)
            continue
        if not r or l.get("name", "").startswith("Background") or l["name"] == "Backdrop":
            continue
        # (the label bar under a row is in the next row's band: it goes with its label)
        if l["name"].startswith("Rectangle 11"):
            n = min(range(4), key=lambda i: abs(labels[i]["y"] - l["y"])) + 1
            l["show"] = "{{Results!Match %d show}}" % n
            l["name"] = f"Match {n} label bar"
            continue
        l["show"] = "{{Results!Match %d show}}" % r
        if l["name"] == "SCS_WHITEBORDER":
            g.picture(l, "{{Results!Match %d team logo}}" % r, name=f"Match {r} team logo")
        elif l["name"] == "SCS_WHITEBORDER copy":
            g.picture(l, "{{Results!Match %d opponent logo}}" % r, name=f"Match {r} opponent logo")
        elif l["type"] == "text":
            g.text(l, "{{Results!Match %d score}}" % r, name=f"Match {r} score", fit="squeeze")
        else:
            l["name"] = f"Match {r} " + l["name"].lower()
    # The team along the bottom.
    team_logo = next(l for l in g.layers if l["name"] == "SCS_WHITEBORDER" and l["x"] > 540)
    g.picture(team_logo, "{{Results!Team logo}}", name="Team logo")
    g.text(g.one("st. clair saints"), "{{Results!Team}}", x=781, w=1090, align="left", name="Team")
    g.text(g.one("nace superconference results"), "{{Results!Title}}", x=781, w=1090, align="left", field="Title",
           name="Title")
    # Its five players (headshots from the team list), left to right.
    shots = sorted([l for l in g.layers if l["name"].startswith("Woody2026")], key=lambda l: l["x"])
    for n, l in enumerate(shots, 1):
        g.picture(l, "{{Roster!Player %d headshot}}" % n, name=f"Player {n} headshot", position="bottom",
                  show="{{Roster!Player %d headshot}}" % n)
    panel = g.one("Rectangle 12 copy")
    panel["name"] = "Players panel"
    g.new_picture("Team logo (no headshots)", 1027, 191, 400, 500, "{{Results!Team logo}}", panel,
                  show="{{Roster!No headshots}}")
    g.c["kind"] = "board"


GRAPHICS = [
    # (graphic's name, PSD, link it up, its kind)
    ("Footer", "Footer New.psd", lambda g, p: footer(g), "overlay"),
    ("Back in bug", "Back In Teams - BUG.psd", back_in, "overlay"),
    ("Back soon bug", "Back Soon - BUG.psd", lambda g, p: back_soon(g), "overlay"),
    ("Head chicklet", "Head Chicklet - Lower Third.psd", lambda g, p: head_chicklet(g), "lower third"),
    ("Caster 1x lower third", "Caster 1x - Lower Third.psd", lambda g, p: casters(g, 1), "lower third"),
    ("Caster 3x lower third", "Caster 3x - Lower Third.psd", lambda g, p: casters(g, 3), "lower third"),
    ("Recent results", "RECENT RESULTS - FPB.psd", lambda g, p: recent_results(g), "board"),
    ("Head to head", "Head to Head - FPB.psd", lambda g, p: head_to_head(g), "board"),
]


def build(psd_dir, only=None):
    tmp = tempfile.mkdtemp()
    try:
        ws = Workspace(tmp, starter="")
        sp_path = os.path.join(STARTER, "project.json")
        with open(sp_path, encoding="utf-8") as f:
            sp = json.load(f)
        for name, psd, link, kind in GRAPHICS:
            if only and name not in only:
                continue
            path = os.path.join(psd_dir, psd)
            comp, fonts = import_psd(path, ws, name)
            folder = os.path.join(tmp, "assets", name)
            g = G(comp, folder)
            link(g, path)
            comp["kind"] = kind
            for l in comp["layers"]:
                if l["type"] == "text" and l.get("font", "").lower().startswith("opensauce"):
                    l["weight"] = 300 if "light" in l["font"].lower() else 700
            # Only the files it uses, into starter/assets/<name>/.
            used = {os.path.basename(l[k]) for l in comp["layers"] for k in ("src", "mask")
                    if str(l.get(k, "")).startswith(f"assets/{name}/")}
            dest = os.path.join(STARTER, "assets", name)
            shutil.rmtree(dest, ignore_errors=True)
            os.makedirs(dest)
            for fn in sorted(used):
                shutil.copy2(os.path.join(folder, fn), os.path.join(dest, fn))
            # In the pack (replacing an older build of it).
            old = next((i for i, c in enumerate(sp["compositions"]) if c["name"] == name), None)
            if old is not None:
                comp["id"] = sp["compositions"][old]["id"]
                hist = sp["pack_history"].setdefault(name, [])
                sig = pack.signature(sp["compositions"][old])
                if sig not in hist:
                    hist.append(sig)
                sp["compositions"][old] = comp
            else:
                sp["compositions"].append(comp)
            hist = sp["pack_history"].setdefault(name, [])
            if pack.signature(comp) not in hist:
                hist.append(pack.signature(comp))
            if name not in sp["pack_new"]:
                sp["pack_new"].append(name)
            print(f"{name}: {len(comp['layers'])} layers, {len(used)} files ({', '.join(fonts)})")
        with open(sp_path, "w", encoding="utf-8") as f:
            json.dump(sp, f, indent=1, ensure_ascii=False)
            f.write("\n")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    build(sys.argv[1], set(sys.argv[2:]) or None)
