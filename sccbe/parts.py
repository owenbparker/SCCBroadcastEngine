"""The parts of SCC Broadcast Engine: the GFX Engine, the six game HUDs,
HUD Builder and Multistream. Each is the app it always was (in apps/<name>),
run inside this one process: its web server starts on its usual port, so
every OBS browser-source link, Companion button, cam link and HUD-to-engine
pairing keeps working exactly as before.

A part can be switched on and off while the app runs (Settings). Starting
one is what its own desktop app did: build it, start its server, and give it
its windows (the HUD-over-the-game window, Multistream's chat window).
"""

import argparse
import errno
import importlib
import os
import sys
import threading
import time
import traceback

from .config import APPS_DIR, FROZEN
from .log import log


def port_taken(e):
    """Is this OSError "the port is already in use"?"""
    return isinstance(e, OSError) and (e.errno in (errno.EADDRINUSE, errno.EACCES, 10048, 10013)
                                       or getattr(e, "winerror", None) in (10048, 10013))


class Part:
    def __init__(self, key, title, kind, folder, package, entry, port, icon, overlay=False, pages=()):
        self.key, self.title, self.kind = key, title, kind
        self.folder, self.package = folder, package   # apps/<folder>/<package>
        self.entry = entry          # the page it opens on
        self.default_port = port
        self.icon = icon            # web/assets/games/...
        self.overlay = overlay      # has a HUD-over-the-game window
        self.pages = list(pages)    # (label, path) shortcuts shown on Home
        self.status = "off"         # off, starting, on, error, stopping
        self.error = ""
        self.app = None
        self.port = port
        self.started_at = None
        self._lock = threading.Lock()

    # --- info --------------------------------------------------------------

    def info(self):
        version = ""
        try:
            if self.app is not None:
                version = self.app.updater.current
        except Exception:
            pass
        return {"key": self.key, "title": self.title, "kind": self.kind, "status": self.status,
                "error": self.error, "port": self.port, "entry": self.entry, "icon": self.icon,
                "pages": [{"label": l, "path": p} for l, p in self.pages], "version": version}

    # --- starting and stopping ----------------------------------------------

    def start(self, windows=None):
        """Start in the background (returns at once). windows: the GUI, for
        the parts that open windows of their own (None without one)."""
        with self._lock:
            if self.status in ("starting", "on"):
                return
            self.status, self.error = "starting", ""
        threading.Thread(target=self._start, args=(windows,), name=f"start-{self.key}", daemon=True).start()

    def _start(self, windows):
        t0 = time.monotonic()
        try:
            self.app = self._build_and_start()
            self.port = self._read_port()
            if windows is not None:
                self._attach_windows(windows)
            self.status, self.started_at = "on", time.time()
            log(f"{self.title} is running on port {self.port} ({time.monotonic() - t0:.1f} s)")
        except OSError as e:
            self.app = None
            self.status = "error"
            if port_taken(e):
                self.error = (f"Port {self.port} is in use. Is the old {self.title} app still open? "
                              "Close it (and its icon by the clock), then press Try again.")
            else:
                self.error = f"{type(e).__name__}: {e}"
            log(f"{self.title} didn't start: {self.error}\n{traceback.format_exc()}", "error")
        except Exception as e:
            self.app = None
            self.status, self.error = "error", f"{type(e).__name__}: {e}"
            log(f"{self.title} didn't start: {self.error}\n{traceback.format_exc()}", "error")

    def _build_and_start(self):
        # Each part keeps its settings and files in data/<folder> (see tools/sync_apps.py).
        data = os.environ.get("SCCBE_DATA")
        if data:
            os.makedirs(os.path.join(data, self.folder), exist_ok=True)
        if self.key == "stream":
            mod = importlib.import_module("multistream.app")
            app = mod.StreamApp()
            mod.start(app, self.port)
            return app
        main = importlib.import_module(f"{self.package}.__main__")
        if self.key == "val":
            # (the VALORANT HUD keeps the day's log with its reader's frames, for problem reports)
            from valhud import log as applog
            from valhud.config import DATA_DIR as val_data
            applog.set_folder(os.path.join(val_data, "frames", "auto"))
        parser = argparse.ArgumentParser()
        main.add_arguments(parser)
        args = parser.parse_args([])
        build = getattr(main, "build_engine", None) or main.build_app
        app = build(args)
        importlib.import_module(f"{self.package}.app").start(app)
        return app

    def _read_port(self):
        app = self.app
        for attr in ("settings", "config"):
            store = getattr(app, attr, None)
            if store is not None and hasattr(store, "get"):
                try:
                    return int(store.get()["http_port"])
                except Exception:
                    pass
        return self.default_port

    def _attach_windows(self, windows):
        if self.overlay:
            mod = importlib.import_module(f"{self.package}.overlay_window")
            self.app.overlay_window = mod.OverlayWindow(self.app.config, self.port)
        if self.key == "stream":
            self.app.open_chat_window = windows.chat_window
        self.app.updater.on_exit = windows.close

    def stop(self):
        with self._lock:
            app, self.app = self.app, None
            if self.status == "off":
                return
            self.status = "stopping"
        try:
            if app is not None:
                ow = getattr(app, "overlay_window", None)
                if ow is not None:
                    try:
                        ow.close()
                    except Exception:
                        pass
                if self.key == "stream":
                    importlib.import_module("multistream.app").stop(app)
                else:
                    app.stop()
            log(f"{self.title} stopped")
        except Exception as e:
            log(f"{self.title} didn't stop cleanly: {type(e).__name__}: {e}", "warn")
        self.status, self.error = "off", ""


PARTS = [
    Part("engine", "GFX Engine", "engine", "gfxengine", "gfxengine", "/control#home", 8782, "gfx.png"),
    Part("lol", "League of Legends", "game", "lolhud", "lolhud", "/start", 8777, "lol.svg", overlay=True),
    Part("val", "VALORANT", "game", "valhud", "valhud", "/start", 8778, "valorant.svg", overlay=True),
    Part("cod", "Call of Duty", "game", "codhud", "codhud", "/control", 8780, "cod.png", overlay=True),
    Part("rl", "Rocket League", "game", "rlhud", "rlhud", "/start", 8781, "rocketleague.png", overlay=True),
    Part("smash", "Smash Ultimate", "game", "smashhud", "smashhud", "/control", 8784, "smash.png"),
    Part("ow", "Overwatch", "game", "owhud", "owhud", "/control", 8785, "overwatch.png"),
    Part("builder", "HUD Builder", "tool", "hudbuilder", "hudbuilder", "/", 8800, "builder.svg"),
    Part("stream", "Multistream", "tool", "multistream", "multistream", "/", 8775, "stream.svg"),
]
BY_KEY = {p.key: p for p in PARTS}


def add_to_path():
    """Running from source: each part's folder goes on the import path (the
    built app has them all in one place already)."""
    if FROZEN:
        return
    for p in PARTS:
        folder = os.path.join(APPS_DIR, p.folder)
        if folder not in sys.path:
            sys.path.insert(0, folder)
