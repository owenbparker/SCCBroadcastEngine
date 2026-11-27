"""Edit a game HUD in place (HUD Builder > Game HUDs).

Every game HUD page (League's overlay and drafts, VALORANT's HUDs, boards and
map bans, CoD, Rocket League, Smash, Overwatch) loads /hudedit.js. That
script applies the changes saved for its design (moved, resized, recoloured,
hidden parts; new fonts and pictures; boxes, text and pictures added on top)
and follows them live, so a Save in HUD Builder is on air within a second.
The HUD's own code and data links are never touched: the changes are a layer
of CSS (and a few added elements) over the page.

Each HUD app answers these on its own port, from handle() below:

    GET  /hudedit.js                         the script
    GET  /hudedit/picker.js                  the HUD design list helper (hudpicker.js) for control pages
    GET  /hudedit/ping                       {"ok": true}
    GET  /hudedit/edits?design=KEY[&rev=N]   the saved changes ({"rev": N} alone when unchanged)
    GET  /hudedit/asset/<name>               an uploaded picture or font
    GET  /hudedit/history?design=KEY         earlier saved versions
    POST /hudedit/save     {design, edits, base_rev}  (409 when someone saved meanwhile)
    POST /hudedit/restore  {design, version}           an earlier version back (saved as a new one)
    POST /hudedit/upload?name=FILE           (raw bytes) -> {"name": stored name}
    GET  /hudedit/copies                     {"copies": [...], "deleted": [...]}
    POST /hudedit/copies   {action: make|rename|delete|undelete|apply|live, ...}
    GET  /hudedit/live?game=G                which copy of each design is on air, the HUD
                                             Builder HUDs that /overlay can go to, and which one does
    GET  /overlay                            -> 302 to the HUD Builder HUD picked as live, if any

Copies: a built-in HUD can be duplicated into a copy with its own name and its
own changes (starting from the original's saved ones). A copy is the same page
with ?hudcopy=<id> (its own browser source); its changes are saved under the
design key "<original key>.c<id>". copies.json lists them. Deleting a copy
moves its changes and versions to deleted/ (Recently deleted brings it back);
built-in HUDs themselves can't be deleted, only their changes undone.

Saved in <the app's data folder>/hud-edits/: <design>.json, assets/ and
history/<design>/ (every version a Save replaced, the last HISTORY kept), so
nothing saved is ever lost by a later Save. Changing anything is only allowed
from this PC.
"""

import hashlib
import ipaddress
import json
import mimetypes
import os
import re
import shutil
import threading
import time
from urllib.parse import parse_qs, unquote, urlparse

from .config import WEB_DIR

HISTORY = 60
MAX_UPLOAD = 60 * 1024 * 1024
KEY = re.compile(r"[a-z0-9][a-z0-9._:-]{0,95}")
ASSET = re.compile(r"[a-f0-9]{16}\.(png|jpe?g|webp|gif|svg|ttf|otf|woff2?|webm|mp4)")
UPLOAD_EXT = {"png", "jpg", "jpeg", "webp", "gif", "svg", "ttf", "otf", "woff", "woff2", "webm", "mp4"}
COLOR = re.compile(r"#[0-9a-fA-F]{3,8}|rgba?\([0-9.,\s%]+\)|hsla?\([0-9.,\s%deg]+\)|[a-zA-Z]{3,20}")
FONT = re.compile(r"[^\"'\\;{}<>]{1,80}")
_lock = threading.Lock()

# What a part's rule may hold: name -> kind.
RULE = {"x": "num", "y": "num", "sx": "num", "sy": "num", "rot": "num", "op": "num", "hide": "bool",
        "color": "color", "font": "font", "size": "num", "weight": "num", "spacing": "num",
        "case": ("upper", "lower", "none", "capitalize"), "bg": "color", "radius": "num",
        "img": "asset", "imgKind": ("img", "bg", "svg"), "svg": "bool", "label": "text",
        "dur": "num", "delay": "num", "noanim": "bool", "del": "bool", "lock": "bool",
        "ease": ("ease", "linear", "ease-in", "ease-out", "ease-in-out", "snappy", "bounce")}
ADDED = {"id": "id", "type": ("box", "shape", "text", "image"),
         "shape": ("rect", "ellipse", "triangle", "line", "slant", "star", "arrow", "chevron"),
         "fill": "color", "fill2": "color", "angle": "num", "stroke": "color", "strokeWidth": "num", "slant": "num",
         "italic": "bool", "shadow": "bool", "x": "num", "y": "num", "w": "num", "h": "num",
         "rot": "num", "op": "num", "hide": "bool", "behind": "bool", "lock": "bool", "bg": "color", "radius": "num",
         "border": "num", "borderColor": "color", "text": "text", "color": "color", "font": "font",
         "size": "num", "weight": "num", "spacing": "num", "align": ("left", "center", "right"),
         "case": ("upper", "lower", "none", "capitalize"), "img": "asset", "fit": ("contain", "cover", "fill"),
         "label": "text"}


def folder(data_dir):
    return os.path.join(data_dir, "hud-edits")


def _key(design):
    design = str(design or "").strip().lower()
    if not KEY.fullmatch(design):
        raise ValueError("Unknown HUD design")
    return design


def _path(data_dir, design):
    return os.path.join(folder(data_dir), _key(design).replace(":", "~") + ".json")


def blank():
    return {"rev": 0, "rules": {}, "added": [], "fonts": [], "settings": {}}


def load(data_dir, design):
    try:
        with open(_path(data_dir, design), encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return blank()
    if not isinstance(doc, dict):
        return blank()
    out = clean(doc)
    out["rev"] = int(doc.get("rev") or 0)
    out["saved"] = doc.get("saved") or 0
    return out


# --- cleaning (the values go into CSS, so only what's expected gets through) --

def _value(kind, v):
    if isinstance(kind, tuple):
        return v if v in kind else None
    if kind == "num":
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or abs(v) > 1e6:
            return None
        return round(float(v), 3)
    if kind == "bool":
        return bool(v) if isinstance(v, bool) else None
    if kind == "color":
        return v.strip() if isinstance(v, str) and COLOR.fullmatch(v.strip()) else None
    if kind == "font":
        return v.strip() if isinstance(v, str) and FONT.fullmatch(v.strip()) else None
    if kind == "asset":
        return v if isinstance(v, str) and ASSET.fullmatch(v) else None
    if kind == "id":
        return v if isinstance(v, str) and re.fullmatch(r"[a-z0-9]{1,24}", v) else None
    if kind == "text":
        return v[:2000] if isinstance(v, str) else None
    return None


def _fields(spec, d):
    out = {}
    for k, kind in spec.items():
        if k in d:
            v = _value(kind, d[k])
            if v is not None:
                out[k] = v
    return out


def _selector(s):
    return isinstance(s, str) and 0 < len(s) <= 600 and not re.search(r"[{}<;@\\]|/\*", s)


def clean(doc):
    rules = {}
    for sel, r in (doc.get("rules") or {}).items() if isinstance(doc.get("rules"), dict) else []:
        if _selector(sel) and isinstance(r, dict):
            r = _fields(RULE, r)
            if r:
                rules[sel] = r
    added = []
    for a in doc.get("added") or [] if isinstance(doc.get("added"), list) else []:
        if isinstance(a, dict):
            a = _fields(ADDED, a)
            if a.get("id") and a.get("type"):
                added.append(a)
    fonts = []
    for f in doc.get("fonts") or [] if isinstance(doc.get("fonts"), list) else []:
        if isinstance(f, dict):
            fam, file = _value("font", f.get("family")), _value("asset", f.get("file"))
            if fam and file:
                fonts.append({"family": fam, "file": file})
    settings = {}
    for k, v in (doc.get("settings") or {}).items() if isinstance(doc.get("settings"), dict) else []:
        if not (isinstance(k, str) and re.fullmatch(r"[a-z0-9_.-]{1,60}", k)):
            continue
        if isinstance(v, bool) or (isinstance(v, (int, float)) and v == v and abs(v) < 1e6):
            settings[k] = v
        elif isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9 _.:-]{0,40}", v):
            settings[k] = v
    return {"rules": rules, "added": added[:300], "fonts": fonts[:40], "settings": dict(list(settings.items())[:200])}


# --- saving -------------------------------------------------------------------

def _write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    os.replace(tmp, path)


def _history_dir(data_dir, design):
    return os.path.join(folder(data_dir), "history", _key(design).replace(":", "~"))


def save(data_dir, design, edits, base_rev=None):
    """Saves the changes for one design. Returns the saved document, or
    raises Conflict when base_rev isn't the saved one (saved elsewhere since)."""
    with _lock:
        path = _path(data_dir, design)
        cur = load(data_dir, design)
        if base_rev is not None and int(base_rev) != cur["rev"]:
            raise Conflict(cur["rev"])
        if cur["rev"] and os.path.exists(path):
            # The version this Save replaces is kept (the last HISTORY of them).
            hist = _history_dir(data_dir, design)
            os.makedirs(hist, exist_ok=True)
            _write(os.path.join(hist, f"{cur['rev']:06d}.json"), cur)
            for old in sorted(os.listdir(hist))[:-HISTORY]:
                try:
                    os.remove(os.path.join(hist, old))
                except OSError:
                    pass
        doc = clean(edits if isinstance(edits, dict) else {})
        doc["rev"] = cur["rev"] + 1
        doc["saved"] = time.time()
        _write(path, doc)
        return doc


class Conflict(Exception):
    def __init__(self, rev):
        super().__init__(f"saved since (version {rev})")
        self.rev = rev


def history(data_dir, design):
    hist = _history_dir(data_dir, design)
    out = []
    try:
        names = sorted(os.listdir(hist), reverse=True)
    except OSError:
        names = []
    for n in names:
        m = re.fullmatch(r"(\d+)\.json", n)
        if not m:
            continue
        try:
            with open(os.path.join(hist, n), encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        out.append({"version": int(m.group(1)), "saved": d.get("saved") or 0,
                    "parts": len(d.get("rules") or {}), "added": len(d.get("added") or [])})
    return out


def restore(data_dir, design, version):
    path = os.path.join(_history_dir(data_dir, design), f"{int(version):06d}.json")
    with open(path, encoding="utf-8") as f:
        old = json.load(f)
    return save(data_dir, design, old)


def store_upload(data_dir, name, blob):
    ext = (os.path.splitext(str(name or ""))[1][1:] or "").lower()
    if ext not in UPLOAD_EXT:
        raise ValueError("Pictures (PNG, JPG, WebP, GIF, SVG), videos (WebM, MP4) or fonts (TTF, OTF, WOFF) only")
    if not blob or len(blob) > MAX_UPLOAD:
        raise ValueError("That file is empty or too big")
    stored = hashlib.sha1(blob).hexdigest()[:16] + "." + ext
    out = os.path.join(folder(data_dir), "assets", stored)
    if not os.path.exists(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out + ".tmp", "wb") as f:
            f.write(blob)
        os.replace(out + ".tmp", out)
    return stored


# --- copies of a built-in HUD ------------------------------------------------------
COPY_ID = re.compile(r"[a-f0-9]{8}")
PATH = re.compile(r"/[A-Za-z0-9/_.-]*(\?[A-Za-z0-9_.=&%-]*)?")


def copy_key(base, cid):
    return _key(f"{_key(base)}.c{cid}")


def _copies_file(data_dir):
    return os.path.join(folder(data_dir), "copies.json")


def list_copies(data_dir):
    try:
        with open(_copies_file(data_dir), encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for c in (doc.get("copies") if isinstance(doc, dict) else None) or []:
        if isinstance(c, dict) and COPY_ID.fullmatch(str(c.get("id") or "")) and KEY.fullmatch(str(c.get("base") or "")):
            out.append({"id": c["id"], "base": c["base"], "name": str(c.get("name") or "Copy")[:80],
                        "path": str(c.get("path") or ""), "created": c.get("created") or 0})
    return out


def _save_copies(data_dir, copies):
    _write(_copies_file(data_dir), {"copies": copies})


def _clean_copy_name(name, fallback="Copy"):
    return re.sub(r"\s+", " ", str(name or "")).strip()[:80] or fallback


def _find(copies, cid):
    for c in copies:
        if c["id"] == cid:
            return c
    raise KeyError("That copy isn't there any more")


def make_copy(data_dir, base, path, name, start_from=None):
    """A copy of a built-in HUD design, with the original's saved changes to
    start from (or another copy's, start_from = that copy's id)."""
    base = _key(base)
    path = str(path or "")
    if not PATH.fullmatch(path) or "hudcopy=" in path:
        raise ValueError("Unknown HUD page")
    with _lock:
        copies = list_copies(data_dir)
        cid = os.urandom(4).hex()
        while any(c["id"] == cid for c in copies):
            cid = os.urandom(4).hex()
        entry = {"id": cid, "base": base, "name": _clean_copy_name(name), "path": path, "created": time.time()}
        copies.append(entry)
        _save_copies(data_dir, copies)
    start = load(data_dir, copy_key(base, start_from) if start_from and COPY_ID.fullmatch(str(start_from)) else base)
    for k in ("rev", "saved"):
        start.pop(k, None)
    save(data_dir, copy_key(base, cid), start)
    return entry


def rename_copy(data_dir, cid, name):
    with _lock:
        copies = list_copies(data_dir)
        c = _find(copies, cid)
        c["name"] = _clean_copy_name(name, c["name"])
        _save_copies(data_dir, copies)
        return c


def _deleted_dir(data_dir):
    return os.path.join(folder(data_dir), "deleted")


def delete_copy(data_dir, cid, confirm):
    """Takes a copy off the list. Its changes and versions are kept in deleted/."""
    with _lock:
        copies = list_copies(data_dir)
        c = _find(copies, cid)
        if str(confirm or "").strip().lower() != c["name"].strip().lower():
            raise ValueError(f"Type {c['name']} to delete it")
        key = copy_key(c["base"], cid)
        dest = os.path.join(_deleted_dir(data_dir), f"{cid}-{int(time.time() * 1000)}")
        os.makedirs(dest, exist_ok=True)
        if os.path.exists(_path(data_dir, key)):
            os.replace(_path(data_dir, key), os.path.join(dest, "edits.json"))
        if os.path.isdir(_history_dir(data_dir, key)):
            os.replace(_history_dir(data_dir, key), os.path.join(dest, "history"))
        _write(os.path.join(dest, "copy.json"), dict(c, deleted=time.time()))
        _save_copies(data_dir, [x for x in copies if x["id"] != cid])
        # (not live any more: its design goes back to the original)
        try:
            with open(_live_file(data_dir), encoding="utf-8") as f:
                live = json.load(f)
            live["active"] = {k: v for k, v in (live.get("active") or {}).items() if v != cid}
            _write(_live_file(data_dir), live)
        except (OSError, ValueError, AttributeError):
            pass
        return c


def deleted_copies(data_dir):
    out = []
    try:
        names = os.listdir(_deleted_dir(data_dir))
    except OSError:
        return out
    for tid in names:
        try:
            with open(os.path.join(_deleted_dir(data_dir), tid, "copy.json"), encoding="utf-8") as f:
                c = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(c, dict):
            out.append({"tid": tid, "id": c.get("id"), "base": c.get("base"), "name": c.get("name"),
                        "deleted": c.get("deleted") or 0})
    out.sort(key=lambda c: -c["deleted"])
    return out


def undelete_copy(data_dir, tid):
    """A deleted copy back, its changes and versions with it."""
    if not re.fullmatch(r"[a-f0-9]{8}-\d{10,16}", str(tid or "")):
        raise KeyError("That deleted copy isn't there")
    src = os.path.join(_deleted_dir(data_dir), tid)
    with _lock:
        try:
            with open(os.path.join(src, "copy.json"), encoding="utf-8") as f:
                c = json.load(f)
        except (OSError, ValueError):
            raise KeyError("That deleted copy isn't there")
        copies = list_copies(data_dir)
        if any(x["id"] == c["id"] for x in copies):
            raise ValueError("That copy is back already")
        key = copy_key(c["base"], c["id"])
        if os.path.exists(os.path.join(src, "edits.json")):
            os.makedirs(folder(data_dir), exist_ok=True)
            os.replace(os.path.join(src, "edits.json"), _path(data_dir, key))
        if os.path.isdir(os.path.join(src, "history")):
            os.makedirs(os.path.dirname(_history_dir(data_dir, key)), exist_ok=True)
            os.replace(os.path.join(src, "history"), _history_dir(data_dir, key))
        entry = {"id": c["id"], "base": c["base"], "name": c.get("name") or "Copy", "path": c.get("path") or "",
                 "created": c.get("created") or 0}
        copies.append(entry)
        _save_copies(data_dir, copies)
        shutil.rmtree(src, ignore_errors=True)
        return entry


def apply_copy(data_dir, cid):
    """The copy's changes put on the original HUD (what's on air at its usual
    address). The original's changes before are kept in its Versions."""
    c = _find(list_copies(data_dir), cid)
    doc = load(data_dir, copy_key(c["base"], cid))
    for k in ("rev", "saved"):
        doc.pop(k, None)
    return save(data_dir, c["base"], doc)


def copies_post(data_dir, body):
    act = body.get("action")
    if act == "make":
        return {"copy": make_copy(data_dir, body.get("base"), body.get("path"), body.get("name"), body.get("from"))}
    if act == "rename":
        return {"copy": rename_copy(data_dir, str(body.get("id") or ""), body.get("name"))}
    if act == "delete":
        return {"copy": delete_copy(data_dir, str(body.get("id") or ""), body.get("confirm"))}
    if act == "undelete":
        return {"copy": undelete_copy(data_dir, body.get("tid"))}
    if act == "live":
        return set_live(data_dir, body)
    if act == "apply":
        doc = apply_copy(data_dir, str(body.get("id") or ""))
        return {"ok": True, "rev": doc["rev"]}
    raise ValueError("Unknown action")


# --- the live HUD: a copy picked for a design, or a whole HUD Builder HUD ----------
# live.json: {"active": {design key: copy id}, "custom": {"src", "id", "name", "port"} | null}
#   active   the copy whose changes a design's pages show on air (instead of the original's)
#   custom   a HUD Builder HUD that /overlay goes to instead of the game's own HUD
#            (src "builder": SCC Broadcast Engine's HUD Builder; "embed": this app's Custom design)
def _live_file(data_dir):
    return os.path.join(folder(data_dir), "live.json")


def get_live(data_dir):
    try:
        with open(_live_file(data_dir), encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    ids = {c["id"] for c in list_copies(data_dir)}
    active = {k: v for k, v in (doc.get("active") or {}).items()
              if isinstance(k, str) and KEY.fullmatch(k) and v in ids}
    custom = doc.get("custom") if isinstance(doc.get("custom"), dict) else None
    if custom and not (custom.get("src") in ("builder", "embed") and re.fullmatch(r"[a-z0-9]{6,40}", str(custom.get("id") or ""))
                       and isinstance(custom.get("port"), int)):
        custom = None
    return {"active": active, "custom": custom}


def set_live(data_dir, body):
    """{"base": key, "id": copy id or "" (the original)}: which version of a design is on air
    (and no HUD Builder HUD over /overlay). {"custom": {...} | null}: a HUD Builder HUD on /overlay."""
    with _lock:
        cur = get_live(data_dir)
        if "custom" in body:
            c = body.get("custom")
            if c:
                c = {"src": c.get("src"), "id": str(c.get("id") or ""), "name": str(c.get("name") or "")[:80],
                     "port": int(c.get("port") or 0)}
                if c["src"] not in ("builder", "embed") or not re.fullmatch(r"[a-z0-9]{6,40}", c["id"]) or not 0 < c["port"] < 65536:
                    raise ValueError("Unknown HUD")
            cur["custom"] = c or None
        if "base" in body:
            base = _key(body.get("base"))
            cid = str(body.get("id") or "")
            if cid:
                _find(list_copies(data_dir), cid)
                cur["active"][base] = cid
            else:
                cur["active"].pop(base, None)
            cur["custom"] = None
        _write(_live_file(data_dir), cur)
        return cur


def live_edits(data_dir, design):
    """The changes a design shows on air: the live copy's, or its own. (doc, served key)"""
    design = _key(design)
    cid = get_live(data_dir)["active"].get(design)
    key = copy_key(design, cid) if cid else design
    return load(data_dir, key), key


def custom_huds(data_dir, game):
    """The HUD Builder HUDs for this game that can go on /overlay: SCC Broadcast
    Engine's HUD Builder's and this app's own Custom design's."""
    out = []
    port = _builder_port()
    try:
        st = _get(f"http://127.0.0.1:{port}/api/state", timeout=0.8)
        for h in st.get("huds") or []:
            if not game or h.get("game") == game:
                out.append({"src": "builder", "id": h["id"], "name": h.get("name") or h["id"], "port": port})
    except Exception:
        pass
    folder_ = os.path.join(data_dir, "hud-builder")
    try:
        with open(os.path.join(folder_, "config.json"), encoding="utf-8") as f:
            eport = int(json.load(f).get("http_port") or 0)
    except (OSError, ValueError, TypeError):
        eport = 0
    if eport:
        try:
            from .store import Store
            for h in Store(os.path.join(folder_, "huds")).list():
                out.append({"src": "embed", "id": h["id"], "name": h["name"], "port": eport})
        except Exception:
            pass
    return out


def _builder_port():
    try:
        from sccbe.parts import BY_KEY
        p = BY_KEY.get("builder")
        if p is not None and p.port:
            return p.port
    except Exception:
        pass
    return 8800


def _host(req):
    host = (req.headers.get("Host") or "").strip()
    if host.startswith("["):
        return host.split("]")[0] + "]"
    host = host.split(":")[0]
    return host if re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host or "") else "127.0.0.1"


_PICKS = ("design", "profile", "layout", "look", "hudcopy", "hudedit", "still", "anim", "rwin")


# --- HTTP ------------------------------------------------------------------------

def _local(ip):
    try:
        a = ipaddress.ip_address(ip)
        if a.version == 6 and a.ipv4_mapped is not None:
            return a.ipv4_mapped.is_loopback
        return a.is_loopback
    except ValueError:
        return False


def _reply(req, body, ctype="application/json", status=200, cache=False):
    if not isinstance(body, bytes):
        body = json.dumps(body).encode("utf-8")
    req.send_response(status)
    req.send_header("Content-Type", ctype)
    req.send_header("Content-Length", str(len(body)))
    req.send_header("Cache-Control", "max-age=31536000, immutable" if cache else "no-store")
    req.send_header("Access-Control-Allow-Origin", "*")
    req.end_headers()
    req.wfile.write(body)
    return True


# --- recolours shipped with the app for one person's copy ---------------------------
# web/hudedit-presets/<name>/preset.json: {id, base, copy_name, rules} plus the pictures
# its rules name. Applied ONCE to each copy of `base` whose name contains copy_name (never
# to the built-in HUD itself), on top of that copy's own changes: only the fields the
# preset names change on those parts, everything else on the copy is kept, and the
# version it replaces goes to Versions like any Save. presets.json remembers what ran.
PRESET_DIR = os.path.join(WEB_DIR, "hudedit-presets")
_presets_done = set()


def _presets_file(data_dir):
    return os.path.join(folder(data_dir), "presets.json")


def apply_presets(data_dir, preset_dir=None):
    """Applies the shipped presets that haven't run on this data folder's copies yet.
    Returns [(preset id, copy id)] applied now."""
    preset_dir = preset_dir or PRESET_DIR
    try:
        names = sorted(os.listdir(preset_dir))
    except OSError:
        return []
    try:
        with open(_presets_file(data_dir), encoding="utf-8") as f:
            done = json.load(f).get("applied") or {}
    except (OSError, ValueError, AttributeError):
        done = {}
    copies, out = list_copies(data_dir), []
    for name in names:
        try:
            with open(os.path.join(preset_dir, name, "preset.json"), encoding="utf-8") as f:
                pre = json.load(f)
        except (OSError, ValueError):
            continue
        pid, base, want = str(pre.get("id") or name), _key(str(pre.get("base") or "")), str(pre.get("copy_name") or "").lower()
        if not want:
            continue
        for c in copies:
            if c["base"] != base or want not in c["name"].lower() or c["id"] in (done.get(pid) or []):
                continue
            stored = {}
            for sel, r in (pre.get("rules") or {}).items():
                pic = r.get("img")
                if pic and pic not in stored:
                    with open(os.path.join(preset_dir, name, os.path.basename(pic)), "rb") as f:
                        stored[pic] = store_upload(data_dir, pic, f.read())
            key = copy_key(base, c["id"])
            cur = load(data_dir, key)
            rules = dict(cur["rules"])
            for sel, r in (pre.get("rules") or {}).items():
                r = dict(r)
                if r.get("img"):
                    r["img"] = stored[r["img"]]
                rules[sel] = dict(rules.get(sel) or {}, **r)
            save(data_dir, key, dict(cur, rules=rules), cur["rev"])
            done.setdefault(pid, []).append(c["id"])
            out.append((pid, c["id"]))
    if out:
        with _lock:
            _write(_presets_file(data_dir), {"applied": done})
    return out


def handle(req, method, path, data_dir):
    """Answers /hudedit.js and /hudedit/... on a BaseHTTPRequestHandler. True when it did."""
    if data_dir not in _presets_done:
        _presets_done.add(data_dir)
        try:
            apply_presets(data_dir)
        except Exception:   # (a shipped recolour must never stop the HUD)
            pass
    if path == "/overlay" and method == "GET":
        # A HUD Builder HUD picked as this game's HUD: /overlay goes there (not when a
        # page asks for a design of its own, or HUD Builder is editing one).
        custom = get_live(data_dir)["custom"]
        q = parse_qs(urlparse(req.path).query)
        if custom and not any(k in q for k in _PICKS):
            req.send_response(302)
            req.send_header("Location", f"http://{_host(req)}:{custom['port']}/hud/{custom['id']}")
            req.send_header("Cache-Control", "no-store")
            req.send_header("Content-Length", "0")
            req.end_headers()
            return True
        return False
    if path != "/hudedit.js" and not path.startswith("/hudedit/"):
        return False
    q = parse_qs(urlparse(req.path).query)
    try:
        if method == "GET":
            if path == "/hudedit.js":
                with open(os.path.join(WEB_DIR, "hudedit.js"), "rb") as f:
                    return _reply(req, f.read(), "text/javascript; charset=utf-8")
            if path == "/hudedit/picker.js":
                with open(os.path.join(WEB_DIR, "hudpicker.js"), "rb") as f:
                    return _reply(req, f.read(), "text/javascript; charset=utf-8")
            if path == "/hudedit/ping":
                return _reply(req, {"ok": True})
            if path == "/hudedit/edits":
                design = (q.get("design") or [""])[0]
                if (q.get("live") or [""])[0] == "1":
                    doc, served = live_edits(data_dir, design)
                    doc["served"] = served
                    same_key = (q.get("served") or [""])[0] == served
                else:
                    doc, same_key = load(data_dir, design), True
                seen = (q.get("rev") or [""])[0]
                if same_key and seen.isdigit() and int(seen) == doc["rev"]:
                    return _reply(req, {"rev": doc["rev"], "same": True})
                return _reply(req, doc)
            if path == "/hudedit/live":
                game = (q.get("game") or [""])[0]
                return _reply(req, dict(get_live(data_dir), copies=list_copies(data_dir),
                                        customs=custom_huds(data_dir, game) if game else []))
            if path == "/hudedit/copies":
                return _reply(req, {"copies": list_copies(data_dir), "deleted": deleted_copies(data_dir)[:30]})
            if path == "/hudedit/history":
                return _reply(req, {"versions": history(data_dir, (q.get("design") or [""])[0])})
            m = re.fullmatch(r"/hudedit/asset/(.+)", path)
            if m and ASSET.fullmatch(unquote(m.group(1))):
                full = os.path.join(folder(data_dir), "assets", unquote(m.group(1)))
                if os.path.isfile(full):
                    with open(full, "rb") as f:
                        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
                        if full.endswith(".woff2"):
                            ctype = "font/woff2"
                        return _reply(req, f.read(), ctype, cache=True)
            return _reply(req, {"error": "not found"}, status=404)
        if method != "POST":
            return _reply(req, {"error": "not allowed"}, status=405)
        if not _local(req.client_address[0]):
            return _reply(req, {"error": "HUDs can only be edited on the PC they run on"}, status=403)
        n = int(req.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD:
            return _reply(req, {"error": "That file is too big"}, status=413)
        raw = req.rfile.read(n) if n else b""
        if path == "/hudedit/upload":
            return _reply(req, {"name": store_upload(data_dir, (q.get("name") or [""])[0], raw)})
        body = json.loads(raw or b"{}")
        if not isinstance(body, dict):
            raise ValueError("Bad request")
        if path == "/hudedit/save":
            try:
                doc = save(data_dir, body.get("design"), body.get("edits"), body.get("base_rev"))
            except Conflict as c:
                return _reply(req, {"error": "These changes were saved somewhere else meanwhile.", "rev": c.rev,
                                    "conflict": True}, status=409)
            return _reply(req, {"ok": True, "rev": doc["rev"], "saved": doc["saved"]})
        if path == "/hudedit/copies":
            return _reply(req, copies_post(data_dir, body))
        if path == "/hudedit/restore":
            doc = restore(data_dir, body.get("design"), body.get("version"))
            return _reply(req, dict(doc, ok=True))
        return _reply(req, {"error": "not found"}, status=404)
    except KeyError as e:
        return _reply(req, {"error": str(e).strip("'")}, status=404)
    except (OSError, ValueError, TypeError) as e:
        return _reply(req, {"error": str(e) or type(e).__name__}, status=400)


# --- what can be edited (HUD Builder's Game HUDs page) ----------------------------

# (part key in SCC Broadcast Engine, game, title, default port)
GAMES = [("lol", "lol", "League of Legends", 8777), ("val", "valorant", "VALORANT", 8778),
         ("cod", "cod", "Call of Duty", 8780), ("rl", "rl", "Rocket League", 8781),
         ("smash", "smash", "Smash Ultimate", 8784), ("ow", "overwatch", "Overwatch", 8785)]

# (game, design key, name, page to open (on the HUD's port), what it is)
DESIGNS = [
    ("valorant", "val-scc2027", "SCC 2027", "/overlay?design=scc2027", "In-game HUD"),
    ("valorant", "val-scc2027", "SCC 2027 scoreboard", "/scoreboard?design=scc2027", "Buy-phase board (same design as the HUD)"),
    ("valorant", "val-default2026-hud", "Default 2026", "/overlay?design=default2026", "In-game HUD"),
    ("valorant", "val-default2026-board", "Default 2026 scoreboard", "/scoreboard?design=default2026", "Buy-phase board"),
    ("valorant", "val-agent-select", "Agent select", "/agent-select?look=default", "Board"),
    ("valorant", "val-agent-select-champions", "Agent select (Champions)", "/agent-select?look=champions", "Board"),
    ("valorant", "val-mapbans", "Map bans", "/map-bans?bo=3", "Board"),
    ("cod", "cod-overlay", "CDL / codcaster HUD", "/overlay", "In-game HUD"),
    ("rl", "rl-newgerrit", "NEW GERRIT", "/overlay-newgerrit", "In-game HUD"),
    ("rl", "rl-gerrit2026", "Gerrit 2026", "/overlay-gerrit2026", "In-game HUD"),
    ("rl", "rl-classic", "Classic", "/overlay-classic", "In-game HUD"),
    ("smash", "smash-scoreboard", "Crews scoreboard", "/scoreboard", "Overlay"),
    ("overwatch", "ow-overlay", "Overwatch HUD", "/overlay", "In-game HUD (all three styles)"),
    ("overwatch", "ow-mapbans", "Map bans", "/map-bans?bg=0", "Board"),
    ("lol", "lol-draft-scc27", "Draft SCC 2027 (fearless)", "/draft?layout=scc27", "Champ select"),
    ("lol", "lol-draft-europe", "Draft Europe", "/draft?layout=europe", "Champ select"),
    ("lol", "lol-draft-lec", "Draft LEC", "/draft?layout=lec", "Champ select"),
]
LOL_PROFILES = [{"id": "scc-2026", "name": "SCC 2026"}, {"id": "scc-2026-static", "name": "SCC 2026 - Static"}]


def _ports():
    """{part key: (port, status)} from SCC Broadcast Engine when this runs inside it."""
    out = {key: (port, "") for key, _g, _t, port in GAMES}
    try:
        from sccbe.parts import BY_KEY
        for key in out:
            p = BY_KEY.get(key)
            if p is not None:
                out[key] = (p.port or out[key][0], p.status)
    except Exception:
        pass
    return out


def _get(url, timeout=0.8):
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as r:
        return json.loads(r.read())


def _post(url, body, timeout=5):
    import urllib.error
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, json.dumps(body).encode("utf-8"), {"Content-Type": "application/json"})
    try:
        with opener.open(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error")
        except Exception:
            msg = None
        raise ValueError(msg or f"The HUD answered {e.code}")
    except OSError:
        raise ValueError("That game HUD isn't running. Turn it on to change its copies")


def copies_action(body):
    """HUD Builder > Game HUDs: make / rename / delete / bring back / put on air
    a copy, in the game HUD app that has it (body["part"] says which)."""
    part = str(body.get("part") or "")
    ports = _ports()
    if part not in ports:
        raise ValueError("Unknown game HUD")
    return _post(f"http://127.0.0.1:{ports[part][0]}/hudedit/copies", {k: v for k, v in body.items() if k != "part"})


def with_copy(path, cid):
    return path + ("&" if "?" in path else "?") + "hudcopy=" + cid


def catalog(only_game=None):
    """Every HUD design that can be edited, and whether its HUD is running."""
    ports = _ports()
    games = [g for g in GAMES if not only_game or g[1] == only_game]
    alive, lol_profiles, copies = {}, list(LOL_PROFILES), {}

    def probe(key, port):
        try:
            alive[key] = bool(_get(f"http://127.0.0.1:{port}/hudedit/ping").get("ok"))
        except Exception:
            alive[key] = False
        if alive[key]:
            try:
                copies[key] = _get(f"http://127.0.0.1:{port}/hudedit/copies")
                game_ = next(g for k, g, _t, _p in GAMES if k == key)
                copies[key]["live"] = _get(f"http://127.0.0.1:{port}/hudedit/live?game={game_}", timeout=2.5)
            except Exception:
                copies[key] = copies.get(key) or {}   # (a HUD from before copies / live)

    threads = [threading.Thread(target=probe, args=(k, ports[k][0]), daemon=True) for k, *_ in games]
    for t in threads:
        t.start()
    for t in threads:
        t.join(1.5)
    if alive.get("lol"):
        try:
            got = _get(f"http://127.0.0.1:{ports['lol'][0]}/api/profiles")
            if isinstance(got, list) and got:
                lol_profiles = [{"id": p["id"], "name": p.get("name") or p["id"]} for p in got if p.get("id")]
        except Exception:
            pass
    out = []
    for key, game, title, _port in games:
        port, status = ports[key]
        designs = []
        if game == "lol":
            designs += [(f"lol-overlay:{p['id']}", p["name"], f"/overlay?profile={p['id']}", "In-game HUD profile")
                        for p in lol_profiles]
        designs += [(k, n, p, what) for g, k, n, p, what in DESIGNS if g == game]
        rows = [{"key": k, "name": n, "path": p, "what": what} for k, n, p, what in designs]
        got = copies.get(key) or {}
        for c in got.get("copies") or []:
            # (under the HUD it's a copy of)
            of = next((r for r in rows if r["key"] == c["base"] and r["path"] == c["path"]), None) \
                or next((r for r in rows if r["key"] == c["base"]), None)
            row = {"key": copy_key(c["base"], c["id"]), "name": c["name"], "path": with_copy(c["path"], c["id"]),
                   "what": f"Copy of {of['name'] if of else c['base']}", "copy": {"id": c["id"], "base": c["base"], "path": c["path"]}}
            at = rows.index(of) + 1 if of else len(rows)
            while at < len(rows) and rows[at].get("copy"):
                at += 1
            rows.insert(at, row)
        live = got.get("live") or {}
        for r in rows:
            base = r["copy"]["base"] if r.get("copy") else r["key"]
            on = (live.get("active") or {}).get(base)
            r["live"] = not live.get("custom") and (on == r["copy"]["id"] if r.get("copy") else not on)
        out.append({"part": key, "game": game, "title": title, "port": port, "running": bool(alive.get(key)),
                    "status": status, "designs": rows, "deleted": got.get("deleted") or [],
                    "live": live.get("custom"), "customs": live.get("customs") or [], "has_live": bool(live)})
    return out
