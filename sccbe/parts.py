"""The parts of SCC Broadcast Engine: the GFX Engine, the six game HUDs,
HUD Builder and Multistream. Each is the app it always was (in apps/<name>),
run inside this one process: its web server starts on its usual port, so
every OBS browser-source link, Companion button, cam link and HUD-to-engine
pairing keeps working exactly as before.

A part can be switched on and off while the app runs (Settings). Starting
one is what its own desktop app did: build it, start its server, and give it
its windows (the HUD-over-the-game window, Multistream's chat window).

A game HUD can also run as a program of its own (Settings > "Run game HUDs
as separate programs"): the same app started again with --part <key>. Then a
HUD that crashes (a screen reader taking the whole program down, say) can't
take the GFX Engine with it, and it's started again by itself. The two talk
over the child's stdin/stdout: it says every couple of seconds what port it's
on, its version and whether a match is on; it stops when its stdin closes
(this app closed, or crashed).
"""

import argparse
import errno
import importlib
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import urllib.request

from .config import APPS_DIR, FROZEN
from .log import log

STATUS_TAG = "SCCBE-PART "   # (a child's status lines on its stdout)


def port_taken_text(text):
    """A child's log ends with "the port is already in use"."""
    return any(s in (text or "") for s in ("Errno 98", "Errno 48", "WinError 10048", "WinError 10013", "Address already in use"))


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
        # Run as a program of its own (see the top of this file).
        self.proc = None            # the child process
        self.child = {}             # its last status: {"port", "version", "busy"}
        self.crashes = []           # when it stopped by itself (restarts stop after too many)
        self._wanted = False

    RESTARTS = 3                    # crashes within RESTART_WINDOW before it's left stopped
    RESTART_WINDOW = 600.0

    # --- info --------------------------------------------------------------

    def info(self):
        version = self.child.get("version") or ""
        try:
            if self.app is not None:
                version = self.app.updater.current
        except Exception:
            pass
        return {"key": self.key, "title": self.title, "kind": self.kind, "status": self.status,
                "error": self.error, "port": self.port, "entry": self.entry, "icon": self.icon,
                "pages": [{"label": l, "path": p} for l, p in self.pages], "version": version,
                "separate": self.proc is not None, "restarts": len(self.crashes)}

    def busy(self):
        """Why updating now would interrupt something (a match being read), or None."""
        if self.proc is not None:
            return self.child.get("busy") or None
        up = getattr(self.app, "updater", None) if self.app is not None else None
        return up._busy() if up is not None and hasattr(up, "_busy") else None

    # --- starting and stopping ----------------------------------------------

    def start(self, windows=None, separate=False):
        """Start in the background (returns at once). windows: the GUI, for
        the parts that open windows of their own (None without one).
        separate: as a program of its own (game HUDs only)."""
        with self._lock:
            if self.status in ("starting", "on"):
                return
            self.status, self.error, self._wanted = "starting", "", True
        if separate and self.kind == "game":
            self.crashes = []
            self._thread = threading.Thread(target=self._supervise, name=f"part-{self.key}", daemon=True)
            self._thread.start()
            return
        threading.Thread(target=self._start, args=(windows,), name=f"start-{self.key}", daemon=True).start()

    # --- as a program of its own -------------------------------------------------

    def command(self):
        """The command line that runs just this part."""
        if FROZEN:
            return [sys.executable, "--part", self.key]
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "SCCBroadcastEngine.py")
        return [sys.executable, script, "--part", self.key]

    def _log_path(self):
        data = os.environ.get("SCCBE_DATA") or "."
        folder = os.path.join(data, "shell", "parts")
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, f"{self.key}.log")

    def _supervise(self):
        """Runs the child, and starts it again when it stops by itself (not
        more than RESTARTS times in RESTART_WINDOW)."""
        while self._wanted:
            t0 = time.monotonic()
            try:
                self._spawn()
            except OSError as e:
                self.status, self.error = "error", f"Couldn't start it as its own program: {e}"
                log(f"{self.title}: {self.error}", "error")
                return
            code = self._follow()
            proc, self.proc = self.proc, None
            for pipe in (proc.stdin, proc.stdout):
                try:
                    pipe.close()
                except OSError:
                    pass
            if not self._wanted:
                break
            now = time.time()
            self.crashes = [t for t in self.crashes if now - t < self.RESTART_WINDOW] + [now]
            tail = self._log_tail()
            if port_taken_text(tail):
                self.status = "error"
                self.error = (f"Port {self.port} is in use. Is the old {self.title} app still open? "
                              "Close it (and its icon by the clock), then press Try again.")
                log(f"{self.title} didn't start: {self.error}", "error")
                return
            if len(self.crashes) > self.RESTARTS:
                self.status = "error"
                self.error = (f"It stopped {len(self.crashes)} times in {int(self.RESTART_WINDOW / 60)} minutes, "
                              f"so it's left off. Press Restart to try again (its log: {self._log_path()}).")
                log(f"{self.title} keeps stopping (exit code {code}); left off.\n{tail}", "error")
                return
            wait = (2, 5, 15)[min(len(self.crashes), 3) - 1]
            self.status, self.error = "starting", f"It stopped (exit code {code}): starting it again"
            log(f"{self.title} stopped by itself after {time.monotonic() - t0:.0f} s (exit code {code}); "
                f"starting it again in {wait} s.\n{tail}", "error")
            for _ in range(wait * 10):
                if not self._wanted:
                    break
                time.sleep(0.1)
        self.status, self.error = "off", ""

    def _spawn(self):
        log_file = open(self._log_path(), "w", encoding="utf-8", errors="replace")
        flags = 0x08000000 if sys.platform == "win32" else 0   # (CREATE_NO_WINDOW: no console flashing up)
        try:
            self.proc = subprocess.Popen(self.command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=log_file, env=dict(os.environ), creationflags=flags,
                                         cwd=os.path.dirname(sys.executable) if FROZEN else None)
        finally:
            log_file.close()   # (the child has its own handle)
        self.child, self.started_at = {}, None

    def _follow(self):
        """Reads the child's status lines until it stops. Returns its exit code."""
        proc = self.proc
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith(STATUS_TAG):
                continue
            try:
                status = json.loads(line[len(STATUS_TAG):])
            except ValueError:
                continue
            self.child = status
            if status.get("port"):
                self.port = int(status["port"])
            if status.get("error"):
                self.error = status["error"]
            elif status.get("ready") and self.status != "on":
                self.status, self.error, self.started_at = "on", "", time.time()
                log(f"{self.title} is running on port {self.port} (its own program, pid {proc.pid})")
        return proc.wait()

    def _log_tail(self, n=15):
        try:
            with open(self._log_path(), encoding="utf-8", errors="replace") as f:
                return "".join(f.readlines()[-n:]).rstrip()
        except OSError:
            return ""

    def _stop_child(self):
        proc = self.proc
        if proc is None:
            return
        try:
            proc.stdin.close()   # (it stops when its stdin closes)
        except OSError:
            pass
        try:
            proc.wait(8)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                pass

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
        self.app.updater.on_exit = windows.close

    def stop(self):
        with self._lock:
            self._wanted = False
            app, self.app = self.app, None
            if self.status == "off" and self.proc is None:
                return
            self.status = "stopping"
        thread = getattr(self, "_thread", None)
        if self.proc is not None or (thread is not None and thread.is_alive()):
            self._stop_child()
            if thread is not None:
                thread.join(15)   # (the supervisor sees it end, and starts nothing again)
            self._thread = None
            log(f"{self.title} stopped")
            self.status, self.error = "off", ""
            return
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


def run_child(key):
    """This process is just one part (--part <key>): start it, say how it's
    doing on stdout every couple of seconds, and stop when stdin closes."""
    part = BY_KEY[key]
    out = sys.stdout if sys.stdout is not None else os.fdopen(1, "w")
    sys.stdout = sys.stderr if sys.stderr is not None else open(os.devnull, "w")   # (prints go to the log, not the status)
    lock = threading.Lock()

    def say(**status):
        line = STATUS_TAG + json.dumps(status, default=str)
        with lock:
            try:
                out.write(line + "\n")
                out.flush()
            except (OSError, ValueError):
                os._exit(0)   # (nobody's listening: this app is gone)

    try:
        part.app = part._build_and_start()
        part.port = part._read_port()
    except Exception as e:
        traceback.print_exc()
        say(port=part.port, error=f"{type(e).__name__}: {e}")
        sys.stderr.flush()
        os._exit(3)
    stop = threading.Event()

    def watch_stdin():
        stdin = sys.stdin if sys.stdin is not None else os.fdopen(0)
        try:
            while stdin.read(1):
                pass
        except (OSError, ValueError):
            pass
        stop.set()

    def report():
        while not stop.is_set():
            busy = None
            try:
                busy = part.busy()
            except Exception as e:
                busy = None
                print(f"Couldn't tell whether a match is on: {e!r}", file=sys.stderr)
            version = getattr(getattr(part.app, "updater", None), "current", "")
            say(ready=True, port=part.port, version=version, busy=busy, pid=os.getpid())
            stop.wait(2)

    threading.Thread(target=watch_stdin, daemon=True).start()
    threading.Thread(target=report, daemon=True).start()
    return part, stop
