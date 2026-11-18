"""vMix GT titles (.gtzip) to a new graphic (Composer's Import button).

A .gtzip is a zip: document.xml (the title), resources.xml (which zip entry
holds each picture) and the pictures, stored under GUID names.

document.xml is a tree of Compositions:

    <Composition Width="1920" Height="1080">
      <Layer Name=".." Dimensions="w,h,0" Location="x,y,0">   a group, its own
        <Layer.Composition><Composition Width= Height=>       canvas scaled into w x h
      <Rectangle Name=".." Dimensions= Location= Opacity=>    picture (Bitmap brush)
        <Rectangle.Fill><Brush Type="Bitmap"><Brush.Bitmap>   or solid colour
          <Bitmap Source="guid\\name.png"/>
      <Ellipse ...>                                            same, round
      <TextBlock Name= Text= FontFamily= FontSize= ...>       text (a field)
        <TextBlock.Fill><Brush Color="#AARRGGBB"/>
      <Storyboard Type="Continuous|TransitionIn|TransitionOut">
        <Storyboard.Animations>
          <RotateContinuous Object="name" Speed= Direction=/>  -> layer "spin"
          <Fade Object= .../>, <Slide.../>, <Wipe.../> ...     -> layer anim in/out

Every picture becomes a PNG in assets/<title>/, every text a field that
Control can change, like the text fields of a vMix title.
"""

import os
import re
import xml.etree.ElementTree as ET
import zipfile

from .log import log
from .project import ANIM_NONE, blank_comp, new_id
from .psdimport import _field_name, auto_animate, guess_kind

EXT = ".gtzip"
SHAPES = ("Rectangle", "Ellipse", "Image", "Picture")


def is_gt(path):
    """A zip holding a vMix title (a .gtzip, or one renamed .zip)."""
    try:
        with zipfile.ZipFile(path) as z:
            return "document.xml" in z.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def _xml(blob):
    """document.xml says utf-16 but is often written as utf-8 (or ASCII)."""
    if blob[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = blob.decode("utf-16")
    else:
        text = blob.decode("utf-8-sig", errors="replace")
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
    return ET.fromstring(text)


def _nums(value, n=2, default=0.0):
    parts = [p for p in (value or "").replace(" ", "").split(",") if p != ""]
    out = []
    for i in range(n):
        try:
            out.append(float(parts[i]))
        except (IndexError, ValueError):
            out.append(default)
    return out


def _colour(value):
    """'#AARRGGBB' (or #RRGGBB) -> ('#rrggbb', alpha 0..1)."""
    v = (value or "").strip().lstrip("#")
    if len(v) == 8:
        return "#" + v[2:].lower(), int(v[:2], 16) / 255
    if len(v) == 6:
        return "#" + v.lower(), 1.0
    return "#ffffff", 1.0


def _brush(el, prop):
    """The <Brush> of el's <X.Fill> (prop = "Fill"), or None."""
    holder = el.find(f"{el.tag}.{prop}")
    return holder.find("Brush") if holder is not None else None


def _bitmap(brush):
    if brush is None:
        return None
    bm = brush.find("Brush.Bitmap/Bitmap")
    if bm is None:
        bm = brush.find(".//Bitmap")
    return bm.get("Source") if bm is not None else None


def _base_layer(name, x, y, w, h, opacity, visible=True):
    return {"id": new_id("l"), "name": name, "x": round(x), "y": round(y), "w": max(1, round(w)), "h": max(1, round(h)),
            "opacity": round(max(0.0, min(1.0, opacity)), 3), "rotation": 0, "visible": visible, "blend": "normal",
            "field": "", "anim": {"in": dict(ANIM_NONE), "out": dict(ANIM_NONE)}}


# vMix storyboard animations -> the engine's layer animations.
def _anim_type(tag, direction):
    t, d = tag.lower(), (direction or "").lower()
    if "fade" in t:
        return "fade"
    if "wipe" in t or "reveal" in t:
        return {"left": "wipe-left", "up": "wipe-up", "down": "wipe-down"}.get(d, "wipe-right")
    if "slide" in t or "fly" in t or "move" in t or "push" in t:
        return {"left": "slide-left", "right": "slide-right", "down": "slide-down"}.get(d, "slide-up")
    if "zoom" in t or "scale" in t or "grow" in t:
        return "scale"
    if "pop" in t or "bounce" in t:
        return "pop"
    if "blur" in t:
        return "blur"
    return None


def _ms(value, default):
    """vMix durations: '00:00:00.5000000' (TimeSpan) or seconds/milliseconds."""
    if not value:
        return default
    if ":" in value:
        try:
            h, m, s = value.split(":")
            return int(round((int(h) * 3600 + int(m) * 60 + float(s)) * 1000))
        except ValueError:
            return default
    try:
        v = float(value)
    except ValueError:
        return default
    return int(round(v * 1000 if v < 20 else v))


def import_gtzip(path, workspace, name):
    """Makes a graphic from a vMix .gtzip. Returns (composition, [font families])."""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        if "document.xml" not in names:
            raise ValueError(f"{name} isn't a vMix title (it has no document.xml)")
        root = _xml(z.read("document.xml"))
        if root.tag != "Composition":
            root = root.find(".//Composition")
            if root is None:
                raise ValueError(f"{name} has no title in it")

        # Picture path in document.xml -> zip entry.
        files = {}
        if "resources.xml" in names:
            try:
                for res in _xml(z.read("resources.xml")).iter("resource"):
                    src = res.find("source")
                    guid = src.get("guid") if src is not None else None
                    if guid and guid in names:
                        files[res.get("filename", "")] = guid
            except ET.ParseError as e:
                log(f"{name}: resources.xml unreadable ({e})", "warn")

        def entry(source):
            if not source:
                return None
            if source in files:
                return files[source]
            for cand in (source, source.replace("\\", "/"), source.replace("\\", "/").split("/")[-1]):
                if cand in names:
                    return cand
            return None

        width, height = int(float(root.get("Width") or 1920)), int(float(root.get("Height") or 1080))
        comp = blank_comp(name)
        comp["width"], comp["height"] = width, height
        folder_rel, folder = workspace.unique_asset(name)
        os.makedirs(folder, exist_ok=True)
        sub = folder_rel[len("assets/"):]
        used, taken, fonts = set(), set(), []
        saved = {}           # zip entry -> asset path (a picture used twice is saved once)
        by_name = {}         # vMix object name -> [layers]

        def picture(member, label):
            if member in saved:
                return saved[member]
            base = re.sub(r"[^\w\- ]+", "_", label).strip() or "layer"
            fname, n = base, 2
            while fname.lower() in used:
                fname, n = f"{base}-{n}", n + 1
            used.add(fname.lower())
            ext = os.path.splitext(member)[1].lower()
            if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"):
                ext = ".png"   # stored under a GUID name: vMix keeps PNGs
            with z.open(member) as src, open(os.path.join(folder, fname + ext), "wb") as out:
                out.write(src.read())
            saved[member] = f"assets/{sub}/{fname}{ext}"
            return saved[member]

        def add(layer, vname):
            comp["layers"].append(layer)
            by_name.setdefault(vname, []).append(layer)

        def walk(container, ox, oy, sx, sy, opacity, visible):
            for el in container:
                tag = el.tag
                if tag in ("Storyboard",) or tag.endswith((".Fill", ".Stroke")):
                    continue
                vname = el.get("Name") or tag
                x, y = _nums(el.get("Location"))
                w, h = _nums(el.get("Dimensions"))
                op = opacity * float(el.get("Opacity", 1) or 1)
                vis = visible and (el.get("Visibility", "Visible") or "Visible").lower() == "visible"
                ax, ay = ox + x * sx, oy + y * sy
                try:
                    if tag == "Layer":
                        inner = el.find("Layer.Composition/Composition")
                        if inner is None:
                            continue
                        cw, ch = float(inner.get("Width") or w or 1), float(inner.get("Height") or h or 1)
                        ksx, ksy = (w / cw if w and cw else 1), (h / ch if h and ch else 1)
                        walk(inner, ax, ay, sx * ksx, sy * ksy, op, vis)
                    elif tag in SHAPES:
                        brush = _brush(el, "Fill")
                        src = entry(_bitmap(brush) or el.get("Source"))
                        if src:
                            layer = _base_layer(vname, ax, ay, w * sx, h * sy, op, vis)
                            layer.update({"type": "image", "src": picture(src, vname), "fit": "fill", "loop": True})
                        elif brush is not None and brush.get("Type", "Solid").lower() in ("solid", ""):
                            colour, alpha = _colour(brush.get("Color"))
                            if alpha <= 0:
                                continue
                            layer = _base_layer(vname, ax, ay, w * sx, h * sy, op * alpha, vis)
                            radius = min(w * sx, h * sy) / 2 if tag == "Ellipse" else float(el.get("RadiusX", 0) or 0) * sx
                            layer.update({"type": "rect", "fill": colour, "radius": round(radius),
                                          "stroke": "#ffffff", "strokeWidth": 0})
                        else:
                            continue   # gradients, video brushes: not carried
                        add(layer, vname)
                    elif tag == "TextBlock":
                        brush = _brush(el, "Fill")
                        colour, alpha = _colour(brush.get("Color") if brush is not None else "#FFFFFFFF")
                        size = float(el.get("FontSize", 32) or 32) * sy
                        family = el.get("FontFamily") or "Inter"
                        if family not in fonts:
                            fonts.append(family)
                        align = (el.get("TextAlignment") or el.get("HorizontalAlignment") or "left").lower()
                        valign = (el.get("VerticalAlignment") or "top").lower()
                        layer = _base_layer(vname, ax, ay, w * sx, h * sy, op * alpha, vis)
                        layer.update({
                            "type": "text", "field": _field_name(vname, taken), "text": el.get("Text", ""),
                            "font": family, "size": round(size, 2), "color": colour,
                            "align": align if align in ("left", "center", "right") else "left",
                            "valign": {"center": "middle"}.get(valign, valign if valign in ("top", "middle", "bottom") else "top"),
                            "tracking": 0, "caps": False, "lineHeight": 1.15, "fit": "shrink",
                            "weight": 700 if (el.get("FontWeight") or "").lower() in ("bold", "semibold", "black", "heavy", "extrabold") else 400,
                            "italic": (el.get("FontStyle") or "").lower() in ("italic", "oblique"), "scroll": 0,
                        })
                        add(layer, vname)
                except Exception as e:   # one odd object shouldn't lose the rest
                    log(f"{name}: skipped {tag} {vname!r} ({e})", "warn")

        walk(root, 0, 0, 1, 1, 1.0, True)

        if not comp["layers"]:
            raise ValueError(f"{name} has nothing in it that a graphic can show")

        auto_animate(comp["layers"], width, height)
        for board in root.iter("Storyboard"):
            kind = (board.get("Type") or "").lower()
            for anim in board.iter():
                target = anim.get("Object")
                if not target or target not in by_name:
                    continue
                for layer in by_name[target]:
                    if kind == "continuous" and anim.tag.lower().startswith("rotate"):
                        # Speed: turns a second. Right/Center = clockwise, Left = anticlockwise.
                        speed = float(anim.get("Speed", 0.1) or 0.1)
                        sign = -1 if (anim.get("Direction") or "Left").lower() == "left" else 1
                        layer["spin"] = round(sign * abs(speed), 4)
                    elif kind in ("transitionin", "transitionout"):
                        t = _anim_type(anim.tag, anim.get("Direction"))
                        if not t:
                            continue
                        slot = "in" if kind == "transitionin" else "out"
                        layer["anim"][slot] = {"type": t, "dur": _ms(anim.get("Duration"), 450),
                                               "delay": _ms(anim.get("Delay") or anim.get("BeginTime"), 0)}
    comp["kind"] = guess_kind(comp["layers"])
    log(f"Imported vMix title {name}: {len(comp['layers'])} layers, {len(saved)} pictures")
    return comp, fonts
