"""Game flow: the score of a Hardpoint or Hijack game, read off the CoD caster
HUD's score box all game long, for the "Game flow" board (web/gameflow.html):
the two teams' scores over the game, with the points each team took on every
hill (Hardpoint) or in each half, with its throws, dunks and runoff (Hijack).

Built from the broadcast team's Game Flow Generator (GameFlow_Hardpoint.py /
GameFlow_Hijack.py): the same score boxes, the same timing rules and the same
sums, read inside the HUD (with Windows' own text recognition, as the player
names are) instead of a separate app with Tesseract.

Timing (so the hill / half clock can't drift):
  * a game's clock starts when the "STARTING IN" countdown banner goes, timed
    by watching it about ten times a second (the middle of the last picture
    with it and the first without); joined mid-game (or the banner missed),
    it starts once the scores have gone up three times in a row;
  * every reading is stamped with the moment its picture was taken;
  * Hardpoint: a hill is 60 seconds; the game ends at 250;
  * Hijack: two 4:00 halves (first to 150, then 300, or the timer); after a
    throw (+15) or dunk (+30) a team scores up to 30 more points, one a
    second, while the game timer stands still: that time is taken off the
    clock, so a drive is one straight rise on the graph.

A score is only taken when it goes up by a believable amount (bigger jumps
must be read twice), so one misread can't spoil the graph. The game in
progress is kept in gameflow/current.json (data folder) and every finished one
in gameflow/games/, so a restart or a new game never loses one.
"""

import copy
import json
import os
import re
import threading
import time

import numpy as np

from .detect import crop
from .log import log

HILL_SECONDS = 60
HP_TARGET = 250
HALF_SECONDS = 240
HALF_TARGETS = {1: 150, 2: 300}
READ_MAX = 350
DRIVE_JUMP_MIN = 14        # a rise this big at once is a throw (15) or a dunk (30)
DRIVE_MAX_BONUS = 30       # then up to 30 more points, one a second, the game timer stopped
DRIVE_IDLE = 2.5           # seconds with no new point: the drive is over
GONE_FRAMES = 2            # leader on (target - 1) and its number gone this many reads: it scored the last point
READ_EVERY = 0.5           # seconds between reads of the score
WATCH_EVERY = 0.1          # ...while timing the countdown banner
KEEP_GAMES = 40            # finished games kept in gameflow/games

# Hills per rotation on each Hardpoint map (the graph's P1..Pn), and the
# Hijack maps (for the title).
HP_MAPS = {"Lotus": 6, "Lithium": 6, "Munition": 6, "Reactor U92": 5, "Rooftops": 6, "Sentry": 5}
HIJACK_MAPS = ["Lotus", "Lithium", "Munition", "Reactor U92", "Rooftops", "Sentry"]
MODES = {"hardpoint": "Hardpoint", "hijack": "Hijack"}

# Where things are on the CoD caster HUD (1920x1080): the scores in the score
# box, the game mode under them, and the "STARTING IN" countdown.
DEFAULT_BOXES = {"left": {"x": 806, "y": 84, "w": 92, "h": 45},
                 "right": {"x": 1027, "y": 84, "w": 92, "h": 45},
                 "mode": {"x": 730, "y": 160, "w": 460, "h": 38},
                 "countdown": {"x": 879, "y": 252, "w": 159, "h": 36}}

_LOOKALIKE = str.maketrans({"l": "1", "I": "1", "i": "1", "|": "1", "!": "1", "O": "0", "o": "0", "D": "0", "Q": "0",
                            "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2", "g": "9", "q": "9", "G": "6", "T": "7"})


# --- reading the picture -------------------------------------------------------------

def number(text, top=READ_MAX):
    """What was read -> the score, or None."""
    t = re.sub(r"\s+", "", str(text or "")).translate(_LOOKALIKE)
    if not re.fullmatch(r"\d{1,3}", t):
        return None
    n = int(t)
    return n if n <= top else None


def read_score(frame, box, ocr):
    cell = crop(frame, box["x"], box["y"], box["w"], box["h"])
    from .names import ink
    words = sorted(ocr.words(ink(cell, scale=3, level=80)), key=lambda w: w[1])
    # (only what reads as digits: a logo's edge at the side can read as a stray mark)
    digits = [t for t, _, _ in words if number(t, 999) is not None]
    return number("".join(digits)) if digits else None


def read_text(frame, box, ocr):
    cell = crop(frame, box["x"], box["y"], box["w"], box["h"])
    from .names import ink
    words = sorted(ocr.words(ink(cell, scale=2, level=80)), key=lambda w: w[1])
    return " ".join(t for t, _, _ in words).upper()


def mode_of(text):
    """The game mode named under the scores -> "hardpoint", "hijack", "" (another
    mode) or None (nothing read)."""
    letters = re.sub(r"[^A-Z]", "", str(text or "").upper())
    if not letters:
        return None
    if "HARDP" in letters or "POINT" in letters and "HARD" in letters:
        return "hardpoint"
    if "HIJACK" in letters or "JACK" in letters:
        return "hijack"
    return ""


def is_starting(text):
    letters = re.sub(r"[^A-Z]", "", str(text or "").upper())
    if "STARTING" in letters:
        return True
    import difflib
    return len(letters) >= 7 and difflib.SequenceMatcher(None, letters, "STARTINGIN").ratio() >= 0.75


def banner_mask(cell):
    """A tiny black/white picture of the banner's bright lettering, to tell in
    a millisecond whether it's still there (Otsu's threshold)."""
    from PIL import Image
    g = np.asarray(Image.fromarray(cell).convert("L").resize((80, 20), Image.BOX), dtype=np.float64)
    hist = np.bincount(g.astype(np.uint8).ravel(), minlength=256).astype(np.float64)
    total, levels = hist.sum(), np.arange(256)
    w0 = np.cumsum(hist)
    m0 = np.cumsum(hist * levels)
    w1 = total - w0
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (m0[-1] * w0 / total - m0) ** 2 / (w0 * w1)
    level = int(np.nanargmax(np.nan_to_num(between, nan=-1))) if total else 127
    m = g > level
    if m.mean() > 0.5:          # (the lettering is the smaller part)
        m = ~m
    return m


def banner_present(cell, tpl):
    if tpl is None:
        return False
    m = banner_mask(cell)
    hit = float((m & tpl).sum())
    return hit / max(1.0, float(tpl.sum())) >= 0.6 and hit / max(1.0, float(m.sum())) >= 0.4


# --- the sums -----------------------------------------------------------------------

class Tracker:
    """Noisy readings -> a score that only goes up. A rise at the normal pace
    is taken at once; a bigger (but believable) one only when read twice."""

    def __init__(self, confirm=2):
        self.confirm = confirm
        self.reset(0.0)

    def reset(self, t):
        self.last = [0, 0]
        self.pending = [None, None]
        self.count = [0, 0]
        self.changed_at = [t, t]

    def update(self, t, readings):
        for i, r in enumerate(readings):
            if r is None or r == self.last[i]:
                self.pending[i], self.count[i] = None, 0
                continue
            dt = max(0.0, t - self.changed_at[i])
            delta = r - self.last[i]
            if 0 < delta <= 2 * dt + 3:
                self.last[i], self.changed_at[i] = r, t
                self.pending[i], self.count[i] = None, 0
            elif 0 < delta <= 30 + 3 * dt:
                if self.pending[i] == r:
                    self.count[i] += 1
                else:
                    self.pending[i], self.count[i] = r, 1
                if self.count[i] >= self.confirm:
                    self.last[i], self.changed_at[i] = r, t
                    self.pending[i], self.count[i] = None, 0
            else:
                self.pending[i], self.count[i] = None, 0
        return tuple(self.last)


def value_at(times, vals, t):
    """The score at time t: the reading nearest t (within 0.3 s), else the last before it."""
    near = min(range(len(times)), key=lambda i: abs(times[i] - t))
    if abs(times[near] - t) <= 0.3:
        return vals[near]
    before = [i for i, x in enumerate(times) if x <= t]
    return vals[before[-1]] if before else vals[0]


def hill_totals(data):
    """Hardpoint: each team's score at the end of every hill, [(left, right), ...]
    from 0:00 (the last one is the score now)."""
    times, L, R = data["times"], data["left"], data["right"]
    if len(times) < 1:
        return [(0, 0)]
    n = max(1, int(np.ceil(times[-1] / HILL_SECONDS - 1e-9)))
    out = [(0, 0)]
    for k in range(1, n + 1):
        if k == n:
            out.append((L[-1], R[-1]))
        else:
            t = k * HILL_SECONDS
            out.append((value_at(times, L, t), value_at(times, R, t)))
    return out


def hill_points(totals, cycle):
    """Points each team took on each hill of the rotation (P1..Pn): the second
    time round is the same hill, so it's added to the first."""
    pts = [(max(0, min(HILL_SECONDS, b[0] - a[0])), max(0, min(HILL_SECONDS, b[1] - a[1])))
           for a, b in zip(totals, totals[1:])]
    folded = [[0, 0] for _ in range(min(cycle, len(pts)))]
    for k, (l_, r_) in enumerate(pts):
        folded[k % cycle][0] += l_
        folded[k % cycle][1] += r_
    return [tuple(x) for x in folded]


def find_drives(times, left, right, halves=None):
    """Hijack's scoring drives: a 15 or 30 chunk, then up to 30 more points at
    one a second (the game timer stopped, so live they share one time)."""
    n, out = len(times), []
    for team, ser in ((0, left), (1, right)):
        j = 1
        while j < n:
            gain = ser[j] - ser[j - 1]
            if gain >= DRIVE_JUMP_MIN and (halves is None or halves[j] == halves[j - 1]):
                t0, k = times[j], j
                while k + 1 < n and (halves is None or halves[k + 1] == halves[j]):
                    step = ser[k + 1] - ser[k]
                    same_clock = abs(times[k + 1] - t0) <= 0.011
                    ticking = 0 < step <= 3 and times[k + 1] - times[k] <= 1.6
                    if not (same_clock or ticking):
                        break
                    k += 1
                total = ser[k] - ser[j - 1]
                chunk = 30 if gain >= 22 else 15
                out.append(dict(team=team, half=halves[j] if halves else 1, t=t0, y0=ser[j - 1], y1=ser[k],
                                total=total, chunk=chunk, bonus=max(0, total - chunk)))
                j = k + 1
            else:
                j += 1
    out.sort(key=lambda d: d["t"])
    return out


def half_points(halves, L, R):
    """Points each team scored in each half; None for a half not played yet."""
    out, prev = [], (0, 0)
    for h in (1, 2):
        idx = [i for i, hh in enumerate(halves) if hh == h]
        if not idx:
            out.append(None)
            continue
        end = (L[idx[-1]], R[idx[-1]])
        out.append((end[0] - prev[0], end[1] - prev[1]))
        prev = end
    return out


def team_stats(drives):
    """Each team's throws (+15), dunks (+30), runoff points and points per score."""
    res = []
    for team in (0, 1):
        mine = [d for d in drives if d["team"] == team]
        pts = sum(d["total"] for d in mine)
        res.append(dict(throws=sum(1 for d in mine if d["chunk"] == 15),
                        dunks=sum(1 for d in mine if d["chunk"] == 30),
                        runoff=sum(d["bonus"] for d in mine),
                        avg=round(pts / len(mine), 1) if mine else None))
    return res


# --- one game, reading by reading ---------------------------------------------------

class Game:
    """The state of the game being tracked, fed one reading at a time
    (step(now, left, right, ...)). No picture, no clock of its own: the
    reader gives it the times, so it can be tested with made-up games."""

    def __init__(self, mode, auto_start=True):
        self.mode = mode if mode in MODES else "hardpoint"
        self.auto_start = auto_start
        self.tr = Tracker()
        self.state = "waiting"
        self.half = 1               # the half being played (Hardpoint: always 1)
        self.pending_half = 1       # the half the next countdown starts
        self.t_start = 0.0          # the wall clock time the data clock counts from
        self.paused = 0.0           # Hijack: seconds the game timer stood still this game
        self.drive = None
        self.prev_cur = (0, 0)
        self.prev_pair = None
        self.live_nonzero = 0
        self.allow_fallback = True
        self.reset_run = 0
        self.gone_n, self.gone_t0, self.gone_idx = 0, 0.0, 0
        self.started_at = None      # wall clock time of 0:00
        self.finished_at = None
        self.data = self._empty()
        self.events = []            # what happened, for the log ("half", "game")
        self.meta = {}              # the map and which map of the series, as they were when it started

    def _empty(self):
        return {"times": [], "left": [], "right": [], "half": []}

    def _append(self, t, cur):
        d = self.data
        d["times"].append(round(t, 3))
        d["left"].append(int(cur[0]))
        d["right"].append(int(cur[1]))
        d["half"].append(self.half)

    def target(self):
        return HP_TARGET if self.mode == "hardpoint" else HALF_TARGETS[self.half]

    def begin(self, when, which=1, seed=None, now=None):
        """The clock starts (a half's, for Hijack)."""
        now = when if now is None else now
        when = min(when, now)
        self.state, self.half, self.drive = "running", which, None
        self.reset_run, self.gone_n = 0, 0
        if which == 1:
            self.t_start, self.paused = when, 0.0
            self.started_at, self.finished_at = when, None
            self.tr.reset(0.0)
            if seed:
                self.tr.last = [int(seed[0]), int(seed[1])]
            self.data = self._empty()
            self._append(0.0, self.tr.last)
        else:
            # the data clock carries on from 4:00
            self.t_start, self.paused = when - HALF_SECONDS, 0.0
            self.tr.pending, self.tr.count = [None, None], [0, 0]
            self.tr.changed_at = [float(HALF_SECONDS)] * 2
            self._append(float(HALF_SECONDS), self.tr.last)
        self.prev_cur = tuple(self.tr.last)

    def clock(self, now):
        """The data clock now (seconds; Hijack's second half from 240)."""
        if self.drive:
            return self.drive["t0"]
        return max(0.0, now - self.t_start - self.paused)

    def _end_half(self, now, timer):
        end_t = self.half * HALF_SECONDS
        if self.mode == "hijack" and timer and self.data["times"] and self.data["times"][-1] < end_t - 0.05:
            self._append(float(end_t), self.tr.last)
        self.gone_n = 0
        if self.mode == "hijack" and self.half == 1:
            self.state, self.pending_half, self.allow_fallback, self.prev_pair = "halftime", 2, True, tuple(self.tr.last)
            self.live_nonzero = 0
            self.events.append(("half", tuple(self.tr.last)))
        else:
            self.state, self.finished_at = "finished", now
            self.events.append(("game", tuple(self.tr.last)))

    def bump_final(self, t):
        """The leader's last score read was one short of the target and the
        game's over: that last point was scored but vanished before it was read."""
        lead = 0 if self.tr.last[0] >= self.tr.last[1] else 1
        goal = self.target()
        if self.tr.last[lead] != goal - 1 or not self.data["times"]:
            return
        self.tr.last[lead] = goal
        self._append(max(t, self.data["times"][-1]), self.tr.last)

    def step(self, now, left, right):
        """One reading of the scores while running (or waiting to fall back on
        climbing scores). Returns what's going on."""
        pair = (left, right)
        if self.state in ("waiting", "halftime"):
            if None not in pair:
                if self.prev_pair is not None:
                    if pair[0] < self.prev_pair[0] or pair[1] < self.prev_pair[1]:
                        self.live_nonzero = 0
                    elif pair != self.prev_pair and max(pair) < (HP_TARGET if self.mode == "hardpoint" else HALF_TARGETS[2]):
                        self.live_nonzero += 1
                self.prev_pair = pair
            if self.allow_fallback and self.live_nonzero >= 3:
                if self.state == "halftime":
                    self.begin(now, 2)
                else:
                    self.begin(now, 1, seed=pair)
                self.prev_pair, self.live_nonzero = None, 0
            return self.state
        if self.state != "running":
            return self.state
        t = self.clock(now)
        if self.mode == "hijack":
            end_t = self.half * HALF_SECONDS
            if t >= end_t + 1.0:                       # the half's timer ran out
                self._end_half(now, True)
                return self.state
        low = left is not None and right is not None and left <= 10 and right <= 10 and max(self.tr.last) >= 40
        self.reset_run = self.reset_run + 1 if low else 0
        if self.reset_run >= 6:                        # scores only go up: a new game has begun
            self.bump_final(t)
            self.state, self.finished_at = "finished", now
            self.events.append(("game", tuple(self.tr.last)))
            return "reset"
        cur = self.tr.update(t, pair)
        if self.mode == "hijack":
            t_rec = min(t, self.half * HALF_SECONDS)
        else:
            t_rec = t
        self._append(t_rec, cur)
        if self.mode == "hijack":
            if self.drive is None:
                for i in (0, 1):
                    if cur[i] - self.prev_cur[i] >= DRIVE_JUMP_MIN:
                        self.drive = {"team": i, "t0": t, "wall0": now, "last_inc": now, "start": self.prev_cur[i],
                                      "chunk": 30 if cur[i] - self.prev_cur[i] >= 22 else 15}
                        break
            else:
                i = self.drive["team"]
                if cur[i] > self.prev_cur[i]:
                    self.drive["last_inc"] = now
                if now - self.drive["last_inc"] >= DRIVE_IDLE or cur[i] - self.drive["start"] >= self.drive["chunk"] + DRIVE_MAX_BONUS:
                    self.paused += max(0.0, self.drive["last_inc"] - self.drive["wall0"])
                    self.drive = None
        self.prev_cur = tuple(cur)
        goal = self.target()
        lead = 0 if self.tr.last[0] >= self.tr.last[1] else 1
        if self.tr.last[lead] == goal - 1 and pair[lead] is None:
            if self.gone_n == 0:
                self.gone_t0, self.gone_idx = t_rec, len(self.data["times"]) - 1
            self.gone_n += 1
        else:
            self.gone_n = 0
        if self.gone_n >= GONE_FRAMES:
            for k in self.data:
                del self.data[k][self.gone_idx:]
            self.tr.last[lead] = goal
            self._append(max(self.gone_t0, self.data["times"][-1] if self.data["times"] else 0.0), self.tr.last)
            cur = tuple(self.tr.last)
            self.gone_n = 0
        if max(cur) >= goal and self.drive is None:
            self._end_half(now, False)
        return self.state

    def countdown_gone(self, start):
        """The countdown banner went at `start` (wall clock): the clock starts."""
        self.begin(start, self.pending_half, now=start)
        self.allow_fallback = True

    def to_dict(self):
        return {"mode": self.mode, "state": self.state, "half": self.half, "data": copy.deepcopy(self.data),
                "started_at": self.started_at, "finished_at": self.finished_at, "meta": dict(self.meta)}

    @classmethod
    def from_dict(cls, d):
        g = cls(d.get("mode") or "hardpoint")
        data = d.get("data") or {}
        if all(isinstance(data.get(k), list) for k in ("times", "left", "right")):
            n = len(data["times"])
            g.data = {"times": data["times"], "left": data["left"][:n], "right": data["right"][:n],
                      "half": (data.get("half") or [1] * n)[:n]}
        g.state = d.get("state") if d.get("state") in ("finished", "halftime") else "finished"
        g.half = int(d.get("half") or 1)
        g.started_at, g.finished_at = d.get("started_at"), d.get("finished_at")
        g.meta = d.get("meta") if isinstance(d.get("meta"), dict) else {}
        if g.data["left"]:
            g.tr.last = [g.data["left"][-1], g.data["right"][-1]]
        return g


# --- what the board shows ----------------------------------------------------------------

def view(game, info):
    """The game -> what the Game flow board draws (web/gameflow.html).
    info: {"map", "map_no", "left"/"right": {"name", "short", "color", "logo"}}."""
    d = game.data
    mode = game.mode
    meta = dict(info, **{k: v for k, v in (game.meta or {}).items() if v not in (None, "")})
    out = {"mode": mode, "mode_name": MODES[mode], "state": game.state, "map": meta.get("map") or "",
           "map_no": meta.get("map_no") or 1, "left": info.get("left") or {}, "right": info.get("right") or {},
           "score": [d["left"][-1], d["right"][-1]] if d["left"] else [0, 0], "half": game.half}
    if len(d["times"]) < 1:
        out["empty"] = True
        return out
    if mode == "hardpoint":
        cycle = HP_MAPS.get(out["map"], 0) or info.get("hills") or 5
        totals = hill_totals(d)
        out.update(target=HP_TARGET, cycle=cycle, hills=[list(x) for x in totals],
                   labels=["HILLS"] + [f"P{(k - 1) % cycle + 1}" for k in range(1, len(totals))],
                   per_hill=[list(x) for x in hill_points(totals, cycle)])
        return out
    halves = d.get("half") or [1 if t <= HALF_SECONDS + 0.5 else 2 for t in d["times"]]
    drives = find_drives(d["times"], d["left"], d["right"], halves)
    finished = halves[-1] == 2 and (max(d["left"][-1], d["right"][-1]) >= HALF_TARGETS[2] or d["times"][-1] >= 2 * HALF_SECONDS - 0.5)
    # (the line only needs a point where it changes)
    pts = []
    for i, (t, l_, r_, h) in enumerate(zip(d["times"], d["left"], d["right"], halves)):
        if 0 < i < len(d["times"]) - 1 and pts and pts[-1][1:] == [l_, r_, h] and d["left"][i + 1] == l_ and d["right"][i + 1] == r_ and halves[i + 1] == h:
            continue
        pts.append([round(t, 2), l_, r_, h])
    out.update(targets=[HALF_TARGETS[1], HALF_TARGETS[2]], half_seconds=HALF_SECONDS, points=pts, finished=finished,
               drives=[{k: dv[k] for k in ("team", "half", "t", "y0", "y1", "total", "chunk")} for dv in drives],
               per_half=[list(x) if x else None for x in half_points(halves, d["left"], d["right"])],
               stats=team_stats(drives))
    return out


def demo_game(mode):
    """A made-up game for the Demo match (and the board before any game):
    Hardpoint as the broadcast team's example (Reactor U92), Hijack a game of throws and dunks."""
    g = Game(mode)
    if mode == "hardpoint":
        hills = [(0, 0), (29, 8), (49, 32), (88, 44), (119, 63), (124, 96), (135, 131), (142, 152), (152, 179),
                 (152, 220), (153, 250)]
        g.begin(0.0, 1)
        g.data = g._empty()
        for k, (a, b) in enumerate(hills):
            g.half = 1
            g._append(k * HILL_SECONDS if k < len(hills) - 1 else (k - 1) * HILL_SECONDS + 52, (a, b))
        g.state = "finished"
        return g
    g.begin(0.0, 1)
    g.data = g._empty()
    score = [0, 0]
    script = [(1, 0, 15, 8), (1, 1, 30, 12), (1, 0, 30, 20), (1, 1, 15, 4), (1, 0, 15, 30), (1, 1, 30, 18), (1, 0, 15, 20),
              (2, 1, 30, 25), (2, 0, 15, 10), (2, 1, 15, 30), (2, 0, 30, 14), (2, 1, 30, 9), (2, 0, 15, 30), (2, 1, 30, 30)]
    times = [20, 55, 95, 130, 170, 200, 228, 262, 300, 335, 370, 410, 440, 460]
    g.half = 1
    g._append(0.0, score)
    for (h, team, chunk, bonus), t in zip(script, times):
        if h == 2 and g.half == 1:
            g.half = 2
            g._append(float(HALF_SECONDS), score)
        g._append(t, score)
        score[team] += chunk
        g._append(t, score)
        for _ in range(bonus):
            score[team] += 1
            g._append(t, score)
    g.half, g.state = 2, "finished"
    return g


# --- the reader -----------------------------------------------------------------------------

class GameFlowReader:
    """Reads the score box in a thread of its own, from the scanner's latest
    picture, and keeps the game going (and the finished ones)."""

    def __init__(self, folder=None, on_change=None, meta=None):
        self.folder = folder
        self.on_change = on_change
        self.meta = meta            # () -> {"map", "map_no"} for a game starting now
        self.game = None
        self.shown = None           # a finished game picked to show instead of the latest ("" = the latest)
        self.status = "Waiting for a game"
        self.mode_read = None
        self.raw = (None, None)
        self.version = 0
        self._ocr = None
        self._tried = False
        self._tpl = None
        self._last_present = None
        self._first_absent = None
        self._absent_n = 0
        self._cd_seen = 0
        self._since_cd = 99
        self._n = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._restart = threading.Event()
        self._load()

    # -- files
    def _path(self, *parts):
        return os.path.join(self.folder, *parts) if self.folder else None

    def _load(self):
        p = self._path("current.json")
        if not p or not os.path.exists(p):
            return
        try:
            with open(p, encoding="utf-8") as f:
                self.game = Game.from_dict(json.load(f))
        except Exception as e:   # (a broken file: kept aside, never deleted)
            log(f"Couldn't read the last game flow ({e!r}); it's kept as current.broken.json", "warn")
            try:
                os.replace(p, self._path("current.broken.json"))
            except OSError:
                pass

    def _write(self, path, obj):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        os.replace(tmp, path)

    def _save(self, final=False):
        if not self.folder or not self.game:
            return
        snap = self.game.to_dict()
        try:
            self._write(self._path("current.json"), snap)
            if final and len(self.game.data["times"]) >= 2:
                stamp = time.strftime("%Y-%m-%d %H-%M-%S", time.localtime(self.game.started_at or time.time()))
                self._write(self._path("games", f"{stamp} {self.game.mode}.json"), snap)
                self._prune()
        except OSError as e:
            log(f"Couldn't save the game flow: {e}", "warn")

    def _prune(self):
        folder = self._path("games")
        try:
            files = sorted(n for n in os.listdir(folder) if n.endswith(".json"))
        except OSError:
            return
        for n in files[:-KEEP_GAMES]:
            try:
                os.remove(os.path.join(folder, n))
            except OSError:
                pass

    def games(self):
        """The finished games kept, newest first: [{"id", "mode", "score"}]."""
        folder = self._path("games")
        out = []
        try:
            names = sorted((n for n in os.listdir(folder) if n.endswith(".json")), reverse=True)
        except (OSError, TypeError):
            return out
        for n in names[:KEEP_GAMES]:
            try:
                with open(os.path.join(folder, n), encoding="utf-8") as f:
                    d = json.load(f)
                data = d.get("data") or {}
                out.append({"id": n[:-5], "mode": d.get("mode"),
                            "score": [(data.get("left") or [0])[-1], (data.get("right") or [0])[-1]]})
            except Exception:
                continue
        return out

    def load_game(self, gid):
        p = self._path("games", os.path.basename(str(gid)) + ".json")
        with open(p, encoding="utf-8") as f:
            return Game.from_dict(json.load(f))

    # -- the OCR
    def available(self):
        if not self._tried:
            self._tried = True
            try:
                from .names import WindowsOcr
                self._ocr = WindowsOcr()
            except Exception as e:
                self._ocr = None
                log(f"The game flow's scores can't be read on this PC ({e})", "warn")
        return self._ocr is not None

    # -- control
    def info(self):
        with self._lock:
            g = self.game
            return {"status": self.status, "state": g.state if g else "none", "mode": g.mode if g else None,
                    "mode_read": self.mode_read, "raw": list(self.raw),
                    "score": [g.data["left"][-1], g.data["right"][-1]] if g and g.data["left"] else None,
                    "clock": round(g.clock(time.time()), 1) if g and g.state == "running" else None,
                    "half": g.half if g else None, "readings": len(g.data["times"]) if g else 0,
                    "shown": self.shown or "", "version": self.version}

    def _new(self, mode):
        g = Game(mode)
        try:
            g.meta = dict(self.meta() or {}) if self.meta else {}
        except Exception:
            g.meta = {}
        return g

    def set_meta(self, changes):
        """The map (or which map it is) changed on the Game flow page: the game shown takes it."""
        with self._lock:
            g = self.game
            if self.shown:
                try:
                    g = self.load_game(self.shown)
                except OSError:
                    g = None
                if g:
                    g.meta.update(changes)
                    self._write(self._path("games", os.path.basename(self.shown) + ".json"), g.to_dict())
            elif g:
                g.meta.update(changes)
                self._save(final=g.state == "finished")
        self._changed()

    def _changed(self):
        self.version += 1
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    def start_now(self, mode):
        """The clock starts now (no countdown seen): a new game, or Hijack's second half."""
        with self._lock:
            now = time.time()
            g = self.game
            if g and g.mode == "hijack" and mode == "hijack" and g.state in ("halftime", "running") and (g.half == 2 or g.state == "halftime"):
                if g.state == "running":   # (the second half's clock again)
                    keep = sum(1 for h in g.data["half"] if h == 1)
                    for k in g.data:
                        del g.data[k][keep:]
                    if keep:
                        g.tr.last = [g.data["left"][-1], g.data["right"][-1]]
                g.begin(now, 2)
                log("Game flow: second half started by hand")
            else:
                self._finish_current()
                self.game = self._new(mode)
                self.game.begin(now, 1)
                log(f"Game flow: {MODES.get(mode, mode)} started by hand")
            self.shown = ""
            self._save()
        self._changed()

    def end_now(self):
        with self._lock:
            g = self.game
            if g and g.state in ("running", "halftime"):
                g.bump_final(g.clock(time.time()))
                g.state, g.finished_at = "finished", time.time()
                self._save(final=True)
                log("Game flow: game ended by hand")
        self._changed()

    def clear(self):
        """Back to waiting for the next game (the last one is kept in games/)."""
        with self._lock:
            self._finish_current()
            self.game = None
            self.shown = ""
            self._cd_seen, self._tpl = 0, None
            try:
                if self.folder and os.path.exists(self._path("current.json")):
                    os.remove(self._path("current.json"))
            except OSError:
                pass
        self._changed()

    def show(self, gid):
        with self._lock:
            self.shown = str(gid or "")
        self._changed()

    def _finish_current(self):
        g = self.game
        if g and len(g.data["times"]) >= 2 and g.state != "finished":
            g.state, g.finished_at = "finished", time.time()
            self._save(final=True)

    # -- reading
    def start(self, scanner, config):
        threading.Thread(target=self._run, args=(scanner, config), daemon=True, name="gameflow").start()
        return self

    def stop(self):
        self._stop.set()

    def _run(self, scanner, config):
        wait = READ_EVERY
        while not self._stop.wait(wait):
            wait = READ_EVERY
            cfg = config.get()
            gf = cfg.get("gameflow") or {}
            if not gf.get("enabled", True) or scanner.demo:
                continue
            frame = scanner.frame
            if frame is None:
                continue
            if not self.available():
                self.status = "Text recognition unavailable on this PC: start games by hand"
                continue
            try:
                wait = self.read(frame, gf, time.time())
            except Exception as e:      # (one bad picture mustn't stop it)
                self.status = f"Read error: {e!r}"

    def _boxes(self, gf):
        b = copy.deepcopy(DEFAULT_BOXES)
        for k, v in (gf.get("boxes") or {}).items():
            if k in b and isinstance(v, dict):
                b[k].update({kk: int(vv) for kk, vv in v.items() if kk in ("x", "y", "w", "h")})
        return b

    def _mode(self, frame, gf, boxes):
        """Which mode this game is: set on the Game flow page, or read off the score box."""
        want = gf.get("mode") or "auto"
        if want in MODES:
            return want
        m = mode_of(read_text(frame, boxes["mode"], self._ocr))
        if m is not None:
            self.mode_read = m
        return self.mode_read if self.mode_read in MODES else None

    def read(self, frame, gf, now):
        """One look at the picture. Returns how long until the next."""
        boxes = self._boxes(gf)
        auto = gf.get("auto_start", True)
        with self._lock:
            g = self.game
            # Not tracking yet (or the last game is over): the countdown, or scores going up.
            if g is None or g.state in ("finished", "waiting", "halftime") or g.state == "countdown":
                return self._watch(frame, gf, boxes, now, auto)
            # Running: read the scores.
            l = read_score(frame, boxes["left"], self._ocr)
            r = read_score(frame, boxes["right"], self._ocr)
            self.raw = (l, r)
            before = (g.state, g.half)
            st = g.step(now, l, r)
            self._n += 1
            if st == "reset":
                log("Game flow: the scores went back to 0 - a new game")
                self._save(final=True)
                self.game = None
            elif (g.state, g.half) != before:
                if g.state == "halftime":
                    log(f"Game flow: first half over, {g.tr.last[0]} - {g.tr.last[1]}")
                    self._save()
                elif g.state == "finished":
                    log(f"Game flow: game over, {g.tr.last[0]} - {g.tr.last[1]}")
                    self._save(final=True)
            elif self._n % 10 == 0:
                self._save()
            # (safety net: the next countdown while it seemed still going)
            if self.game is g and g.state == "running" and auto:
                self._since_cd += 1
                if self._since_cd >= 6 and g.clock(now) - (g.half - 1) * HALF_SECONDS > 30:
                    self._since_cd = 0
                    cell = crop(frame, **boxes["countdown"])
                    if is_starting(read_text(frame, boxes["countdown"], self._ocr)):
                        g.bump_final(g.clock(now))
                        if g.mode == "hijack" and g.half == 1:
                            g.state, g.pending_half = "countdown", 2
                        else:
                            g.state, g.finished_at = "finished", now
                            self._save(final=True)
                            self.game = self._new(g.mode)
                            self.game.state = "countdown"
                            g = self.game
                        self._tpl, self._last_present, self._absent_n, self._first_absent = banner_mask(cell), now, 0, None
                        log("Game flow: next countdown seen")
            self.status = self._status()
        self._changed()
        return READ_EVERY

    def _watch(self, frame, gf, boxes, now, auto):
        g = self.game
        cell = crop(frame, **boxes["countdown"])
        if g is not None and g.state == "countdown":
            # timing the banner going: compared with the picture of it (fast)
            if banner_present(cell, self._tpl):
                self._last_present, self._absent_n, self._first_absent = now, 0, None
            else:
                if self._absent_n == 0:
                    self._first_absent = now
                self._absent_n += 1
                if self._absent_n >= 2:
                    if is_starting(read_text(frame, boxes["countdown"], self._ocr)):
                        self._tpl, self._last_present, self._absent_n, self._first_absent = banner_mask(cell), now, 0, None
                    else:
                        start = (self._last_present + self._first_absent) / 2 if self._last_present else self._first_absent
                        g.countdown_gone(start)
                        self._since_cd = 99
                        log(f"Game flow: {MODES[g.mode]} {'second half ' if g.half == 2 else ''}clock started")
                        self._save()
            self.status = self._status()
            self._changed()
            return WATCH_EVERY
        if not auto:
            self.status = "Waiting: start the game by hand" if not g or g.state == "finished" else self._status()
            return READ_EVERY
        seen = is_starting(read_text(frame, boxes["countdown"], self._ocr))
        self._cd_seen = self._cd_seen + 1 if seen else 0
        if self._cd_seen >= 2:
            mode = self._mode(frame, gf, boxes)
            if mode is None:
                self.status = "Countdown seen, but the mode isn't Hardpoint or Hijack: not tracked"
                return READ_EVERY
            self._cd_seen = 0
            if g is not None and g.mode == "hijack" and g.state == "halftime":
                g.state = "countdown"
            else:
                if g is not None and g.state != "finished":
                    self._finish_current()
                self.game = g = self._new(mode)
                self.shown = ""
                g.state = "countdown"
            self._tpl, self._last_present, self._absent_n, self._first_absent = banner_mask(cell), now, 0, None
            log(f"Game flow: {MODES[g.mode]} countdown seen")
            self.status = self._status()
            self._changed()
            return WATCH_EVERY
        # (no countdown: a game joined part way through starts once its scores climb)
        l = read_score(frame, boxes["left"], self._ocr)
        r = read_score(frame, boxes["right"], self._ocr)
        self.raw = (l, r)
        if g is not None and g.state == "halftime":
            g.step(now, l, r)
            if g.state == "running":
                log("Game flow: scores climbing - second half started")
                self._save()
                self._changed()
        elif None not in (l, r):
            if g is None or g.state == "finished":
                mode = self._mode(frame, gf, boxes)
                if mode is not None:
                    # (a finished game's score stays put on screen, so it can't look like one climbing)
                    probe = self._probe if getattr(self, "_probe", None) and self._probe.mode == mode else self._new(mode)
                    probe.step(now, l, r)
                    self._probe = probe
                    if probe.state == "running":
                        log(f"Game flow: {MODES[mode]} scores climbing - recording from {l} - {r}")
                        self.game, self._probe, self.shown = probe, None, ""
                        self._save()
                        self._changed()
        self.status = self._status()
        return READ_EVERY

    def _status(self):
        g = self.game
        if g is None:
            return "Waiting for a Hardpoint or Hijack game (the STARTING IN countdown, or the scores going up)"
        name = MODES[g.mode]
        if g.state == "countdown":
            return f"{name}: countdown on screen - the clock starts when it goes"
        if g.state == "halftime":
            return f"{name}: halftime, {g.tr.last[0]} - {g.tr.last[1]} - waiting for the second half"
        if g.state == "finished":
            return f"{name}: game over, {g.tr.last[0]} - {g.tr.last[1]} (the next game starts on its own)"
        t = g.clock(time.time())
        if g.mode == "hardpoint":
            k = int(t // HILL_SECONDS)
            return f"{name}: hill {k + 1}, {int(t % HILL_SECONDS)} s in - {g.tr.last[0]} - {g.tr.last[1]}"
        left = max(0, g.half * HALF_SECONDS - t)
        drive = " (scoring drive: timer stopped)" if g.drive else ""
        return f"{name}: half {g.half}, {int(left // 60)}:{int(left % 60):02d} left - {g.tr.last[0]} - {g.tr.last[1]}{drive}"
