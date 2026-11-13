"""The shell: the top bar, Home and Settings pages (web/), and the parts
switched on for this PC. Serves http://127.0.0.1:8770/ for the app window.
"""

import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import parts as P
from .config import APP_DIR, DATA_DIR, FROZEN, ROLES, Settings, control_pc_url, web_file
from .log import log, lines
from .ros import RunOfShow
from .updater import Updater, clean_up_old_update
from .version import VERSION

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("video/webm", ".webm")


class Shell:
    def __init__(self, settings=None):
        self.settings = settings or Settings()
        self.updater = Updater()
        self.parts = P.PARTS
        self.windows = None     # the GUI (sccbe/gui.py), once the window is up
        self.httpd = None
        self._engine = {"t": 0, "data": None}
        self._engine_lock = threading.Lock()
        self.ros = RunOfShow(os.path.join(DATA_DIR, "shell", "run-of-show.json"))

    # --- parts ---------------------------------------------------------------

    def start_parts(self):
        """Start every part switched on in Settings (in the background)."""
        if not self.settings.get()["setup_done"]:
            return   # first start: "What does this PC do?" decides
        on = self.settings.get()["parts"]
        for part in self.parts:
            if on.get(part.key):
                part.start(self.windows)

    def set_part(self, key, on):
        part = P.BY_KEY.get(key)
        if not part:
            raise ValueError(f"No part called {key}")
        self.settings.update({"parts": {key: bool(on)}})
        if on:
            part.start(self.windows)
        else:
            threading.Thread(target=part.stop, daemon=True).start()

    def restart_part(self, key):
        part = P.BY_KEY.get(key)
        if not part:
            raise ValueError(f"No part called {key}")

        def go():
            part.stop()
            part.start(self.windows)
        threading.Thread(target=go, daemon=True).start()

    def setup(self, body):
        """First start (or Settings > This PC's role): what the PC does."""
        role = body.get("role") or "control"
        if role not in ROLES and role != "custom":
            raise ValueError(f"Unknown role {role}")
        want = dict(self.settings.get()["parts"])
        want.update(ROLES.get(role, {}))
        for key, on in (body.get("parts") or {}).items():
            if key in P.BY_KEY:
                want[key] = bool(on)
        changes = {"role": role, "parts": want, "setup_done": True}
        if "name" in body:
            changes["name"] = str(body.get("name") or "")[:40]
        if "control_pc" in body:
            changes["control_pc"] = control_pc_url(body.get("control_pc"))
        self.settings.update(changes)
        for part in self.parts:
            if want.get(part.key):
                part.start(self.windows)
            elif part.status != "off":
                threading.Thread(target=part.stop, daemon=True).start()

    def stop(self):
        for part in reversed(self.parts):
            if part.status != "off":
                part.stop()
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()

    # --- the GFX Engine this PC uses (its own, or the Control PC's) ------------

    def engine_base(self):
        """(address the window uses, is_remote)."""
        s = self.settings.get()
        engine = P.BY_KEY["engine"]
        if s["parts"].get("engine") or engine.status != "off":
            return f"http://127.0.0.1:{engine.port}", False
        return (s.get("control_pc") or ""), True

    def engine_summary(self):
        """Tonight's match and what's on air, from the engine (cached 2 s)."""
        base, remote = self.engine_base()
        with self._engine_lock:
            if self._engine["data"] is not None and time.monotonic() - self._engine["t"] < 2 and self._engine["base"] == base:
                return self._engine["data"]
        out = {"base": base, "remote": remote, "ok": False}
        if base:
            try:
                with urllib.request.urlopen(base + "/api/state", timeout=1.5) as r:
                    s = json.loads(r.read().decode("utf-8"))
                names = {c.get("id"): c.get("name") for c in (s.get("project") or {}).get("compositions", [])}
                live = s.get("live") or {}
                g = s.get("global") or {}

                def team(side):
                    t = g.get(side) or {}
                    logo = t.get("logo") or ""
                    if logo and not logo.startswith(("http:", "https:", "data:")):
                        logo = base + "/" + logo.lstrip("/")
                    return {"name": t.get("name") or "", "short": t.get("short") or "", "score": t.get("score") or 0,
                            "color": t.get("color") or "", "logo": logo}
                sched = g.get("schedule") or {}
                out.update(ok=True, version=(s.get("app") or {}).get("version", ""),
                           schedule=[m for m in sched.get("matches") or [] if isinstance(m, dict)],
                           graphics=[{"id": c.get("id"), "name": c.get("name")} for c in (s.get("project") or {}).get("compositions", [])],
                           workspace=(s.get("workspace") or {}).get("name", ""),
                           match={"event": g.get("event") or "", "stage": g.get("stage") or "",
                                  "best_of": g.get("best_of") or 0, "left": team("left"), "right": team("right")},
                           program=[names.get(i, i) for i in (live.get("program") or {}).get("on", [])],
                           preview=[names.get(i, i) for i in (live.get("preview") or {}).get("on", [])])
            except Exception as e:
                out["error"] = str(getattr(e, "reason", e))
        with self._engine_lock:
            self._engine = {"t": time.monotonic(), "data": out, "base": base}
        return out

    def engine_call(self, path, body=None, timeout=4):
        """Ask the GFX Engine this PC uses (its own or the Control PC's)."""
        base, _ = self.engine_base()
        if not base:
            raise ValueError("No GFX Engine: switch it on, or set the Control PC in Settings")
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error")
            except Exception:
                msg = None
            raise ValueError(msg or f"The GFX Engine said {e.code}")
        except (urllib.error.URLError, OSError) as e:
            raise ValueError(f"Can't reach the GFX Engine at {base} ({getattr(e, 'reason', e)})")

    def ros_state(self):
        e = self.engine_summary()
        if e.get("ok"):
            try:
                self.ros.auto_apply(e.get("schedule") or [], (e.get("match") or {}).get("best_of"))
            except Exception as err:
                log(f"Run of show: couldn't follow the Schedule ({err})", "warn")
        out = self.ros.state()
        out["engine"] = {"ok": e.get("ok", False), "graphics": e.get("graphics") or [],
                         "schedule": e.get("schedule") or [], "match": e.get("match")}
        return out

    def ros_post(self, path, body):
        r = self.ros
        if path == "/api/ros/template":
            return {"template": r.save_template(body.get("template") or {})}
        if path == "/api/ros/template/delete":
            r.delete_template(body.get("id"))
        elif path == "/api/ros/template/new":
            from .ros import starter_template
            return {"template": r.save_template(starter_template(body.get("game") or "val", int(body.get("best_of") or 3)))}
        elif path == "/api/ros/apply":
            e = self.engine_summary()
            from .ros import pick_match
            match = body.get("match") or pick_match(e.get("schedule") or []) or {}
            if not match.get("best_of") and (e.get("match") or {}).get("best_of"):
                match["best_of"] = e["match"]["best_of"]
            r.apply(match, body.get("template_id"), body.get("best_of"))
        elif path in ("/api/ros/next", "/api/ros/go"):
            show = r.data.get("show")
            if not show:
                raise ValueError("No run of show yet")
            e = self.engine_summary()
            m = e.get("match") if e.get("ok") else None
            scores = [m["left"]["score"], m["right"]["score"]] if m else None
            index = show.get("current", -1) + 1 if path == "/api/ros/next" else int(body.get("index", -1))
            r.go(index, scores if path == "/api/ros/next" else None)
        elif path == "/api/ros/reset":
            r.reset()
        elif path == "/api/ros/show":
            r.edit_show(body.get("segments"), body.get("start"))
        elif path == "/api/ros/auto":
            r.set_auto(body.get("on"))
        else:
            raise KeyError(path)
        return self.ros_state()

    # --- state -----------------------------------------------------------------

    def state(self):
        return {"app": {"name": "SCC Broadcast Engine", "version": VERSION, "frozen": FROZEN,
                        "app_dir": APP_DIR, "data_dir": DATA_DIR, "platform": sys.platform},
                "settings": self.settings.get(),
                "parts": [p.info() for p in self.parts],
                "engine": self.engine_summary(),
                "update": self.updater.info()}


def open_folder(path):
    os.makedirs(path, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 (a folder, in Explorer)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def make_handler(shell):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, code=200):
            self._send(code, json.dumps(data).encode("utf-8"), "application/json")

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            data = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            return data

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/state":
                return self._json(shell.state())
            if path == "/api/log":
                return self._json({"lines": lines()})
            if path == "/api/ros":
                return self._json(shell.ros_state())
            if path == "/api/engine/workspaces":
                try:
                    return self._json(shell.engine_call("/api/workspaces"))
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
            if path in ("/", "/index.html"):
                path = "/index.html"
            f = web_file(path)
            if not f:
                return self._send(404, b"Not found", "text/plain")
            with open(f, "rb") as fh:
                body = fh.read()
            self._send(200, body, mimetypes.guess_type(f)[0] or "application/octet-stream")

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                body = self._body()
                if path.startswith("/api/ros/"):
                    return self._json(shell.ros_post(path, body))
                if path == "/api/engine/workspace":
                    shell.engine_call("/api/workspaces/open", {"id": body.get("id")})
                    with shell._engine_lock:
                        shell._engine["data"] = None
                    return self._json(shell.engine_call("/api/workspaces"))
                if path == "/api/engine/cue":
                    # A graphic of the run of show onto Preview (by its name).
                    e = shell.engine_summary()
                    name = (body.get("name") or "").strip().lower()
                    comp = next((g for g in e.get("graphics") or [] if (g.get("name") or "").strip().lower() == name), None)
                    if not comp:
                        raise ValueError(f"No graphic called {body.get('name')} in this workspace")
                    shell.engine_call("/api/cue", {"id": comp["id"], "on": True})
                    return self._json({"ok": True, "graphic": comp})
                if path == "/api/setup":
                    shell.setup(body)
                elif path == "/api/part":
                    shell.set_part(body.get("key"), body.get("on"))
                elif path == "/api/part/restart":
                    shell.restart_part(body.get("key"))
                elif path == "/api/settings":
                    allowed = {"name", "background", "solid_colour", "control_pc"}
                    changes = {k: v for k, v in body.items() if k in allowed}
                    if "background" in changes and changes["background"] not in ("solid", "loop"):
                        raise ValueError("Background is solid or loop")
                    if "control_pc" in changes:
                        changes["control_pc"] = control_pc_url(changes["control_pc"])
                    shell.settings.update(changes)
                elif path == "/api/update/check":
                    shell.updater.check()
                elif path == "/api/update/install":
                    shell.updater.install_in_background()
                elif path == "/api/open-folder":
                    open_folder(DATA_DIR if body.get("which") != "app" else APP_DIR)
                else:
                    return self._json({"error": "not found"}, 404)
                self._json(shell.state())
            except (ValueError, KeyError, OSError) as e:
                self._json({"error": str(e)}, 400)

    return Handler


def start(shell, port=None):
    """Serve the shell's pages on 127.0.0.1 and start the parts. Raises
    OSError if the port is taken (the app is already open)."""
    port = port or shell.settings.get()["http_port"]
    shell.httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(shell))
    shell.httpd.daemon_threads = True
    threading.Thread(target=shell.httpd.serve_forever, name="shell-http", daemon=True).start()
    clean_up_old_update()
    shell.updater.check_in_background()
    log(f"SCC Broadcast Engine {VERSION} at http://127.0.0.1:{port}/ (data in {DATA_DIR})")
    return port
