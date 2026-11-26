"""Run of show templates between PCs on the network.

Each SCC Broadcast Engine listens on NET_PORT (all networks) for two things
only: "who are you?" (GET /api/ros/hello) and "here are some templates"
(POST /api/ros/receive). Everything else stays on 127.0.0.1:8770.

Finding the other PCs: the GFX Engine's list of engines it has heard on the
network (each is an SCC Broadcast Engine PC), the Control PC, and every
address on this PC's own networks (each /24) answering on NET_PORT, so HUD
and Stream PCs without a GFX Engine are found too.
"""

import concurrent.futures
import ipaddress
import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from scc_shared import netpeers

from .log import log
from .ros import read_doc
from .version import VERSION

NET_PORT = 8771
APP = "scc-broadcast-engine"
MAX_BODY = 4 * 1024 * 1024
_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # (LAN: never a proxy)


def pc_name():
    return socket.gethostname() or "This PC"


def own_addresses():
    """This PC's IPv4 addresses on private networks."""
    found = set()
    try:
        found.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))   # (no traffic is sent)
            found.add(s.getsockname()[0])
    except OSError:
        pass
    out = []
    for a in found:
        try:
            ip = ipaddress.IPv4Address(a)
        except ValueError:
            continue
        if ip.is_private and not ip.is_loopback and not ip.is_link_local:
            out.append(str(ip))
    return sorted(out)


def address(text):
    """"192.168.2.41", "STREAM-PC", "http://192.168.2.41:8770/..." -> http://host:NET_PORT."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Type the other PC's address (e.g. 192.168.2.41)")
    u = urlparse(text if "://" in text else "http://" + text)
    if not u.hostname:
        raise ValueError(f"That doesn't look like an address: {text}")
    host = f"[{u.hostname}]" if ":" in u.hostname else u.hostname
    return f"http://{host}:{NET_PORT}"


def hello(base, timeout=1.5):
    with _direct.open(base + "/api/ros/hello", timeout=timeout) as r:
        h = json.loads(r.read().decode("utf-8"))
    if h.get("app") != APP:
        raise ValueError("That isn't an SCC Broadcast Engine")
    return h


def find(hints=(), scan=True):
    """The other SCC Broadcast Engines answering: [{"name", "address", "version", "templates"}]."""
    mine = set(own_addresses()) | {"127.0.0.1", "localhost"}
    hosts = []
    for h in hints:
        try:
            host = urlparse(address(h)).hostname
        except ValueError:
            continue
        if host and host not in mine and host not in hosts:
            hosts.append(host)
    if scan:
        # (this PC's networks, then Settings > Network's other networks and PCs: other VLANs)
        for ip in netpeers.candidates(own_addresses(), skip=mine):
            if ip not in hosts:
                hosts.append(ip)

    def is_open(host):
        try:
            with socket.create_connection((host, NET_PORT), timeout=0.4):
                return True
        except OSError:
            return False

    def ask(host):
        try:
            h = hello(f"http://{host}:{NET_PORT}")
            return {"name": str(h.get("name") or host)[:60], "address": host, "version": str(h.get("version") or ""),
                    "templates": int(h.get("templates") or 0)}
        except Exception:
            return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=128) as pool:
        up = [h for h, ok in zip(hosts, pool.map(is_open, hosts)) if ok]
        found = [x for x in pool.map(ask, up) if x]
    return sorted(found, key=lambda x: x["name"].lower())


def send(to, doc, mode, timeout=6):
    """Send an export_doc to another PC. Returns its answer ({"added", "replaced", "name"})."""
    base = address(to)
    body = json.dumps({"doc": doc, "mode": mode, "from": pc_name()}).encode("utf-8")
    req = urllib.request.Request(base + "/api/ros/receive", data=body, headers={"Content-Type": "application/json"})
    try:
        with _direct.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error")
        except Exception:
            msg = None
        raise ValueError(msg or f"That PC said {e.code}")
    except (urllib.error.URLError, OSError) as e:
        host = urlparse(base).hostname
        raise ValueError(f"Can't reach an SCC Broadcast Engine at {host} ({getattr(e, 'reason', e)}). "
                         "Is it open on that PC? On another network (VLAN), Settings > Network > Check another PC says what's in the way.")


def make_handler(ros):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _json(self, data, code=200):
            body = json.dumps(data).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if urlparse(self.path).path == "/api/ros/hello":
                return self._json({"app": APP, "name": pc_name(), "version": VERSION,
                                   "templates": len(ros.data["templates"])})
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            if urlparse(self.path).path != "/api/ros/receive":
                return self._json({"error": "not found"}, 404)
            # JSON only: a web page can't send that to another PC without asking
            # first (a preflight this server never answers).
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                return self._json({"error": "Expected JSON"}, 415)
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_BODY:
                return self._json({"error": "Too big"}, 413)
            try:
                body = json.loads(self.rfile.read(n).decode("utf-8"))
                templates = read_doc(body.get("doc"))
                source = str(body.get("from") or self.client_address[0])[:60]
                result = ros.import_templates(templates, body.get("mode") or "keep", source=source)
            except (ValueError, AttributeError, TypeError) as e:
                return self._json({"error": str(e)}, 400)
            log(f"Run of show: got {len(templates)} template(s) from {source} "
                f"({', '.join(result['added'] + result['replaced'])})")
            self._json({**result, "name": pc_name()})

    return Handler


def start(ros, port=NET_PORT):
    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", port), make_handler(ros))
    except OSError as e:
        log(f"Run of show: can't take templates from other PCs (port {port}: {e})", "warn")
        return None
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, name="ros-net", daemon=True).start()
    return httpd
