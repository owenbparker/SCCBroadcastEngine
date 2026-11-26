"""Bitfocus Companion control (the module is in companion-module/).

    GET  /api/companion   the graphics (and which are on Preview and Program),
                          the transitions, the quick functions' states and the
                          variables (Companion polls this for its feedbacks)
    POST /api/companion   {"action": "preview" | "program", "id": graphic, "mode": "toggle" | "on" | "off",
                           "transition": "" (program only: "" = the graphic's own animation)}
                          {"action": "take", "transition": "" (= the default)}
                          {"action": "clear", "bus": "program" | "preview" | "both"}
                          {"action": "send", "id": graphic or "" (= everything on Program)}
                          {"action": "run", "id": "score_left_up"}
                          {"action": "score", "side": "left", "value": 2}
                          {"action": "best_of", "value": 5}
                          {"action": "team", "side": "left", "team": name (or "name|game")}
                          {"action": "text", "field": "event" | "stage", "value": "..."}
                          {"action": "workspace", "id": workspace id or name}
                          {"action": "tournament", "id": tournament id or name}

SCC Broadcast Engine's Companion module (companion/ in the app) reaches this
through the app's own /api/companion (sccbe/companion.py), with the run of
show, the game HUDs and Multistream alongside.

A graphic is its id or its name (so a button still works in another
workspace that has the same graphics).
"""

from . import globalcfg
from .globalcfg import CASTER_SCALE, CLOCK_LABELS, timer_now, timer_running
from .log import log

# Quick functions: id -> name. Each has a state (lit on the button) where it makes sense.
QUICK = {
    "score_left_up": "Score: left team +1",
    "score_left_down": "Score: left team -1",
    "score_right_up": "Score: right team +1",
    "score_right_down": "Score: right team -1",
    "score_reset": "Score: reset to 0-0",
    "clock_time": "Clock: local time",
    "clock_soon": "Clock: Starting Soon countdown",
    "clock_brb": "Clock: Be Right Back countdown",
    "timer_toggle": "Timer: start / pause",
    "timer_reset": "Timer: reset",
    "bgloop": "Background loop: on / off",
    "bug_loop": "Back in bug: live loop behind VS on / off",
    "swap_sides": "Teams: swap sides (left <-> right, and the game HUDs follow)",
    **{f"best_of_{n}": f"Series: best of {n}" for n in (1, 3, 5, 7)},
    "roster_left": "Player graphics: left team",
    "roster_right": "Player graphics: right team",
    **{f"caster_{n}": f"Casters: {n} box{'es' if n > 1 else ''}" for n in sorted(CASTER_SCALE)},
}

# On/off states that can only be read (feedbacks).
STATES = {
    "preview_any": "Something is on Preview",
    "program_any": "Something is on Program",
}


def _names(ws):
    return {c["id"]: c["name"] for c in ws.snapshot()["compositions"]}


def find(ws, key):
    """A graphic's id, from its id or its name."""
    comps = ws.snapshot()["compositions"]
    key = str(key or "").strip()
    for c in comps:
        if c["id"] == key:
            return c["id"]
    for c in comps:
        if c["name"].strip().lower() == key.lower():
            return c["id"]
    raise ValueError(f"No graphic {key!r} in this workspace")


def state(engine):
    project = engine.ws.snapshot()   # (read only)
    live = engine.live.get()
    g = engine.global_config()
    pvw, pgm = live["preview"]["on"], live["program"]["on"]
    graphics = [{"id": c["id"], "name": c["name"], "kind": c.get("kind") or "overlay",
                 "preview": c["id"] in pvw, "program": c["id"] in pgm} for c in project["compositions"]]
    transitions = [{"id": t["id"], "name": t.get("name") or t["id"]} for t in project["transitions"]
                   if t.get("enabled") is not False]
    names = _names(engine.ws)
    on = {
        "preview_any": bool(pvw), "program_any": bool(pgm),
        "clock_time": g["clock"]["mode"] == "time", "clock_soon": g["clock"]["mode"] == "soon",
        "clock_brb": g["clock"]["mode"] == "brb", "timer_toggle": timer_running(g["timer"]), "bgloop": g["bgloop"]["on"],
        "roster_left": g["roster"] == "left", "roster_right": g["roster"] == "right",
        "bug_loop": bool(g.get("bug_loop")),
        **{f"best_of_{n}": int(g["best_of"]) == n for n in (1, 3, 5, 7)},
        **{f"caster_{n}": g["caster"]["count"] == n for n in CASTER_SCALE},
    }
    default = next((t["name"] for t in transitions if t["id"] == project.get("default_transition")), "")
    variables = {
        "workspace": project.get("name", ""),
        "preview": ", ".join(names.get(i, "") for i in pvw),
        "program": ", ".join(names.get(i, "") for i in pgm),
        "default_transition": default,
        "clock": CLOCK_LABELS.get(g["clock"]["mode"], ""),
        "timer": "%02d:%02d" % divmod(int(timer_now(g["timer"]) + (0.999 if g["timer"]["down"] else 0)), 60),
        "best_of": str(g["best_of"]),
        "casters": str(g["caster"]["count"]),
        "event": str(g.get("event") or ""),
        "stage": str(g.get("stage") or ""),
        "series": f"{g['left']['score']}-{g['right']['score']}",
        "game_number": str(globalcfg.game_number(g)),
    }
    for side in ("left", "right"):
        for key in ("name", "short", "score", "color"):
            variables[f"{side}_{key}"] = str(g[side].get(key, ""))
    out = {"graphics": graphics, "transitions": transitions, "default_transition": project.get("default_transition"),
           "states": on, "variables": variables}
    # (more for SCC Broadcast Engine's module: the team list, workspaces, tournaments)
    try:
        out["teams"] = [{"name": t.get("name") or "", "game": t.get("game") or ""}
                        for t in engine.teams.list() if t.get("name")][:500]
    except Exception:
        out["teams"] = []
    try:
        w = engine.workspaces_info()
        out["workspaces"] = [{"id": x["id"], "name": x.get("name") or x["id"]} for x in w.get("workspaces") or []]
        out["workspace"] = w.get("current")
    except Exception:
        out["workspaces"], out["workspace"] = [], None
    try:
        t = engine.tournaments_info()
        out["tournaments"] = [{"id": x["id"], "name": x.get("name") or x["id"]} for x in t.get("tournaments") or []]
        out["tournament"] = t.get("active")
        variables["tournament"] = next((x["name"] for x in out["tournaments"] if x["id"] == out["tournament"]), "")
    except Exception:
        out["tournaments"], out["tournament"] = [], None
        variables["tournament"] = ""
    return out


def _pick(items, key, what):
    """An id from a list of {"id", "name"}, by its id or its name."""
    key = str(key or "").strip()
    for x in items:
        if x["id"] == key:
            return x["id"]
    for x in items:
        if (x.get("name") or "").strip().lower() == key.lower():
            return x["id"]
    raise ValueError(f"No {what} {key!r}")


def _team(engine, side, key):
    """Fill a side from the team list (as the Event page's "Pick a team" does)."""
    if side not in ("left", "right"):
        raise ValueError("side is left or right")
    key = str(key or "").strip()
    name, _, game = key.partition("|")
    teams = [t for t in engine.teams.list() if t.get("name")]
    match = [t for t in teams if t["name"].strip().lower() == name.strip().lower()]
    if game:
        match = [t for t in match if (t.get("game") or "").strip().lower() == game.strip().lower()] or match
    if not match:
        raise ValueError(f"No team {name!r} in the team list")
    t, g = match[0], engine.global_config()
    changes = {"name": t["name"], "short": t.get("short") or g[side]["short"], "logo": t.get("logo") or "",
               "game": t.get("game") or ""}
    if t.get("color"):
        changes["color"] = t["color"]
    engine.set_global({side: changes})


def _run(engine, key):
    g = engine.global_config()
    if key.startswith("score_"):
        if key == "score_reset":
            engine.set_global({"left": {"score": 0}, "right": {"score": 0}})
        else:
            _, side, way = key.split("_")
            engine.set_global({side: {"score": max(0, g[side]["score"] + (1 if way == "up" else -1))}})
    elif key.startswith("clock_"):
        engine.set_global({"clock": dict(g["clock"], mode=key.split("_", 1)[1])})
    elif key.startswith("timer_"):
        engine.timer(key.split("_", 1)[1])
    elif key == "bgloop":
        engine.set_global({"bgloop": {"on": not g["bgloop"]["on"]}})
    elif key == "bug_loop":
        engine.set_global({"bug_loop": not g.get("bug_loop")})
    elif key == "swap_sides":
        engine.set_global({"left": g["right"], "right": g["left"]})
    elif key.startswith("best_of_"):
        engine.set_global({"best_of": int(key.rsplit("_", 1)[1])})
    elif key.startswith("roster_"):
        engine.set_global({"roster": key.split("_", 1)[1]})
    elif key.startswith("caster_"):
        engine.set_global({"caster": dict(g["caster"], count=int(key.split("_", 1)[1]))})
    else:
        raise ValueError(f"Unknown quick function: {key}")


def act(engine, body):
    """Do one Companion action; returns state(engine)."""
    action = body.get("action")
    live, ws = engine.live, engine.ws
    if action in ("preview", "program"):
        cid = find(ws, body.get("id"))
        mode = body.get("mode") or "toggle"
        now = cid in live.get()[action]["on"]
        want = (not now) if mode == "toggle" else mode == "on"
        if action == "preview":
            if want != now:
                live.cue(cid, want)
        elif want or now:
            # (taking a graphic that's on air again replays it with its Preview values)
            live.program(cid, want, body.get("transition") or "animate")
    elif action == "take":
        live.take(body.get("transition") or None)
    elif action == "clear":
        bus = body.get("bus") or "program"
        if bus in ("preview", "both"):
            live.clear("preview")
        if bus in ("program", "both"):
            live.clear("program", body.get("transition") or "animate")
    elif action == "send":
        now = live.get()
        ids = ([find(ws, body["id"])] if body.get("id") else
               [i for i in now["program"]["on"] if i in now["preview"]["values"]])   # (not ones never edited)
        for cid in ids:
            live.send_values(cid)
    elif action == "run":
        key = body.get("id") or ""
        if key not in QUICK:
            raise ValueError(f"Unknown quick function: {key}")
        _run(engine, key)
        log(f"Companion: {QUICK[key]}")
    elif action == "score":
        side = body.get("side")
        if side not in ("left", "right"):
            raise ValueError("side is left or right")
        engine.set_global({side: {"score": max(0, int(body.get("value") or 0))}})
    elif action == "best_of":
        engine.set_global({"best_of": max(1, int(body.get("value") or 1))})
    elif action == "team":
        _team(engine, body.get("side"), body.get("team"))
        log(f"Companion: {body.get('side')} team is {body.get('team')}")
    elif action == "text":
        field = body.get("field")
        if field not in ("event", "stage"):
            raise ValueError("field is event or stage")
        engine.set_global({field: str(body.get("value") or "")[:200]})
    elif action == "workspace":
        w = engine.workspaces_info()
        wid = _pick([{"id": x["id"], "name": x.get("name") or ""} for x in w.get("workspaces") or []], body.get("id"), "workspace")
        if wid != w.get("current"):
            engine.open(wid)
            log(f"Companion: opened the workspace {wid}")
    elif action == "tournament":
        t = engine.tournaments_info()
        tid = _pick([{"id": x["id"], "name": x.get("name") or ""} for x in t.get("tournaments") or []], body.get("id"), "tournament")
        if tid != t.get("active"):
            engine.open_tournament(tid)
            log(f"Companion: opened the tournament {tid}")
    else:
        raise ValueError(f"Unknown action: {action}")
    return state(engine)
