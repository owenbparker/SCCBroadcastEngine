"""Run of show: the evening's segments, on the left of Control.

Built by hand from TEMPLATES, one or more per game (Settings > Run of show):

    template = {"id", "name", "game": "val" | "lol" | ... | "any", "best_of": 3,
                "blocks": [{"id", "name", "color", "repeat": False,   # True: once per map in the series
                            "segments": [{"id", "title", "notes", "color",
                                          "mins": 15,          # its length (an estimate when "game")
                                          "game": False,       # lasts as long as the game: times after it move
                                          "skip_last": False,  # (in a repeat block) not after the last map
                                          "graphics": ["Caster L3", ...]}]}]}

Tonight's SHOW is a template laid out for the newest match in the GFX
Engine's Schedule (teams, game, start time): repeat blocks once per map, the
text filled in ({{Match.TeamA}}, {{Map.N}}, ...). The app picks the game from
that match and uses its template; a game with no template starts blank.

Times are worked out, not stored: a segment starts when the one before it
ended (or, before then, when it's expected to). "Next segment" records the
real times, so when a game runs long everything after it moves.
"""

import copy
import datetime
import json
import os
import re
import threading
import time
import uuid

GAMES = {"lol": "League of Legends", "val": "VALORANT", "cod": "Call of Duty", "rl": "Rocket League",
         "smash": "Smash", "ow": "Overwatch", "any": "Any game"}
COLOURS = ["#ffffff", "#ffd60a", "#64d2ff", "#30d158", "#ff9f0a", "#ff375f", "#bf5af2"]
_GAME_WORDS = [("lol", r"league|\blol\b"), ("val", r"valorant|\bval\b"), ("cod", r"call of duty|\bcod\b|\bcdl\b"),
               ("rl", r"rocket"), ("smash", r"smash"), ("ow", r"overwatch|\bow\b")]


def new_id():
    return uuid.uuid4().hex[:10]


def game_of(text):
    """"ROCKET LEAGUE | PLAYOFFS" -> "rl" ("" when it doesn't say)."""
    text = (text or "").lower()
    for key, pattern in _GAME_WORDS:
        if re.search(pattern, text):
            return key
    return ""


def _str(v, n=200):
    return str(v or "").strip()[:n]


def _colour(v, default="#ffffff"):
    v = str(v or "")
    return v if re.match(r"^#[0-9a-fA-F]{6}$", v) else default


def clean_template(t):
    t = t if isinstance(t, dict) else {}
    game = t.get("game") if t.get("game") in GAMES else "any"
    try:
        best_of = max(1, min(9, int(t.get("best_of") or 3)))
    except (TypeError, ValueError):
        best_of = 3
    blocks = []
    for b in (t.get("blocks") or [])[:40]:
        if not isinstance(b, dict):
            continue
        segs = []
        for s in (b.get("segments") or [])[:80]:
            if not isinstance(s, dict):
                continue
            try:
                mins = max(0.0, min(600.0, float(s.get("mins") or 0)))
            except (TypeError, ValueError):
                mins = 0.0
            segs.append({"id": _str(s.get("id"), 20) or new_id(), "title": _str(s.get("title"), 120) or "Segment",
                         "notes": _str(s.get("notes"), 300), "color": _colour(s.get("color")),
                         "mins": mins, "game": bool(s.get("game")), "skip_last": bool(s.get("skip_last")),
                         "graphics": [_str(g, 80) for g in (s.get("graphics") or []) if _str(g, 80)][:12]})
        blocks.append({"id": _str(b.get("id"), 20) or new_id(), "name": _str(b.get("name"), 60) or "Block",
                       "color": _colour(b.get("color"), "#bf5af2"), "repeat": bool(b.get("repeat")), "segments": segs})
    return {"id": _str(t.get("id"), 20) or new_id(), "name": _str(t.get("name"), 80) or "Run of show",
            "game": game, "best_of": best_of, "blocks": blocks}


def starter_template(game="val", best_of=3):
    """A first template to start from (the one in the design)."""
    seg = lambda title, mins, color="#ffffff", notes="", graphics=(), **kw: dict(  # noqa: E731
        id=new_id(), title=title, mins=mins, color=color, notes=notes, graphics=list(graphics), **kw)
    name = GAMES.get(game, "Show")
    return clean_template({
        "name": f"{name} · Best of {best_of}", "game": game, "best_of": best_of,
        "blocks": [
            {"name": "Pre-show", "color": "#bf5af2", "segments": [
                seg("Countdown", 15, "#bf5af2", "Starting soon, sponsors", ["Countdown bug"]),
                seg("Desk · Casters", 10, "#ffffff", "Casters introduce {{Match.TeamA}} vs {{Match.TeamB}}", ["Caster L3"])]},
            {"name": "Match", "color": "#64d2ff", "repeat": True, "segments": [
                seg("Map {{Map.N}}", 40, "#30d158", "Live game", ["Scorebug"], game=True),
                seg("Between maps", 5, "#ff9f0a", "Skipped after the last map", ["Sponsor board"], skip_last=True)]},
            {"name": "Post-show", "color": "#bf5af2", "segments": [
                seg("Wrap-up", 10, "#bf5af2", "Result, standings, what's next", ["Standings"])]},
        ]})


def fill(text, match, map_n=None):
    out = text or ""
    teams = {"Match.TeamA": match.get("team1") or "Team A", "Match.TeamB": match.get("team2") or "Team B",
             "Match.BestOf": str(match.get("best_of") or ""), "Match.Game": match.get("game") or "",
             "Match.Tournament": match.get("tournament") or "", "Match.Start": match.get("time") or ""}
    if map_n is not None:
        teams["Map.N"] = str(map_n)
    for k, v in teams.items():
        out = out.replace("{{" + k + "}}", v)
    return out


def build_show(template, match):
    """Tonight's segments from a template (None: a blank show) for a match."""
    match = dict(match or {})
    segs = []
    if template:
        best_of = int(match.get("best_of") or template.get("best_of") or 1)
        match["best_of"] = best_of
        for b in template["blocks"]:
            rounds = range(1, best_of + 1) if b.get("repeat") else [None]
            for n in rounds:
                for s in b["segments"]:
                    if n is not None and s.get("skip_last") and n == best_of:
                        continue
                    segs.append({"id": new_id(), "title": fill(s["title"], match, n), "notes": fill(s["notes"], match, n),
                                 "color": s["color"], "mins": s["mins"], "game": s["game"], "graphics": list(s["graphics"]),
                                 "block": b["name"], "block_color": b["color"], "map": n})
    return {"template_id": template["id"] if template else "", "template_name": template["name"] if template else "",
            "match": match, "match_key": match_key(match), "segments": segs, "current": -1,
            "times": {}, "built": time.time()}


def match_key(m):
    m = m or {}
    return "|".join(str(m.get(k) or "") for k in ("date", "time", "team1", "team2", "game"))


def pick_match(matches, now=None):
    """The match the run of show is for: the next one still to come in the
    Schedule (else the last one listed)."""
    now = now or datetime.datetime.now()
    best, best_t = None, None
    for m in matches or []:
        try:
            t = datetime.datetime.fromisoformat(f"{m.get('date')}T{m.get('time') or '00:00'}")
        except ValueError:
            continue
        if t.date() >= now.date() and (best_t is None or t < best_t):
            best, best_t = m, t
    if best is None and matches:
        best = matches[-1]
    return dict(best) if best else None


def series_over(show, scores):
    """Has a team won the series (from the GFX Engine's Global scores)?"""
    best_of = int(show["match"].get("best_of") or 1)
    need = best_of // 2 + 1
    return bool(scores) and max(scores) >= need


def timeline(show, now=None):
    """Each segment's start and end (epoch seconds) and whether it's an
    estimate. Before the show starts, the first starts at the match's time."""
    now = now or time.time()
    segs, times = show["segments"], show.get("times") or {}
    out, t, est = [], None, False
    start = None
    m = show.get("match") or {}
    try:
        start = datetime.datetime.fromisoformat(f"{m.get('date')}T{m.get('time')}").timestamp()
    except (TypeError, ValueError):
        start = None
    for i, s in enumerate(segs):
        real = times.get(s["id"]) or {}
        if real.get("start"):
            begin, b_est = real["start"], False
        else:
            begin = t if t is not None else (start or now)
            b_est = est or (t is None and not start)
        if real.get("end"):
            end, e_est = real["end"], False
        else:
            end = begin + s["mins"] * 60
            if i == show.get("current") and end < now:
                end = now   # running long: everything after moves
            e_est = b_est or s["game"] or i == show.get("current")
        out.append({"start": begin, "end": end, "est_start": b_est, "est_end": e_est})
        t, est = end, e_est
    return out


class RunOfShow:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.data = {"templates": [], "show": None, "auto": True}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
                self.data["templates"] = [clean_template(t) for t in d.get("templates") or []]
                self.data["show"] = d.get("show")
                self.data["auto"] = d.get("auto", True) is not False
            except (OSError, ValueError):
                pass

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1)
        os.replace(tmp, self.path)

    # --- templates ---------------------------------------------------------

    def template(self, tid):
        return next((t for t in self.data["templates"] if t["id"] == tid), None)

    def save_template(self, t):
        t = clean_template(t)
        with self.lock:
            ts = self.data["templates"]
            i = next((n for n, x in enumerate(ts) if x["id"] == t["id"]), None)
            if i is None:
                ts.append(t)
            else:
                ts[i] = t
            self.save()
        return t

    def delete_template(self, tid):
        with self.lock:
            self.data["templates"] = [t for t in self.data["templates"] if t["id"] != tid]
            self.save()

    def for_game(self, game):
        return next((t for t in self.data["templates"] if t["game"] == game), None) or \
            next((t for t in self.data["templates"] if t["game"] == "any"), None)

    # --- tonight -------------------------------------------------------------

    def apply(self, match, template_id=None, best_of=None):
        """Lay out tonight's show for a match (from a chosen template, or the
        one for the match's game)."""
        match = dict(match or {})
        if best_of:
            match["best_of"] = best_of
        game = match.get("game_key") or game_of(match.get("game"))
        match["game_key"] = game
        template = self.template(template_id) if template_id else self.for_game(game)
        if template and not match.get("best_of"):
            match["best_of"] = template["best_of"]
        with self.lock:
            self.data["show"] = build_show(template, match)
            self.save()
        return self.data["show"]

    def auto_apply(self, matches, global_best_of=None):
        """When the Schedule's next match changes (and tonight's show hasn't
        started), lay the show out again for it."""
        if not self.data.get("auto"):
            return False
        m = pick_match(matches)
        if not m:
            return False
        show = self.data.get("show")
        if global_best_of and not m.get("best_of"):
            m["best_of"] = global_best_of
        if show and (show.get("current", -1) >= 0 or show.get("match_key") == match_key(m)):
            return False
        self.apply(m)
        return True

    def edit_show(self, segments=None, start=None):
        with self.lock:
            show = self.data.get("show") or build_show(None, {})
            if segments is not None:
                keep = {s["id"]: s for s in show["segments"]}
                new = []
                for s in segments:
                    old = keep.get(s.get("id"), {})
                    base = {**old, **{k: s[k] for k in ("title", "notes", "color", "mins", "game", "graphics") if k in s}}
                    c = clean_template({"blocks": [{"segments": [base]}]})["blocks"][0]["segments"][0]
                    c.update({k: old.get(k, s.get(k, "")) for k in ("block", "block_color", "map")})
                    c["id"] = old.get("id") or c["id"]
                    new.append(c)
                cur = show["segments"][show["current"]]["id"] if 0 <= show.get("current", -1) < len(show["segments"]) else None
                show["segments"] = new
                show["current"] = next((i for i, s in enumerate(new) if s["id"] == cur), -1)
            if start is not None:
                show["match"]["time"] = start if re.match(r"^\d{1,2}:\d{2}$", start or "") else show["match"].get("time", "")
                if not show["match"].get("date"):
                    show["match"]["date"] = datetime.date.today().isoformat()
            self.data["show"] = show
            self.save()
        return show

    def go(self, index, scores=None, now=None):
        """Make segment `index` the one on air (records the real times).
        Past the last map of a series that's already won, it skips ahead."""
        now = now or time.time()
        with self.lock:
            show = self.data.get("show")
            if not show:
                raise ValueError("No run of show yet")
            segs = show["segments"]
            index = max(-1, min(index, len(segs)))
            cur = show.get("current", -1)
            if scores is not None and index == cur + 1 and 0 <= index < len(segs) and segs[index].get("map"):
                # The series is decided: skip the maps that won't be played.
                # (Only from inside the match block, so last match's scores
                # still in Global don't skip a new show's maps.)
                if cur >= 0 and segs[cur].get("map") and series_over(show, scores):
                    while index < len(segs) and segs[index].get("map"):
                        index += 1
            times = show.setdefault("times", {})
            if 0 <= cur < len(segs):
                times.setdefault(segs[cur]["id"], {})["end"] = now
            if index < cur:   # (going back: forget what came after)
                for s in segs[index:]:
                    times.pop(s["id"], None)
            if 0 <= index < len(segs):
                t = times.setdefault(segs[index]["id"], {})
                t["start"] = now
                t.pop("end", None)
            show["current"] = index if index < len(segs) else len(segs)
            self.save()
            return show

    def reset(self):
        with self.lock:
            show = self.data.get("show")
            if show:
                show["current"], show["times"] = -1, {}
                self.save()
            return show

    def set_auto(self, on):
        with self.lock:
            self.data["auto"] = bool(on)
            self.save()

    def state(self, now=None):
        show = copy.deepcopy(self.data.get("show"))
        if show:
            show["timeline"] = timeline(show, now)
        return {"templates": copy.deepcopy(self.data["templates"]), "show": show, "auto": self.data.get("auto", True),
                "games": GAMES, "colours": COLOURS}
