"""Adobe Fonts, two ways, both within Adobe's licence (no font file is
copied, read for its letters or served by the engine):

1. Fonts the Creative Cloud app has added on this PC. The app lists them in
   its entitlements.xml (names only, read here); the fonts themselves are
   installed on the PC by Creative Cloud, so graphics ask the browser for
   them by name (CSS local()). Works in the app and in OBS on a PC where
   Creative Cloud has them.

2. An Adobe Fonts web project ("kit"): its ID (or embed code) is saved once
   and every page that shows graphics loads https://use.typekit.net/<id>.css,
   the way any web page uses Adobe Fonts. Works on every PC with internet
   (OBS on the stream PC too). Adobe doesn't limit web projects to domains.

Both kinds are listed as fonts like the added ones ({"postscript", "family",
"style", "aliases", ...}) with "adobe": "pc" or "web", "local" (names the
browser finds an installed font by), "kit" ({"family", "weight", "style"}
in the kit's CSS) and "weight" / "italic".
"""

import json
import os
import re
import sys
import threading
import time
import urllib.request
import xml.etree.ElementTree as ElementTree

KIT_FILE = "adobe-fonts.json"   # (in the shared library folder)
KIT_URL = "https://use.typekit.net/{}.css"

# Style words for each weight (what a design may call it).
WEIGHT_WORDS = [
    (100, ["Thin", "Hairline"]), (200, ["ExtraLight", "UltraLight"]), (300, ["Light"]),
    (400, ["Regular", "Book", "Normal", "Roman", ""]), (500, ["Medium"]),
    (600, ["SemiBold", "DemiBold", "Demi"]), (700, ["Bold"]),
    (800, ["ExtraBold", "UltraBold", "Heavy"]), (900, ["Black", "Heavy", "Ultra"]),
]


def norm(name):
    """A font name to compare by: "DIN 2014 Bold" == "DIN2014-Bold" == "din-2014 bold"."""
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def weight_of(style):
    """(weight, italic) from a style name ("Bold Italic", "Condensed Black"...)."""
    s = norm(style)
    italic = "italic" in s or "oblique" in s or s.endswith("it")
    s = s.replace("italic", "").replace("oblique", "")
    for words, w in (("thin hairline", 100), ("extralight ultralight", 200),
                     ("semibold demibold demi", 600), ("extrabold ultrabold", 800),
                     ("black heavy ultra", 900), ("light", 300), ("medium", 500), ("bold", 700)):
        if any(word in s for word in words.split()):
            return w, italic
    return 400, italic


def _uniq(names):
    seen, out = set(), []
    for n in names:
        if n and n.strip("-") and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


# --- 1. fonts Creative Cloud added on this PC ---------------------------------

def entitlements_paths():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser(r"~\AppData\Roaming")
        return [os.path.join(base, "Adobe", "CoreSync", "plugins", "livetype", "c", "entitlements.xml")]
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support/Adobe/CoreSync/plugins/livetype")
        return [os.path.join(base, ".c", "entitlements.xml"), os.path.join(base, "c", "entitlements.xml")]
    return []


def _text(el, tag):
    """A child's text, whatever its case or namespace."""
    for child in el:
        if child.tag.rsplit("}", 1)[-1].lower() == tag.lower():
            return (child.text or "").strip()
    return ""


def _child(el, tag):
    for child in el:
        if child.tag.rsplit("}", 1)[-1].lower() == tag.lower():
            return child
    return None


OFF_STATES = ("uninstall", "deactiv", "remov", "false", "pending")


def parse_entitlements(xml_text):
    """[font] from Creative Cloud's entitlements.xml (fonts > font > properties)."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    out = []
    for font in root.iter():
        if font.tag.rsplit("}", 1)[-1].lower() != "font":
            continue
        props = _child(font, "properties")
        if props is None:
            continue
        family = _text(props, "familyName")
        if not family:
            continue
        state = _text(props, "installState").lower()
        if state in ("0",) or any(w in state for w in OFF_STATES):
            continue
        style = _text(props, "variationName") or "Regular"
        full = _text(props, "fullName") or f"{family} {style}"
        ps = _text(props, "postscriptName") or _text(props, "postScriptName") or \
            f"{family.replace(' ', '')}-{style.replace(' ', '')}"
        weight, italic = weight_of(style)
        out.append({
            "postscript": ps, "family": family, "style": style, "path": "", "adobe": "pc",
            "aliases": _uniq([ps, full.replace(" ", "-"), full.replace(" ", ""), full,
                              f"{family}-{style}".replace(" ", ""), f"{family} {style}"]),
            "local": _uniq([full, ps, f"{family} {style}", family if style.lower() == "regular" else ""]),
            "weight": weight, "italic": italic,
        })
    return out


_pc_cache = {"key": None, "fonts": []}


def pc_fonts():
    """The fonts Creative Cloud has added on this PC ([] if it isn't installed)."""
    for path in entitlements_paths():
        try:
            st = os.stat(path)
        except OSError:
            continue
        key = (path, st.st_size, st.st_mtime)
        if _pc_cache["key"] != key:
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    fonts = parse_entitlements(f.read())
            except OSError:
                fonts = []
            _pc_cache.update(key=key, fonts=fonts)
        return _pc_cache["fonts"]
    return []


# --- 2. a web project (kit) ---------------------------------------------------

def kit_id(text):
    """The kit's ID from what was pasted: the ID, its CSS link, or the embed code."""
    text = (text or "").strip()
    m = re.search(r"use\.typekit\.net/([a-z0-9]+)\.(?:css|js)", text, re.I) or \
        re.search(r"Typekit\.load\(\s*\{[^}]*kitId\s*:\s*['\"]([a-z0-9]+)", text, re.I)
    if m:
        return m.group(1).lower()
    if re.fullmatch(r"[a-z0-9]{5,12}", text, re.I):
        return text.lower()
    return ""


def parse_kit_css(css):
    """[{"family", "weight", "style"}] for each @font-face in a kit's CSS."""
    faces = []
    for block in re.findall(r"@font-face\s*\{([^}]*)\}", css or "", re.I):
        fam = re.search(r"font-family\s*:\s*['\"]?([^;'\"]+)", block, re.I)
        if not fam:
            continue
        w = re.search(r"font-weight\s*:\s*(\d+)", block, re.I)
        s = re.search(r"font-style\s*:\s*(\w+)", block, re.I)
        face = {"family": fam.group(1).strip(), "weight": int(w.group(1)) if w else 400,
                "style": (s.group(1).lower() if s else "normal")}
        if face not in faces:
            faces.append(face)
    return faces


def _display(css_family):
    """"din-2014" -> "Din 2014" (a kit's CSS only has the family's web name)."""
    return " ".join(p[:1].upper() + p[1:] for p in re.split(r"[-_ ]+", css_family) if p)


def kit_fonts(kit):
    """The kit's faces as fonts, with every name a design may know them by."""
    out = []
    for face in kit.get("faces") or []:
        fam, w, italic = face["family"], face["weight"], face["style"] != "normal"
        words = dict(WEIGHT_WORDS).get(w) or [str(w)]
        names_ = [n for n in (kit.get("names") or {}).get(fam, []) if n] or [_display(fam)]
        styles = [(word + ("Italic" if italic else "")) or ("Italic" if italic else "") for word in words]
        if italic:
            styles += [word + "It" for word in words if word]
        main_style = styles[0] or "Regular"
        aliases = []
        for name in names_ + [fam]:
            for st in styles:
                aliases += [f"{name.replace(' ', '')}-{st}" if st else name.replace(" ", ""),
                            f"{name} {st}".strip(), name if not st else ""]
        out.append({
            "postscript": f"{names_[0].replace(' ', '')}-{main_style}", "family": names_[0], "style": main_style,
            "path": "", "adobe": "web", "aliases": _uniq(aliases),
            "kit": {"id": kit.get("id", ""), "family": fam, "weight": w, "style": face["style"]}, "weight": w, "italic": italic,
        })
    return out


class Kit:
    """The saved web project, in the shared library folder (every workspace)."""

    def __init__(self, library_dir):
        self.path = os.path.join(library_dir, KIT_FILE) if library_dir else None
        self.lock = threading.Lock()
        self._fonts = None

    def get(self):
        if not self.path:
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.path)
        self._fonts = None

    def set(self, text, fetch=None):
        """Saves the web project pasted (or clears it with ""), reading its fonts."""
        if not self.path:
            raise ValueError("No library folder")
        with self.lock:
            if not (text or "").strip():
                self._save({})
                return {}
            kid = kit_id(text)
            if not kid:
                raise ValueError("That isn't an Adobe Fonts web project: paste its project ID "
                                 "(like abc1234) or its embed code from fonts.adobe.com > My Adobe Fonts > Web Projects")
            css = (fetch or _fetch)(KIT_URL.format(kid))
            faces = parse_kit_css(css)
            if not faces:
                raise ValueError(f"The web project {kid} has no fonts in it (add some at fonts.adobe.com, then save it again)")
            data = {"id": kid, "faces": faces, "names": _comment_names(css), "read": int(time.time())}
            self._save(data)
            return data

    def refresh(self, fetch=None):
        """Reads the project's fonts again (fonts added to it on fonts.adobe.com)."""
        kid = self.get().get("id")
        return self.set(kid, fetch) if kid else {}

    def fonts(self):
        if self._fonts is None:
            self._fonts = kit_fonts(self.get())
        return self._fonts


def _comment_names(css):
    """{css family: [display names]} from the kit CSS's notice, where it has them
    (e.g. " * DIN 2014:" / " *   - http://typekit.com/eulas/..."): best effort."""
    out = {}
    for name in re.findall(r"^\s*\*\s+([^:*\n]+):\s*$", css or "", re.M):
        name = name.strip()
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if slug and name and name != slug:   # (usually just the web name: nothing to add)
            out.setdefault(slug, []).append(name)
    return out


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "SCC-Broadcast-Engine"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:   # (offline, 404...)
        code = getattr(e, "code", None)
        if code == 404:
            raise ValueError("Adobe doesn't know that web project ID (check it at fonts.adobe.com > Web Projects)") from None
        raise ValueError(f"Couldn't reach Adobe Fonts ({getattr(e, 'reason', e)})") from None


def all_fonts(kit):
    """Adobe fonts on this PC, then the web project's (a font in both: the PC's
    entry also names the web one, so other PCs still get it)."""
    pc = pc_fonts()
    web = kit.fonts() if kit else []
    by = {}
    for f in web:
        for a in f["aliases"]:
            by.setdefault(norm(a), f)
    out = []
    for f in pc:
        match = next((by[norm(a)] for a in f["aliases"] if norm(a) in by), None)
        if match and match["weight"] == f["weight"] and match["italic"] == f["italic"]:
            f = dict(f, kit=match["kit"])
        out.append(f)
    have = {norm(a) for f in out for a in f["aliases"]}
    out += [f for f in web if not any(norm(a) in have for a in f["aliases"][:2])]
    return out


def known_names(fonts):
    """Every name (normalised) the given Adobe fonts answer to."""
    return {norm(a) for f in fonts for a in [f.get("postscript"), f.get("family")] + list(f.get("aliases") or []) if a}
