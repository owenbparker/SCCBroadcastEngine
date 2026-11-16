"""The saved tournaments: each event's own brackets, standings, schedule,
logo and event name, kept in the workspace (project.json "tournaments") so
a crew can switch between events without typing them in again.

    {"active": "nace-fall",
     "list": [{"id": "nace-fall", "name": "NACE Fall", "updated": 1700000000.0,
               "data": {"event", "tournament_logo", "tournament", "standings", "schedule", "results"}}, ...]}

Global stays what the graphics read: the active tournament's data is a copy
of those Global keys, saved back into it whenever Global changes (Engine.
set_global), and switching puts the picked tournament's data into Global.
A workspace from before tournaments gets one, made from its Global.
"""

import copy
import re
import time

from . import results, schedule, standings, tournament

KEYS = ("event", "tournament_logo", "tournament", "standings", "schedule", "results")
MAX = 100


def _slug(name, taken):
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:40] or "tournament"
    tid, n = slug, 2
    while tid in taken:
        tid, n = f"{slug}-{n}", n + 1
    return tid


def blank_data(name=""):
    return {"event": name, "tournament_logo": "", "tournament": tournament.default(),
            "standings": standings.default(), "schedule": schedule.default(), "results": results.default()}


def data_of(g):
    """The tournament's part of a (clean) Global."""
    return {k: copy.deepcopy(g[k]) for k in KEYS}


def _clean_data(d, name):
    d = d if isinstance(d, dict) else {}
    return {"event": str(d.get("event") if d.get("event") is not None else name)[:200],
            "tournament_logo": str(d.get("tournament_logo") or "")[:300],
            "tournament": tournament.clean(d.get("tournament")),
            "standings": standings.clean(d.get("standings")),
            "schedule": schedule.clean(d.get("schedule")),
            "results": results.clean(d.get("results"))}


def clean(t, g):
    """The saved tournaments, with at least one (made from Global g) and a valid active one."""
    t = t if isinstance(t, dict) else {}
    out, taken = [], set()
    for x in (t.get("list") if isinstance(t.get("list"), list) else [])[:MAX]:
        if not isinstance(x, dict):
            continue
        name = str(x.get("name") or "").strip()[:80] or "Tournament"
        tid = str(x.get("id") or "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,60}", tid) or tid in taken:
            tid = _slug(name, taken)
        taken.add(tid)
        try:
            updated = float(x.get("updated") or 0)
        except (TypeError, ValueError):
            updated = 0.0
        out.append({"id": tid, "name": name, "updated": updated, "data": _clean_data(x.get("data"), name)})
    if not out:
        # (the brackets and standings from before there were tournaments)
        name = (g.get("event") or "").strip()[:80] or "My tournament"
        out.append({"id": _slug(name, set()), "name": name, "updated": time.time(), "data": data_of(g)})
    active = t.get("active") if any(x["id"] == t.get("active") for x in out) else out[0]["id"]
    return {"active": active, "list": out}


def find(t, tid):
    return next((x for x in t["list"] if x["id"] == tid), None)


def active(t):
    return find(t, t["active"])


def active_name(raw):
    """The open tournament's name, straight from project.json (for {{Global!Tournament name}})."""
    raw = raw if isinstance(raw, dict) else {}
    for x in raw.get("list") or []:
        if isinstance(x, dict) and x.get("id") == raw.get("active"):
            return str(x.get("name") or "")[:80]
    return ""


def sync(t, g):
    """Global changed: the active tournament keeps its copy. True if it changed."""
    cur = active(t)
    new = data_of(g)
    if cur["data"] == new:
        return False
    cur["data"] = new
    cur["updated"] = time.time()
    return True


def add(t, name, data):
    if len(t["list"]) >= MAX:
        raise ValueError(f"{MAX} tournaments at most: delete one first")
    name = (name or "").strip()[:80] or "New tournament"
    x = {"id": _slug(name, {y["id"] for y in t["list"]}), "name": name, "updated": time.time(),
         "data": _clean_data(data, name)}
    t["list"].append(x)
    return x


def summary(t):
    """For the dropdowns: each tournament's name, logo and what it has."""
    out = []
    for x in t["list"]:
        d = x["data"]
        top = d["tournament"]["top"]
        out.append({"id": x["id"], "name": x["name"], "logo": d["tournament_logo"], "event": d["event"],
                    "updated": x["updated"],
                    "teams": sum(1 for n in top["teams"][:top["size"]] if n),
                    "standings": sum(1 for s in d["standings"]["teams"] if s["name"]),
                    "matches": len(d["schedule"].get("matches") or [])})
    return {"active": t["active"], "tournaments": out}
