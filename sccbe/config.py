"""Where things are, and this PC's settings (data/shell/settings.json).

In the built app (C:\\SCC Broadcast Engine by default, or the folder chosen
in Setup):

    SCCBroadcastEngine.exe
    _internal/            the app (replaced on every update)
        web/              the top bar, Home and Settings pages
        apps/<part>/      each part's own files (its web folder, ...)
    data/                 everything that's yours (kept by updates)
        shell/            this file's settings
        gfxengine/        the GFX Engine's workspaces and settings
        lolhud/ ...       each game HUD's config, logos, profiles
"""

import copy
import json
import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FROZEN = getattr(sys, "frozen", False)
RESOURCE_DIR = getattr(sys, "_MEIPASS", ROOT) if FROZEN else ROOT
APP_DIR = os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else ROOT
DATA_DIR = os.environ.get("SCCBE_DATA") or os.path.join(APP_DIR, "data")
WEB_DIR = os.path.join(RESOURCE_DIR, "web")
APPS_DIR = os.path.join(RESOURCE_DIR, "apps")
SHELL_DIR = os.path.join(DATA_DIR, "shell")
SETTINGS_PATH = os.path.join(SHELL_DIR, "settings.json")

# What each kind of PC runs. The parts can be switched on and off one by one
# in Settings afterwards; the role is just the starting point.
ROLES = {
    "control": {"engine": True, "builder": True},
    "hud": {"engine": False, "builder": False},
    "stream": {"engine": False, "builder": False, "stream": True},
}

DEFAULTS = {
    # The top bar, Home and Settings (not a port any other part uses).
    "http_port": 8770,
    # Set on first start, from "What does this PC do?".
    "setup_done": False,
    "role": "control",
    # Which parts run on this PC. Games start off: switch on the ones you use.
    "parts": {"engine": True, "builder": True, "stream": False,
              "lol": False, "val": False, "cod": False, "rl": False, "smash": False, "ow": False},
    # A HUD PC's Control PC (its GFX Engine), e.g. "192.168.2.40" or
    # "http://192.168.2.40:8782". Control, Composer and Event open from it.
    "control_pc": "",
    # The Control PC engine's pairing code (its Outputs & Network page), when it asks for one.
    "control_pc_key": "",
    # Game HUDs run as programs of their own: one that crashes starts again by
    # itself and can't take the GFX Engine (or the other HUDs) down with it.
    "separate_huds": False,
    # Home's background: "solid" (a solid colour) or "loop" (the SCC BG loop).
    "background": "solid",
    "solid_colour": "#0c0c0e",
    "name": "",   # shown on Home ("Good evening, <name>.")
    # Settings > Network: other networks (VLANs) and PCs every part looks
    # through when it finds PCs ("10.230.2.0/24", "10.230.2.15", "HUD-PC-3"),
    # see scc_shared/netpeers.py.
    "other_networks": [],
    # The game HUDs already opened to the network once (sccbe/network.py Opener).
    "network_opened": [],
}

_lock = threading.Lock()


def _merge(base, extra):
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Settings:
    def __init__(self, path=SETTINGS_PATH):
        self.path = path
        self.data = copy.deepcopy(DEFAULTS)
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.data = _merge(DEFAULTS, json.load(f))
            except (OSError, ValueError):
                pass

    def get(self):
        with _lock:
            return copy.deepcopy(self.data)

    def update(self, changes):
        with _lock:
            self.data = _merge(self.data, changes)
            snapshot = copy.deepcopy(self.data)
        self.save(snapshot)
        return snapshot

    def save(self, snapshot=None):
        snapshot = snapshot if snapshot is not None else self.get()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
        os.replace(tmp, self.path)


def control_pc_url(text):
    """The Control PC's GFX Engine as http://host:port from whatever was typed
    ("192.168.2.40", "192.168.2.40:8782", "http://192.168.2.40:8782/control")."""
    from urllib.parse import urlparse
    text = (text or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "http://" + text
    u = urlparse(text)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError(f"That doesn't look like an address: {text}")
    host = f"[{u.hostname}]" if ":" in u.hostname else u.hostname
    return f"{u.scheme}://{host}:{u.port or 8782}"


def web_file(rel):
    """Path on disk for a URL path in the web folder (None if it climbs out or isn't there)."""
    rel = rel.replace("\\", "/").lstrip("/")
    path = os.path.normpath(os.path.join(WEB_DIR, rel))
    if not path.startswith(os.path.normpath(WEB_DIR) + os.sep) or not os.path.isfile(path):
        return None
    return path
