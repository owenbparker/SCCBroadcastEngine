"""Builds the "CEN Desk Front TV" board into the engine's SCC graphics
(apps/gfxengine/starter), from owen's vMix title CEN_Desk_Front_TV.gtzip.

The title's layout, made live: the two teams' colours glow in from the sides
(Global's Left / Right colour), their logos, names and series score, the
stage ("GRAND FINALS"), the game's logo on top and the tournament's logo at
the bottom, over the background loop like the other full-page boards.

    python tools/build_cen_desk.py

Run again after a change: the graphic is replaced, its older signature kept
in pack_history (so workspaces with the untouched older copy get the new one)
and it is in pack_new (so every workspace made from the pack gets it once).
"""

import json
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STARTER = os.path.join(ROOT, "apps", "gfxengine", "starter")
sys.path.insert(0, os.path.join(ROOT, "apps", "gfxengine"))
from gfxengine.pack import signature  # noqa: E402

NAME = "CEN Desk Front TV"
FOLDER = f"assets/{NAME}"
W, H = 1920, 1080
OUT_MS = 500        # the title's TransitionOut: everything fades in 0.5 s


def _glows():
    """The side glows (white, for the team colour; 'recolor') and their dark
    shades: vMix's 1040 x 1880 rectangles blurred by 170, at half size."""
    os.makedirs(os.path.join(STARTER, FOLDER), exist_ok=True)
    k, pad = 0.5, 400       # (drawn on a bigger canvas so the blur doesn't fade at the frame's edge)
    cw, ch = int((W + 2 * pad) * k), int((H + 2 * pad) * k)
    sigma = 85 * k
    for side, x in (("left", -450), ("right", 1330)):
        x0, x1 = (x + pad) * k, (x + 1040 + pad) * k
        y0, y1 = (-400 + pad) * k, (1480 + pad) * k
        glow = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(glow).rectangle([x0, y0, x1, y1], fill=255)
        glow = glow.filter(ImageFilter.GaussianBlur(sigma))
        # The shade: clear to 65 % black across the rectangle, darkest towards the middle.
        shade = Image.new("L", (cw, ch), 0)
        d = ImageDraw.Draw(shade)
        for i in range(int(x0), int(x1) + 1):
            t = (i - x0) / max(1, x1 - x0)
            if side == "right":
                t = 1 - t
            a = 0 if t <= 0.4327 else (t - 0.4327) / (1 - 0.4327) * 0xA6
            d.line([(i, y0), (i, y1)], fill=int(a))
        shade = shade.filter(ImageFilter.GaussianBlur(sigma))
        box = (int(pad * k), int(pad * k), int(pad * k) + int(W * k), int(pad * k) + int(H * k))
        white = Image.new("RGBA", (int(W * k), int(H * k)), (255, 255, 255, 0))
        white.putalpha(glow.crop(box))
        white.save(os.path.join(STARTER, FOLDER, f"{side} glow.png"), optimize=True)
        black = Image.new("RGBA", (int(W * k), int(H * k)), (0, 0, 0, 0))
        black.putalpha(shade.crop(box))
        black.save(os.path.join(STARTER, FOLDER, f"{side} shade.png"), optimize=True)


def _anim(kind, delay, dur):
    return {"in": {"type": kind, "dur": int(dur * 1000), "delay": int(delay * 1000)},
            "out": {"type": "fade", "dur": OUT_MS, "delay": 0}}


def _layer(lid, name, x, y, w, h, anim, **more):
    out = {"id": lid, "name": name, "x": x, "y": y, "w": w, "h": h, "opacity": 1, "rotation": 0, "visible": True,
           "blend": "normal", "field": "", "anim": anim}
    out.update(more)
    return out


SHADOW_S = [{"type": "shadow", "x": 0, "y": 3, "blur": 6, "color": "#00000099"}]
SHADOW_L = [{"type": "shadow", "x": 0, "y": 5, "blur": 10, "color": "#00000099"}]
WHITE = "{{Global!Text primary}}"


def _text(lid, name, x, y, w, h, text, font, size, align, anim, weight=700, field="", fx=SHADOW_S, fit="shrink"):
    return _layer(lid, name, x, y, w, h, anim, type="text", text=text, font=font, size=size, color=WHITE,
                  align=align, valign="top", tracking=0, caps=True, lineHeight=1.15, fit=fit, weight=weight,
                  italic=False, scroll=0, field=field, fx=fx)


def _image(lid, name, x, y, w, h, src, anim, **more):
    more.setdefault("fit", "contain")
    return _layer(lid, name, x, y, w, h, anim, type="image", src=src, loop=True, **more)


def build():
    _glows()
    NEO, SCORE = "Neographik MT Std", "Bourgeois Medium Condensed"
    layers = [
        # The backdrop and the background loop, as on the other full-page boards.
        _layer("lcen0bd01", "Backdrop", 0, 0, W, H, _anim("fade", 0.024, 0.45), opacity=0.749, type="image",
               src="assets/Team stats/Layer 1.png", fit="fill", loop=True, tint="{{Global!BG loop colour}}"),
        _layer("lcen0bl02", "Background loop", 0, 0, W, H, _anim("fade", 0, 0.6), blend="screen", type="video",
               src="{{Global!BG loop}}", fit="cover", loop=True, audio=False, tint="{{Global!BG loop colour}}",
               brightness="{{Global!BG loop brightness}}", speed="{{Global!BG loop speed}}"),
        # Each team's colour glowing in from its side, darker towards the middle.
        _image("lcen0rc03", "Team B colour", 0, 0, W, H, f"{FOLDER}/right glow.png", _anim("slide-left", 0, 0.7),
               opacity=0.75, fit="fill", recolor="{{Global!Right color}}"),
        _image("lcen0lc04", "Team A colour", 0, 0, W, H, f"{FOLDER}/left glow.png", _anim("slide-right", 0, 0.7),
               opacity=0.75, fit="fill", recolor="{{Global!Left color}}"),
        _image("lcen0rs05", "Team B shade", 0, 0, W, H, f"{FOLDER}/right shade.png", _anim("slide-left", 0, 0.7),
               fit="fill"),
        _image("lcen0ls06", "Team A shade", 0, 0, W, H, f"{FOLDER}/left shade.png", _anim("slide-right", 0, 0.7),
               fit="fill"),
        _image("lcen0gl07", "Game logo", 560, 49, 800, 206, "{{Global!Game logo}}", _anim("scale", 0.2, 0.5),
               fx=SHADOW_S),
        _text("lcen0rt08", "Round", 619, 255, 684, 70, "{{Global!Stage}}", NEO, 60, "center", _anim("fade", 0.5, 0.4)),
        _image("lcen0ll09", "Left team logo", 67, 249, 500, 500, "{{Global!Left logo}}", _anim("scale", 0.4, 0.5),
               fx=SHADOW_L),
        _image("lcen0rl10", "Right team logo", 1353, 249, 500, 500, "{{Global!Right logo}}", _anim("scale", 0.4, 0.5),
               fx=SHADOW_L),
        _text("lcen0vs11", "VS", 880, 446, 160, 139, "VS", "Dharma Gothic E", 150, "center", _anim("fade", 0.9, 0.4),
              weight=900, field="VS"),
        # Team names: a small line and a big one; which pair shows depends on the
        # name (Global "Left name small over"...: "St. Clair Saints" = small
        # "St. Clair" over a big "Saints", "Fuel Esports" = a big "Fuel" over "Esports").
        _text("lcen0ls12", "Left name small over", 94, 839, 740, 90, "{{Global!Left name small over}}", NEO, 72, "left",
              _anim("wipe-right", 0.6, 0.5)),
        _text("lcen0lb13", "Left name big low", 92, 918, 861, 150, "{{Global!Left name big low}}", NEO, 110, "left",
              _anim("wipe-right", 0.5, 0.5), fx=SHADOW_L),
        _text("lcen0lh14", "Left name big high", 92, 830, 861, 150, "{{Global!Left name big high}}", NEO, 110, "left",
              _anim("wipe-right", 0.5, 0.5), fx=SHADOW_L),
        _text("lcen0lu15", "Left name small under", 94, 957, 740, 90, "{{Global!Left name small under}}", NEO, 72,
              "left", _anim("wipe-right", 0.6, 0.5)),
        _text("lcen0rs16", "Right name small over", 1084, 839, 740, 90, "{{Global!Right name small over}}", NEO, 72,
              "right", _anim("wipe-left", 0.6, 0.5)),
        _text("lcen0rb17", "Right name big low", 967, 918, 861, 150, "{{Global!Right name big low}}", NEO, 110,
              "right", _anim("wipe-left", 0.5, 0.5), fx=SHADOW_L),
        _text("lcen0rh18", "Right name big high", 967, 830, 861, 150, "{{Global!Right name big high}}", NEO, 110,
              "right", _anim("wipe-left", 0.5, 0.5), fx=SHADOW_L),
        _text("lcen0ru19", "Right name small under", 1084, 957, 740, 90, "{{Global!Right name small under}}", NEO, 72,
              "right", _anim("wipe-left", 0.6, 0.5)),
        _text("lcen0pb20", "Presented by", 760, 1019, 400, 50, "PRESENTED BY", NEO, 24, "center",
              _anim("fade", 1.2, 0.5), field="Presented by"),
        _text("lcen0rx21", "Right score", 1042, 262, 300, 400, "{{Global!Right score}}", SCORE, 380, "center",
              _anim("scale", 0.8, 0.5), fx=SHADOW_L, fit="squeeze"),
        _text("lcen0lx22", "Left score", 555, 262, 300, 400, "{{Global!Left score}}", SCORE, 380, "center",
              _anim("scale", 0.8, 0.5), fx=SHADOW_L, fit="squeeze"),
        _image("lcen0tl23", "Tournament logo", 705, 717, 505, 307, "{{Global!Tournament logo}}",
               _anim("scale", 0.2, 0.5)),
    ]
    # The teams and the game come from the "Desk" table: Global's, unless other
    # teams (from the Teams tab) or another game are picked for the board in Control.
    layers = json.loads(re.sub(r"\{\{Global!((Left|Right) [^}]*|Game logo)\}\}", r"{{Desk!\1}}", json.dumps(layers)))
    comp = {"id": "ccendesk1", "name": NAME, "layer": 0, "width": W, "height": H, "kind": "board", "layers": layers}

    path = os.path.join(STARTER, "project.json")
    with open(path, encoding="utf-8") as f:
        project = json.load(f)
    comps = project["compositions"]
    old = next((c for c in comps if c["name"] == NAME), None)
    if old:
        comps[comps.index(old)] = comp
    else:
        comps.append(comp)
    hist = project.setdefault("pack_history", {}).setdefault(NAME, [])
    if signature(comp) not in hist:
        hist.append(signature(comp))
    if NAME not in project.setdefault("pack_new", []):
        project["pack_new"].append(NAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(project, f, indent=1, ensure_ascii=False)
    print(f"{NAME}: {len(layers)} layers, signature {signature(comp)}")


if __name__ == "__main__":
    build()
