"""Game Flow: the score over time in Hardpoint and Hijack, for the GFX
Engine's "Game flow" graphic (the score line, points per hill / per half).

Made from the broadcast team's GameFlow_Hardpoint.py / GameFlow_Hijack.py:
the same rules, read off the same places on the CDL caster HUD, but with
Windows' text recognition (no Tesseract to install) and the picture the HUD
already reads.

    * Both teams' scores are read off the score box at the top (twice a
      second). A score only goes up; a misread is dropped (Tracker below).
    * The map's clock starts when the "STARTING IN" countdown banner goes
      away (watched ten times a second once it's seen), or, joining a game
      already going, when the scores start climbing.
    * Hardpoint: a hill every 60 seconds of that clock (P1..P5 or P6 by map);
      the game is over at 250. The graphic shows the score at the end of
      every hill and the points each team took on each hill.
    * Hijack: two 4:00 halves, first to 150, then to 300. A score is a 15
      (a throw) or 30 (a dunk) and then up to 30 points at one a second while
      the game timer stands still: the clock is held for that long. The
      graphic shows the score line with every score, points per half,
      throws, dunks, runoff points and the average per score.
    * The mode is told from the scores (Auto): jumps of 15 or 30 are Hijack,
      a point at a time is Hardpoint. Search & Destroy and Control never
      start a game flow.

Everything about a game is in plain numbers (Tracker), so it can be tested
off recordings without a screen: python -m codhud.gameflow (runs the checks).
"""

import json
import os
import re
import threading
import time

import numpy as np

from .config import WEB_DIR
from .detect import crop
from .log import log

# Where things are on a 1920x1080 picture (the CDL caster HUD), as in the
# broadcast team's scripts: [x, y, w, h].
REGIONS = {"left": [806, 84, 92, 45], "right": [1027, 84, 92, 45],
           "banner": [879, 252, 159, 36]}

HILL_SECONDS = 60
HP_TARGET = 250
HALF_SECONDS = 240
HJ_TARGETS = {1: 150, 2: 300}
READ_MAX = 350
DRIVE_JUMP_MIN = 14       # a rise this big at once is the first part (15 or 30) of a Hijack score
DRIVE_MAX_BONUS = 30      # then up to 30 more points, one a second, the game timer stopped
DRIVE_IDLE = 2.5          # seconds with no new point: the score is done, the timer runs again
GONE_FRAMES = 2           # the leader stuck on target-1 and its number gone: it reached the target
# Hills per Hardpoint map (P1..Pn).
MAPS = {"Lotus": 6, "Lithium": 6, "Munition": 6, "Reactor U92": 5, "Rooftops": 6, "Sentry": 5}
DEFAULT_HILLS = 5
MODES = ("auto", "hardpoint", "hijack", "off")


# --- the numbers -------------------------------------------------------------------

class ScoreFilter:
    """Noisy reads -> a score that only goes up (the scripts' LiveTracker): a
    rise at the normal pace is taken at once, a bigger one (a Hijack score)
    only when read the same twice, anything lower or wild is dropped."""

    def __init__(self, confirm=2):
        self.confirm = confirm
        self.reset(0.0)

    def reset(self, t, start=(0, 0)):
        self.last = [int(start[0]), int(start[1])]
        self.pending = [None, None]
        self.count = [0, 0]
        self.changed_at = [t, t]

    def update(self, t, reads):
        for i, r in enumerate(reads):
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


class Tracker:
    """One map's game flow from (time, left read, right read, banner on
    screen) steps. state: waiting -> countdown -> running (-> halftime ->
    countdown -> running in Hijack) -> final."""

    def __init__(self, mode="auto", hills=None, map_name="", map_no=1):
        self.want = mode if mode in MODES else "auto"
        self.hills = hills or DEFAULT_HILLS
        self.map_name, self.map_no = map_name, map_no
        self.f = ScoreFilter()
        self.new_game()
        self.finished = []        # the last game's summary once it's over (kept until the next one starts)

    # (the game in progress)
    def new_game(self):
        self.mode = self.want if self.want in ("hardpoint", "hijack") else None
        self.state = "waiting"
        self.half = self.pending_half = 1
        self.t0 = 0.0             # wall clock when this half's clock started (minus the earlier half)
        self.paused = 0.0         # Hijack: seconds the game timer stood still this half
        self.drive = None
        self.data = {"times": [], "left": [], "right": [], "half": []}
        self.f.reset(0.0)
        self.prev_cur = (0, 0)
        self.prev_pair, self.climbing, self.reset_run = None, 0, 0
        self.banner_seen, self.banner_gone, self.last_present, self.first_absent = 0, 0, None, None
        self.gone_n, self.gone_t0, self.gone_idx = 0, 0.0, 0
        self.allow_climb = True
        self.started_at = None

    def clock(self, now):
        """The map's clock (seconds) at wall time now: the hill timer / the half's timer."""
        if self.drive:
            return self.drive["t0"]
        return max(0.0, now - self.t0 - self.paused)

    def _begin(self, when, which=1, seed=None):
        self.state, self.half = "running", which
        self.paused, self.drive, self.reset_run = 0.0, None, 0
        if which == 1:
            self.t0 = when
            self.f.reset(0.0, seed or (0, 0))
            self.data = {"times": [0.0], "left": [self.f.last[0]], "right": [self.f.last[1]], "half": [1]}
            self.started_at = time.time()
            self.finished = []
        else:
            self.t0 = when - HALF_SECONDS        # the second half's clock carries on from 240
            self.f.pending, self.f.count = [None, None], [0, 0]
            self.f.changed_at = [float(HALF_SECONDS)] * 2
            self._add(float(HALF_SECONDS), tuple(self.f.last))
        self.prev_cur = tuple(self.f.last)

    def _add(self, t, cur):
        d = self.data
        d["times"].append(round(t, 3)); d["left"].append(cur[0]); d["right"].append(cur[1]); d["half"].append(self.half)

    def _target(self):
        return HP_TARGET if self.mode == "hardpoint" else HJ_TARGETS[self.half] if self.mode == "hijack" else HP_TARGET

    def _decide_mode(self):
        """Auto: Hijack when a score went up by 15 or more at once, Hardpoint
        when one has gone up a point at a time for a while."""
        if self.mode or self.want not in ("auto",):
            return
        L, R = self.data["left"], self.data["right"]
        for s in (L, R):
            if any(b - a >= DRIVE_JUMP_MIN for a, b in zip(s, s[1:])):
                self.mode = "hijack"
                log("Game flow: scores of 15/30: Hijack")
                return
        # (a point a second: 8 in the last 30 s; Search & Destroy's rounds are minutes apart)
        T = self.data["times"]
        recent = [i for i in range(1, len(T)) if T[i] >= T[-1] - 30]
        steps = sum(1 for s in (L, R) for i in recent if 0 < s[i] - s[i - 1] <= 3)
        if steps >= 8:
            self.mode = "hardpoint"
            log("Game flow: scores a point at a time: Hardpoint")

    def step(self, now, left, right, banner):
        """One look at the game: now (wall seconds), the scores read (None when
        unreadable) and whether the STARTING IN banner is on screen (None:
        not looked). Returns True when the summary changed."""
        if self.want == "off":
            return False
        pair = (left, right)
        if self.state in ("waiting", "halftime", "final"):
            if banner:
                self.banner_seen += 1
                if self.banner_seen >= 2:
                    if self.state == "final" or (self.state == "waiting" and self.pending_half == 1):
                        self.pending_half = 1
                    self.state = "countdown"
                    self.banner_gone, self.first_absent, self.last_present = 0, None, now
                    return True
            else:
                self.banner_seen = 0 if banner is False else self.banner_seen
            # Joined a game already going: the scores climbing (3 rises, none down).
            if None not in pair:
                if self.prev_pair is not None:
                    if pair[0] < self.prev_pair[0] or pair[1] < self.prev_pair[1]:
                        self.climbing = 0
                    elif pair != self.prev_pair and max(pair) < READ_MAX:
                        self.climbing += 1
                self.prev_pair = pair
            if self.allow_climb and self.climbing >= 3 and self.state != "final":
                self.prev_pair, self.climbing = None, 0
                if self.state == "halftime":
                    self._begin(now, 2)
                else:
                    self._begin(now, 1, seed=pair)
                    log(f"Game flow: scores climbing, recording from {pair[0]}-{pair[1]}")
                return True
            if self.state == "final" and None not in pair and max(pair) <= 10 and self.prev_pair_low(pair):
                # a new game's scores (low again) without the banner seen
                self.state, self.allow_climb = "waiting", True
            return False

        if self.state == "countdown":
            if banner:
                self.last_present, self.banner_gone, self.first_absent = now, 0, None
            elif banner is False:
                if self.banner_gone == 0:
                    self.first_absent = now
                self.banner_gone += 1
                if self.banner_gone >= 2:
                    start = (self.last_present + self.first_absent) / 2 if self.last_present else self.first_absent
                    if self.pending_half == 2:
                        self._begin(start, 2)
                        log("Game flow: second half started")
                    else:
                        self.new_game()
                        self._begin(start, 1)
                        log("Game flow: countdown over, the clock started")
                    self.allow_climb = True
                    return True
            return False

        # running
        t = self.clock(now)
        if self.mode == "hijack":
            end_t = self.half * HALF_SECONDS
            if t >= end_t + 1.0:
                self._end_half(True)
                return True
        low = left is not None and right is not None and left <= 10 and right <= 10 and max(self.f.last) >= 40
        self.reset_run = self.reset_run + 1 if low else 0
        if self.reset_run >= 6:           # the scores went back to 0: a new game began
            log("Game flow: the scores were reset - a new game")
            self._finish(t)
            self.new_game()
            return True
        cur = self.f.update(t, pair)
        if self.mode == "hijack":
            t = min(t, self.half * HALF_SECONDS)
        changed = cur != self.prev_cur
        self._add(t, cur)
        if self.mode is None:
            self._decide_mode()
        if self.mode == "hijack":
            if self.drive is None:
                for i in (0, 1):
                    if cur[i] - self.prev_cur[i] >= DRIVE_JUMP_MIN:
                        self.drive = {"team": i, "t0": t, "wall0": now, "last_inc": now, "start": self.prev_cur[i]}
                        break
            else:
                i = self.drive["team"]
                if cur[i] > self.prev_cur[i]:
                    self.drive["last_inc"] = now
                if now - self.drive["last_inc"] >= DRIVE_IDLE or cur[i] - self.drive["start"] >= 30 + DRIVE_MAX_BONUS:
                    self.paused += max(0.0, self.drive["last_inc"] - self.drive["wall0"])
                    self.drive = None
        self.prev_cur = tuple(cur)
        goal = self._target()
        lead = 0 if self.f.last[0] >= self.f.last[1] else 1
        if self.f.last[lead] == goal - 1 and pair[lead] is None:
            if self.gone_n == 0:
                self.gone_t0, self.gone_idx = t, len(self.data["times"]) - 1
            self.gone_n += 1
        else:
            self.gone_n = 0
        if self.gone_n >= GONE_FRAMES and self.mode:
            for k in self.data:
                del self.data[k][self.gone_idx:]
            self.f.last[lead] = goal
            self._add(max(self.gone_t0, self.data["times"][-1] if self.data["times"] else 0.0), tuple(self.f.last))
            cur, self.gone_n, changed = tuple(self.f.last), 0, True
        if self.mode and max(cur) >= goal and self.drive is None:
            if self.mode == "hijack":
                self._end_half(False)
            else:
                self._finish(t)
            return True
        return changed

    def prev_pair_low(self, pair):
        return bool(self.data["times"]) and max(self.data["left"][-1], self.data["right"][-1]) >= 40

    def _end_half(self, timer):
        end_t = self.half * HALF_SECONDS
        if timer and self.data["times"] and self.data["times"][-1] < end_t - 0.05:
            self._add(float(end_t), tuple(self.f.last))
        self.drive, self.gone_n = None, 0
        if self.half == 1:
            self.state, self.pending_half, self.allow_climb = "halftime", 2, True
            self.prev_pair, self.climbing, self.banner_seen = tuple(self.f.last), 0, 0
            log(f"Game flow: first half over {self.f.last[0]}-{self.f.last[1]}")
        else:
            self._finish(end_t)

    def _finish(self, t):
        """The game is over (the target, the timer, or the next game began)."""
        if len(self.data["times"]) >= 2 and self.mode:
            self.state = "final"
            self.finished = [self._build("final")]
            log(f"Game flow: {self.mode} over {self.f.last[0]}-{self.f.last[1]}")
        else:
            self.state = "waiting"
        self.pending_half, self.allow_climb, self.drive = 1, False, None
        self.prev_pair, self.climbing, self.banner_seen = None, 0, 0

    # --- what the GFX Engine gets ---------------------------------------------------

    def summary(self):
        """{} before a Hardpoint / Hijack game has started; else the numbers
        the Game flow graphic draws."""
        if self.finished and self.state != "running":
            return dict(self.finished[0], state="final")
        second_half_next = self.state == "countdown" and self.pending_half == 2
        if (self.state not in ("running", "halftime") and not second_half_next) or not self.mode or len(self.data["times"]) < 2:
            return {}
        return self._build("halftime" if self.state in ("halftime", "countdown") else "live")

    def _build(self, state):
        d = self.data
        out = {"mode": self.mode, "map": self.map_name, "map_no": self.map_no, "state": state,
               "score": [d["left"][-1], d["right"][-1]], "clock": round(d["times"][-1], 1)}
        if self.mode == "hardpoint":
            out.update(hardpoint_summary(d, self.hills, final=state == "final"))
        else:
            out.update(hijack_summary(d))
        return out


def value_at(times, vals, t):
    """The score at time t: the read nearest t (within 0.3 s), else the last before it."""
    near = min(range(len(times)), key=lambda i: abs(times[i] - t))
    if abs(times[near] - t) <= 0.3:
        return vals[near]
    before = [i for i, x in enumerate(times) if x <= t]
    return vals[before[-1]] if before else vals[0]


def hardpoint_summary(d, hills, final=False):
    """The score at the end of every hill (marks: [[l, r], ...], from 0-0),
    each hill's label (P1..Pn, round and round) and the points each team took
    on each hill of the rotation (per_hill: [[l, r], ...] for P1..Pn)."""
    times, L, R = d["times"], d["left"], d["right"]
    n = max(1, int(np.ceil((times[-1] - 1.0) / HILL_SECONDS)))   # (a second into a hill is still the one before)
    marks = [[L[0] if L else 0, R[0] if R else 0]]
    for k in range(1, n + 1):
        if k == n:
            marks.append([L[-1], R[-1]])
        else:
            t = k * HILL_SECONDS
            marks.append([value_at(times, L, t), value_at(times, R, t)])
    per = [[0, 0] for _ in range(hills)]
    for k in range(1, len(marks)):
        for s in (0, 1):
            per[(k - 1) % hills][s] += min(HILL_SECONDS, max(0, marks[k][s] - marks[k - 1][s]))
    labels = [f"P{(k % hills) + 1}" for k in range(len(marks) - 1)]
    # (the hill being played now isn't over: marked so the graphic can say so)
    return {"hills": hills, "marks": marks, "labels": labels, "per_hill": per,
            "hill_now": None if final else labels[-1] if labels else "P1"}


def find_drives(times, left, right, halves):
    """Hijack scores: a 15 or 30 and the runoff after it, all at one moment of
    the game clock -> [{team, half, t, y0, y1, total, chunk, bonus}]."""
    n, out = len(times), []
    for team, ser in ((0, left), (1, right)):
        j = 1
        while j < n:
            gain = ser[j] - ser[j - 1]
            if gain >= DRIVE_JUMP_MIN and halves[j] == halves[j - 1]:
                t0, k = times[j], j
                while k + 1 < n and halves[k + 1] == halves[j]:
                    step = ser[k + 1] - ser[k]
                    if not (abs(times[k + 1] - t0) <= 0.011 or (0 < step <= 3 and times[k + 1] - times[k] <= 1.6)):
                        break
                    k += 1
                total = ser[k] - ser[j - 1]
                chunk = 30 if gain >= 22 else 15
                out.append({"team": team, "half": halves[j], "t": t0, "y0": ser[j - 1], "y1": ser[k],
                            "total": total, "chunk": chunk, "bonus": max(0, total - chunk)})
                j = k + 1
            else:
                j += 1
    out.sort(key=lambda x: x["t"])
    return out


def hijack_summary(d):
    times, L, R, H = d["times"], d["left"], d["right"], d["half"]
    drives = find_drives(times, L, R, H)
    halves, prev = [], (0, 0)
    for h in (1, 2):
        idx = [i for i, x in enumerate(H) if x == h]
        if not idx:
            halves.append(None)
            continue
        end = (L[idx[-1]], R[idx[-1]])
        halves.append([end[0] - prev[0], end[1] - prev[1]])
        prev = end
    stats = []
    for team in (0, 1):
        mine = [x for x in drives if x["team"] == team]
        pts = sum(x["total"] for x in mine)
        stats.append({"throws": sum(1 for x in mine if x["chunk"] == 15), "dunks": sum(1 for x in mine if x["chunk"] == 30),
                      "runoff": sum(x["bonus"] for x in mine), "avg": round(pts / len(mine), 1) if mine else None})
    # The line: only where the score changed (each score's first and last read), and each half's ends.
    # (and the read just before each change, so a flat stretch stays flat up to the score)
    line, n = [], len(times)
    for i, (t, l, r, h) in enumerate(zip(times, L, R, H)):
        edge = i == 0 or i == n - 1 or H[i - 1] != h or H[i + 1] != h
        moved = i > 0 and (L[i - 1], R[i - 1]) != (l, r)
        moves = i + 1 < n and (L[i + 1], R[i + 1]) != (l, r)
        if edge or moved or moves:
            line.append([round(t, 2), l, r, h])
    # (a score's runoff is all at one moment: only its first and last point)
    line = [p for i, p in enumerate(line)
            if not (0 < i < len(line) - 1 and line[i - 1][0] == p[0] == line[i + 1][0] and line[i - 1][3] == p[3] == line[i + 1][3])]
    return {"line": line, "drives": [{k: x[k] for k in ("team", "half", "t", "y0", "y1", "total", "chunk", "bonus")} for x in drives],
            "halves": halves, "stats": stats, "half": H[-1] if H else 1}


# --- reading the picture -------------------------------------------------------------

_LOOKALIKE = str.maketrans({"l": "1", "I": "1", "|": "1", "i": "1", "O": "0", "o": "0", "D": "0", "S": "5", "s": "5",
                            "B": "8", "Z": "2", "z": "2", "g": "9", "q": "9"})


def score_ink(cell, scale=3):
    """The score's digits (white on the dark score box) as black on white,
    trimmed to the digits with a margin, enlarged: what Windows reads best.
    None when there's nothing bright there (the score box isn't up)."""
    from PIL import Image
    g = cell.astype(np.int16).max(axis=-1)
    on = g >= 170
    if on.sum() < 25:
        return None
    ys, xs = np.where(on)
    box = on[max(0, ys.min() - 2):ys.max() + 3, max(0, xs.min() - 2):xs.max() + 3]
    img = Image.fromarray(np.where(box, 0, 255).astype(np.uint8), "L")
    pad = max(10, img.height // 2)
    out = Image.new("L", (img.width + 2 * pad, img.height + 2 * pad), 255)
    out.paste(img, (pad, pad))
    return out.resize((out.width * scale, out.height * scale), Image.LANCZOS)


def _digits(words):
    text = "".join(t for t, _, _ in sorted(words, key=lambda w: w[1]))
    text = re.sub(r"\D", "", text.translate(_LOOKALIKE))
    return text


GLYPH_W, GLYPH_H = 12, 20
# (the digits of a real CDL screenshot, to start with: 1 5 6 8 9)
DIGITS_FILE = os.path.join(WEB_DIR, "assets", "gameflow-digits.json")


def glyphs(cell):
    """The score's digits, left to right, each as a GLYPH_W x GLYPH_H mask."""
    on = cell.astype(np.int16).max(axis=-1) >= 170
    cols = on.any(axis=0)
    out, x = [], 0
    while x < len(cols):
        if cols[x]:
            x0 = x
            while x < len(cols) and cols[x]:
                x += 1
            part = on[:, x0:x]
            ys = np.where(part.any(axis=1))[0]
            if x - x0 >= 2 and len(ys) >= on.shape[0] * 0.3:      # (not a speck)
                part = part[ys[0]:ys[-1] + 1]
                h, w = part.shape
                # (a thin glyph - a 1 - keeps its thinness: placed in a box as wide as it is tall x 0.6)
                box = np.zeros((h, max(w, int(h * 0.6))), bool)
                box[:, (box.shape[1] - w) // 2:(box.shape[1] - w) // 2 + w] = part
                yi = (np.arange(GLYPH_H) * box.shape[0] / GLYPH_H).astype(int)
                xi = (np.arange(GLYPH_W) * box.shape[1] / GLYPH_W).astype(int)
                out.append(box[yi][:, xi])
        x += 1
    return out


class DigitBook:
    """The score box's digits as seen: learnt from every number Windows reads
    (and a few from a real CDL screenshot to start with), so a lone digit,
    which text recognition often can't read, is still known."""

    def __init__(self, path=None):
        self.path = path
        self.book = {}
        for f in (DIGITS_FILE, path):
            try:
                with open(f, encoding="utf-8") as fh:
                    for d, masks in json.load(fh).items():
                        for m in masks:
                            self._add(d, np.array([c == "1" for c in m], bool).reshape(GLYPH_H, GLYPH_W))
            except (OSError, ValueError, TypeError):
                pass
        self._dirty = False

    def _add(self, d, mask):
        have = self.book.setdefault(d, [])
        if any(_iou(mask, m) > 0.92 for m in have):
            return False
        have.append(mask)
        del have[:-4]
        return True

    def learn(self, text, gl):
        if len(text) == len(gl) and text.isdigit():
            for d, m in zip(text, gl):
                self._dirty |= self._add(d, m)

    def read(self, gl):
        out = ""
        for g in gl:
            scores = sorted(((max(_iou(g, m) for m in ms), d) for d, ms in self.book.items() if ms), reverse=True)
            if not scores or scores[0][0] < 0.8 or (len(scores) > 1 and scores[0][0] - scores[1][0] < 0.06):
                return ""
            out += scores[0][1]
        return out

    def save(self):
        if not (self.path and self._dirty):
            return
        data = {d: ["".join("1" if v else "0" for v in m.ravel()) for m in ms] for d, ms in self.book.items()}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, self.path)
        self._dirty = False


def _iou(a, b):
    return float((a & b).sum()) / max(1.0, float((a | b).sum()))


_BOOK = None


def read_score(cell, ocr, cache=None, key=None, book=None):
    """A score (an int) off its cell of the score box, or None."""
    global _BOOK
    img = score_ink(cell)
    if img is None:
        return None
    if cache is not None:
        sig = np.asarray(img.resize((48, 24))).tobytes()
        hit = cache.get(key)
        if hit and hit[0] == sig:
            return hit[1]
    if book is None:
        _BOOK = _BOOK or DigitBook()
        book = _BOOK
    gl = glyphs(cell)
    text = _digits(ocr.words(img))
    if text:
        book.learn(text, gl)
    else:
        # A lone digit is the hardest thing for text recognition: the digits seen before,
        # else read it twice side by side ("77").
        text = book.read(gl)
        if not text:
            from PIL import Image
            two = Image.new("L", (img.width * 2, img.height), 255)
            two.paste(img, (0, 0)); two.paste(img, (img.width - img.width // 6, 0))
            t2 = _digits(ocr.words(two))
            text = t2[:len(t2) // 2] if len(t2) % 2 == 0 and t2 and t2[:len(t2) // 2] == t2[len(t2) // 2:] else ""
    value = int(text) if text and len(text) <= 3 and int(text) <= READ_MAX else None
    if cache is not None and value is not None:
        cache[key] = (sig, value)
    return value


def banner_mask(cell):
    """The banner's letters (bright) as a mask, for telling quickly whether it's still there."""
    g = cell.astype(np.int16).max(axis=-1)
    return g >= 170


def banner_still(cell, mask):
    m = banner_mask(cell)
    hit = float((m & mask).sum())
    return hit / max(1.0, float(mask.sum())) >= 0.6 and hit / max(1.0, float(m.sum())) >= 0.4


def says_starting(cell, ocr):
    """Does this read STARTING IN?"""
    from .names import ink
    import difflib
    words = ocr.words(ink(cell))
    letters = re.sub(r"[^A-Z]", "", " ".join(t for t, _, _ in words).upper())
    return "STARTING" in letters or difflib.SequenceMatcher(None, letters, "STARTINGIN").ratio() >= 0.75


def _box(cfg, name):
    r = (cfg.get("regions") or {}).get(name) or REGIONS[name]
    return [int(v) for v in r]


class GameFlowReader:
    """Reads the scores and the countdown banner off the scanner's picture
    and keeps the Tracker; the summary goes to the GFX Engine."""

    def __init__(self, on_change=None):
        self.on_change = on_change
        self.tracker = Tracker()
        self.status = "Waiting for a Hardpoint or Hijack game"
        self.reads = (None, None)
        self.version = 0
        self._cache = {}
        self._tpl = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._settings = None
        self._next_banner = 0.0
        try:
            from .config import DATA_DIR
            self.book = DigitBook(os.path.join(DATA_DIR, "gameflow-digits.json"))
        except Exception:
            self.book = DigitBook()
        self._saved_at = time.time()

    def info(self):
        with self._lock:
            t = self.tracker
            return {"status": self.status, "state": t.state, "mode": t.mode or "", "want": t.want,
                    "reads": list(self.reads), "score": list(t.f.last), "map": t.map_name, "map_no": t.map_no,
                    "hills": t.hills, "half": t.half, "clock": round(t.clock(time.time()), 1) if t.state == "running" else None,
                    "summary": self.summary()}

    def summary(self):
        return self.tracker.summary()

    def start(self, scanner, config, series_no=None):
        self.series_no = series_no
        threading.Thread(target=self._run, args=(scanner, config), daemon=True, name="gameflow").start()
        return self

    def stop(self):
        self._stop.set()

    def configure(self, cfg, map_no=None):
        """The Game flow settings (mode, map) into the tracker, when they change."""
        g = cfg.get("gameflow") or {}
        key = (g.get("mode"), g.get("map"))
        with self._lock:
            t = self.tracker
            if key != self._settings:
                self._settings = key
                t.want = g.get("mode") if g.get("mode") in MODES else "auto"
                if t.want in ("hardpoint", "hijack") and t.state != "final":
                    t.mode = t.want
                t.map_name = g.get("map") or ""
                t.hills = MAPS.get(t.map_name, DEFAULT_HILLS)
            if map_no and t.state in ("waiting", "countdown"):
                t.map_no = map_no

    def clear(self):
        with self._lock:
            self.tracker.new_game()
            self.tracker.finished = []
            self.status = "Cleared: waiting for a Hardpoint or Hijack game"
            self.version += 1
        log("Game flow cleared")

    def start_now(self):
        """The Control page's "Start clock now": the map (or Hijack's second half) starts now."""
        with self._lock:
            t = self.tracker
            if t.state in ("halftime",) or (t.state == "countdown" and t.pending_half == 2):
                t._begin(time.time(), 2)
            else:
                t.new_game()
                t._begin(time.time(), 1)
            self.version += 1
        log("Game flow: clock started by hand")

    def _run(self, scanner, config):
        from .names import NameReader  # noqa: F401  (the OCR lives on the scanner's name reader)
        while not self._stop.is_set():
            t = self.tracker
            fast = t.state == "countdown"
            self._stop.wait(0.1 if fast else 0.5)
            cfg = config.get()
            try:
                self.configure(cfg, self.series_no() if self.series_no else None)
                if t.want == "off":
                    self.status = "Off"
                    continue
                names = scanner.names
                ocr = names._ocr if names.available() else None
                frame = scanner.frame
                if frame is None:
                    continue
                if ocr is None:
                    self.status = "Needs Windows text recognition to read the score"
                    continue
                self.look(frame, scanner.hub.state.get("hud"), ocr, cfg.get("gameflow") or {})
            except Exception as e:     # (keep going: the next picture may read)
                self.status = f"Read error: {e!r}"

    def look(self, frame, hud, ocr, g, now=None):
        now = time.time() if now is None else now
        t = self.tracker
        if hud in ("on", "score"):
            reads = tuple(read_score(crop(frame, *_box(g, s)), ocr, self._cache, s, self.book) for s in ("left", "right"))
            if now - self._saved_at > 30:       # (the digits learnt, kept for the next start)
                self._saved_at = now
                try:
                    self.book.save()
                except OSError:
                    pass
        else:
            reads = (None, None)
        banner = None
        cell = crop(frame, *_box(g, "banner"))
        if t.state == "countdown" and self._tpl is not None:
            banner = banner_still(cell, self._tpl)
            if not banner and says_starting(cell, ocr):     # (the quick look was fooled)
                self._tpl, banner = banner_mask(cell), True
        elif t.state != "running" or now >= self._next_banner:
            # (while a game runs: a look now and then, for a countdown missed)
            banner = says_starting(cell, ocr)
            if banner:
                self._tpl = banner_mask(cell)
            if t.state == "running":
                self._next_banner = now + 1.5
        if t.state == "running" and banner and t.clock(now) > 30:
            # The next countdown came up with this game still going: that game is over.
            with self._lock:
                if t.mode == "hijack" and t.half == 1:
                    t._end_half(False)
                else:
                    t._finish(t.clock(now))
        with self._lock:
            self.reads = reads
            changed = t.step(now, reads[0], reads[1], banner if t.state != "running" else None)
            self.status = self._describe()
            if changed:
                self.version += 1
        if changed and self.on_change:
            self.on_change()

    def _describe(self):
        t = self.tracker
        mode = {"hardpoint": "Hardpoint", "hijack": "Hijack"}.get(t.mode, "")
        s = t.f.last
        if t.state == "running":
            c = t.clock(time.time())
            if t.mode == "hijack":
                left = max(0, t.half * HALF_SECONDS - c)
                return f"Hijack half {t.half}: {s[0]} - {s[1]}, {int(left // 60)}:{int(left % 60):02d} left"
            if t.mode == "hardpoint":
                return f"Hardpoint: {s[0]} - {s[1]}, hill P{int(c // HILL_SECONDS) % t.hills + 1}"
            return f"Recording: {s[0]} - {s[1]} (telling the mode from the scores)"
        if t.state == "countdown":
            return "Countdown on screen: the clock starts when it goes"
        if t.state == "halftime":
            return f"Hijack halftime: {s[0]} - {s[1]}"
        if t.state == "final":
            return f"{mode} over: {s[0]} - {s[1]} (on the GFX Engine's Game flow)"
        return "Waiting for a Hardpoint or Hijack game (the STARTING IN countdown, or the scores climbing)"


# --- checks ---------------------------------------------------------------------------

def simulate_hardpoint(final=(153, 250), hills=5, seed=1):
    """A made-up Hardpoint game as reads twice a second: (wall, left, right, banner)."""
    import random
    rnd = random.Random(seed)
    steps, t, s = [], 1000.0, [0, 0]
    for _ in range(6):
        steps.append((t, None, None, True)); t += 0.1
    steps.append((t, None, None, False)); t += 0.1
    steps.append((t, None, None, False))
    start = t - 0.05
    while max(s) < 250:
        t += 0.5
        clock = t - start
        if int(clock * 2) % 2 == 0:
            hill = int(clock // 60)
            owner = 1 if (hill % 3) else 0
            if rnd.random() < 0.85:
                s[owner] = min(250, s[owner] + 1)
        steps.append((t, s[0] if rnd.random() > 0.05 else None, s[1] if s[1] < 250 else None, None))
    for _ in range(4):      # (the winning number vanishes as the game ends)
        t += 0.5
        steps.append((t, s[0], None, None))
    return steps


def simulate_hijack(seed=3, stop_at_half=False):
    """A made-up Hijack game: scores of 15 or 30 and their runoff at one a second."""
    import random
    rnd = random.Random(seed)
    steps, t, s = [], 1000.0, [0, 0]

    def countdown():
        nonlocal t
        for _ in range(4):
            steps.append((t, None, None, True)); t += 0.1
        steps.append((t, None, None, False)); t += 0.1
        steps.append((t, None, None, False))
    countdown()
    for half, goal in ((1, 150), (2, 300)):
        clock = 0.0
        while clock < HALF_SECONDS and max(s) < goal:
            t += 0.5; clock += 0.5
            if rnd.random() < 0.025:
                team = 0 if rnd.random() < 0.45 else 1
                s[team] += 30 if rnd.random() < 0.35 else 15
                steps.append((t, s[0], s[1], None)); t += 0.5; steps.append((t, s[0], s[1], None))
                for _ in range(rnd.randint(0, 30)):
                    t += 1.0; s[team] += 1; steps.append((t, s[0], s[1], None))
                t += 3.0
            steps.append((t, s[0], s[1], None))
        if half == 1:
            if stop_at_half:
                return steps
            for _ in range(10):
                t += 1; steps.append((t, s[0], s[1], False))
            countdown()
    for _ in range(4):
        t += 1.5; steps.append((t, s[0], s[1], None))
    return steps


def _fixture_cells():
    """Score box cells made from the CDL screenshot in the tests (58 and 196,
    and numbers put together from those digits): (expected, cell)."""
    from PIL import Image
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pic = np.asarray(Image.open(os.path.join(here, "tests", "fixtures", "cdl-top.png")).convert("RGB"))
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[:pic.shape[0], :min(1920, pic.shape[1])] = pic[:, :1920]
    left, right = crop(frame, *REGIONS["left"]), crop(frame, *REGIONS["right"])
    out = [(58, left), (196, right)]
    # each digit's columns
    glyphs = {}
    for text, cell in (("58", left), ("196", right)):
        lit = (cell.max(axis=-1) >= 170).any(axis=0)
        runs, x = [], 0
        while x < len(lit):
            if lit[x]:
                x0 = x
                while x < len(lit) and lit[x]:
                    x += 1
                if x - x0 >= 3:
                    runs.append((x0, x))
            x += 1
        for ch, (a, b) in zip(text, runs):
            glyphs[ch] = cell[:, max(0, a - 1):b + 1]
    bg = left[2:6, 2:6].reshape(-1, 3).mean(axis=0).astype(np.uint8)
    for number in ("5", "8", "1", "9", "6", "15", "86", "99", "158", "169", "61", "1"):
        parts = [glyphs[c] for c in number]
        gap = 4
        w = sum(p.shape[1] for p in parts) + gap * (len(parts) - 1)
        cell = np.empty_like(left); cell[:] = bg
        x = max(2, (cell.shape[1] - w) // 2)
        for p in parts:
            cell[:, x:x + p.shape[1]] = p
            x += p.shape[1] + gap
        out.append((int(number), cell))
    return out


def ocr_check():
    """Reads the score cells with Windows' text recognition: python -m codhud.gameflow --ocr-check"""
    from .names import WindowsOcr
    ocr = WindowsOcr()
    good = 0
    cells = _fixture_cells()
    for expect, cell in cells:
        t0 = time.perf_counter()
        got = read_score(cell, ocr)
        ms = (time.perf_counter() - t0) * 1000
        good += got == expect
        print(f"  {expect:>4} -> {got!s:>5}  {'ok' if got == expect else 'WRONG'}  ({ms:.0f} ms)")
    print(f"{good}/{len(cells)} read right")
    return good == len(cells)


if __name__ == "__main__":
    import sys
    if "--ocr-check" in sys.argv:
        sys.exit(0 if ocr_check() else 1)
    tr = Tracker(hills=5, map_name="Reactor U92")
    for st in simulate_hardpoint():
        tr.step(*st)
    print(json.dumps(tr.summary())[:600])
