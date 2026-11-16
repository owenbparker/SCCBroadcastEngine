"""NEW GERRIT's replay stinger: which video plays as the game's replay starts.

In order:
  1. the one uploaded in this HUD's control panel (config replay_stinger.src),
     an optional override; a .mov (or any video a browser can't play) is
     converted to WebM (see-through) or MP4 first, as the GFX Engine does;
  2. the connected GFX Engine's "Replay stinger" transition (its video and cut
     point), copied here so the overlay plays it from this HUD, on any PC;
  3. the SCC replay stinger the GFX Engine ships with (its starter project).
"""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import RESOURCE_DIR, STINGER_DIR
from .log import log

CHECK_EVERY = 15          # s, between looks at the engine's transitions
# The GFX Engine's own SCC replay stinger (its starter project), and its cut.
BUILTIN_DIR = os.path.join(os.path.dirname(RESOURCE_DIR), "gfxengine", "starter", "assets", "stingers")
BUILTIN = {"file": "SCC_Replay.webm", "cut": 653, "name": "SCC replay stinger (built in)"}
ENGINE_SUB = "engine"     # stingers/engine/...: the copy of the engine's
UPLOAD_TYPES = (".webm", ".mp4", ".m4v", ".mov", ".mkv", ".avi", ".mxf")
UPLOAD_MAX = 1024 * 1024 * 1024


def _get(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def builtin_path():
    path = os.path.join(BUILTIN_DIR, BUILTIN["file"])
    return path if os.path.isfile(path) else None


def pick_replay(transitions):
    """The engine's replay stinger: the stinger transition named "Replay stinger",
    else the first stinger with "replay" in its name."""
    stingers = [t for t in transitions or [] if isinstance(t, dict) and t.get("type") == "stinger" and t.get("src")]
    for t in stingers:
        if (t.get("name") or "").strip().lower() == "replay stinger":
            return t
    return next((t for t in stingers if "replay" in (t.get("name") or "").lower()), None)


def _safe_name(name, default="stinger"):
    return re.sub(r"[^A-Za-z0-9 _.-]+", "", os.path.basename(name or "")).strip(" .") or default


class ReplayStinger:
    def __init__(self, config, engine, on_change):
        self.config, self.engine, self.on_change = config, engine, on_change
        self.from_engine = None    # {"src", "cut", "name", "audio", "volume", "engine"} (copied here)
        self.converting = ""       # the upload being made playable
        self.error = ""
        self._wake = threading.Event()
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="replay-stinger").start()

    # --- which one plays -------------------------------------------------------------
    def current(self):
        """For the overlay: {"src", "cut" (ms or None = halfway), "name", "from", "audio", "volume"}, or {"src": ""}."""
        own = self.config.get().get("replay_stinger") or {}
        if own.get("on") is False:
            return {"src": "", "from": "off"}
        if own.get("src"):
            return {"src": own["src"], "cut": own.get("cut"), "name": own.get("name") or own["src"], "from": "upload",
                    "audio": True, "volume": 1}
        if self.from_engine:
            return dict(self.from_engine, **{"from": "engine"})
        if builtin_path():
            return {"src": "builtin-stinger/" + BUILTIN["file"], "cut": BUILTIN["cut"], "name": BUILTIN["name"],
                    "from": "builtin", "audio": True, "volume": 1}
        return {"src": "", "from": "none"}

    def info(self):
        return dict(self.current(), converting=self.converting, error=self.error,
                    engine_connected=bool(self.engine.connected and self.engine.url))

    def check_now(self):
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()

    # --- the GFX Engine's "Replay stinger" ---------------------------------------------
    def _run(self):
        failed = ""
        while not self._stop.is_set():
            eng = self.engine
            if eng.connected and eng.url:
                try:
                    self._take_from(eng)
                    failed = self.error = ""
                except Exception as e:
                    msg = str(getattr(e, "reason", e))
                    if msg != failed:
                        log(f"Couldn't take the replay stinger from the GFX Engine: {msg}", "warn")
                    failed = self.error = msg
            self._wake.wait(CHECK_EVERY)
            self._wake.clear()

    def _take_from(self, eng):
        try:
            reply = json.loads(_get(eng.url + "/api/transitions", 5))
        except urllib.error.HTTPError as e:
            if e.code == 404:   # (an engine from before this: the built-in one plays)
                return
            raise
        t = pick_replay(reply.get("transitions"))
        if not t:
            if self.from_engine:
                self.from_engine = None
                log("The GFX Engine has no \"Replay stinger\" any more: the built-in one plays")
                self.on_change()
            return
        src = t["src"]
        name = _safe_name(src.split("/")[-1])
        rel = f"stingers/{ENGINE_SUB}/{name}"
        want = {"src": rel, "cut": t.get("cut") if t.get("cut") not in ("", None) else None, "name": t.get("name") or "Replay stinger",
                "audio": t.get("audio") is not False, "volume": 1 if t.get("volume") is None else float(t.get("volume")),
                "engine": src}
        path = os.path.join(STINGER_DIR, ENGINE_SUB, name)
        have = self.from_engine or {}
        if have.get("engine") != src or not os.path.isfile(path):
            blob = _get(eng.url + "/" + urllib.parse.quote(src), 120)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + ".part", "wb") as f:
                f.write(blob)
            os.replace(path + ".part", path)
            log(f'Took the replay stinger "{want["name"]}" from the GFX Engine {eng.name or eng.url}')
        if want != have:
            self.from_engine = want
            self.on_change()

    # --- your own (an optional override) ------------------------------------------------
    def save_upload(self, filename, stream, length):
        """A stinger sent from the control panel (the file's bytes). A browser-ready
        WebM/MP4 is used at once; a .mov and the like are converted first."""
        name = _safe_name(filename)
        stem, ext = os.path.splitext(name)
        ext = ext.lower()
        if ext not in UPLOAD_TYPES:
            raise ValueError("Send the stinger as a MOV, WebM or MP4 video")
        if length <= 0 or length > UPLOAD_MAX:
            raise ValueError("That stinger is empty or over 1 GB")
        os.makedirs(STINGER_DIR, exist_ok=True)
        path = os.path.join(STINGER_DIR, stem + ext)
        left = length
        with open(path + ".part", "wb") as f:
            while left > 0:
                chunk = stream.read(min(left, 1 << 20))
                if not chunk:
                    raise ValueError("The upload stopped part way")
                f.write(chunk)
                left -= len(chunk)
        os.replace(path + ".part", path)
        media = _media()
        if ext in (".webm", ".mp4", ".m4v"):   # (browser-ready as it is)
            return self._use(path, filename)
        if not media or not media.ffmpeg_path():
            raise ValueError("This video needs converting and FFmpeg isn't available here: export it as WebM or MP4")
        self.converting = os.path.basename(filename or name)
        log(f"Converting the replay stinger {self.converting} so the overlay can play it…")
        threading.Thread(target=self._convert, args=(media, path, filename), daemon=True).start()
        return {"converting": self.converting}

    def _convert(self, media, path, filename):
        try:
            info = media.probe(path)
            out = media.convert(path, os.path.splitext(path)[0] + ".converted", alpha=info["alpha"])
            os.remove(path)
            self._use(out, filename)
        except Exception as e:
            self.error = f"Couldn't convert {os.path.basename(filename or path)}: {e}"
            log(self.error, "error")
        finally:
            self.converting = ""
            self.on_change()

    def _use(self, path, filename):
        rel = "stingers/" + os.path.relpath(path, STINGER_DIR).replace(os.sep, "/")
        cut = None
        media = _media()
        if media:
            try:
                cut = media.stinger_cut(path)
            except Exception:
                cut = None
        self.config.update({"replay_stinger": {"src": rel, "name": os.path.basename(filename or path), "cut": cut, "on": True}})
        log(f"Replay stinger is now your own: {os.path.basename(filename or path)}"
            + (f" (the replay graphics swap in under it at {cut} ms)" if cut is not None else ""))
        self.error = ""
        self.on_change()
        return {"src": rel, "cut": cut}

    def use_engine(self):
        """Back to the GFX Engine's (or the built-in) replay stinger."""
        self.config.update({"replay_stinger": {"src": "", "name": "", "cut": None, "on": True}})
        log("Replay stinger: the GFX Engine's \"Replay stinger\" plays (the built-in one when no engine is connected)")
        self.check_now()
        self.on_change()


def _media():
    """The GFX Engine's video tools (FFmpeg: probe, convert, stinger cut), when they're here."""
    try:
        from gfxengine import media
        return media
    except Exception:
        return None
