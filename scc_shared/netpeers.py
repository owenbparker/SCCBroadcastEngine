"""Other networks and PCs: finding SCC Broadcast Engine PCs on other VLANs.

By itself each part only looks for other PCs on this PC's own network (its
/24, e.g. 10.230.5.x) and hears engines' UDP broadcasts, which routers never
pass on. A PC on another VLAN (10.230.2.x) can still be reached when the
network routes between the two, but it's never found. So Settings > Network
keeps a list of other networks and PCs (shell settings "other_networks"):

    "10.230.2.0/24"   a whole network (VLAN), looked through like this PC's own
    "10.230.2.15"     one PC
    "HUD-PC-3"        one PC by its name

Every scan (HUD -> GFX Engine, the engine's list of other engines, VALORANT
observer -> GFX PC, run of show and workspace Send) looks through these as
well, and engines announce themselves straight to the single PCs listed
(a unicast beacon, which routers do pass on).

One copy, shared by every part (scc_shared is on every part's import path).
"""

import ipaddress
import json
import os
import socket
import threading
import time

# Bigger networks than this are refused: a /22 is 1,022 PCs, about 10 s to look through.
MAX_PREFIX = 22
SETTINGS_KEY = "other_networks"

_cache = {"path": None, "mtime": None, "entries": []}
_lock = threading.Lock()
_override = None   # (tests) a list of entries instead of the shell's settings


def settings_path():
    data = os.environ.get("SCCBE_DATA") or ""
    return os.path.join(data, "shell", "settings.json") if data else ""


def use(entries):
    """(tests) Use these entries instead of the shell's settings; None goes back."""
    global _override
    _override = None if entries is None else [parse(e) for e in entries]


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


def parse(text):
    """One typed entry -> its tidy form, or ValueError saying what's wrong.

    "10.230.2.0/24", "10.230.2.*", "10.230.2.x" -> "10.230.2.0/24"
    "10.230.2.15" (or "http://10.230.2.15:8782/control") -> "10.230.2.15"
    "HUD-PC-3" -> "HUD-PC-3"
    """
    t = str(text or "").strip()
    if not t:
        raise ValueError("Type a network (10.230.2.0/24), a PC's address (10.230.2.15) or its name")
    if "://" in t:
        t = t.split("://", 1)[1]
    t = t.split("/", 1)[0] if "/" in t and not t.split("/", 1)[1].strip().isdigit() else t
    for wild in (".*", ".x", ".X"):
        if t.endswith(wild) and t.count(".") == 3:
            t = t[: -len(wild)] + ".0/24"
    if "/" in t:
        try:
            net = ipaddress.IPv4Network(t, strict=False)
        except ValueError:
            raise ValueError(f"That isn't a network: {text}")
        if net.prefixlen < MAX_PREFIX:
            raise ValueError(f"{net} is too big to look through (up to /{MAX_PREFIX}, 1,022 PCs). "
                             "Add the VLAN the PCs are on, e.g. 10.230.2.0/24")
        if not net.is_private:
            raise ValueError(f"{net} isn't a private (local) network")
        return str(net)
    host = t.rsplit(":", 1)[0] if t.count(":") == 1 else t   # (a port typed after it)
    try:
        return str(ipaddress.IPv4Address(host))
    except ValueError:
        pass
    ok = all(c.isalnum() or c in "-._" for c in host) and len(host) <= 253
    if not ok:
        raise ValueError(f"That doesn't look like a PC's address or name: {text}")
    return host


def entries():
    """The saved other networks and PCs (tidied; bad ones left out)."""
    if _override is not None:
        return list(_override)
    path = settings_path()
    if not path:
        return []
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return []
    with _lock:
        if _cache["path"] == path and _cache["mtime"] == mtime:
            return list(_cache["entries"])
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f).get(SETTINGS_KEY) or []
    except (OSError, ValueError, AttributeError):
        raw = []
    for e in raw if isinstance(raw, list) else []:
        try:
            e = parse(e)
        except ValueError:
            continue
        if e not in out:
            out.append(e)
    with _lock:
        _cache.update(path=path, mtime=mtime, entries=out)
    return list(out)


def is_network(entry):
    return "/" in entry


def resolve(name, timeout=2.0):
    """A PC's name -> its IPv4 address, or None (gives up after timeout)."""
    try:
        return str(ipaddress.IPv4Address(name))
    except ValueError:
        pass
    box = []

    def look():
        try:
            box.append(socket.gethostbyname(name))
        except OSError:
            pass
    t = threading.Thread(target=look, daemon=True)
    t.start()
    t.join(timeout)
    return box[0] if box else None


def single_pcs():
    """The single PCs saved (names looked up): [ip]."""
    out = []
    for e in entries():
        if is_network(e):
            continue
        ip = resolve(e)
        if ip and ip not in out:
            out.append(ip)
    return out


def candidates(own=None, skip=()):
    """Every address to look at: each of own's /24 (this PC's networks unless
    given), then the saved networks and PCs. Without skip and own's addresses."""
    own = list(own_addresses() if own is None else own)
    leave_out = set(own) | set(skip)
    out, seen = [], set()

    def add(ip):
        if ip not in seen and ip not in leave_out:
            seen.add(ip)
            out.append(ip)
    for a in sorted(set(own)):
        try:
            net = ipaddress.IPv4Network(a + "/24", strict=False)
        except ValueError:
            continue
        for h in net.hosts():
            add(str(h))
    for e in entries():
        if is_network(e):
            for h in ipaddress.IPv4Network(e, strict=False).hosts():
                add(str(h))
    for ip in single_pcs():
        add(ip)
    return out


def probe(host, port, timeout=4.0):
    """Can this PC open a connection to host:port? {"state", "ms", "detail"}:

    open     something answers there
    refused  the PC answered "nothing here": it's reachable, but nothing is
             listening on that port (the part is off, or set to this PC only)
    timeout  no answer at all: a firewall (Windows or the network's) or a
             router between the VLANs drops it, or the PC is off
    noname   the name couldn't be looked up

    (Windows tries a refused connection again for about 2 s before saying so,
    so the timeout has to be longer than that to tell refused from blocked.)
    """
    ip = resolve(host) if host else None
    if not ip:
        return {"state": "noname", "ms": None, "detail": f"Couldn't find a PC called {host}"}
    t0 = time.monotonic()
    try:
        with socket.create_connection((ip, int(port)), timeout=timeout):
            return {"state": "open", "ms": round((time.monotonic() - t0) * 1000), "ip": ip, "detail": ""}
    except ConnectionRefusedError:
        return {"state": "refused", "ms": round((time.monotonic() - t0) * 1000), "ip": ip,
                "detail": "Reachable, but nothing is listening on this port"}
    except socket.timeout:
        return {"state": "timeout", "ms": None, "ip": ip, "detail": "No answer (blocked by a firewall or the network)"}
    except OSError as e:
        # e.g. "No route to host" / "network unreachable": the network has no way there.
        return {"state": "timeout", "ms": None, "ip": ip, "detail": str(getattr(e, "strerror", "") or e)}
