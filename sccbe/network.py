"""Settings > Network: connecting SCC Broadcast Engine PCs on different
networks (VLANs), and saying plainly what's in the way when they can't.

- Other networks and PCs (settings "other_networks", see
  scc_shared/netpeers.py): every part's scan looks through them too.
- This PC: its addresses, and for each part whether other PCs can reach it
  (tried on this PC's own network address, as another PC would).
- Check another PC: tries every port SCC Broadcast Engine uses there and says
  what each answer means (open / nothing listening / blocked).
- Windows Firewall: the rules for this app, and a button that allows it on
  every network (Domain, Private and Public), from any address.
- Game HUDs are opened to the network once each (allow_network, before they
  start), so the observer PC, the GFX Engine and OBS on other PCs reach them;
  switching one back to "this PC only" afterwards sticks.
"""

import concurrent.futures
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

from scc_shared import netpeers

from . import parts as P
from .config import DATA_DIR, FROZEN
from .log import log

# Every port another SCC Broadcast Engine PC may use on this one: (port, what, part key or "").
PORTS = [
    (8771, "SCC Broadcast Engine (finding PCs, run of show)", ""),
    (8782, "GFX Engine (HUDs connect here, Control, Companion, Send to engine)", "engine"),
    (8777, "League of Legends HUD", "lol"),
    (8787, "League of Legends HUD (https, cams)", "lol"),
    (8778, "VALORANT HUD (observer PC, overlay)", "val"),
    (8788, "VALORANT HUD (https, cams)", "val"),
    (8780, "Call of Duty HUD", "cod"),
    (8781, "Rocket League HUD", "rl"),
    (8784, "Smash Ultimate HUD", "smash"),
    (8785, "Overwatch HUD", "ow"),
]
UDP_PORT = 8783   # engines announce themselves (broadcast; and straight to saved PCs)
GAMES = ("lol", "val", "cod", "rl", "smash", "ow")
RULE_NAME = "SCC Broadcast Engine"
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ports_text():
    """For IT: what has to be let through between the VLANs."""
    tcp = ", ".join(str(p) for p, _, _ in PORTS)
    return (f"TCP {tcp} (and {UDP_PORT} UDP, optional) both ways between the networks the "
            "SCC Broadcast Engine PCs are on")


# --- other networks and PCs ------------------------------------------------------

def add_other(settings, text):
    entry = netpeers.parse(text)
    have = list(settings.get().get("other_networks") or [])
    if entry not in have:
        have.append(entry)
        settings.update({"other_networks": have})
        log(f"Network: will also look for PCs on {entry}")
    return entry


def remove_other(settings, text):
    have = [e for e in settings.get().get("other_networks") or [] if e != text]
    settings.update({"other_networks": have})


def suggest(addresses):
    """Each of this PC's networks as x.y.z.0/24, to type on the other PCs."""
    out = []
    for a in addresses:
        net = ".".join(a.split(".")[:3]) + ".0/24"
        if net not in out:
            out.append(net)
    return out


# --- this PC -------------------------------------------------------------------

def _reachable(ip, port):
    try:
        with socket.create_connection((ip, port), timeout=0.6):
            return True
    except OSError:
        return False


def this_pc(shell):
    """Each running part: can other PCs reach it? (tried on this PC's own
    network address, so a part listening on 127.0.0.1 only shows up)."""
    mine = netpeers.own_addresses()
    ip = mine[0] if mine else None
    rows = []
    ros = getattr(shell, "ros_net", None)
    rows.append({"key": "", "title": "SCC Broadcast Engine", "port": rosnet_port(),
                 "running": bool(ros), "open": bool(ros and ip and _reachable(ip, rosnet_port())),
                 "can_share": False})
    for part in P.PARTS:
        if part.key in ("builder", "stream"):
            continue   # (on this PC only, by design)
        running = part.status == "on"
        rows.append({"key": part.key, "title": part.title + ("" if part.key == "engine" else " HUD"), "port": part.port,
                     "running": running, "open": bool(running and ip and _reachable(ip, part.port)),
                     "can_share": part.key in GAMES})
    return rows


def rosnet_port():
    from .rosnet import NET_PORT
    return NET_PORT


def status(shell):
    s = shell.settings.get()
    mine = netpeers.own_addresses()
    return {"hostname": socket.gethostname(), "addresses": mine, "suggest": suggest(mine),
            "other_networks": s.get("other_networks") or [], "parts": this_pc(shell),
            "ports": [{"port": p, "what": w} for p, w, _ in PORTS], "udp": UDP_PORT, "ports_text": ports_text(),
            "windows": sys.platform == "win32"}


def share(key, on):
    """Let other PCs read a game HUD (its "Let other PCs on the network read the HUD")."""
    part = P.BY_KEY.get(key)
    if not part or key not in GAMES:
        raise ValueError("Only a game HUD can be opened to the network here")
    if part.status != "on":
        raise ValueError(f"{part.title} isn't running")
    body = json.dumps({"enabled": bool(on), "on": bool(on)}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{part.port}/api/network", data=body,
                                 headers={"Content-Type": "application/json"})
    with _direct.open(req, timeout=4) as r:
        r.read()
    log(f"Network: {part.title} HUD {'can now be reached from other PCs' if on else 'is now on this PC only'}")


def open_once(settings, part):
    """Before a game HUD starts the first time with this version: its "Let
    other PCs on the network read the HUD" goes on (in its config.json, only
    that one setting; everything else is kept), so the observer PC, the GFX
    Engine and OBS on other PCs reach it. Once per HUD: switching it back to
    "this PC only" afterwards sticks."""
    if part.key not in GAMES:
        return False
    done = list(settings.get().get("network_opened") or [])
    if part.key in done:
        return False
    path = os.path.join(DATA_DIR, part.folder, "config.json")
    data = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return False   # (unreadable: leave it alone, the HUD deals with it)
        if not isinstance(data, dict):
            return False
    changed = not data.get("allow_network")
    if changed:
        data["allow_network"] = True
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
        log(f"Network: other PCs can now reach the {part.title} HUD (Settings > Network)")
    settings.update({"network_opened": done + [part.key]})
    return changed


# --- another PC --------------------------------------------------------------------

def _hello(host, port):
    """What answers at host:port (a name for the results), or ""."""
    paths = {8771: "/api/ros/hello", 8782: "/api/hello"}
    try:
        with _direct.open(f"http://{host}:{port}{paths.get(port, '/api/state')}", timeout=2) as r:
            data = json.loads(r.read(200000).decode("utf-8", "replace") or "{}")
    except Exception:
        return ""
    return str(data.get("name") or (data.get("app") or {}).get("name") or "")[:60] if isinstance(data, dict) else ""


def check(host):
    """Every SCC Broadcast Engine port on another PC: [{port, what, state, detail}] and a summary."""
    host = netpeers.parse(host)
    if netpeers.is_network(host):
        raise ValueError("Type one PC's address or name to check (e.g. 10.230.2.15)")
    ip = netpeers.resolve(host)
    if not ip:
        return {"host": host, "ip": None, "results": [], "verdict": "noname",
                "summary": f"Couldn't find a PC called {host}. Try its address (e.g. 10.230.2.15) instead: "
                           "names often don't work across VLANs."}
    with concurrent.futures.ThreadPoolExecutor(len(PORTS)) as pool:
        answers = list(pool.map(lambda p: netpeers.probe(ip, p[0], timeout=2.5), PORTS))
    results = []
    for (port, what, key), a in zip(PORTS, answers):
        name = _hello(ip, port) if a["state"] == "open" and port in (8771, 8782) else ""
        results.append({"port": port, "what": what, "key": key, "state": a["state"], "ms": a.get("ms"),
                        "detail": a.get("detail") or "", "name": name})
    states = {r["state"] for r in results}
    app = results[0]
    mine = netpeers.own_addresses()
    same = any(".".join(ip.split(".")[:3]) == ".".join(m.split(".")[:3]) for m in mine)
    if states == {"timeout"}:
        verdict = "blocked"
        summary = (f"Nothing at {ip} answered on any port. Either SCC Broadcast Engine isn't open there, the PC is off, "
                   + ("or Windows Firewall on that PC is blocking it (open Settings > Network there and press "
                      "Allow through Windows Firewall)." if same else
                      "or the network between this PC's VLAN and that one doesn't let it through. If the app is open "
                      "there and its Windows Firewall is allowed, IT needs to allow " + ports_text() + "."))
    elif app["state"] == "open":
        verdict = "ok"
        refused = [str(r["port"]) for r in results[1:] if r["state"] == "refused"]
        blocked = [str(r["port"]) for r in results[1:] if r["state"] not in ("open", "refused")]
        summary = f"Connected to {app['name'] or ip}. "
        if not refused and not blocked:
            summary += "Every part answers."
        if refused:
            summary += (f"Nothing listening on {', '.join(refused)}: those parts are off there, or set to that PC only "
                        "(Settings > Network there: Let other PCs connect). ")
        if blocked:
            summary += (f"Blocked: {', '.join(blocked)}. The network between the VLANs (or that PC's firewall) "
                        "isn't letting those ports through: IT needs to allow them.")
        summary = summary.strip()
    elif app["state"] == "refused":
        verdict = "not_running"
        summary = (f"{ip} answered, but SCC Broadcast Engine isn't open there (or is an older version). "
                   "Open or update it on that PC.")
    else:
        verdict = "partly"
        summary = (f"Some ports on {ip} answer and some don't: the network (or that PC's firewall) is letting only some "
                   "through. IT needs to allow " + ports_text() + ".")
    return {"host": host, "ip": ip, "results": results, "verdict": verdict, "summary": summary, "same_network": same}


# --- Windows Firewall --------------------------------------------------------------

def _exe():
    return sys.executable if FROZEN else ""


def _ps(script, timeout=30):
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                       text=True, timeout=timeout, creationflags=_NO_WINDOW)
    return r.stdout.strip()


def firewall_status():
    """{"rules": [{name, enabled, action, profile}], "profiles": [{name, category}], "verdict", "text"}."""
    if sys.platform != "win32":
        return {"available": False, "text": "Windows Firewall is only on Windows."}
    exe = _exe()
    prog = exe.replace("'", "''")
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        + (f"$r=@(Get-NetFirewallApplicationFilter -Program '{prog}' | Get-NetFirewallRule | "
           "Where-Object {$_.Direction -eq 'Inbound'} | ForEach-Object {@{name=$_.DisplayName;enabled=\"$($_.Enabled)\";"
           "action=\"$($_.Action)\";profile=\"$($_.Profile)\"}});" if exe else "$r=@();")
        + "$c=@(Get-NetConnectionProfile | ForEach-Object {@{name=$_.InterfaceAlias;category=\"$($_.NetworkCategory)\"}});"
        "@{rules=$r;profiles=$c} | ConvertTo-Json -Depth 4 -Compress")
    try:
        data = json.loads(_ps(script) or "{}")
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return {"available": True, "error": str(e), "text": "Couldn't read Windows Firewall's rules."}
    rules = data.get("rules") or []
    rules = [rules] if isinstance(rules, dict) else rules
    profiles = data.get("profiles") or []
    profiles = [profiles] if isinstance(profiles, dict) else profiles
    on = [r for r in rules if str(r.get("enabled")).lower() == "true"]
    blocks = [r for r in on if str(r.get("action")).lower() == "block"]
    allows = [r for r in on if str(r.get("action")).lower() == "allow"]
    covered = set()
    for r in allows:
        p = str(r.get("profile") or "").lower()
        covered |= {"domain", "private", "public"} if p in ("any", "") else {x.strip() for x in p.split(",")}
    need = {"domainauthenticated": "domain", "private": "private", "public": "public"}
    missing = sorted({need.get(str(p.get("category")).lower(), "public") for p in profiles} - covered)
    if not exe:
        verdict, text = "source", "Running from source: Windows Firewall rules are for the installed app."
    elif blocks:
        verdict, text = "blocked", ("Windows Firewall is BLOCKING SCC Broadcast Engine (someone pressed Cancel when "
                                    "Windows asked). Press Allow through Windows Firewall.")
    elif missing:
        verdict, text = "missing", (f"Windows Firewall doesn't let other PCs in on this PC's {' / '.join(missing)} "
                                    "network. Press Allow through Windows Firewall.")
    else:
        verdict, text = "ok", "Windows Firewall lets other PCs reach SCC Broadcast Engine."
    return {"available": True, "exe": exe, "rules": rules, "profiles": profiles, "verdict": verdict, "text": text}


def firewall_fix():
    """Allow this app through Windows Firewall on every network, from any
    address (Windows asks for administrator rights). Old rules for the app
    (a Block made by pressing Cancel) are taken out first."""
    if sys.platform != "win32":
        raise ValueError("Windows Firewall is only on Windows")
    exe = _exe()
    if not exe:
        raise ValueError("Running from source: allow python.exe in Windows Firewall yourself")
    cmd = (f'netsh advfirewall firewall delete rule name=all dir=in program="{exe}" & '
           f'netsh advfirewall firewall add rule name="{RULE_NAME}" dir=in action=allow program="{exe}" '
           'enable=yes profile=any remoteip=any')
    arg = "/c " + cmd
    script = ("$p=Start-Process -FilePath cmd.exe -ArgumentList '" + arg.replace("'", "''") + "' -Verb RunAs "
              "-WindowStyle Hidden -Wait -PassThru; exit $p.ExitCode")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                           text=True, timeout=120, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise ValueError("Windows didn't answer (the administrator prompt may still be open)")
    if r.returncode != 0 and "canceled" in (r.stderr or "").lower():
        raise ValueError("Windows needs administrator rights for this: press Yes when it asks")
    time.sleep(0.5)
    log("Network: allowed SCC Broadcast Engine through Windows Firewall (every network, any address)")
    return firewall_status()
