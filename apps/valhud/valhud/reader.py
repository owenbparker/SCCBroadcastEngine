"""Reads the match off the VALORANT spectator screen.

VALORANT gives other programs no live match data, so this captures the game
window a couple of times a second and reads what the spectator view shows:

  - the top bar (always on screen): each player's agent, health bar (none
    when dead), who carries the spike, the score, the round timer and the
    planted spike;
  - the Tab scoreboard, whenever it's open (e.g. the buy phase): names, ult
    points, kills / deaths / assists, weapon, shield and credits.
  - agent select, when that's on screen instead: the map and each player's
    agent, hovered or locked (see selectreader.py).

Agents and weapons are recognised by comparing against the HUD's own agent
and weapon images; text is read with Windows' built-in text recognition.
Everything is measured on a 1920x1080 frame and scaled with the window's
height, centred (the spectator HUD is laid out that way).

    python -m valhud.reader SCREENSHOT.png      read a saved screenshot
"""

import asyncio
import os
import re
import sys
import threading
import time

from . import game
from .config import WEB_DIR
from .log import log, log_once

REF_H = 1080
# Top bar: centre of each player's portrait / health bar, left team then right.
TOP_X = {"left": [466, 532, 598, 664, 730], "right": [1191, 1257, 1323, 1389, 1455]}
BAR_Y = (76, 82)            # the white health bar under each portrait
BAR_HALF = 20               # bar is 40px wide
PORTRAIT_Y, PORTRAIT_SIZE = 30, 40
CARRIER_Y = (90, 124)       # the spike icon under the carrier's portrait
SCORE_LINE = (790, 24, 1130, 72)   # "0   0:24   0" (read for the timer)
SCORE_BOX = {"left": (800, 28, 846, 72), "right": (1074, 28, 1120, 72)}
SPIKE_ICON = (930, 24, 990, 70)    # replaces the timer once planted
# Tab scoreboard: row tops (34px rows), left team's block then right's.
ROW_TOP = {"left": 338, "right": 569}
ROW_H = 34
# The Tab scoreboard's layouts: a 5v5's two blocks of five rows, and a 2v2's
# one block of four (left team's two on top), centred on the same line. The
# top bar fills from the score outwards, so a 2v2's players sit in the left
# team's seats 4 and 5 and the right team's 1 and 2 (see game.SEATS_2V2).
BOARDS = {5: {"top": ROW_TOP, "rows": 5, "seats": {"left": [1, 2, 3, 4, 5], "right": [1, 2, 3, 4, 5]}},
          2: {"top": {"left": 471, "right": 539}, "rows": 2, "seats": {"left": [4, 5], "right": [1, 2]}}}
COLS = {"portrait": (573, 607), "name": (634, 812), "ult": (812, 933),
        "ult_have": (812, 867), "ult_need": (879, 933),  # either side of the "/"
        "k": (934, 973), "d": (974, 1013),
        "a": (1014, 1053), "weapon": (1060, 1168), "shield": (1170, 1204), "creds": (1204, 1294)}
WINDOW_TITLE = "VALORANT"


# --- geometry ---------------------------------------------------------------

class Frame:
    """A captured frame and the mapping from 1920x1080 coordinates to it."""

    def __init__(self, image):
        # A capture of just the top of the window says how tall the whole was.
        info = image.info if hasattr(image, "info") else {}
        full = info.get("full_height", image.height)
        self.image = image if getattr(image, "mode", "") == "RGB" else image.convert("RGB")   # (read only: no copy)
        # The game's picture inside black bars (a 16:10 or 4:3 screen showing
        # 16:9): the layout is found inside them.
        self.top, bottom = (0, 0) if "full_height" in info else letterbox(self.image)
        full -= self.top + bottom
        self.k = full / REF_H
        self.cx = self.image.width / 2

    def x(self, x):
        return round(self.cx + (x - 960) * self.k)

    def y(self, y):
        return round(self.top + y * self.k)

    def crop(self, x0, y0, x1, y1, size=None):
        """A region given in 1080p coordinates, resized back to 1080p scale
        (or to size) so the measurements below hold at any resolution."""
        from PIL import Image
        img = self.image.crop((self.x(x0), self.y(y0), self.x(x1), self.y(y1)))
        target = size or (x1 - x0, y1 - y0)
        return img if img.size == target else img.resize(target, Image.BILINEAR)


def _np():
    import numpy
    return numpy


def letterbox(image):
    """(top, bottom): the black bars above and below a 16:9 picture on a
    taller screen (16:10, 4:3), in pixels; (0, 0) for none. The bars are
    where a 16:9 picture would leave them, and must be black there (a dark
    scene can make the black run further, never shorter)."""
    np = _np()
    w, h = image.size
    inner = round(w * 9 / 16)
    if h - inner < max(8, h * 0.02):
        return 0, 0
    top = (h - inner) // 2
    bottom = h - inner - top
    step = max(1, w // 240)
    g = np.asarray(image.convert("L"))[:, ::step]
    if (g[:max(1, top - 1)] <= 8).all() and (g[h - max(1, bottom - 1):] <= 8).all():
        return top, bottom
    return 0, 0


# --- agents and weapons -----------------------------------------------------

_icons, _weapons = {}, {}


def _agent_icon(agent, size):
    np = _np()
    from PIL import Image
    key = (agent, size)
    if key not in _icons:
        path = os.path.join(WEB_DIR, "hud", "Resources", "Agentes", agent, agent + ".png")
        t = np.asarray(Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS), dtype=np.float32)
        _icons[key] = (t[..., :3], t[..., 3] > 128)
    return _icons[key]


def _ncc(a, b):
    np = _np()
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d else 0.0


# Real spectator portraits for agents whose HUD art looks too unlike them
# (web/reader_refs/<Agent>-top*.png for the top bar, -row*.png for the
# scoreboard): cut from real frames, a few pixels inside the portrait.
REFS_DIR = os.path.join(WEB_DIR, "reader_refs")
_refs = {}


def _agent_refs(agent, kind):
    np = _np()
    from PIL import Image
    key = (agent, kind)
    if key not in _refs:
        _refs[key] = []
        if kind and os.path.isdir(REFS_DIR):
            for name in sorted(os.listdir(REFS_DIR)):
                if name.lower().startswith(f"{agent}-{kind}".lower()) and name.endswith(".png"):
                    img = Image.open(os.path.join(REFS_DIR, name)).convert("RGB")
                    _refs[key].append(np.asarray(img, dtype=np.float32))
    return _refs[key]


def templates(rgb, mask):
    """Templates for ncc_many: rgb (A, n, 3), mask (A, n) (1 where a pixel
    counts). Worked out once and kept."""
    np = _np()
    mask = np.asarray(mask, dtype=np.float64)
    tm = np.asarray(rgb, dtype=np.float64) * mask[..., None]
    return mask, tm.reshape(len(tm), -1), tm.sum(axis=2), (tm * tm).sum(axis=2)


def windows(win, inside):
    """Windows for ncc_many, worked out once: win (O, n, 3) (0 where outside
    the picture), inside (O, n) (1 where a window's pixel is in it)."""
    np = _np()
    win = np.ascontiguousarray(win, dtype=np.float64)
    O = win.shape[0]
    flat = win.reshape(O, -1)
    three = np.ones(3)
    return (flat, np.asarray(inside, dtype=np.float64), (win.reshape(-1, 3) @ three).reshape(O, -1),
            ((flat * flat).reshape(-1, 3) @ three).reshape(O, -1))


def ncc_many(win, inside, bank, prepared=None):
    """Normalised cross-correlation of every window against every template,
    each over the pixels both cover (the same number _ncc gives for each
    pair, all at once: a few matrix products instead of thousands of small
    numpy calls, which held the whole app up).

    win, inside: see windows() (or prepared=windows(win, inside), to compare
    the same windows with several banks); bank: templates(). Returns ((A, O)
    scores, (A, O) pixels compared)."""
    np = _np()
    mask, tflat, tsum, tsq = bank
    flat, inside, wsum, wsq = prepared or windows(win, inside)
    count = mask @ inside.T                       # pixels compared
    n = 3 * count                                 # values compared (3 a pixel)
    sa = mask @ wsum.T                            # the windows' side
    saa = mask @ wsq.T
    sb = tsum @ inside.T                          # the templates' side
    sbb = tsq @ inside.T
    sab = tflat @ flat.T
    with np.errstate(divide="ignore", invalid="ignore"):
        safe = np.maximum(n, 1)
        va = saa - sa * sa / safe
        vb = sbb - sb * sb / safe
        cov = sab - sa * sb / safe
        d = np.sqrt(np.maximum(va, 0) * np.maximum(vb, 0))
        ok = (n > 0) & (va > 1e-9 * np.maximum(saa, 1)) & (vb > 1e-9 * np.maximum(sbb, 1))
        out = np.where(ok, cov / np.where(ok, d, 1), 0.0)
    return out, count


_icon_banks = {}


def _icon_bank(agents, s):
    """templates() of these agents' icons at size s."""
    np = _np()
    key = (tuple(agents), s)
    bank = _icon_banks.get(key)
    if bank is None:
        icons = [_agent_icon(a, s) for a in agents]
        bank = templates(np.stack([rgb.reshape(-1, 3) for rgb, _ in icons]),
                         np.stack([m.reshape(-1) for _, m in icons]))
        if len(_icon_banks) > 64:
            _icon_banks.clear()
        _icon_banks[key] = bank
    return bank


_ref_banks = {}


def _ref_bank(ref):
    np = _np()
    bank = _ref_banks.get(id(ref))
    if bank is None:
        h, w = ref.shape[:2]
        bank = _ref_banks[id(ref)] = templates(ref.reshape(1, -1, 3), np.ones((1, h * w)))
    return bank


def identify_agent(crop, sizes, slack=3, agents=None, kind=None):
    """[(score, agent), ...] best first, for a portrait crop whose top-left is
    roughly where the icon starts (within `slack` px). kind ("top"/"row")
    also compares against real portraits from web/reader_refs."""
    np = _np()
    slide = np.lib.stride_tricks.sliding_window_view
    c = np.asarray(crop, dtype=np.float64)
    if c.ndim == 2:
        c = np.repeat(c[..., None], 3, axis=2)
    c = c[..., :3]
    H, W = c.shape[:2]
    agents = list(agents or game.AGENTS)
    best = np.full(len(agents), -1.0)
    for i, agent in enumerate(agents):
        for ref in _agent_refs(agent, kind):
            h, w = ref.shape[:2]
            if H < h or W < w:
                continue
            v = slide(c, (h, w, 3))[:, :, 0].reshape(-1, h * w, 3)
            score, _ = ncc_many(v, np.ones(v.shape[:2]), _ref_bank(ref))
            best[i] = max(best[i], float(score.max()))
    for s in sizes:
        # The crop padded with nothing round it, so a window can hang off its
        # edges (only the pixels on the crop count, as before).
        pad = slack + s
        padded = np.zeros((H + 2 * pad, W + 2 * pad, 3))
        padded[pad:pad + H, pad:pad + W] = c
        on = np.zeros((H + 2 * pad, W + 2 * pad))
        on[pad:pad + H, pad:pad + W] = 1
        lo, hi = pad - slack, pad + slack + 1
        v = slide(padded, (s, s, 3))[lo:hi, lo:hi, 0].reshape(-1, s * s, 3)
        inside = slide(on, (s, s))[lo:hi, lo:hi].reshape(-1, s * s)
        # (offsets whose overlap with the crop is under 10 px a side don't count)
        span = [min(H, d + s) - max(0, d) for d in range(-slack, slack + 1)]
        spanx = [min(W, d + s) - max(0, d) for d in range(-slack, slack + 1)]
        wide = np.array([[sy >= 10 and sx >= 10 for sx in spanx] for sy in span]).reshape(-1)
        score, count = ncc_many(v, inside, _icon_bank(agents, s))
        score = np.where(wide[None, :] & (count >= 120), score, -np.inf)
        best = np.maximum(best, score.max(axis=1))
    out = [(round(float(b), 3), agent) for b, agent in zip(best, agents)]
    out.sort(reverse=True)
    return out


def clear_match(best):
    """A good match, or a fair one well ahead of the next agent."""
    (top, _), (second, _) = best[0], best[1] if len(best) > 1 else (-1.0, None)
    return (top >= 0.6 and top - second >= 0.05) or (top >= 0.5 and top - second >= 0.15)


def _silhouette(mask, size=(72, 24)):
    np = _np()
    from PIL import Image
    ys, xs = np.nonzero(mask)
    if len(xs) < 20:
        return None
    m = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    img = Image.fromarray((m * 255).astype("uint8"))
    w, h = img.size
    k = min(size[0] / w, size[1] / h)
    img = img.resize((max(1, round(w * k)), max(1, round(h * k))), Image.BILINEAR)
    out = Image.new("L", size, 0)
    out.paste(img, ((size[0] - img.width) // 2, (size[1] - img.height) // 2))
    return np.asarray(out, dtype=np.float32) / 255, w / h


def identify_weapon(crop):
    """(weapon, score) from the white weapon icon in a scoreboard cell."""
    np = _np()
    from PIL import Image
    if not _weapons:
        folder = os.path.join(WEB_DIR, "hud", "Resources", "Armas")
        for name in game.WEAPONS:
            alpha = np.asarray(Image.open(os.path.join(folder, name + ".png")).convert("RGBA"))[..., 3] > 100
            _weapons[name] = _silhouette(alpha)
    seen = _silhouette(np.asarray(crop.convert("L")) > 170)
    if seen is None:
        return None, 0.0
    shape, ratio = seen
    best = (None, -1.0)
    for name, (t, r) in _weapons.items():
        score = float(np.minimum(shape, t).sum() / np.maximum(shape, t).sum()) - 0.15 * abs(float(np.log(ratio / r)))
        if score > best[1]:
            best = (name, round(score, 3))
    return best


# --- the top bar ------------------------------------------------------------

def _pixels(img):
    img = img.convert("RGB")
    return img.get_flattened_data() if hasattr(img, "get_flattened_data") else img.getdata()


def _bright(img, level=185):
    """Fraction of pixels that are near-white."""
    data = _pixels(img)
    return sum(1 for p in data if min(p) >= level) / max(1, len(data))


def _bar_pixel(p):
    r, g, b = p
    return max(p) >= 170 or (r >= 90 and r - g >= 40 and r - b >= 30)


def health_bar(frame, side, slot):
    """(alive, health 0-100) from the bar under a portrait."""
    x = TOP_X[side][slot - 1]
    strip = frame.crop(x - BAR_HALF, BAR_Y[0], x + BAR_HALF, BAR_Y[1])
    # White when healthy, red when low: any bright or red pixel is bar (the
    # bar's frame is a dull grey, never either). At a few HP the bar is a
    # pixel or so of red, so one column is enough: a dead player has no bar.
    cols = [any(_bar_pixel(strip.getpixel((cx, cy))) for cy in range(strip.height)) for cx in range(strip.width)]
    lit = sum(cols)
    if lit < 1:
        return False, 0
    if lit >= strip.width - 2:
        return True, 100   # full (the bar's ends are soft)
    return True, max(1, round(100 * lit / strip.width))


def carries_spike(frame, side, slot):
    x = TOP_X[side][slot - 1]
    return _bright(frame.crop(x - 18, CARRIER_Y[0], x + 18, CARRIER_Y[1]), 160) > 0.08


def spike_planted(frame):
    """The timer turns into a red spike icon once it's planted."""
    data = _pixels(frame.crop(*SPIKE_ICON))
    red = sum(1 for r, g, b in data if r > 150 and r > g + 70 and r > b + 70)
    return red / max(1, len(data)) > 0.12


def top_portrait(frame, side, slot):
    x = TOP_X[side][slot - 1]
    from PIL import Image
    crop = frame.crop(x - 20 - 3, PORTRAIT_Y - 3, x + 20 + 3, PORTRAIT_Y + PORTRAIT_SIZE + 3)
    return crop.transpose(Image.FLIP_LEFT_RIGHT) if side == "right" else crop


# --- the scoreboard ---------------------------------------------------------

def _tint(frame, x0, y0, x1, y1):
    """(teal, red) fractions of a box's pixels."""
    try:
        np = _np()
    except ImportError:
        data = _pixels(frame.crop(x0, y0, x1, y1))
        teal = sum(1 for p in data if p[1] > p[0] + 30 and p[2] > p[0] + 15)
        red = sum(1 for p in data if p[0] > p[1] + 40 and p[0] > p[2] + 30)
        return teal / max(1, len(data)), red / max(1, len(data))
    a = np.asarray(frame.crop(x0, y0, x1, y1).convert("RGB"), dtype=np.int16).reshape(-1, 3)
    if not len(a):
        return 0.0, 0.0
    r, g, b = a[:, 0], a[:, 1], a[:, 2]
    return float(((g > r + 30) & (b > r + 15)).mean()), float(((r > g + 40) & (r > b + 30)).mean())


def select_header(frame):
    """Is agent select's header across the top? (teal DEFENDERS half on the
    left, red ATTACKERS half on the right, from the very top of the screen to
    below where the match's top bar would be.) Its colours are where the
    top bar's are, so without this agent select reads as the match."""
    return (_tint(frame, 330, 5, 560, 25)[0] > 0.6 and _tint(frame, 330, 95, 560, 130)[0] > 0.6
            and _tint(frame, 1360, 5, 1590, 25)[1] > 0.5 and _tint(frame, 1360, 95, 1590, 130)[1] > 0.5)


def attacking_side(frame):
    """Which team attacks, from the top bar: defenders' half is teal,
    attackers' red. None if it can't be told (top bar not on screen, or
    agent select's header there instead)."""
    def tint(x0, x1):
        return _tint(frame, x0, 34, x1, 66)
    if select_header(frame):
        return None
    # The whole bar, then only the two seats each side of the score (a 2v2's
    # bar is just those: across all five seats it's mostly the map behind).
    for (l0, l1, r0, r1), need in (((TOP_X["left"][0] - 40, TOP_X["left"][-1] + 30,
                                     TOP_X["right"][0] - 30, TOP_X["right"][-1] + 40), 0.15),
                                   ((TOP_X["left"][3] - 30, TOP_X["left"][-1] + 30,
                                     TOP_X["right"][0] - 30, TOP_X["right"][1] + 30), 0.3)):
        lt, lr = tint(l0, l1)
        rt, rr = tint(r0, r1)
        if lr > need and rt > need and lr > lt and rt > rr:
            return "left"
        if lt > need and rr > need and lt > lr and rr > rt:
            return "right"
    return None


def in_match(frame, bars=None):
    """Is the match's top bar on screen? Its colours tell the attacking side;
    a 2v2's (two players a side) may be too short for that, so a lit health
    bar counts too, unless it's agent select. Loading screens, menus and the
    end-of-match screen are none of these, and nothing is read off them."""
    if attacking_side(frame):
        return True
    if select_header(frame):
        return False
    bars = bars if bars is not None else [health_bar(frame, side, slot)[0] for side in ("left", "right")
                                          for slot in range(1, 6)]
    return any(bars)


# Round history on the Tab scoreboard: a row for the defending team and one
# for the attacking team, each round's win marked by an icon in the
# winner's row (skull = elimination, pliers = defuse, ...).
HISTORY_X = (648, 1330)
# Top row: the team in the top block (the left team); bottom: the right
# team. They stay with their teams when the sides swap (only the DEF/ATK
# labels and colours change).
HISTORY_ROWS = {"left": (512, 540), "right": (540, 568)}
WIN_TYPES = ("Elimination", "Deactivation", "Detonation", "Time")
_win_icons = []


def _win_templates():
    """[(win_type, silhouette)]: real in-game icons (web/reader_refs/round-*)
    and the scoreboard template's own icons."""
    np = _np()
    from PIL import Image
    if not _win_icons:
        for kind in WIN_TYPES:
            for path in (os.path.join(REFS_DIR, f"round-{kind}.png"),
                         os.path.join(WEB_DIR, "scoreboard", "Resources", "Logos", f"{kind}.png")):
                if os.path.isfile(path):
                    img = Image.open(path).convert("RGBA")
                    mask = np.asarray(img)[..., 3] > 100 if img.getextrema()[3][0] < 200 else \
                        np.asarray(img.convert("L")) > 127
                    sil = _silhouette(mask, (20, 20))
                    if sil:
                        _win_icons.append((kind, sil))
    return _win_icons


def _icon_mask(img):
    """The coloured (teal or red) icon pixels of a history cell."""
    np = _np()
    a = np.asarray(img.convert("RGB")).astype(int)
    return (a.max(axis=2) - a.min(axis=2) > 50) & (a.max(axis=2) > 110)


def win_type(mask):
    np = _np()
    seen = _silhouette(mask, (20, 20))
    if seen is None:
        return "Elimination"
    shape, ratio = seen
    best = ("Elimination", -1.0)
    for kind, (t, r) in _win_templates():
        score = float(np.minimum(shape, t).sum() / np.maximum(shape, t).sum()) - 0.15 * abs(float(np.log(ratio / r)))
        if score > best[1]:
            best = (kind, score)
    return best[0]


def round_history(frame):
    """[{"winner": "left"/"right", "win_type": ...}] for every round played,
    from the Tab scoreboard. Icons are taken left to right across both
    rows, one per round, so the half-time divider and spacing don't matter."""
    np = _np()
    team = {"left": "left", "right": "right"}
    icons = []
    for row, (y0, y1) in HISTORY_ROWS.items():
        strip = frame.crop(HISTORY_X[0], y0, HISTORY_X[1], y1)
        mask = _icon_mask(strip)
        cols = mask.any(axis=0)
        x, w = 0, len(cols)
        while x < w:
            if cols[x]:
                start = x
                while x < w and cols[x]:
                    x += 1
                piece = mask[:, start:x]
                rows_lit = np.nonzero(piece.any(axis=1))[0]
                # Icons are ~14px square; the spike-plant dots and the
                # half-time line are much smaller or thinner.
                if 9 <= x - start <= 22 and len(rows_lit) and rows_lit[-1] - rows_lit[0] >= 9:
                    icons.append((start, team[row], win_type(piece)))
            x += 1
    return [{"winner": winner, "win_type": kind} for _, winner, kind in sorted(icons)]


BUY_BANNER = (812, 140, 1110, 162)   # the grey box behind "ROUND n //////" above BUY PHASE


def buy_phase(frame):
    """Is the BUY PHASE banner up? Spectators see it for the whole buy phase."""
    data = _pixels(frame.crop(*BUY_BANNER))
    grey = sum(1 for p in data if 35 <= p[0] <= 110 and max(p) - min(p) < 14)
    return grey / max(1, len(data)) > 0.7


# --- tactical timeouts --------------------------------------------------------
# A timeout called in the match puts a banner across the middle of the screen
# (seen in owen's recording of 2026-11-19, round 6, Lotus): "TIMEOUT STARTING
# IN" for a few seconds, then "TIMEOUT ACTIVE" for the minute, with the
# calling team's side above it ("ATTACKERS") and a countdown bar in that
# side's colour (red: attackers) that shrinks from the right. Pale teal
# letters, drawn under the Tab scoreboard when it's open.
TIMEOUT_BOX = (680, 445, 1240, 525)      # the big words (the templates' box)
TIMEOUT_BAR = (666, 537, 1254, 543)      # the countdown bar's top edge (its middle has the digits): full width is the minute
TIMEOUT_LABEL = (860, 396, 1060, 420)    # "ATTACKERS" / "DEFENDERS"
TIMEOUT_MATCH = 0.55                     # template overlap that counts (others score <= 0.45)
_timeout_refs = {}
_timeout_ocr_at = [0.0]


def _timeout_ink(img):
    """The banner's pale teal letters."""
    np = _np()
    a = np.asarray(img.convert("RGB"), dtype=np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return (g - r >= 18) & (b - r >= 14) & (r >= 105) & (g >= 140)


def _timeout_templates():
    np = _np()
    from PIL import Image
    if not _timeout_refs:
        for state in ("starting", "active"):
            path = os.path.join(REFS_DIR, f"timeout-{state}.png")
            if os.path.isfile(path):
                _timeout_refs[state] = np.asarray(Image.open(path).convert("L")) > 127
    return _timeout_refs


def _shifted_iou(mask, ref, dy=3, dx=4):
    """Best intersection-over-union of mask and ref, shifted a few pixels."""
    np = _np()
    best = 0.0
    h, w = mask.shape
    for y in range(-dy, dy + 1):
        for x in range(-dx, dx + 1):
            a = mask[max(0, y):h + min(0, y), max(0, x):w + min(0, x)]
            b = ref[max(0, -y):h + min(0, -y), max(0, -x):w + min(0, -x)]
            union = np.count_nonzero(a | b)
            if union:
                best = max(best, np.count_nonzero(a & b) / union)
    return best


def timeout_bar(frame):
    """(colour, width): the countdown bar's colour ("red" / "teal", None when
    there's none) and how far it reaches from its left end, in 1080p px."""
    np = _np()
    a = np.asarray(frame.crop(*TIMEOUT_BAR).convert("RGB"), dtype=np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    for colour, lit in (("red", (r > g + 60) & (r > b + 60) & (r > 120)),
                        ("teal", (g > r + 50) & (b > r + 30) & (g > 120))):
        cols = lit.mean(axis=0) > 0.8
        if cols[:6].any():
            gaps = np.nonzero(~cols[int(np.argmax(cols)):])[0]
            width = int(np.argmax(cols)) + (int(gaps[0]) if len(gaps) else len(cols))
            if width >= 4:
                return colour, width
    return None, 0


def _timeout_words(frame, ocr):
    """The banner's words by text recognition ("" if none)."""
    try:
        words = ocr.words(ink(frame.crop(TIMEOUT_BOX[0], TIMEOUT_BOX[1] - 10, TIMEOUT_BOX[2], TIMEOUT_BOX[3] + 5),
                              2, 140))
    except Exception:
        return ""
    return " ".join(w for w, _, _ in words).upper()


def read_timeout(frame, ocr=None):
    """A timeout on screen: {"state": "starting" / "active", "caller":
    "attackers" / "defenders" / None, "seconds": left (active, from the bar)
    or None}; None when there's no timeout banner."""
    np = _np()
    mask = _timeout_ink(frame.crop(*TIMEOUT_BOX))
    state = None
    if mask.mean() > 0.08:   # (a frame without the banner has a few percent at most)
        scores = {s: _shifted_iou(mask, ref) for s, ref in _timeout_templates().items() if ref.shape == mask.shape}
        if scores:
            best = max(scores, key=scores.get)
            if scores[best] >= TIMEOUT_MATCH:
                state = best
    colour, width = timeout_bar(frame)
    if state is None and colour and width >= 20 and ocr is not None and time.time() - _timeout_ocr_at[0] > 2:
        # The letters' colour is only known over the Tab scoreboard: with a
        # countdown bar up, the words are read instead (every 2 s at most:
        # something red in the game where the bar goes would be read too).
        _timeout_ocr_at[0] = time.time()
        words = _timeout_words(frame, ocr)
        if "TIMEOUT" in words:
            state = "starting" if "START" in words else "active"
    if state is None:
        return None
    caller = {"red": "attackers", "teal": "defenders"}.get(colour)
    if ocr is not None:
        try:
            label = " ".join(w for w, _, _ in ocr.words(ink(frame.crop(*TIMEOUT_LABEL), 3, 120))).upper()
        except Exception:
            label = ""
        if "ATTACK" in label:
            caller = "attackers"
        elif "DEFEND" in label:
            caller = "defenders"
    seconds = None
    if state == "active":
        full = TIMEOUT_BAR[2] - TIMEOUT_BAR[0]
        seconds = int(round(60 * width / full)) if colour else 0
    return {"state": state, "caller": caller, "seconds": seconds}


def scoreboard_open(frame):
    """Is the Tab scoreboard on screen? Two blocks of coloured rows (five a
    team, or two in a 2v2): usually teal above red, but both teal (or both
    red) at times, e.g. at half time. Which layout it is goes on the frame
    (frame.board) for the cells below."""
    def coloured(y0, rows):
        data = _pixels(frame.crop(820, y0, 930, y0 + rows * ROW_H))
        hit = sum(1 for p in data if (p[1] > p[0] + 25 and p[1] > 60) or (p[0] > p[1] + 25 and p[0] > 60))
        return hit / max(1, len(data))
    for board in (BOARDS[5], BOARDS[2]):
        if all(coloured(board["top"][side], board["rows"]) > 0.6 for side in ("left", "right")):
            frame.board = board
            return True
    return False


def _row_top(frame, side):
    return getattr(frame, "board", BOARDS[5])["top"][side]


def row_cell(frame, side, row, col, pad=0):
    x0, x1 = COLS[col]
    y0 = _row_top(frame, side) + ROW_H * row
    return frame.crop(x0, y0 + pad, x1, y0 + ROW_H - pad)


# Where the gun can be in a row: from the assists column to before the
# credits. Its column moves a little between scoreboard layouts, so the gun
# is found in this strip rather than at a fixed place.
WEAPON_STRIP = (1030, 1250)


def weapon_cell(frame, side, row):
    """The gun icon in a scoreboard row, or None: the widest solid white
    shape in the strip (the assists digits and the shield icon are narrower;
    rifles reach further right than pistols)."""
    np = _np()
    y0 = _row_top(frame, side) + ROW_H * row
    strip = frame.crop(WEAPON_STRIP[0], y0 + 4, WEAPON_STRIP[1], y0 + ROW_H - 4)
    cols = (np.asarray(strip.convert("L")) > 170).any(axis=0)
    runs, start, last = [], None, None
    for x, lit in enumerate(cols):
        if lit:
            if start is None:
                start = x
            elif x - last > 4:   # a gap: the next shape
                runs.append((start, last))
                start = x
            last = x
    if start is not None:
        runs.append((start, last))
    runs = [(a, b) for a, b in runs if b - a + 1 >= 26]
    if not runs:
        return None
    a, b = max(runs, key=lambda r: r[1] - r[0])
    return strip.crop((a, 0, b + 1, strip.height))


_shield_refs = None


def _shield_ink(img):
    np = _np()
    return np.asarray(img.convert("L"), dtype=np.float32) > 170


def _overlap(a, b, m=3):
    """How well two icons' white shapes overlap (intersection over union),
    the best within m px either way."""
    H, W = a.shape
    best = 0.0
    for dy in range(-m, m + 1):
        for dx in range(-m, m + 1):
            A = a[max(0, dy):H + min(0, dy), max(0, dx):W + min(0, dx)]
            B = b[max(0, -dy):H + min(0, -dy), max(0, -dx):W + min(0, -dx)]
            union = (A | B).sum()
            if union:
                best = max(best, float((A & B).sum()) / float(union))
    return best


def shield_reading(cell):
    """(points, regen) from the shield icon next to the weapon: no icon
    (0, False); the outlined shield light (25, False); the filled one with
    wings heavy (50, False); the round one (a ring around a disc with an
    arrow) the regen shield (25, True). Matched against real icons from the
    game (web/reader_refs/shield-light/heavy/regen.png). None when there's
    an icon that looks like none of them (the scoreboard fading in, a
    highlight): the last reading stands."""
    global _shield_refs
    from PIL import Image
    if _bright(cell, 170) < 0.04:
        return 0, False
    if _shield_refs is None:
        _shield_refs = {k: _shield_ink(Image.open(os.path.join(REFS_DIR, f"shield-{k}.png"))) for k in SHIELD_KINDS}
    size = _shield_refs["light"].shape[::-1]
    ink = _shield_ink(cell.resize(size) if cell.size != size else cell)
    scores = {k: _overlap(ink, ref) for k, ref in _shield_refs.items()}
    kind = max(scores, key=scores.get)
    if scores[kind] < 0.5:
        return None
    return SHIELD_KINDS[kind]


SHIELD_KINDS = {"light": (25, False), "heavy": (50, False), "regen": (25, True)}


def shield_level(cell):
    """0 / 25 / 50, or None (see shield_reading)."""
    seen = shield_reading(cell)
    return seen[0] if seen else None


# --- text ---------------------------------------------------------------------

class WindowsOcr:
    """Windows.Media.Ocr through the winrt packages."""

    def __init__(self):
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
        engine = OcrEngine.try_create_from_language(Language("en-US"))
        if engine is None:
            engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise RuntimeError("Windows text recognition isn't installed for any of your languages")
        self.engine = engine

    def words(self, image):
        """[(text, x_centre, y_centre), ...] in the image's pixels."""
        from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.storage.streams import DataWriter
        rgba = image.convert("RGBA")
        writer = DataWriter()
        writer.write_bytes(rgba.tobytes("raw", "BGRA"))
        buffer = writer.detach_buffer()
        try:
            bitmap = SoftwareBitmap.create_copy_from_buffer(buffer, BitmapPixelFormat.BGRA8, rgba.width, rgba.height)
        except TypeError:
            bitmap = SoftwareBitmap(BitmapPixelFormat.BGRA8, rgba.width, rgba.height, BitmapAlphaMode.PREMULTIPLIED)
            bitmap.copy_from_buffer(buffer)

        async def run():
            return await self.engine.recognize_async(bitmap)

        result = asyncio.run(run())
        out = []
        for line in result.lines:
            for word in line.words:
                r = word.bounding_rect
                out.append((word.text, r.x + r.width / 2, r.y + r.height / 2))
        return out


def ink(img, scale=2, level=150):
    """White text -> black on white, enlarged: what Windows OCR reads best."""
    from PIL import Image
    gray = img.convert("L").point(lambda v: 0 if v >= level else 255)
    return gray.resize((gray.width * scale, gray.height * scale), Image.LANCZOS)


_DIGITS = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "l": "1", "I": "1", "|": "1", "i": "1",
                         "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2", "g": "9"})


def number(text):
    digits = re.sub(r"\D", "", (text or "").translate(_DIGITS))
    return int(digits) if digits else None


# Windows OCR reads lone digits badly ("0" on its own often comes back as
# nothing), but reads them fine next to words. So numbers are read in lines
# like "kills 0 deaths 2 assists 1 ult 3 8 creds 2300": our own rendered
# label words with the screen's cells pasted between them.
_label_cache = {}


def _label(text, height):
    from PIL import Image, ImageDraw, ImageFont
    key = (text, height)
    if key not in _label_cache:
        font = ImageFont.truetype(os.path.join(WEB_DIR, "fonts", "Inter.ttf"), max(8, int(height * 0.62)))
        w = int(font.getlength(text)) + 8
        img = Image.new("L", (w, height), 255)
        ImageDraw.Draw(img).text((4, height // 2), text, fill=0, font=font, anchor="lm")
        _label_cache[key] = img
    return _label_cache[key]


def _drop_currency(cell):
    """Remove the credits symbol in front of the number (the first blob of
    ink, followed by a wider gap than between digits)."""
    w, h = cell.size
    cols = [any(cell.getpixel((x, y)) < 128 for y in range(h)) for x in range(w)]
    runs, x = [], 0
    while x < w:
        if cols[x]:
            start = x
            while x < w and cols[x]:
                x += 1
            runs.append((start, x))
        x += 1
    if len(runs) >= 2 and runs[1][0] - runs[0][1] >= 6:
        return cell.crop((runs[1][0] - 2, 0, w, h))
    return cell


def _fit(img, text_h=34):
    """Crop to the ink and scale it so the text is text_h px tall (the
    size of the label words), with a white margin."""
    from PIL import Image, ImageOps
    box = ImageOps.invert(img).getbbox()
    if not box:
        return Image.new("L", (text_h // 2, text_h), 255)
    img = img.crop(box)
    k = text_h / img.height
    img = img.resize((max(1, round(img.width * k)), text_h), Image.LANCZOS)
    return ImageOps.expand(img, 6, 255)


def _line(parts, height, gap=14):
    from PIL import Image
    width = sum(p.width for p in parts) + gap * (len(parts) + 1)
    out = Image.new("L", (width, height), 255)
    x = gap
    for p in parts:
        out.paste(p, (x, (height - p.height) // 2))
        x += p.width + gap
    return out


def _stack(lines, spacing=24):
    from PIL import Image
    width = max(l.width for l in lines)
    out = Image.new("L", (width, sum(l.height + spacing for l in lines) + spacing), 255)
    y = spacing
    for l in lines:
        out.paste(l, (0, y))
        y += l.height + spacing
    return out


def _lines_of(words, line_h, spacing):
    """Words grouped by which pasted line they're on, in reading order."""
    lines = {}
    for text, cx, cy in words:
        i = int((cy - spacing / 2) // (line_h + spacing))
        lines.setdefault(i, []).append((cx, text))
    return {i: " ".join(t for _, t in sorted(ws)) for i, ws in lines.items()}


_NUM = r"([0-9OoDQlI|SsBZzg]{1,4})"


def _field(text, label):
    m = re.search(label + r"\W*" + _NUM, text, re.I)
    return number(m.group(1)) if m else None


def _money(text):
    """Credits from "... creds 3,550 end": the whole amount, thousands
    separator and all (it used to stop at the comma: 3,550 -> 3)."""
    m = re.search(r"creds\W*(.*?)\s*end", text, re.I)
    value = number(m.group(1)) if m else None
    if value is not None and value > 9000 and value % 10 ** (len(str(value)) - 1) <= 9000:
        value %= 10 ** (len(str(value)) - 1)   # the credits sign read as a digit
    return value if value is not None and value <= 9000 else None


def read_score_line(frame, ocr):
    """{"left": int, "right": int, "timer": seconds} from the top bar."""
    out = {}
    x0, y0, x1, y1 = SCORE_LINE
    for text, _, _ in ocr.words(ink(frame.crop(x0, y0, x1, y1), 2, 170)):
        m = re.search(r"(\d+)[:.](\d\d)", text.translate(_DIGITS))
        if m:
            out["timer"] = int(m.group(1)) * 60 + int(m.group(2))
    h = 80
    left = _fit(ink(frame.crop(*SCORE_BOX["left"]), 1, 170))
    right = _fit(ink(frame.crop(*SCORE_BOX["right"]), 1, 170))
    line = _line([_label("home", h), left, _label("away", h), right, _label("end", h)], h)
    text = " ".join(t for t, _, _ in ocr.words(line))
    for side, label in (("left", "home"), ("right", "away")):
        value = _field(text, label)
        if value is not None and value <= 30:
            out[side] = value
    out["_text"] = text
    return out


_TAG = re.compile(r"^\S{1,8}(?:\s+\S{1,4})?\s*[|\u00a6\u2502]\s*|^\S{1,8}\s+[Il1!]\s+(?=\S)")


def player_name(text):
    """The name without a team tag the text recognition still caught
    ("FIT | Panda Nate", "HII I Panda Nate" -> "Panda Nate")."""
    text = " ".join(text.split())
    rest = _TAG.sub("", text, count=1)
    return rest if len(rest) >= 2 else text


def read_scoreboard(frame, ocr):
    """Per row (left rows 0-4, right rows 0-4; 0-1 in a 2v2): name, ult,
    K/D/A, credits."""
    rows = {}
    n = getattr(frame, "board", BOARDS[5])["rows"]
    # Names: whole name column per team.
    for side in ("left", "right"):
        top = _row_top(frame, side)
        x0, x1 = COLS["name"]
        # (The grey team tag before a name, "FAPP | ", is taken off after.)
        words = ocr.words(ink(frame.crop(x0, top, x1, top + n * ROW_H), 2, 150))
        for r in range(n):
            mine = sorted((cx, t) for t, cx, cy in words if r * ROW_H <= cy / 2 < (r + 1) * ROW_H)
            rows[(side, r)] = {"name": player_name(" ".join(t for _, t in mine))}
    # Numbers: one labelled line per player.
    h, spacing, lines, keys = ROW_H * 2, 24, [], []
    for side in ("left", "right"):
        for r in range(n):
            cell = lambda c: _fit(ink(row_cell(frame, side, r, c, 3), 1, 150))
            lines.append(_line([_label("kills", h), cell("k"), _label("deaths", h), cell("d"),
                                _label("assists", h), cell("a"), 
                                _label("creds", h), _fit(_drop_currency(ink(row_cell(frame, side, r, "creds", 3), 1, 150))),
                                _label("end", h)], h))
            keys.append((side, r))
    texts = _lines_of(ocr.words(_stack(lines, spacing)), h, spacing)
    for i, key in enumerate(keys):
        text = texts.get(i, "")
        info = rows[key]
        info["_text"] = text
        info["k"], info["d"], info["a"] = _field(text, "kills"), _field(text, "deaths"), _field(text, "assists")
        info["creds"] = _money(text)
        info["ult"] = None
    # Ult points ("0 / 7"): OCR sometimes drops the first digit, so they're
    # read three ways and the first reading that makes sense is kept.
    variants = [
        lambda have, need: [_label("ult", h), have, _label("of", h), need, _label("end", h)],
        lambda have, need: [_label("points", h), have, _label("needs", h), need, _label("end", h)],
        lambda have, need: [_label("charge", h), have, _label("slash", h), need, _label("done", h)],
    ]
    pairs = [(_fit(ink(row_cell(frame, side, r, "ult_have", 3), 1, 150)),
              _fit(ink(row_cell(frame, side, r, "ult_need", 3), 1, 150))) for side, r in keys]
    labels = [("ult", "of"), ("points", "needs"), ("charge", "slash")]
    for make, (first, second) in zip(variants, labels):
        todo = [i for i, key in enumerate(keys) if rows[key]["ult"] is None]
        if not todo:
            break
        texts = _lines_of(ocr.words(_stack([_line(make(*pairs[i]), h) for i in todo], spacing)), h, spacing)
        for n, i in enumerate(todo):
            text = texts.get(n, "")
            have, need = _field(text, first), _field(text, second)
            if have is not None and need is not None and have <= need and 5 <= need <= 9:
                rows[keys[i]]["ult"] = (have, need)
            rows[keys[i]]["_ult_text"] = rows[keys[i]].get("_ult_text", []) + [text]
    return rows


# --- who the observer is spectating -----------------------------------------

# Spectating a player, the game shows their name: in tournament spectating
# at the bottom, by their health ("100T bang"); in a custom game's observer
# view in a card at the bottom left, by their portrait ("Gora46"). Both
# stretches are read; the GFX PC matches the text to its players' names (see
# game.observed_player). Free-cam shows no name.
SPECTATED_TEXT = (440, 940, 1000, 1004)
SPECTATED_CARD = (112, 812, 480, 860)


def spectated_text(frame, ocr):
    """The text where the spectated player's name shows (the name, with any
    team tag and health digits around it), or ""."""
    seen = []
    for box, levels in ((SPECTATED_CARD, (200, 160)), (SPECTATED_TEXT, (150, 185))):
        crop = frame.crop(*box)
        for level in levels:
            words = sorted(ocr.words(ink(crop, 2, level)), key=lambda w: w[1])
            text = " ".join(t for t, _, _ in words)
            if text and text not in seen:
                seen.append(text)
    return " / ".join(seen)


# The custom-game observer view's card also shows the spectated player's
# agent (their bust portrait, on red for the attackers or teal for the
# defenders): who it is when their name isn't known to the HUD.
SPECTATED_PORTRAIT = (30, 795, 111, 876)
_bust_refs = None


def _busts():
    global _bust_refs
    if _bust_refs is None:
        np = _np()
        from PIL import Image
        folder = os.path.join(WEB_DIR, "reader_refs", "select", "agents")
        _bust_refs = {}
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            if name.endswith(".png"):
                t = np.asarray(Image.open(os.path.join(folder, name)).convert("RGBA").resize((80, 80), Image.BILINEAR),
                               dtype=np.float32)
                _bust_refs[name[:-4]] = (t[..., :3], t[..., 3] > 230)
    return _bust_refs


_bust_bank_cache = None


def _bust_bank():
    """(names, templates()) of the observer card's agent portraits."""
    global _bust_bank_cache
    if _bust_bank_cache is None:
        np = _np()
        busts = _busts()
        names = list(busts)
        _bust_bank_cache = (names, templates(np.stack([busts[a][0].reshape(-1, 3) for a in names]),
                                             np.stack([busts[a][1].reshape(-1) for a in names])))
    return _bust_bank_cache


def spectated_agent(frame):
    """(agent, "attackers" / "defenders") from the spectated player's card,
    or (None, None) (no card: free cam, or another kind of spectating)."""
    np = _np()
    card = np.asarray(frame.crop(*SPECTATED_PORTRAIT), dtype=np.float32)
    r, g, b = card[2:8, 2:8].reshape(-1, 3).mean(axis=0)   # the card's own colour, top left
    side = "attackers" if r > 150 and r - g > 60 else "defenders" if g > 120 and g - r > 40 else None
    if not side:
        return None, None
    busts = _busts()
    if not busts:
        return None, None
    names, bank = _bust_bank()
    wins = np.stack([card[oy:oy + 80, ox:ox + 80].reshape(-1, 3) for ox in (0, 1) for oy in (0, 1)])
    scores, _ = ncc_many(wins, np.ones(wins.shape[:2]), bank)
    each = [float(v) for v in scores.max(axis=1)]
    best, second = (0.0, None), 0.0
    for agent, score in zip(names, each):
        if score > best[0]:
            best, second = (score, agent), best[0]
        elif score > second:
            second = score
    return (best[1], side) if best[0] >= 0.6 and best[0] - second >= 0.1 else (None, None)


# --- putting it together ----------------------------------------------------

def seat_rows(frame, side, top_agents, known_agents=None):
    """({row: seat}, {row: agent}) for one team's scoreboard rows.

    The rows are sorted by score, not in top-bar order: each row goes to the
    seat with the same agent. A row is only placed when that's certain (or
    it's the last row left for the last seat), so a name or loadout never
    lands on the wrong player."""
    board = getattr(frame, "board", BOARDS[5])
    seats = board["seats"][side]
    row_agents = {}
    team = [a for (t, s_), a in (known_agents or {}).items() if t == side and s_ in seats]
    for r in range(board["rows"]):
        best = identify_agent(row_cell(frame, side, r, "portrait"), (32, 34, 36), kind="row",
                              agents=team if len(set(team)) == len(seats) else None)
        row_agents[r] = best[0][1] if clear_match(best) else None
    free = list(seats)
    assign = {}
    seats_of = {}
    for s_ in seats:
        seats_of.setdefault(top_agents.get((side, s_)), []).append(s_)
    for r, agent in row_agents.items():
        match = [s_ for s_ in seats_of.get(agent, []) if s_ in free] if agent else []
        if len(match) == 1 and list(row_agents.values()).count(agent) == 1:
            assign[r] = match[0]
            free.remove(match[0])
    left_rows = [r for r in range(board["rows"]) if r not in assign]
    if len(left_rows) == 1 and len(free) == 1:
        assign[left_rows[0]] = free[0]
    return assign, row_agents


def read_name(frame, side, row, ocr):
    """One row's name, read carefully: at three contrasts, keeping the
    reading that comes up most (the longest on a tie)."""
    x0, x1 = COLS["name"]
    y0 = _row_top(frame, side) + ROW_H * row
    crop = frame.crop(x0, y0 + 2, x1, y0 + ROW_H - 2)
    seen = {}
    for level in (150, 120, 185):
        text = player_name(" ".join(t for t, _, _ in sorted(ocr.words(ink(crop, 3, level)), key=lambda w: w[1])))
        if len(text) >= 2:
            seen[text] = seen.get(text, 0) + 1
    return max(seen, key=lambda t: (seen[t], len(t))) if seen else ""


def read_frame(image, ocr=None, known_agents=None, bank=None):
    """Everything readable in one frame, as an update for game.merge().
    bank: a glyphbank.GlyphBank (digits by shape): it learns from the text
    recognition's readings and adds its own (match.score_shape, kda_shape)."""
    frame = Frame(image)
    players = []
    top_agents = {}
    seen = []   # agents recognised on the top bar in this frame (the reader learns from these)
    for side in ("left", "right"):
        for slot in range(1, 6):
            alive, health = health_bar(frame, side, slot)
            p = {"team": side, "slot": slot, "alive": alive, "health": health,
                 "spike": alive and carries_spike(frame, side, slot)}
            agent = (known_agents or {}).get((side, slot))
            if alive:
                # The top bar is the only place a seat's agent is certain:
                # check the agent known for it still matches, else look again.
                portrait = top_portrait(frame, side, slot)
                if agent and identify_agent(portrait, (40, 42), agents=[agent], kind="top")[0][0] < 0.5:
                    agent = None
                if agent:
                    seen.append((side, slot, agent))
                else:
                    best = identify_agent(portrait, (40, 42), kind="top")
                    if clear_match(best):
                        agent = best[0][1]
                        seen.append((side, slot, agent))
            if agent:
                p["agent"] = agent
                top_agents[(side, slot)] = agent
            players.append(p)
    update = {"source": "screen", "match": {}, "players": players, "seen_agents": seen}
    side = attacking_side(frame)
    if side:   # the top bar is on screen, so the phase can be told too
        update["match"]["attackers"] = side
        update["match"]["phase"] = "buy" if buy_phase(frame) else "combat"
        # A tactical timeout's banner (None: none on this frame).
        update["match"]["timeout"] = read_timeout(frame, ocr)
    planted = spike_planted(frame)
    update["match"]["spike"] = {"state": "planted"} if planted else {}
    carrier = next(((p["team"], p["slot"]) for p in players if p["spike"]), None)
    if not planted:
        update["match"]["spike"] = {"state": "carried" if carrier else "", "carrier": list(carrier) if carrier else None}
    if ocr:
        line = read_score_line(frame, ocr)
        if "left" in line and "right" in line:
            update["match"]["score"] = {"left": line["left"], "right": line["right"]}
            update["match"]["round"] = line["left"] + line["right"] + 1
        if "timer" in line:
            update["match"]["timer"] = line["timer"]
    if bank is not None and side:
        shape = {}
        for s_ in ("left", "right"):
            cell = frame.crop(*SCORE_BOX[s_])
            if ocr:
                bank.offer("score", s_, cell, (update["match"].get("score") or {}).get(s_), 170)
            shape[s_] = bank.read("score", cell, 170)
        if shape["left"] is not None and shape["right"] is not None and max(shape.values()) <= 30:
            update["match"]["score_shape"] = shape
    if scoreboard_open(frame):
        board = read_scoreboard(frame, ocr) if ocr else {}
        by_slot = {(p["team"], p["slot"]): p for p in players}
        for side in ("left", "right"):
            assign, row_agents = seat_rows(frame, side, top_agents, known_agents)
            for r, slot in assign.items():
                p = by_slot[(side, slot)]
                if row_agents[r]:
                    p["agent"] = row_agents[r]
                cell = weapon_cell(frame, side, r)
                weapon, score = identify_weapon(cell) if cell else (None, 0.0)
                if weapon and score >= 0.55:
                    p["weapon"] = weapon
                elif cell is None:
                    p["weapon"] = ""   # empty loadout: no gun (don't keep last round's)
                shield = shield_reading(row_cell(frame, side, r, "shield", 4))
                if shield:
                    p["shield"], p["regen_shield"] = shield
                info = board.get((side, r)) or {}
                if info.get("name"):
                    p["name"] = info["name"]
                if info.get("ult"):
                    p["ult_points"], p["ult_max"] = info["ult"]
                for key, field in (("k", "kills"), ("d", "deaths"), ("a", "assists"), ("creds", "credits")):
                    if info.get(key) is not None:
                        p[field] = info[key]
                if bank is not None:
                    kda = []
                    for key in ("k", "d", "a"):
                        cell = row_cell(frame, side, r, key, 3)
                        bank.offer("kda", (side, r, key), cell, info.get(key))
                        kda.append(bank.read("kda", cell))
                    if None not in kda:
                        p["kda_shape"] = kda
        update["match"]["scoreboard_open"] = True
        # (a 2v2's board has its round history somewhere else: not read yet)
        history = round_history(frame) if frame.board is BOARDS[5] else None
        if history:
            update["match"]["rounds"] = history
    return update


def _drop_shadow_fields(update):
    (update.get("match") or {}).pop("score_shape", None)
    for p in update.get("players") or []:
        p.pop("kda_shape", None)


# --- capturing the game window ----------------------------------------------

# Which window is read. Set from the Control page's "Game window" (config
# "capture"): {"title": "", "exe": ""} finds VALORANT by itself; a title
# (and the program it belongs to) reads that window; "screen": n (1, 2, ...)
# reads that whole screen.
PICK = {"title": "", "exe": "", "screen": 0}
VALORANT_EXE = "valorant-win64-shipping.exe"


def set_pick(capture):
    capture = capture or {}
    PICK.update({"title": str(capture.get("title") or ""), "exe": str(capture.get("exe") or ""),
                 "screen": int(capture.get("screen") or 0)})


def _exe_of(hwnd):
    """The file name of the program that owns the window ("" if unknown)."""
    import ctypes
    import os
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(handle)


def game_windows():
    """Every window a game could be in: visible, not minimised, titled and at
    least 200x200, biggest first: [{"hwnd", "title", "exe", "width",
    "height", "x", "y", "screen", "valorant"}]. In real pixels."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes
    from scc_shared import dpi
    user32 = ctypes.windll.user32
    out = []
    own = os.getpid()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        if not n or not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == own:
            return True   # this app's own windows
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        rect = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        point = wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(point))
        out.append({"hwnd": hwnd, "title": buf.value.strip(), "width": rect.right, "height": rect.bottom,
                    "x": point.x, "y": point.y, "minimised": bool(user32.IsIconic(hwnd))})
        return True

    with dpi.real_pixels():
        user32.EnumWindows(each, 0)
        screens = dpi.monitors()
        for w in out:
            w["exe"] = _exe_of(w["hwnd"])
            w["screen"] = dpi.screen_of(w["x"] + w["width"] // 2, w["y"] + w["height"] // 2, screens)
            w["valorant"] = w["exe"].lower() == VALORANT_EXE or w["title"] == WINDOW_TITLE
    out = [w for w in out if w["title"] and w["title"] != "Program Manager" and (w["valorant"] or (not w["minimised"] and w["width"] >= 200 and w["height"] >= 200))]
    out.sort(key=lambda w: (not w["valorant"], -w["width"] * w["height"]))
    return out


_found = {"key": None, "win": None, "reason": "", "at": 0.0}
FIND_EVERY = 2.0   # seconds between full looks through every window (each capture checks the one found is still there)


def _find_window():
    """(window, None) for the window to read, or (None, reason). The window
    found is kept and only checked (still open, where it is now) on each
    capture: going through every window on the PC (and the program behind
    each) twenty times a second cost a lot."""
    key = (PICK["title"], PICK["exe"])
    win, age = _found["win"], time.time() - _found["at"]
    if _found["key"] == key:
        if win and age < FIND_EVERY:
            now = _window_now(win)
            if now:
                return now, None
        elif not win and age < FIND_EVERY / 2:
            return None, _found["reason"]   # (not open a moment ago)
    win, reason = _look_for_window()
    _found.update(key=key, win=win, reason=reason, at=time.time())
    return win, reason


def _window_now(win):
    """The window kept by _find_window, with where it is now, or None (it's
    gone, or hidden: look again)."""
    import ctypes
    from ctypes import wintypes
    from scc_shared import dpi
    user32 = ctypes.windll.user32
    hwnd = win["hwnd"]
    if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
        return None
    rect = wintypes.RECT()
    point = wintypes.POINT(0, 0)
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)) or not user32.ClientToScreen(hwnd, ctypes.byref(point)):
        return None
    now = dict(win, width=rect.right, height=rect.bottom, x=point.x, y=point.y,
               minimised=bool(user32.IsIconic(hwnd)))
    if (now["x"], now["y"], now["width"], now["height"]) != (win["x"], win["y"], win["width"], win["height"]):
        now["screen"] = dpi.screen_of(now["x"] + now["width"] // 2, now["y"] + now["height"] // 2)
        _found["win"] = now
    return now


def _look_for_window():
    found = game_windows()
    if PICK["title"]:
        title, exe = PICK["title"], PICK["exe"].lower()
        hits = ([w for w in found if w["title"] == title and (not exe or w["exe"].lower() == exe)]
                or [w for w in found if title.casefold() in w["title"].casefold()])
        if not hits:
            return None, (f"The game window you picked (“{title}”) isn't open: open it, or pick another "
                          "window under Game window")
        return hits[0], None
    hits = [w for w in found if w["valorant"]]
    if not hits:
        return None, "VALORANT window not found (if it's open, pick it under Game window)"
    # The biggest (a game can have small helper windows with the same name).
    hits.sort(key=lambda w: (w["minimised"], -w["width"] * w["height"]))
    return hits[0], None


def capture_valorant(top=None):
    """(image, None) with the VALORANT window's client area (only its top
    `top` rows, in 1080p terms, if given), or (None, reason).

    While VALORANT is on top it's copied off the screen. When another window
    covers it (someone tabbed into the HUD or a browser on this PC), the
    screen shows that window instead, so VALORANT's own picture is asked for
    (PrintWindow): it keeps being read wherever the focus is.

    Everything is in real pixels (scc_shared/dpi.py), so it reads VALORANT on
    any screen, whatever each screen's display scaling."""
    from scc_shared import dpi
    with dpi.real_pixels():
        return _capture(top)


def _capture(top):
    import ctypes
    user32 = ctypes.windll.user32
    if PICK["screen"]:
        from scc_shared import dpi
        screens = dpi.monitors()
        n = PICK["screen"]
        if not 1 <= n <= len(screens):
            return None, f"Screen {n} isn't connected: pick another under Game window"
        left, top_, right, bottom = screens[n - 1]
        height = bottom - top_
        rows = height if top is None else min(height, max(1, round(top * height / REF_H)))
        box = (left, top_, right, top_ + rows)
        CAPTURE["window"] = f"Screen {n} ({right - left}x{height}), whole screen"
        image = _grab_box(box, True)
        if _is_black(image):
            return None, _black_reason(None)
        image.info["full_height"] = height
        return image, None
    win, reason = _find_window()
    if win is None:
        CAPTURE["window"] = ""
        return None, reason
    hwnd = win["hwnd"]
    CAPTURE["window"] = (f"“{win['title']}”" + (f" on screen {win['screen']}" if win["screen"] else "")
                         + f" ({win['width']}x{win['height']})")
    if user32.IsIconic(hwnd):
        return None, ("VALORANT is minimised: set its Display Mode to Windowed Fullscreen so it keeps "
                      "drawing while you're in another window")
    width, height = win["width"], win["height"]
    if width < 200 or height < 200:
        return None, "VALORANT window is too small"
    x, y = win["x"], win["y"]
    rows = height if top is None else min(height, max(1, round(top * height / REF_H)))
    box = (x, y, x + width, y + rows)
    uncovered = _uncovered(hwnd, x, y, width, rows)
    image = None if uncovered else _print_window(hwnd, width, height)
    if image is not None:
        if rows < height:
            image = image.crop((0, 0, width, rows))
    else:
        image = _grab_box(box, uncovered)
    if uncovered and _is_black(image):
        return None, _black_reason(hwnd)
    image.info["full_height"] = height
    return image, None


def _grab_box(box, uncovered):
    """The screen area box, as on screen. Some PCs (windowed fullscreen drawn
    straight to the display, HDR, some GPU drivers) give Windows' ordinary
    screen copy a black game: then it's taken off the graphics card (DXGI
    desktop duplication)."""
    from PIL import ImageGrab
    image = None
    if not CAPTURE["gdi_black"]:
        image = _gdi_grab(box) or ImageGrab.grab(box, all_screens=True)
    if image is None or (uncovered and _is_black(image)):
        dx = _dxgi_grab(box)
        if dx is not None and not _is_black(dx):
            if not CAPTURE.get("gdi_black"):
                log("VALORANT comes out black in Windows' screen copy on this PC: "
                    "reading it straight off the graphics card instead")
            CAPTURE["gdi_black"], CAPTURE["method"] = True, "graphics card"
            image = dx
        elif image is None:
            image = ImageGrab.grab(box, all_screens=True)
    return image


def _bitmap_header(width, height):
    import ctypes
    from ctypes import wintypes

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    info = BITMAPINFOHEADER()
    info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.biWidth, info.biHeight = width, -height   # top-down rows
    info.biPlanes, info.biBitCount = 1, 32
    return info


def _gdi_grab(box):
    """The screen area box = (left, top, right, bottom), copied off the
    screen (what PIL's ImageGrab does, but only that area: ImageGrab copies
    every screen whole and then cuts the box out, which on a PC with three
    screens, one 4K, was a lot of copying twenty times a second). None if it
    couldn't be (the caller falls back to ImageGrab)."""
    import ctypes
    from ctypes import wintypes
    from PIL import Image
    left, top, right, bottom = (int(v) for v in box)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return None
    try:
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        user32.GetDC.restype = wintypes.HDC
        user32.GetDC.argtypes = [wintypes.HWND]
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, ctypes.c_uint,
                                           ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi32.DeleteDC.argtypes = [wintypes.HDC]
        gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                 wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
        screen = user32.GetDC(None)
        if not screen:
            return None
        dc = gdi32.CreateCompatibleDC(screen)
        try:
            info = _bitmap_header(width, height)
            bits = ctypes.c_void_p()
            bitmap = gdi32.CreateDIBSection(dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
            if not bitmap:
                return None
            old = gdi32.SelectObject(dc, bitmap)
            try:
                if not gdi32.BitBlt(dc, 0, 0, width, height, screen, left, top, 0x00CC0020):   # SRCCOPY
                    return None
                data = ctypes.string_at(bits, width * height * 4)
            finally:
                gdi32.SelectObject(dc, old)
                gdi32.DeleteObject(bitmap)
        finally:
            gdi32.DeleteDC(dc)
            user32.ReleaseDC(None, screen)
        return Image.frombuffer("RGBX", (width, height), data, "raw", "BGRX", 0, 1).convert("RGB")
    except Exception as e:
        log_once("gdi-grab", f"Screen copy of just the game's area failed, copying every screen instead: {e!r}")
        return None


# How the game's being captured (for the status line and the log).
CAPTURE = {"gdi_black": False, "method": "screen", "dxgi_error": None, "dxgi_failed_at": 0.0, "black_logged": False,
           "window": ""}


def _is_black(image):
    # (shrunk first, then made grey: the same answer for a fraction of the
    # work on a big screen)
    from PIL import Image
    small = image.resize((64, 36), Image.BOX, reducing_gap=2.0).convert("L")
    return max(small.getdata()) < 8


def _black_reason(hwnd):
    """Why every capture of VALORANT is black, as far as can be told."""
    import ctypes
    from ctypes import wintypes
    affinity = wintypes.DWORD(0)
    try:
        ctypes.windll.user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(affinity))
    except Exception:
        pass
    if affinity.value in (1, 0x11):
        why = (f"VALORANT is hiding its window from screen capture (display affinity {affinity.value:#x}): "
               "nothing on this PC can copy it")
    else:
        why = ("VALORANT comes out black when the screen is copied"
               + (f" (graphics card capture: {CAPTURE['dxgi_error']})" if CAPTURE.get("dxgi_error") else
                  " (also off the graphics card)")
               + ". Try: Windows Settings > System > Display > Graphics > turn off 'Optimizations for windowed "
               "games', and turn HDR off, then restart VALORANT")
    if not CAPTURE["black_logged"]:
        CAPTURE["black_logged"] = True
        log(why, "warn")
    return why


_dxgi = {}


def _dxgi_grab(box):
    """The screen area box = (left, top, right, bottom) in desktop pixels,
    copied off the graphics card (DXGI desktop duplication, via dxcam), or
    None."""
    if time.time() - CAPTURE["dxgi_failed_at"] < 30:
        return None
    try:
        import dxcam
        from PIL import Image
        factory = vars(dxcam)["__factory"]
        x, y = box[0], box[1]
        for d, outputs in enumerate(factory.outputs):
            for o, out in enumerate(outputs):
                r = out.desc.DesktopCoordinates
                if r.left <= x < r.right and r.top <= y < r.bottom:
                    cam = _dxgi.get((d, o))
                    if cam is None:
                        cam = _dxgi[(d, o)] = dxcam.create(device_idx=d, output_idx=o, output_color="RGB",
                                                           processor_backend="numpy")
                    region = (max(0, box[0] - r.left), max(0, box[1] - r.top),
                              min(r.right - r.left, box[2] - r.left), min(r.bottom - r.top, box[3] - r.top))
                    frame = cam.grab(region=region, new_frame_only=False)
                    if frame is None:
                        return None
                    return Image.fromarray(frame)
        raise RuntimeError("no display holds the VALORANT window")
    except Exception as e:
        CAPTURE["dxgi_failed_at"] = time.time()
        if CAPTURE["dxgi_error"] != repr(e):
            CAPTURE["dxgi_error"] = repr(e)
            log(f"Graphics card capture failed: {e!r}", "warn")
        return None


def _uncovered(hwnd, x, y, width, height):
    """Is VALORANT what's on screen across this area? (Checked at a grid of
    points: the top bar, the middle and the corners.)"""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetAncestor.restype = wintypes.HWND
    target = user32.GetAncestor(hwnd, 2) or hwnd   # GA_ROOT
    for fx in (0.02, 0.25, 0.5, 0.75, 0.98):
        for fy in (0.02, 0.5, 0.98):
            pt = wintypes.POINT(x + int(width * fx), y + int(height * fy))
            at = user32.WindowFromPoint(pt)
            if not at or (user32.GetAncestor(at, 2) or at) != target:
                return False
    return True


def _print_window(hwnd, width, height):
    """The window's client area as Windows composes it, even when other
    windows are over it, or None (it came back black: no picture)."""
    import ctypes
    from ctypes import wintypes
    from PIL import Image
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, ctypes.c_uint,
                                       ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.c_uint]

    info = BITMAPINFOHEADER()
    info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.biWidth, info.biHeight = width, -height   # top-down rows
    info.biPlanes, info.biBitCount = 1, 32
    bits = ctypes.c_void_p()
    dc = gdi32.CreateCompatibleDC(None)
    bitmap = gdi32.CreateDIBSection(dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
    if not bitmap:
        gdi32.DeleteDC(dc)
        return None
    old = gdi32.SelectObject(dc, bitmap)
    try:
        # PW_CLIENTONLY | PW_RENDERFULLCONTENT: DirectX games come out too.
        if not user32.PrintWindow(hwnd, dc, 1 | 2):
            return None
        data = ctypes.string_at(bits, width * height * 4)
    finally:
        gdi32.SelectObject(dc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(dc)
    image = Image.frombuffer("RGBX", (width, height), data, "raw", "BGRX", 0, 1).convert("RGB")
    small = image.resize((64, 36))
    if max(max(p) for p in _pixels(small)) < 8:
        return None
    return image


def make_dpi_aware():
    import ctypes
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()


class BuyBanner:
    """The buy phase, from the BUY PHASE banner (whatever it says under
    ROUND n): on as soon as it's seen, off once it's been gone for two reads
    running (the round has started: the timer shows 1:40)."""

    def __init__(self):
        self.on, self.missed = False, 0

    def seen(self, banner):
        if banner:
            self.on, self.missed = True, 0
        elif self.on:
            self.missed += 1
            if self.missed >= 2:
                self.on = False
        return "buy" if self.on else "combat"


def _name_key(text):
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


def _close_names(a, b):
    """Two readings of one name? (the same letters, one cut short, or a
    letter or two off)."""
    import difflib
    a, b = _name_key(a), _name_key(b)
    if not a or not b:
        return False
    if a == b or (min(len(a), len(b)) >= 3 and (a.startswith(b) or b.startswith(a))):
        return True
    return len(a) >= 4 and len(b) >= 4 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


class NameKeeper:
    """Seat names for a map, read off the Tab scoreboard (a few times a
    round). A name counts once it's been read the same twice; once it's been
    read LOCK times it's the seat's name for the map. After that:
      - a reading with the same letters (spaces apart), a team tag in front
        ("SPHI f4ngz"), cut short or a letter off is a misread of it: the
        name stays (written with the fewest spaces it's been read with);
      - a plainly different name (the seats were swapped round) takes
        CHANGE readings in a row."""

    LOCK = 4
    CHANGE = 6

    def __init__(self):
        self.seats = {}   # seat -> {"name", "counts": {text: n}, "locked", "pending", "run"}

    def name(self, seat):
        return (self.seats.get(seat) or {}).get("name")

    def locked(self, seat):
        return bool((self.seats.get(seat) or {}).get("locked"))

    def offer(self, seat, text):
        text = " ".join(str(text or "").split())
        s = self.seats.setdefault(seat, {"name": None, "counts": {}, "locked": False, "pending": None, "run": 0})
        have = s["name"]
        if not text:
            return have
        if have and self._tagged(text, have):
            return have   # (a team tag left on: not counted)
        if have and (_close_names(text, have) or self._tagged(have, text)):
            s["pending"], s["run"] = None, 0
            if self._tagged(have, text):
                # (the tag was on the first readings: the name is without it)
                s["counts"] = {text: s["counts"].pop(have, 0)}
            s["counts"][text] = s["counts"].get(text, 0) + 1
            s["name"] = self._best(s["counts"])
            s["locked"] = s["locked"] or sum(s["counts"].values()) >= self.LOCK
            return s["name"]
        # A different name.
        s["run"] = s["run"] + 1 if s["pending"] and _name_key(s["pending"]) == _name_key(text) else 1
        s["pending"] = text
        need = self.CHANGE if s["locked"] else 2
        if have is None and s["run"] >= 2 or have is not None and s["run"] >= need:
            s.update(name=text, counts={text: s["run"]}, locked=False, pending=None, run=0)
        return s["name"]

    @staticmethod
    def _best(counts):
        """The name the readings of one name agree on: the letters read most
        (the longer on a tie: names get cut short, not made longer), written
        with the fewest spaces it's been read with twice."""
        by_key = {}
        for t, n in counts.items():
            by_key[_name_key(t)] = by_key.get(_name_key(t), 0) + n
        key = max(by_key, key=lambda k: (by_key[k], len(k)))
        # (text recognition puts spaces into names more than it drops them:
        # the fewest spaces of those read twice or more)
        return max((t for t in counts if _name_key(t) == key),
                   key=lambda t: (counts[t] >= 2, -t.count(" "), counts[t]))

    @staticmethod
    def _tagged(text, name):
        """text is name with a short team tag in front ("SPHI f4ngz")."""
        words = text.split()
        return len(words) >= 2 and len(words[0]) <= 5 and _name_key(" ".join(words[1:])) == _name_key(name)


class ReadingHealth:
    """How the reading's going, in one line for Live data: what it's found on
    the last minute's frames, how long a full read takes, and how many
    readings the game's rules held back this map (each one kept as a frame
    in frames/auto for the Problem report)."""

    WINDOW = 60.0
    SLOW = 1.5   # seconds a full read; slower and deaths, kills and the score lag

    def __init__(self):
        self.frames = []        # (time, what: "none" / "black" / "select" / "match" / "other")
        self.reads = []         # (time, seconds a full read took)
        self.held = {"score": 0, "kda": 0, "name": 0}

    def new_map(self):
        self.held = {k: 0 for k in self.held}

    def frame(self, what, now=None):
        now = time.time() if now is None else now
        self.frames = [f for f in self.frames if now - f[0] < self.WINDOW] + [(now, what)]

    def read(self, took, now=None):
        now = time.time() if now is None else now
        self.reads = [r for r in self.reads if now - r[0] < self.WINDOW] + [(now, took)]

    def info(self, now=None):
        now = time.time() if now is None else now
        frames = [w for t, w in self.frames if now - t < self.WINDOW]
        reads = [d for t, d in self.reads if now - t < self.WINDOW]
        warn = []
        if frames:
            n = len(frames)
            if frames.count("none") > n / 2:
                warn.append("VALORANT's window isn't being found: pick it under Game window")
            elif frames.count("black") > n / 4:
                warn.append(f"{frames.count('black')} of the last {n} captures were black (the game hidden or minimised)")
        took = sum(reads) / len(reads) if reads else None
        if took and took > self.SLOW:
            warn.append(f"a full read takes {took:.1f} s (the PC is busy): turn on 'Run game HUDs as separate "
                        "programs' in Settings, or close what else is running")
        held = ", ".join(f"{n} {k}" for k, n in self.held.items() if n)
        line = ("Reading check: " + ("; ".join(warn) + "." if warn else "good.") +
                (f" Misreads held back this map: {held}." if held else "") +
                (f" Full read {took:.1f} s." if took and not warn else ""))
        return {"line": line, "warn": bool(warn), "read_s": round(took, 2) if took else None,
                "held": dict(self.held), "frames": {w: frames.count(w) for w in set(frames)}}


class ScreenReader:
    """Reads the game in the background and hands each update to `send`."""

    def __init__(self, send):
        self.send = send
        self.status = "off"
        self.enabled = False
        self.last = None
        self.read_at = 0.0
        self.agents = {}       # (side, slot) -> agent, kept for the match
        self._agent_votes = {}
        self.banner = BuyBanner()
        from .killfeed import LiveKda
        self.kda = LiveKda()   # K/D/A through the round (scoreboard + deaths + kill feed)
        self._dead_reads = {}  # seat -> reads running its health bar's been gone (or back)
        self._stop = threading.Event()
        self._thread = None
        self.spectate, self.spectate_status = False, "off"
        self._spectate_stop = threading.Event()
        self._spectate_thread = None
        self.ocr = None
        self.select = SelectTracker(self.send)   # agent select, when it's on screen
        self.recorder = None   # recorder.MatchRecorder, set by the app: keeps frames for replay
        from .tracker import Tracker
        self.tracker = Tracker()   # the new reader, in shadow mode (tracker.py)
        from .config import DATA_DIR
        from .glyphbank import GlyphBank
        self.bank = GlyphBank(os.path.join(DATA_DIR, "glyphs.json"))   # digits by shape (glyphbank.py)
        self._bank_saved = time.time()
        self._shadow_differs = 0.0
        self.health = ReadingHealth()
        self.available, self.reason = self._check()

    def _check(self):
        if sys.platform != "win32":
            return False, "Reading the screen only works on Windows"
        make_dpi_aware()  # real pixels, whatever the display scaling
        try:
            import numpy  # noqa: F401
            import PIL  # noqa: F401
            self.ocr = WindowsOcr()
        except Exception as e:
            return False, f"Screen reading unavailable: {e!r}"
        return True, ""

    def info(self):
        return {"available": self.available, "enabled": self.enabled, "status": self.status if self.available else self.reason,
                "detail": getattr(self, "detail", "") if self.enabled else "",
                "window": CAPTURE.get("window", ""),
                "spectate": self.spectate, "spectate_status": self.spectate_status if self.available else self.reason,
                "age": round(time.time() - self.read_at, 1) if self.read_at else None,
                "health": self.health.info() if self.enabled else None}

    def set_enabled(self, on):
        self.enabled = bool(on) and self.available
        if self.enabled and not (self._thread and self._thread.is_alive()):
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            threading.Thread(target=self._run_alive, daemon=True).start()
            log("Reading VALORANT off the screen")
        elif not self.enabled:
            self._stop.set()
            self.status = "off"

    def stop(self):
        self._stop.set()
        self._spectate_stop.set()

    SPECTATE_EVERY = 0.25
    SPECTATE_FAST = 0.1   # with the observer card: its portrait is quick to check

    def set_spectate(self, on):
        """Observer client: track who's being spectated (sent with send())."""
        if on and not self.available:
            raise ValueError(self.reason)
        self.spectate = bool(on)
        if self.spectate and not (self._spectate_thread and self._spectate_thread.is_alive()):
            self._spectate_stop.clear()
            self._spectate_thread = threading.Thread(target=self._run_spectate, daemon=True)
            self._spectate_thread.start()
            log("Scanning for the spectated player")
        elif not self.spectate:
            self._spectate_stop.set()
            self.spectate_status = "off"
            try:
                self.send({"source": "observer", "spectating": {"text": ""}})
            except Exception:
                pass

    def _run_spectate(self):
        last, sent_at, last_reason = None, 0.0, None
        text, text_at, wait = "", 0.0, self.SPECTATE_EVERY
        while not self._spectate_stop.is_set():
            reason = None
            try:
                image, reason = capture_valorant()
                # Agent select (read and sent by the tracker, twice a second
                # while it's up, else checked once a second): nobody to spectate.
                since = time.time() - self.select.checked_at
                if image is not None and (since >= 1 or (self.select.active and since >= 0.5)):
                    if self.select.check(image, self.ocr):
                        image = None
                elif self.select.active:
                    image = None
                if image is not None:
                    frame = Frame(image)
                    # The observer card's portrait says who it is in a few
                    # milliseconds: a cut is sent straight away, and the name
                    # (slow to read) follows in the next look. Without a card
                    # (tournament spectating) the name is all there is.
                    agent, side = spectated_agent(frame)
                    if agent:
                        wait = self.SPECTATE_FAST
                        if last and (agent, side) != (last.get("agent"), last.get("side")):
                            text, text_at = "", 0.0
                        elif time.time() - text_at > 2:
                            text, text_at = spectated_text(frame, self.ocr), time.time()
                    else:
                        wait = self.SPECTATE_EVERY
                        text = spectated_text(frame, self.ocr)
                    reading = {"text": text, "agent": agent, "side": side}
                    if reading != last or time.time() - sent_at > 1:
                        reply = self.send({"source": "observer", "spectating": reading}) or {}
                        last, sent_at = reading, time.time()
                        who = reply.get("observed") if isinstance(reply, dict) else None
                        self.spectate_status = (f"Spectating {who}" if who else
                                                "Not spectating anyone (free cam)" if not text and not agent else
                                                f"Read \"{text or agent}\": no player by that name or agent on the HUD")
            except Exception as e:
                reason = f"Couldn't send to the GFX PC: {e}" if isinstance(e, OSError) else f"Scan failed: {e!r}"
            if reason:
                self.spectate_status = reason
            if reason != last_reason:
                if reason:
                    log(reason, "warn")
                last_reason = reason
            self._spectate_stop.wait(wait)

    def save_frame(self, folder):
        """Capture the screen as the reader sees it and save it with what was
        read from it (for checking and tuning the reader). Returns the path."""
        import json
        image, reason = capture_valorant()
        if image is None:
            raise ValueError(reason)
        update = read_frame(image, self.ocr, self.agents, self.bank)
        os.makedirs(folder, exist_ok=True)
        base = os.path.join(folder, time.strftime("frame-%Y%m%d-%H%M%S"))
        image.save(base + ".png")
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(update, f, indent=1)
        return base + ".png"

    KEEP_EVERY, KEEP_MAX = 30.0, 20

    def _keep_frame(self, image, why):
        """Save a frame the reader couldn't make sense of to frames/auto (by
        the app), at most one every 30 s and 20 a run: send them in to have
        the reader taught that screen."""
        now = time.time()
        kept_at = self.__dict__.setdefault("_kept_at", {})
        if now - kept_at.get(why, 0) < self.KEEP_EVERY or getattr(self, "_kept", 0) >= self.KEEP_MAX:
            return
        kept_at[why], self._kept = now, getattr(self, "_kept", 0) + 1
        try:
            from .config import DATA_DIR
            folder = os.path.join(DATA_DIR, "frames", "auto")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, time.strftime(f"%Y%m%d-%H%M%S-{why}.png"))
            image.save(path)
            log(f"Problem frame saved ({why}): {os.path.basename(path)}", "warn")
        except OSError:
            pass

    def scan_names(self):
        """Read every name off the Tab scoreboard carefully and say whose
        seat each belongs to: {"left": {1: "name", ...}, "right": {...}}.
        The scoreboard must be open."""
        if not self.ocr:
            raise ValueError(self.reason or "Windows text recognition isn't available")
        image, reason = capture_valorant()
        if image is None:
            raise ValueError(reason)
        frame = Frame(image)
        if not scoreboard_open(frame):
            where = CAPTURE.get("window")
            raise ValueError("Open the Tab scoreboard in VALORANT (it's up in the buy phase), then scan"
                             + (f". Reading {where}: if that's not the game, pick it under Live Game > Game window"
                                if where else ""))
        update = read_frame(image, None, self.agents)
        self._learn_agents(update)
        top_agents = {(p["team"], p["slot"]): self.agents.get((p["team"], p["slot"])) or p.get("agent")
                      for p in update["players"]}
        names, missed = {"left": {}, "right": {}}, []
        for side in ("left", "right"):
            assign, _ = seat_rows(frame, side, top_agents, self.agents)
            for r in range(frame.board["rows"]):
                name = read_name(frame, side, r, self.ocr)
                if r in assign and name:
                    names[side][assign[r]] = name
                elif name:
                    missed.append(name)
        return names, missed

    ALIVE_EVERY = 0.1   # seconds between top-bar checks (deaths show within about this)
    ALIVE_TOP = 170     # rows of the screen the health bars and BUY PHASE banner need (1080p)

    def _run_alive(self):
        """Deaths and health, fast: only the top bar's health bars, about ten
        times a second, on their own (the full read, with text recognition,
        takes a second or more). The full read leaves these to this loop."""
        last, sent_at = None, 0.0
        while not self._stop.is_set():
            try:
                image, reason = capture_valorant(top=self.ALIVE_TOP)
                frame = Frame(image) if image is not None else None
                players = []
                for side in ("left", "right") if frame else ():
                    for slot in range(1, 6):
                        alive, health = health_bar(frame, side, slot)
                        players.append({"team": side, "slot": slot, "alive": alive, "health": health})
                # Only off the match's top bar: on agent select, a loading
                # screen or a menu every bar reads as gone (everyone dead,
                # and a death counted for each).
                if frame and in_match(frame, [p["alive"] for p in players]):
                    update = {"source": "screen", "players": players}
                    if attacking_side(frame):   # the top bar's on screen: the phase can be told
                        update["match"] = {"phase": self.banner.seen(buy_phase(frame))}
                        self._count_deaths(players)
                    self._add_kda(players)
                    key = [(p["alive"], p["health"], p.get("kills"), p.get("deaths")) for p in players] + \
                        [update.get("match")]
                    if key != last or time.time() - sent_at > 1:
                        self.send(update)
                        last, sent_at = key, time.time()
                    self.fast_at = time.time()
            except Exception as e:
                # (the full read reports capture problems; this says when
                # the death / health check itself breaks)
                log_once("alive-loop", f"Health bar check failed: {e!r}")
            self._stop.wait(self.ALIVE_EVERY)

    DEAD_READS = 2     # a health bar gone this many reads running is a death...
    BACK_FOR = 0.7     # ...and back (two reads or more) this many seconds is alive again

    def _count_deaths(self, players, now=None):
        """A health bar gone for two reads running is a death (one for each
        life: the player has to be back first). Back to life takes 0.7 s of
        the bar showing (by the clock, not reads: the loop slows down when the
        PC's busy): a bar hidden for a moment mid-round (a flash, something
        drawn over it) used to make a second death in the same round when it
        came back and went again. A real comeback (the
        next round, a revive) shows the bar for much longer. The death goes
        in at the time the bar was first seen gone."""
        now = time.time() if now is None else now
        for p in players:
            seat = (p["team"], p["slot"])
            state, n, since = self._dead_reads.get(seat, (p["alive"], 0, now))
            if p["alive"] == state:
                n += 1
            else:
                state, n, since = p["alive"], 1, now
            if state and n >= self.DEAD_READS and now - since >= self.BACK_FOR and n > 0:
                self.kda.alive(seat, True, at=since)
                n = -10 ** 9   # (counted: not again until it changes)
            elif not state and n == self.DEAD_READS:
                self.kda.alive(seat, False, at=since)
            self._dead_reads[seat] = (state, n, since)

    def _add_kda(self, players, skip=()):
        """Each player's K/D/A so far this round, where the scoreboard's been read."""
        for p in players:
            seat = (p["team"], p["slot"])
            values = None if seat in skip else self.kda.values(seat)
            if values:
                p["kills"], p["deaths"], p["assists"] = values

    def _read_kill_feed(self, image, update, at=None):
        """Kills (and the killer's gun) off the kill feed, mid-round."""
        from . import killfeed
        attackers = update["match"].get("attackers")
        if not attackers or update["match"].get("scoreboard_open") or self.banner.on:
            return
        by_seat = {(p["team"], p["slot"]): p for p in update["players"]}
        for bar in self._kill_bars(Frame(image), attackers):
            if bar["killer"] and bar["victim"] and not bar["team_kill"]:
                if self.kda.kill(bar["killer"], bar["victim"], at=at):
                    log(f"Kill: {bar['killer']} -> {bar['victim']} ({bar['weapon'] or '?'})")
            if bar["killer"] and bar["weapon"] and bar["weapon"] in game.WEAPONS:
                by_seat[bar["killer"]]["weapon"] = bar["weapon"]

    def _kill_bars(self, frame, attackers):
        """killfeed.read(), remembering bars already read (a bar stays up a
        few seconds and moves down as new ones come in)."""
        from . import killfeed
        np = _np()
        cache = getattr(self, "_bar_cache", {})
        now = time.time()
        cache = {k: v for k, v in cache.items() if now - v[0] < 15}
        out = []
        seats = dict(self.agents)
        for bar in killfeed.find_bars(frame):
            x0, y0, x1, y1 = bar[:4]
            sig = (bar[4], bar[5], (np.asarray(frame.crop(x0, y0, x1, y1).convert("L").resize((24, 4))) // 32).tobytes(),
                   attackers, tuple(sorted(seats.items())))
            if sig not in cache:
                cache[sig] = (now, killfeed.read_bar(frame, bar, seats, attackers))
            out.append(cache[sig][1])
        self._bar_cache = cache
        return out

    def _report_held(self, image):
        """This frame's readings the rules held back: logged, kept with the
        match recording, and the frame saved (a few) for the Problem report."""
        held, self._held_now = getattr(self, "_held_now", []), []
        if not held:
            return
        what = "; ".join(w for _, w in held)
        log_once("held-" + held[0][0], f"Held back a misread (the game's rules don't allow it): {what}", "info", every=20)
        rec = self.recorder
        if rec is not None:
            try:
                rec.event("held", {"held": [{"kind": k, "what": w} for k, w in held]})
            except Exception:
                pass
        self._keep_frame(image, "held-" + "-".join(sorted({k for k, _ in held})))

    def _held(self, kind, what):
        """A reading the game's rules held back: counted for Live data's
        reading check, and the frame kept for the Problem report."""
        health = self.__dict__.setdefault("health", ReadingHealth())
        health.held[kind] = health.held.get(kind, 0) + 1
        self._held_now = getattr(self, "_held_now", []) + [(kind, what)]

    def _rounds_started(self):
        """Rounds started so far in this map (the one on included), from the
        steady score; None before a score's been read."""
        score = getattr(self, "_score", None)
        return None if score is None else sum(score) + 1

    def _steady_score(self, update):
        """A new score only counts once it's been read the same twice in a
        row: one misread (10 -> 1 -> 10) would otherwise play round-win
        banners and throw the HUD's buy-phase timing out."""
        m = update["match"]
        score = m.get("score")
        if not score:
            return
        key = (score["left"], score["right"])
        have = getattr(self, "_score", None)
        now = time.time()
        # A new map starts after agent select (or a long while with no score:
        # agent select missed, the reader off between maps).
        if now - getattr(self, "_score_read_at", now) > 60:
            self._select_seen = True
        between_maps = getattr(self, "_select_seen", False)
        self._score_read_at = now
        if key == have:
            self._score_pending, self._score_seen = None, 0
            self._select_seen = False
            return
        # A round on (one side +1) counts at its second read; anything else
        # (a score going down mid-map, a jump of several rounds: the usual
        # misreads, "11" read as "1") needs five reads running. The first
        # score seen, a new map (back near 0-0 from a score the map could
        # have ended at, or from the first rounds) and going back to the
        # score before the last jump (one misread that got through) count at
        # two: "12-11" read as "1-1" twice used to stick for five reads, and
        # cut the round history down to two rounds. Back near 0-0 only counts
        # as a new map after agent select (or a long gap): mid-map it's a
        # misread, and needs the five.
        step = have is None or key == getattr(self, "_score_before", None) or (
            sum(key) <= 2 and between_maps and (max(have) >= 12 or sum(have) <= 3)) or (
            sorted((key[0] - have[0], key[1] - have[1])) == [0, 1])
        self._score_seen = getattr(self, "_score_seen", 0) + 1 if key == getattr(self, "_score_pending", None) else 1
        self._score_pending = key
        if self._score_seen >= (2 if step else 5):
            self._score_before = have
            self._score, self._score_pending, self._score_seen = key, None, 0
            self._select_seen = False
            return
        if self._score_seen == 1 and not step and have is not None:
            self._held("score", f"score {key[0]}-{key[1]} after {have[0]}-{have[1]}")
        m.pop("score", None)
        m.pop("round", None)

    def _steady_names(self, update):
        """Each seat's name off the scoreboard, kept for the map (NameKeeper):
        one misread ("chr" for "chronicle"), a split ("yoog ee") or a team
        tag left on ("SPHI f4ngz") doesn't replace a name read the same many
        times; the name it had stays meanwhile."""
        keeper = self.__dict__.setdefault("names", NameKeeper())
        for p in update["players"]:
            text = p.pop("name", None)
            seat = (p["team"], p["slot"])
            shown = keeper.offer(seat, text) if text else keeper.name(seat)
            if shown:
                p["name"] = shown
            if text and shown and keeper.locked(seat) and _name_key(text) != _name_key(shown) \
                    and not _close_names(text, shown) and not NameKeeper._tagged(text, shown):
                self._held("name", f"{p['team']} {p['slot']}: \"{text}\" for {shown}")

    def _learn_agents(self, update):
        """An agent counts once it's been seen three times in the same seat on
        the top bar (the scoreboard's rows are in score order, so they don't
        say which seat is which). A seat whose agent changes, e.g. in the
        next game, is learned again the same way."""
        for side, slot, agent in update.pop("seen_agents", []):
            key = (side, slot)
            if self.agents.get(key) == agent:
                self._agent_votes.pop(key, None)
                continue
            votes = self._agent_votes.setdefault(key, {})
            votes[agent] = votes.get(agent, 0) + 1
            if votes[agent] >= 3:
                self.agents[key] = agent
                self._agent_votes[key] = {}

    def _record(self, image, selecting):
        """Hands the frame to the match recorder (if there's one), saying
        whether agent select or a match is on it."""
        rec = self.recorder
        if rec is None or image is None:
            return
        try:
            if selecting:
                rec.seen("select")
            elif in_match(Frame(image)):
                rec.seen("match")
            rec.frame(image)
        except Exception as e:
            log_once("recorder", f"Match recorder failed: {e!r}")

    def _shadow(self, update):
        """The frame's raw reading (before today's steadying) goes to the new
        reader (tracker.py), and both are kept with the match recording: what
        the new reader would show is compared with what the HUD showed by
        python -m valhud.replay. Nothing here changes the HUD."""
        import copy
        try:
            raw = copy.deepcopy(update)
            self.tracker.observe(raw)
            rec = self.recorder
            if rec is not None:
                rec.event("obs", raw)
                rec.event("shadow", self.tracker.view())
        except Exception as e:
            log_once("shadow", f"New reader (shadow) failed: {e!r}")

    def _shadow_check(self, update):
        """Logs when the new reader's score and today's disagree for a while."""
        s = (update.get("match") or {}).get("score")
        mine = self.tracker.score.score
        if not s or mine is None:
            return
        if (s["left"], s["right"]) != mine:
            if not self._shadow_differs:
                self._shadow_differs = time.time()
            elif time.time() - self._shadow_differs > 5:
                log_once("shadow-score", f"New reader (shadow) has the score {mine[0]}-{mine[1]}, "
                         f"the HUD has {s['left']}-{s['right']}", "info", every=30)
        else:
            self._shadow_differs = 0.0

    def _describe(self, frame, update):
        """One plain line on what the reader sees now (Live data shows it)."""
        m = update.get("match") or {}
        bits = ["Top bar found" + (f" (the game's picture is inside black bars, {frame.top} px)" if frame.top else "")]
        s, shape = m.get("score"), m.get("score_shape")
        if s:
            bits.append(f"score {s['left']}-{s['right']}" + (
                "" if not shape else " (digit shapes agree)" if shape == s
                else f" (digit shapes say {shape['left']}-{shape['right']})"))
        elif shape:
            bits.append(f"score {shape['left']}-{shape['right']} by digit shapes only")
        else:
            bits.append("score not read")
        if m.get("scoreboard_open"):
            rows = [p for p in update.get("players") or [] if p.get("kills") is not None or p.get("kda_shape")]
            bits.append(f"Tab scoreboard open ({len(rows)} of {len(update.get('players') or [])} rows' K/D/A read)")
        else:
            bits.append("Tab scoreboard closed")
        to = m.get("timeout")
        if to:
            bits.append(f"TIMEOUT {to['state'].upper()} banner ({to.get('caller') or 'side not read'}"
                        + (f", {to['seconds']} s left" if to.get("seconds") is not None else "") + ")")
        known = [f"{name} {len(self.bank.known(kind))}/10" for kind, name in (("score", "score"), ("kda", "K/D/A"))]
        bits.append("digits learned: " + ", ".join(known))
        return "; ".join(bits) + "."

    def _run(self):
        last_reason = None
        while not self._stop.is_set():
            reason = None
            try:
                shot_at = time.time()
                image, reason = capture_valorant()
                if image is not None and self.spectate and time.time() - self.select.checked_at < 0.4:
                    # (the spectate loop read agent select off a frame just
                    # now: not read again, it's the slow part of agent select)
                    selecting = self.select.active
                else:
                    selecting = image is not None and self.select.check(image, self.ocr)
                self._record(image, selecting)
                if image is None:
                    self.health.frame("black" if "black" in str(reason or "").lower() else "none")
                elif selecting:
                    self.health.frame("select")
                if selecting:
                    self._select_seen = True   # (the score may go back to 0-0 now)
                    self.health.new_map()
                    self.tracker.agent_select()
                    if self.kda.base:   # a new game: last game's K/D/A is done with
                        from .killfeed import LiveKda
                        self.kda = LiveKda()
                    # ...and the agents learned for each seat (kept, they'd
                    # put last map's agents on this map's seats until
                    # learned again)
                    self.agents, self._agent_votes = {}, {}
                    self.names = NameKeeper()
                    if self.select.empty_for() > 20:
                        self._keep_frame(image, "agent-select-unread")
                    elif self.select.unread_for() > 8:
                        self._keep_frame(image, "agent-select-cards-unread")
                elif image is not None and attacking_side(Frame(image)) is None:
                    # Neither agent select nor the match's top bar: a screen
                    # the reader doesn't know (kept, a few, for tuning it).
                    self._keep_frame(image, "unknown")
                if image is None:
                    self.detail = ""
                elif self.select.active:
                    self.detail = "Agent select on screen."   # (sent by the agent select tracker: no match to read)
                elif not in_match(Frame(image)):
                    # (a loading screen, a menu, the end of the match: nothing to read)
                    self.health.frame("other")
                    self.detail = "No match on screen (a menu, loading, or the match is over): waiting for the top bar."
                else:
                    self.health.frame("match")
                    self._held_now = []
                    update = read_frame(image, self.ocr, self.agents, self.bank)
                    if time.time() - self._bank_saved > 60:
                        self._bank_saved = time.time()
                        self.bank.save()
                    self.detail = self._describe(Frame(image), update)
                    self._shadow(update)
                    _drop_shadow_fields(update)   # (the shapes' readings are the new reader's: not the HUD's yet)
                    # (this frame's own top-bar agents: a learned one only
                    # stands in where the top bar didn't show another)
                    fresh = {(t, s_): a for t, s_, a in update.get("seen_agents", [])}
                    self._learn_agents(update)
                    self._steady_score(update)
                    self._shadow_check(update)
                    self._steady_names(update)
                    if update["match"].get("scoreboard_open"):
                        for p in update["players"]:
                            if all(p.get(k) is not None for k in ("kills", "deaths", "assists")):
                                if not self.kda.board((p["team"], p["slot"]), p["kills"], p["deaths"], p["assists"],
                                                      at=shot_at, rounds=self._rounds_started()):
                                    seat, read, why = self.kda.last_rejected
                                    self._held("kda", f"{seat[0]} {seat[1]}: {why}")
                    else:
                        try:
                            self._read_kill_feed(image, update, shot_at)
                        except Exception as e:
                            log(f"Kill feed read failed: {e!r}", "warn")
                    # Every seat's K/D/A from the tally, the board's too: the
                    # board's frame is older than deaths the fast loop has
                    # counted since, and a board reading the rules turned
                    # away isn't shown.
                    for p in update["players"]:
                        for k in ("kills", "deaths", "assists"):
                            p.pop(k, None)
                    self._add_kda(update["players"])
                    if time.time() - getattr(self, "fast_at", 0) < 2:
                        # The fast loop has newer alive/health and phase than this frame.
                        update["match"].pop("phase", None)
                        for p in update["players"]:
                            p.pop("alive", None)
                            p.pop("health", None)
                    for p in update["players"]:
                        seat = (p["team"], p["slot"])
                        if seat in self.agents and fresh.get(seat, self.agents[seat]) == self.agents[seat]:
                            p["agent"] = self.agents[seat]
                    self.last, self.read_at = update, time.time()
                    self.health.read(self.read_at - shot_at)
                    self._report_held(image)
                    self.send(update)
            except Exception as e:
                reason = f"Screen read failed: {e!r}"
            self.status = reason or "reading"
            if reason != last_reason:
                log(reason or "Reading the spectator screen", "warn" if reason else "info")
                last_reason = reason
            self._stop.wait(0.5)


class SelectTracker:
    """Agent select off the screen (valhud/selectreader.py): sends each
    reading as {"agent_select": ...}, once a card's new agent or lock has
    been seen twice running (so one misread doesn't flicker), and says when
    agent select is over."""

    HOLD = 120.0   # longest the loading screen keeps agent select up
    AWAY = 15.0    # agent select back after this long off screen is a new one

    def __init__(self, send):
        self.send = send
        self.active = False
        self.checked_at = 0.0
        self.seen_at = 0.0
        self.empty_since = 0.0
        self.unread_since = 0.0   # a card with a portrait no agent matches, since
        self._names = {}
        self._layout = None   # where the cards are (selectreader.Layout), kept while VALORANT runs
        self._steady = {}
        self._pending = {}
        self._lock = threading.Lock()

    def unread_for(self):
        """Seconds a card's shown a portrait the reader can't name."""
        return time.time() - self.unread_since if self.active and self.unread_since else 0.0

    def empty_for(self):
        """Seconds agent select's been on screen with no agent read on any card."""
        return time.time() - self.empty_since if self.active and self.empty_since else 0.0

    def check(self, image, ocr):
        """Is agent select on screen? (If so, it's read and sent.)"""
        from . import selectreader
        with self._lock:
            self.checked_at = time.time()
            if self._layout is None:
                self._layout = selectreader.Layout()
            reading = selectreader.read(image, ocr, self._names, self._layout)
            if reading is None:
                if not self.active:
                    return False
                # Agent select stays up through the loading screen, until the
                # match's top bar shows (or it's been too long).
                in_game = in_match(Frame(image))
                if in_game or time.time() - self.seen_at > self.HOLD:
                    self.active = False
                    self.empty_since = 0.0
                    self._names, self._steady, self._pending = {}, {}, {}
                    self.send({"source": "screen", "agent_select": {"active": False}})
                    log("Agent select over: the match is on")
                    return False
                self.send({"source": "screen", "agent_select": {"active": True}})   # (still up)
                return True
            if self.seen_at and time.time() - self.seen_at > self.AWAY:
                # Gone a while and back (a remake, the next map without the
                # match seen in between): its cards and names start again,
                # the seats may hold other players now.
                self._names, self._steady, self._pending = {}, {}, {}
                self.empty_since = self.unread_since = 0.0
                if self.active:
                    self.send({"source": "screen", "agent_select": {"active": False}})
                self.active = False
            self.seen_at = time.time()
            if not self.active:
                log("Agent select on screen" + (f" ({reading['map']})" if reading.get("map") else ""))
            self.active = True
            if any(p["agent"] for p in reading["players"]):
                self.empty_since = 0.0
            elif not self.empty_since:
                self.empty_since = time.time()
            if not reading.pop("unread", 0):
                self.unread_since = 0.0
            elif not self.unread_since:
                self.unread_since = time.time()
            for p in reading["players"]:
                key, value = (p["team"], p["slot"]), (p["agent"], p["locked"])
                held = self._steady.get(key)
                if held and held[1] and not (value[1] and value[0]):
                    # Locked in is final: a card misread for a moment (its
                    # portrait not matched, the name's colour missed) keeps
                    # its pick. Only another locked reading replaces it.
                    value = held
                if key not in self._steady or self._pending.get(key) == value:
                    self._steady[key] = value
                self._pending[key] = value
                p["agent"], p["locked"] = self._steady[key]
            self.send({"source": "screen", "agent_select": reading})
            return True


def _similar(a, b):
    import difflib
    norm = lambda t: re.sub(r"[^a-z0-9]", "", str(t or "").lower().replace("1", "l").replace("0", "o"))
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio() >= 0.75


TEXT_FIELDS = ("name", "credits", "ult_points", "ult_max", "kills", "deaths", "assists")


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return _main(argv)


def _main(argv):
    """python -m valhud.reader IMAGE [--expect EXPECTED.json]

    Prints what was read from a saved screenshot; with --expect, checks the
    given players' fields and exits 1 on a mismatch.
    """
    import argparse
    import json
    from PIL import Image
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--expect")
    parser.add_argument("--no-ocr", action="store_true")
    args = parser.parse_args(argv)
    ocr = None if args.no_ocr else WindowsOcr()
    image = Image.open(args.image)
    update = read_frame(image, ocr)
    if ocr:  # what the text recognition saw, for tuning
        frame = Frame(image)
        print("score line:", read_score_line(frame, ocr))
        for key, info in read_scoreboard(frame, ocr).items():
            print("row", key, info)
    print(json.dumps(update["match"], ensure_ascii=False))
    for p in update["players"]:
        print(json.dumps(p, ensure_ascii=False))
    if not args.expect:
        return 0
    with open(args.expect, encoding="utf-8") as f:
        expected = json.load(f)
    bad = []
    for key, value in expected.get("match", {}).items():
        if ocr is None and key in ("score", "timer", "round"):
            continue
        if update["match"].get(key) != value:
            bad.append(f"match {key}: read {update['match'].get(key)!r}, expected {value!r}")
    by_slot = {(p["team"], p["slot"]): p for p in update["players"]}
    for e in expected.get("players", []):
        p = by_slot[(e["team"], e["slot"])]
        for key, value in e.items():
            if key in ("team", "slot") or (ocr is None and key in TEXT_FIELDS):
                continue
            if key == "name" and _similar(p.get(key), value):
                continue  # names only need to be close (OCR mixes up l / 1, symbols)
            if p.get(key) != value:
                bad.append(f"{e['team']} {e['slot']} {key}: read {p.get(key)!r}, expected {value!r}")
    print("\n".join(bad) if bad else "OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
