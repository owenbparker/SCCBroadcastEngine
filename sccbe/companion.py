"""Bitfocus Companion for the whole of SCC Broadcast Engine (the module is
in companion/ at the top of this repository).

One address for everything this PC runs: the GFX Engine (its own Companion
API, gfxengine/companion.py, or the Control PC's on a HUD PC), the run of
show, each game HUD that's switched on, Multistream, and the parts
themselves.

    GET  /api/companion   everything Companion shows: the engine's graphics,
                          transitions and states, the run of show's segments,
                          every on/off "control" (with whether it's on now), the
                          sliders, and the variables (Companion polls this)
    POST /api/companion   {"do": "engine", ...}         the GFX Engine's own actions
                                                         (preview, program, take, clear,
                                                         send, run, score, best_of, team,
                                                         text, workspace, tournament)
                          {"do": "control", "id": "val.tech_pause", "mode": "toggle" | "on" | "off"}
                          {"do": "control", "id": "ros.next"}   (a command: no mode)
                          {"do": "value", "id": "lol.bg_speed", "how": "set" | "adjust", "value": 0.1}
                          {"do": "ros_go", "index": 3}

From another PC, Companion reaches this through the GFX Engine's port
(http://<pc>:8782/sccbe/api/companion), which asks for the engine's pairing
code when it's on. A HUD PC without the engine: Companion on that PC uses
http://127.0.0.1:8770/api/companion.
"""

import json
import threading
import time
import urllib.error
import urllib.request

from . import parts as P
from .log import log
from .ros import timeline


def _get(d, path, default=None):
    for k in path.split("."):
        if isinstance(d, dict) and k in d:
            d = d[k]
        elif isinstance(d, list) and k.isdigit() and int(k) < len(d):
            d = d[int(k)]
        else:
            return default
    return d


def _mmss(secs):
    secs = int(round(secs))
    sign = "-" if secs < 0 else ""
    secs = abs(secs)
    if secs >= 3600:
        return f"{sign}{secs // 3600}:{secs % 3600 // 60:02d}:{secs % 60:02d}"
    return f"{sign}{secs // 60}:{secs % 60:02d}"


class Ctl:
    """One button's worth: an on/off setting ("toggle") or a "command".
    read(state) -> on now (toggles, and commands that light up);
    do(want, state) -> [(path, body), ...] to POST to the part."""

    def __init__(self, cid, label, kind="toggle", read=None, do=None):
        self.id, self.label, self.kind, self.read, self.do = cid, label, kind, read, do


def _cfg(path, key_path=None):
    """A toggle that is a config setting, sent as a nested /api/config change."""
    keys = (key_path or path).split(".")

    def do(want, _st):
        body = want
        for k in reversed(keys):
            body = {k: body}
        return [("/api/config", body)]
    return dict(read=lambda st: bool(_get(st, "config." + path)), do=do)


def _post(path, body=None):
    return lambda _want, _st: [(path, body or {})]


def _hud_window():
    return Ctl("hud_on_game", "HUD on game (the HUD window over the game)",
               read=lambda st: bool(_get(st, "app.overlay_window.open", _get(st, "overlay_window.open"))),
               do=lambda want, _st: [("/api/overlay-window", {"open": want})])


def _val_timeout(side):
    def do(want, st):
        cfg = st.get("config") or {}
        change = {"timeout_call": side if want else "", "tech_pause": False}
        left = int(_get(cfg, f"timeouts.{side}", 0) or 0)
        if want and cfg.get("timeout_call") != side and left > 0:
            change["timeouts"] = {side: left - 1}
        return [("/api/config", change)]
    return Ctl(f"timeout_{side}", f"Timeout: {side} team calls one (uses one up)",
               read=lambda st: _get(st, "config.timeout_call") == side, do=do)


# Each game HUD's controls (League has its own Companion API: see _lol).
GAMES = {
    "val": [
        _hud_window(),
        Ctl("demo", "Demo match", read=lambda st: _get(st, "app.mode") == "demo",
            do=lambda want, _st: [("/api/mode", {"mode": "demo" if want else "live"})]),
        Ctl("reader", "Read the game on this PC (screen reader)", read=lambda st: bool(_get(st, "app.reader.enabled")),
            do=lambda want, _st: [("/api/reader", {"enabled": want})]),
        Ctl("auto_sides", "Auto sides (teams swap by themselves)", **_cfg("auto_sides")),
        Ctl("tech_pause", "Technical pause",
            read=lambda st: bool(_get(st, "config.tech_pause")),
            do=lambda want, _st: [("/api/config", {"tech_pause": want, "timeout_call": ""})]),
        _val_timeout("left"),
        _val_timeout("right"),
        Ctl("show_timeouts", "Timeout diamonds under the score", **_cfg("show.timeouts")),
        Ctl("agent_select_demo", "Agent select: demo", read=lambda st: bool(_get(st, "agent_select.demo")),
            do=lambda want, _st: [("/api/agent-select/demo", {"on": want})]),
    ],
    "cod": [
        _hud_window(),
        Ctl("demo", "Demo match", read=lambda st: bool(_get(st, "scanner.demo")),
            do=lambda want, _st: [("/api/demo", {"on": want})]),
        *[Ctl(f"overlay_{k}", f"HUD: {label}", read=(lambda k: lambda st: bool(_get(st, f"config.overlay.{k}")))(k),
              do=(lambda k: lambda want, _st: [("/api/config", {"path": f"overlay.{k}", "value": want})])(k))
          for k, label in (("plates", "player name plates"), ("logos", "logos"), ("pips", "series pips"),
                           ("cam", "player cam"), ("sponsor", "sponsor"))],
        Ctl("cams", "Webcams on the HUD", read=lambda st: bool(_get(st, "config.cams.enabled")),
            do=lambda want, _st: [("/api/config", {"path": "cams.enabled", "value": want})]),
        Ctl("postgame_read", "Post-game: read the scoreboard on screen now", "command", do=_post("/api/postgame/read")),
        Ctl("postgame_swap", "Post-game: swap the teams' stats", "command", do=_post("/api/postgame/swap")),
        Ctl("postgame_clear", "Post-game: clear the stats", "command", do=_post("/api/postgame/clear")),
        Ctl("names_clear", "Player names: read them again", "command", do=_post("/api/names/clear")),
    ],
    "rl": [
        _hud_window(),
        Ctl("demo", "Demo match", read=lambda st: bool(_get(st, "app.demo")),
            do=lambda want, _st: [("/api/demo", {"on": want})]),
        Ctl("reader", "Read the game (Stats API)", read=lambda st: bool(_get(st, "config.stats_api.read")),
            do=lambda want, _st: [("/api/reader", {"enabled": want})]),
        *[Ctl(f"show_{k}", f"Show: {label}", **_cfg(f"show.{k}"))
          for k, label in (("players", "player boxes"), ("sponsors", "sponsors"), ("target", "spectated player"),
                           ("boost", "boost meter"), ("events", "events feed"), ("replay_cams", "cams in replays"))],
        Ctl("cams", "Webcams on the HUD", **_cfg("cams.on")),
        Ctl("stinger_left", "Replay stinger: play it (left team)", "command", do=_post("/api/stinger/preview", {"team": 0})),
        Ctl("stinger_right", "Replay stinger: play it (right team)", "command", do=_post("/api/stinger/preview", {"team": 1})),
    ],
    "smash": [
        Ctl("demo", "Demo match", read=lambda st: bool(_get(st, "app.demo")),
            do=lambda want, _st: [("/api/demo", {"on": want})]),
        Ctl("reader", "Read the stocks off the screen", read=lambda st: bool(_get(st, "config.reader.on")),
            do=lambda want, _st: [("/api/reader", {"on": want})]),
        Ctl("show_sponsors", "Show sponsors", **_cfg("show.sponsors")),
        *[Ctl(f"stock_{side}_{way}", f"Stocks: {side} crew {'loses one' if way == 'down' else 'gets one back'}", "command",
              do=(lambda side, way: _post("/api/stocks", {"side": side, "delta": -1 if way == "down" else 1}))(side, way))
          for side in ("left", "right") for way in ("down", "up")],
        Ctl("stocks_reset", "Stocks: reset (new game)", "command", do=_post("/api/stocks", {"reset": True})),
        *[Ctl(f"wins_{side}_{way}", f"Wins: {side} crew {'+1' if way == 'up' else '-1'}", "command",
              do=(lambda side, way: _post("/api/wins", {"side": side, "delta": 1 if way == "up" else -1}))(side, way))
          for side in ("left", "right") for way in ("up", "down")],
    ],
    "ow": [
        *[Ctl(f"map_{side}", f"Map result: {'draw' if side == 'draw' else side + ' team won'}", "command",
              do=(lambda side: _post("/api/result", {"side": side, "delta": 1}))(side))
          for side in ("left", "right", "draw")],
        *[Ctl(f"undo_{side}", f"Map result: undo {'a draw' if side == 'draw' else 'a ' + side + ' team win'}", "command",
              do=(lambda side: _post("/api/result", {"side": side, "delta": -1}))(side))
          for side in ("left", "right", "draw")],
        Ctl("series_reset", "New series (clear map bans and scores)", "command", do=_post("/api/series/reset")),
        *[Ctl(f"style_{n}", f"Overlay style: SCC {n}", "command",
              read=(lambda n: lambda st: int(_get(st, "config.overlay.style", 0) or 0) == n)(n),
              do=(lambda n: _post("/api/config", {"overlay": {"style": n}}))(n)) for n in (1, 2, 3)],
        Ctl("logos", "Overlay: logos", **_cfg("overlay.logos")),
        Ctl("records", "Overlay: records", **_cfg("overlay.records")),
    ],
}

# Each game's variables: name -> (label, path in its /api/state, how to show it).
GAME_VARS = {
    "val": {"map": ("Map", "fields.MAP", None), "round": ("Round", "fields.ROUND", None),
            "phase": ("Phase", "fields.PHASE", None), "timer": ("Round timer", "fields.TIMER", None),
            "score_left": ("Left team's rounds", "fields.SCORE LEFT", None),
            "score_right": ("Right team's rounds", "fields.SCORE RIGHT", None),
            "side_left": ("Left team's side (ATK/DEF)", "fields.SIDE LEFT", None),
            "timeouts_left": ("Left team's timeouts left", "config.timeouts.left", None),
            "timeouts_right": ("Right team's timeouts left", "config.timeouts.right", None),
            "status": ("Game connected", "fields.CONNECTED", None)},
    "cod": {"status": ("Reader status", "scanner.status", None),
            "postgame": ("Post-game reader", "scanner.postgame.status", None)},
    "rl": {"clock": ("Game clock", "game.clock", "mmss"), "score_left": ("Left team's goals", "game.teams.0.score", None),
           "score_right": ("Right team's goals", "game.teams.1.score", None), "arena": ("Arena", "game.arena", None)},
    "smash": {"stocks_left": ("Left crew's stocks", "config.crews.left", None),
              "stocks_right": ("Right crew's stocks", "config.crews.right", None),
              "wins_left": ("Left crew's wins", "config.left.wins", None),
              "wins_right": ("Right crew's wins", "config.right.wins", None)},
    "ow": {"map_no": ("Map number", "overlay.map_no", None), "map": ("Map", "overlay.map", None),
           "score_left": ("Left team's maps", "overlay.left.score", None),
           "score_right": ("Right team's maps", "overlay.right.score", None)},
}

ROS_COMMANDS = {
    "next": "Run of show: next segment",
    "prev": "Run of show: back one segment",
    "reset": "Run of show: start again (nothing on air)",
    "cue": "Run of show: the segment's graphics onto Preview",
}

VARIABLES = {
    # (the GFX Engine's, from apps/gfxengine/gfxengine/companion.py)
    "workspace": "GFX: workspace open", "tournament": "GFX: tournament open",
    "preview": "GFX: graphics on Preview", "program": "GFX: graphics on Program",
    "default_transition": "GFX: default transition (Take)", "clock": "GFX: clock mode", "timer": "GFX: timer (m:ss)",
    "best_of": "Series: best of", "series": "Series: score (1-0)", "game_number": "Series: game number",
    "casters": "GFX: caster boxes", "event": "Event name", "stage": "Stage",
    **{f"{side}_{k}": f"{side.title()} team: {label}" for side in ("left", "right")
       for k, label in (("name", "name"), ("short", "short name"), ("score", "score"), ("color", "colour"))},
    "ros_current": "Run of show: segment on now",
    "ros_next": "Run of show: next segment",
    "ros_block": "Run of show: block on now",
    "ros_left": "Run of show: time left in this segment (m:ss, - when over)",
    "ros_elapsed": "Run of show: time in this segment",
    "ros_next_at": "Run of show: when the next segment starts (HH:MM)",
    "ros_position": "Run of show: segment number (3/12)",
    "ros_match": "Run of show: the match (team 1 vs team 2)",
    "stream_live": "Multistream: platforms live",
    "stream_ingest": "Multistream: OBS stream in (live / waiting / error)",
    "app_version": "SCC Broadcast Engine version",
}


class Companion:
    GAME_TTL = 0.6      # a game HUD's state is read at most this often
    TTL = 0.15          # everything, at most this often (two Companions polling)

    def __init__(self, shell):
        self.shell = shell
        self._lock = threading.Lock()
        self._games = {}         # part key -> (monotonic, state or None, error)
        self._lol_names = None
        self._cache = (0.0, None)

    # --- talking to the parts -------------------------------------------------

    def _call(self, part, path, body=None, timeout=1.5):
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(f"http://127.0.0.1:{part.port}{path}", data=data,
                                     headers={"Content-Type": "application/json"},
                                     method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error")
            except Exception:
                msg = None
            raise ValueError(f"{part.title}: {msg or e.code}")
        except (urllib.error.URLError, OSError) as e:
            raise ValueError(f"{part.title} isn't answering ({getattr(e, 'reason', e)})")

    def _game_state(self, part, fresh=False):
        """The part's /api/state (League: its /api/companion), cached briefly."""
        now = time.monotonic()
        t, st, _ = self._games.get(part.key, (0, None, ""))
        if not fresh and now - t < self.GAME_TTL:
            return st
        try:
            st = self._call(part, "/api/companion" if part.key == "lol" else "/api/state")
            if part.key == "lol":
                if self._lol_names is None:
                    self._lol_names = self._call(part, "/api/companion/describe")
                # (demo mode isn't one of League's own Companion controls)
                st["mode"] = _get(self._call(part, "/api/state"), "app.mode")
            err = ""
        except ValueError as e:
            st, err = None, str(e)
        self._games[part.key] = (now, st, err)
        return st

    def _running(self, key):
        p = P.BY_KEY.get(key)
        return p if p is not None and p.status == "on" else None

    # --- what Companion sees --------------------------------------------------

    def state(self):
        with self._lock:
            t, data = self._cache
            if data is not None and time.monotonic() - t < self.TTL:
                return data
            data = self._build()
            self._cache = (time.monotonic(), data)
            return data

    def _forget(self):
        self._cache = (0.0, None)

    def _build(self):
        from .version import VERSION
        controls, values, variables = {}, {}, {"app_version": VERSION}
        groups = []

        def add(cid, group, label, kind, on=None):
            controls[cid] = {"label": label, "group": group, "kind": kind, "on": on}

        # The GFX Engine (this PC's, or the Control PC's).
        engine, engine_error = None, ""
        try:
            engine = self.shell.engine_call("/api/companion", timeout=2)
            variables.update({k: v for k, v in (engine.get("variables") or {}).items()})
        except ValueError as e:
            engine_error = str(e)

        # The run of show.
        ros = self._ros(variables)
        groups.append(("ros", "Run of show"))
        for k, label in ROS_COMMANDS.items():
            add(f"ros.{k}", "Run of show", label, "command")
        add("ros.auto", "Run of show", "Run of show: follow the Schedule (auto)", "toggle", bool(ros.get("auto")))

        # The game HUDs and Multistream.
        for part in P.PARTS:
            if part.kind != "game" and part.key != "stream":
                continue
            running = part.status == "on"
            st = self._game_state(part) if running else None
            group = part.title
            if part.key == "lol":
                names = self._lol_names or {}
                for k, label in (names.get("toggles") or {}).items():
                    add(f"lol.{k}", group, label, "toggle", bool(_get(st, f"toggles.{k}")) if st else None)
                add("lol.hud_on_game", group, "HUD on game (the HUD window over the game)", "toggle",
                    bool(_get(st, "toggles.hud_on_game")) if st else None)
                add("lol.demo", group, "Demo game", "toggle", (st.get("mode") == "demo") if st else None)
                for k, label in (names.get("commands") or {}).items():
                    add(f"lol.{k}", group, label, "command")
                for k, v in (names.get("values") or {}).items():
                    values[f"lol.{k}"] = {"label": v["name"], "group": group, "min": v["min"], "max": v["max"],
                                          "value": _get(st, f"values.{k}") if st else None}
                for k, v in ((st or {}).get("variables") or {}).items():
                    variables[f"lol_{k}"] = v
            elif part.key == "stream":
                for d in (st or {}).get("destinations") or []:
                    add(f"stream.dest_{d['id']}", group, f"Stream to {d.get('name') or d['id']}", "toggle", bool(d.get("enabled")))
                add("stream.restart", group, "Restart the relay (every platform reconnects)", "command")
                if st:
                    outs = (st.get("relay") or {}).get("outputs") or []
                    names = {d["id"]: d.get("name") or d["id"] for d in st.get("destinations") or []}
                    live = [names.get(o["id"], o["id"]) for o in outs if o.get("status") == "live"]
                    variables["stream_live"] = ", ".join(live) or "off"
                    variables["stream_ingest"] = _get(st, "relay.ingest.status", "") or ""
                    for o in outs:
                        variables[f"stream_{o['id']}"] = o.get("status") or ""
                        controls.setdefault(f"stream.live_{o['id']}", {
                            "label": f"{names.get(o['id'], o['id'])} is live", "group": group, "kind": "state",
                            "on": o.get("status") == "live"})
                    controls["stream.ingest"] = {"label": "OBS is streaming in", "group": group, "kind": "state",
                                                 "on": variables["stream_ingest"] == "live"}
            else:
                for c in GAMES.get(part.key, []):
                    on = None
                    if st is not None and c.read is not None:
                        try:
                            on = bool(c.read(st))
                        except Exception:
                            on = None
                    add(f"{part.key}.{c.id}", group, c.label, c.kind, on)
                for name, (_, path, how) in GAME_VARS.get(part.key, {}).items():
                    v = _get(st, path, "") if st else ""
                    if how == "mmss" and isinstance(v, (int, float)):
                        v = _mmss(v)
                    variables[f"{part.key}_{name}"] = "" if v is None else str(v)
            # The part itself: is it running?
            controls[f"part.{part.key}"] = {"label": f"{part.title}: running (switch on / off)", "group": "Parts",
                                            "kind": "toggle", "on": part.status in ("on", "starting")}
            controls[f"part.{part.key}.restart"] = {"label": f"{part.title}: restart", "group": "Parts",
                                                    "kind": "command", "on": None}
        controls["part.builder"] = {"label": "HUD Builder: running (switch on / off)", "group": "Parts", "kind": "toggle",
                                    "on": P.BY_KEY["builder"].status in ("on", "starting")}

        parts = [{"key": p.key, "title": p.title, "status": p.status} for p in P.PARTS]
        for p in P.PARTS:
            variables[f"part_{p.key}"] = p.status
        return {"app": {"name": "SCC Broadcast Engine", "version": VERSION},
                "engine": engine, "engine_error": engine_error,
                "ros": ros, "parts": parts, "controls": controls, "values": values,
                "variables": variables, "variable_names": self._variable_names(variables)}

    def _variable_names(self, variables):
        names = dict(VARIABLES)
        for key, table in GAME_VARS.items():
            title = P.BY_KEY[key].title
            for name, (label, _, _) in table.items():
                names[f"{key}_{name}"] = f"{title}: {label}"
        for k in variables:
            if k.startswith("lol_"):
                names.setdefault(k, "League of Legends: " + k[4:].replace("_", " "))
            elif k.startswith("stream_"):
                names.setdefault(k, "Multistream: " + k[7:] + " status")
            elif k.startswith("part_"):
                p = P.BY_KEY.get(k[5:])
                names.setdefault(k, f"{p.title if p else k[5:]}: off / starting / on / error")
        return names

    def _ros(self, variables):
        r = self.shell.ros
        s = r.state()
        show = s.get("show") or {}
        segs = show.get("segments") or []
        cur = show.get("current", -1)
        out = {"auto": bool(s.get("auto")), "current": cur,
               "segments": [{"index": i, "title": x.get("title") or "", "block": x.get("block") or ""}
                            for i, x in enumerate(segs)]}
        now = time.time()
        title = lambda i: segs[i].get("title") or "" if 0 <= i < len(segs) else ""   # noqa: E731
        variables["ros_current"] = title(cur)
        variables["ros_next"] = title(cur + 1)
        variables["ros_block"] = segs[cur].get("block") or "" if 0 <= cur < len(segs) else ""
        variables["ros_position"] = f"{cur + 1}/{len(segs)}" if 0 <= cur < len(segs) else f"0/{len(segs)}"
        m = show.get("match") or {}
        variables["ros_match"] = f"{m.get('team1') or ''} vs {m.get('team2') or ''}" if m.get("team1") or m.get("team2") else ""
        variables["ros_left"] = variables["ros_elapsed"] = variables["ros_next_at"] = ""
        if segs:
            try:
                tl = timeline(show, now)
                if 0 <= cur < len(segs):
                    variables["ros_left"] = _mmss(tl[cur]["end"] - now) if segs[cur].get("mins") else ""
                    variables["ros_elapsed"] = _mmss(now - tl[cur]["start"])
                if cur + 1 < len(segs):
                    variables["ros_next_at"] = time.strftime("%H:%M", time.localtime(tl[max(0, cur + 1)]["start"]))
            except Exception:
                pass
        return out

    # --- doing things -----------------------------------------------------------

    def act(self, body):
        what = body.get("do")
        try:
            if what == "engine":
                self.shell.engine_call("/api/companion", {k: v for k, v in body.items() if k != "do"}, timeout=8)
                with self.shell._engine_lock:
                    self.shell._engine["data"] = None
            elif what == "control":
                self._control(str(body.get("id") or ""), body.get("mode") or "toggle")
            elif what == "value":
                self._value(str(body.get("id") or ""), body.get("how") or "set", body.get("value"))
            elif what == "ros_go":
                self.shell.ros_post("/api/ros/go", {"index": int(body.get("index", -1))})
            else:
                raise ValueError(f"Unknown action: {what}")
        finally:
            with self._lock:
                self._forget()
        return self.state()

    def _control(self, cid, mode):
        if mode not in ("toggle", "on", "off"):
            raise ValueError("mode is toggle, on or off")
        group, _, key = cid.partition(".")
        if group == "ros":
            if key == "next":
                self.shell.ros_post("/api/ros/next", {})
            elif key == "prev":
                cur = (self.shell.ros.state().get("show") or {}).get("current", -1)
                self.shell.ros_post("/api/ros/go", {"index": max(-1, cur - 1)})
            elif key == "reset":
                self.shell.ros_post("/api/ros/reset", {})
            elif key == "cue":
                self._ros_cue()
            elif key == "auto":
                now = bool(self.shell.ros.state().get("auto"))
                self.shell.ros_post("/api/ros/auto", {"on": (not now) if mode == "toggle" else mode == "on"})
            else:
                raise ValueError(f"Unknown run of show command: {key}")
            log(f"Companion: {ROS_COMMANDS.get(key, 'run of show ' + key)}")
            return
        if group == "part":
            name, _, restart = key.partition(".")
            part = P.BY_KEY.get(name)
            if part is None or part.key == "engine":
                raise ValueError(f"Companion can't switch {name!r} on or off")
            if restart:
                self.shell.restart_part(part.key)
                log(f"Companion: restarting {part.title}")
                return
            now = part.status in ("on", "starting")
            want = (not now) if mode == "toggle" else mode == "on"
            if want != now:
                self.shell.set_part(part.key, want)
                log(f"Companion: {part.title} switched {'on' if want else 'off'}")
            return
        part = self._running(group)
        if part is None:
            p = P.BY_KEY.get(group)
            raise ValueError(f"{p.title if p else group} isn't running on this PC")
        if group == "lol":
            self._lol(part, key, mode)
            return
        st = self._game_state(part, fresh=True) or {}
        if group == "stream":
            if key == "restart":
                self._call(part, "/api/restart", {})
            elif key.startswith("dest_"):
                dest = next((d for d in st.get("destinations") or [] if d["id"] == key[5:]), None)
                if dest is None:
                    raise ValueError(f"No stream destination {key[5:]!r}")
                want = (not dest.get("enabled")) if mode == "toggle" else mode == "on"
                self._call(part, "/api/destination", {"id": dest["id"], "enabled": want})
            else:
                raise ValueError(f"Unknown Multistream control: {key}")
            self._games.pop(part.key, None)
            return
        c = next((c for c in GAMES.get(group, []) if c.id == key), None)
        if c is None:
            raise ValueError(f"Unknown {part.title} control: {key}")
        if c.kind == "command":
            want = True
        else:
            now = bool(c.read(st)) if c.read else False
            want = (not now) if mode == "toggle" else mode == "on"
            if want == now:
                return
        for path, body in c.do(want, st):
            self._call(part, path, body, timeout=8)
        self._games.pop(part.key, None)
        log(f"Companion: {part.title}: {c.label}" + ("" if c.kind == "command" else f" {'on' if want else 'off'}"))

    def _lol(self, part, key, mode):
        if key == "demo":
            st = self._call(part, "/api/state")
            now = _get(st, "app.mode") == "demo"
            want = (not now) if mode == "toggle" else mode == "on"
            if want != now:
                self._call(part, "/api/mode", {"mode": "demo" if want else "live"})
        elif key in ((self._lol_names or {}).get("commands") or {}):
            self._call(part, "/api/companion", {"action": "run", "id": key}, timeout=8)
        else:
            self._call(part, "/api/companion", {"action": mode, "id": key}, timeout=8)
        self._games.pop(part.key, None)

    def _value(self, vid, how, value):
        group, _, key = vid.partition(".")
        if group != "lol":
            raise ValueError(f"Unknown value: {vid}")
        part = self._running("lol")
        if part is None:
            raise ValueError("League of Legends isn't running on this PC")
        if how not in ("set", "adjust"):
            raise ValueError("how is set or adjust")
        self._call(part, "/api/companion", {"action": how, "id": key, "value": float(value or 0)}, timeout=8)
        self._games.pop(part.key, None)

    def _ros_cue(self):
        show = self.shell.ros.state().get("show") or {}
        segs, cur = show.get("segments") or [], show.get("current", -1)
        if not 0 <= cur < len(segs):
            raise ValueError("No segment on air")
        names = segs[cur].get("graphics") or []
        if not names:
            raise ValueError(f"{segs[cur].get('title') or 'This segment'} has no graphics")
        missing = []
        for name in names:
            try:
                self.shell.engine_call("/api/companion", {"action": "preview", "id": name, "mode": "on"})
            except ValueError:
                missing.append(name)
        if missing:
            log(f"Companion: run of show: no graphic called {', '.join(missing)} in this workspace", "warn")
        if len(missing) == len(names):
            raise ValueError(f"No graphic called {', '.join(missing)} in this workspace")
