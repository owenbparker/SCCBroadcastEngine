"""The control panel's page and its API, on this PC only (127.0.0.1).

Multistream works off stream keys alone: paste each platform's key, switch
it on, and it goes live when OBS / vMix streams in. Every change applies
(and is saved) at once; there's no Save button to forget.
"""

import json
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from . import selftest
from .config import WEB_DIR
from .log import log, since
from .relay import Relay
from .settings import PLATFORMS, Settings, missing, server_of
from .updater import Updater, clean_up_old_update

mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("image/svg+xml", ".svg")


class StreamApp:
    def __init__(self, settings=None, relay=None):
        self.settings = settings or Settings()
        self.relay = relay or Relay(self.settings)
        self.updater = Updater()
        self.test = selftest.Runner()
        self.httpd = None

    def state(self):
        snap = self.settings.snapshot()
        dests = []
        for d in snap["destinations"]:
            dests.append({k: d.get(k) for k in ("id", "platform", "name", "enabled", "key", "video", "bitrate")}
                         | {"server": server_of(d), "missing": missing(d),
                            "fixed": bool(PLATFORMS.get(d["platform"], {}).get("fixed"))})
        return {"destinations": dests, "relay": self.relay.state(),
                "platforms": {k: {"name": p["name"], "server": p["server"], "help": p["help"],
                                  "fixed": bool(p.get("fixed"))} for k, p in PLATFORMS.items()},
                "test": self.test.info(),
                "update": self.updater.info()}


def web_file(rel):
    rel = rel.replace("\\", "/").lstrip("/")
    path = os.path.normpath(os.path.join(WEB_DIR, rel))
    if not path.startswith(os.path.normpath(WEB_DIR) + os.sep) or not os.path.isfile(path):
        return None
    return path


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, body, ctype="application/json", status=200):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, status=200):
            self._send(json.dumps(data), status=status)

        def do_GET(self):
            url = urlparse(self.path)
            path = url.path
            if path == "/":
                path = "/index.html"
            if path == "/api/state":
                return self._json(app.state())
            if path == "/api/log":
                after = int((dict(p.split("=", 1) for p in url.query.split("&") if "=" in p)).get("after") or 0)
                return self._json({"lines": since(after)})
            full = web_file(unquote(path))
            if not full:
                return self._json({"error": "not found"}, 404)
            with open(full, "rb") as f:
                self._send(f.read(), mimetypes.guess_type(full)[0] or "application/octet-stream")

        def do_POST(self):
            # Pages on other sites can't drive the relay (or read keys) through the browser.
            if self.headers.get("Origin") not in (None, "null") and \
                    urlparse(self.headers["Origin"]).hostname not in ("127.0.0.1", "localhost"):
                return self._json({"error": "forbidden"}, 403)
            path = urlparse(self.path).path
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if path == "/api/destination":
                    d = app.settings.update_destination(body)
                    if "enabled" in body:
                        log(f"{d['name']}: switched {'on' if d['enabled'] else 'off'}")
                    elif "key" in body:
                        log(f"{d['name']}: stream key {'saved' if d['key'] else 'cleared'}")
                elif path == "/api/destination/remove":
                    app.settings.remove_destination(body.get("id"))
                elif path == "/api/lan":
                    app.settings.set(lan=bool(body.get("lan")))
                    app.relay.restart(lan=bool(body.get("lan")))
                elif path == "/api/restart":
                    app.relay.restart()
                elif path == "/api/test":
                    app.test.start()
                else:
                    return self._json({"error": "not found"}, 404)
                app.relay.poke()
                self._json(app.state())
            except (ValueError, KeyError, OSError) as e:
                self._json({"error": str(e)}, 400)

    return Handler


def start(app, port):
    """Serve the page on 127.0.0.1:port and start the relay. Raises OSError
    if the port is taken."""
    app.httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    app.httpd.daemon_threads = True
    threading.Thread(target=app.httpd.serve_forever, daemon=True).start()
    clean_up_old_update()
    app.relay.start()
    log(f"SCC Multistream {app.updater.current} running at http://127.0.0.1:{port}/")
    return app.httpd


def stop(app):
    app.relay.stop()
    if app.httpd:
        app.httpd.shutdown()
        app.httpd.server_close()
