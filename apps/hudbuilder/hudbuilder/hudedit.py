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
    GET  /hudedit/ping                       {"ok": true}
    GET  /hudedit/edits?design=KEY[&rev=N]   the saved changes ({"rev": N} alone when unchanged)
    GET  /hudedit/asset/<name>               an uploaded picture or font
    GET  /hudedit/history?design=KEY         earlier saved versions
    POST /hudedit/save     {design, edits, base_rev}  (409 when someone saved meanwhile)
    POST /hudedit/restore  {design, version}           an earlier version back (saved as a new one)
    POST /hudedit/upload?name=FILE           (raw bytes) -> {"name": stored name}

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
        "dur": "num", "delay": "num", "noanim": "bool", "del": "bool",
        "ease": ("ease", "linear", "ease-in", "ease-out", "ease-in-out", "snappy", "bounce")}
ADDED = {"id": "id", "type": ("box", "shape", "text", "image"),
         "shape": ("rect", "ellipse", "triangle", "line", "slant", "star", "arrow", "chevron"),
         "fill": "color", "fill2": "color", "angle": "num", "stroke": "color", "strokeWidth": "num", "slant": "num",
         "italic": "bool", "shadow": "bool", "x": "num", "y": "num", "w": "num", "h": "num",
         "rot": "num", "op": "num", "hide": "bool", "behind": "bool", "bg": "color", "radius": "num",
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


def handle(req, method, path, data_dir):
    """Answers /hudedit.js and /hudedit/... on a BaseHTTPRequestHandler. True when it did."""
    if path != "/hudedit.js" and not path.startswith("/hudedit/"):
        return False
    q = parse_qs(urlparse(req.path).query)
    try:
        if method == "GET":
            if path == "/hudedit.js":
                with open(os.path.join(WEB_DIR, "hudedit.js"), "rb") as f:
                    return _reply(req, f.read(), "text/javascript; charset=utf-8")
            if path == "/hudedit/ping":
                return _reply(req, {"ok": True})
            if path == "/hudedit/edits":
                design = (q.get("design") or [""])[0]
                doc = load(data_dir, design)
                seen = (q.get("rev") or [""])[0]
                if seen.isdigit() and int(seen) == doc["rev"]:
                    return _reply(req, {"rev": doc["rev"], "same": True})
                return _reply(req, doc)
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
        if path == "/hudedit/restore":
            doc = restore(data_dir, body.get("design"), body.get("version"))
            return _reply(req, dict(doc, ok=True))
        return _reply(req, {"error": "not found"}, status=404)
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


def catalog(only_game=None):
    """Every HUD design that can be edited, and whether its HUD is running."""
    ports = _ports()
    games = [g for g in GAMES if not only_game or g[1] == only_game]
    alive, lol_profiles = {}, list(LOL_PROFILES)

    def probe(key, port):
        try:
            alive[key] = bool(_get(f"http://127.0.0.1:{port}/hudedit/ping").get("ok"))
        except Exception:
            alive[key] = False

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
        out.append({"part": key, "game": game, "title": title, "port": port, "running": bool(alive.get(key)),
                    "status": status,
                    "designs": [{"key": k, "name": n, "path": p, "what": what} for k, n, p, what in designs]})
    return out
