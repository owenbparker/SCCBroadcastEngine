"""Where things live, and the app's own settings (settings.json).

The graphics themselves (compositions, transitions, data sources) and their
files are workspaces: workspaces/<id>/project.json and assets/, next to the
app (next to GFXEngine.exe in the desktop build). Fonts are shared by every
workspace, in library/fonts.
"""

import copy
import json
import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FROZEN = getattr(sys, "frozen", False)
# SCC Broadcast Engine: this part's files are in _internal/apps/gfxengine in the built app
RESOURCE_DIR = os.path.join(getattr(sys, "_MEIPASS", ROOT), "apps", "gfxengine") if FROZEN else ROOT
# SCC Broadcast Engine: settings and data in data/gfxengine (SCCBE_DATA is set by sccbe/gui.py)
DATA_DIR = (os.path.join(os.environ["SCCBE_DATA"], "gfxengine") if os.environ.get("SCCBE_DATA") else
            os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else ROOT)
WEB_DIR = os.path.join(RESOURCE_DIR, "web")
STARTER_DIR = os.path.join(RESOURCE_DIR, "starter")
WORKSPACES_DIR = os.path.join(DATA_DIR, "workspaces")
LEGACY_WORKSPACE_DIR = os.path.join(DATA_DIR, "workspace")   # (v1.0.1: one workspace)
LIBRARY_DIR = os.path.join(DATA_DIR, "library")             # shared by every workspace (fonts)
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")

# Not the League (8777, 8779), VALORANT (8778), CoD (8780), RL (8781) HUDs'
# or the HUD Manager's (8790) ports. Engines find each other on DISCOVERY_PORT.
PORT = 8782
DISCOVERY_PORT = 8783

DEFAULTS = {
    "http_port": PORT,
    # Other PCs can open the outputs and the control panel, and find this
    # engine (it announces itself on the network).
    "allow_network": True,
    # The one network other PCs reach it on (this PC's address on it, e.g. the
    # NDI VLAN's), or "" for every network.
    "network_address": "",
    # This engine's name on the network.
    "name": "",
    # The pairing code (6 digits, made once): other PCs that change anything
    # (a HUD on another PC, Companion, the control panel opened there) send it.
    "network_key": "",
    # Other PCs need the pairing code to change anything (outputs and every
    # other read stay open). On for new installs; off for ones that ran
    # before it existed, so nothing stops working after an update.
    "require_key": False,
    # This engine's own ID (made once): a game HUD pairs with it, so a HUD
    # never sends to, or takes Global Information from, another engine.
    "engine_id": "",
    # The PC it was made on (a copy of this folder on another PC makes its own).
    "engine_id_pc": "",
    # The workspace open (its folder in workspaces/).
    "workspace": "",
    # The Camera Control Room's saved lighting: [{"name", "cams": {"<pc>|<camera>":
    # {setting: {"value", "auto"}}}}]
    "camera_looks": [],
}

_lock = threading.Lock()


class Settings:
    def __init__(self, path=SETTINGS_PATH):
        self.path = path
        self.data = copy.deepcopy(DEFAULTS)
        if not os.path.exists(path):
            self.data["require_key"] = True   # (a new install: ask for the code from the start)
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.data.update(json.load(f))
            except (OSError, ValueError):
                pass

    def get(self):
        with _lock:
            return copy.deepcopy(self.data)

    def update(self, changes):
        with _lock:
            self.data.update({k: v for k, v in changes.items() if k in DEFAULTS})
            snapshot = copy.deepcopy(self.data)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
        os.replace(tmp, self.path)
        return snapshot


def safe_join(base, rel):
    """base/rel on disk if it's a file inside base, else None."""
    rel = rel.replace("\\", "/").lstrip("/")
    path = os.path.normpath(os.path.join(base, rel))
    if not path.startswith(os.path.normpath(base) + os.sep) or not os.path.isfile(path):
        return None
    return path
