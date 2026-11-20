"""Reads the kill feed off the VALORANT spectator screen (top right).

Each kill is a bar: the killer's agent icon and name on their team's colour
(teal for the defenders, red for the attackers), the gun (white) and any
headshot / wallbang marks, then the victim's name and agent icon on their
team's colour. Bars stack down from the top right and fade after a few
seconds.

The Tab scoreboard (read in the buy phase) has everyone's K/D/A, but it's
closed while the round is played: the kill feed is what says, mid-round, who
got a kill and with what gun. See reader.ScreenReader for how kills are
counted (each victim once a round).

Everything is measured on a 1920x1080 frame, like the rest of the reader.
"""

from . import game
from .reader import _agent_icon, _np, identify_weapon, ncc_many, templates, windows

AREA = (1100, 80, 1920, 560)   # where kill bars can be
BAND_H = (22, 48)              # a bar's height
MIN_COLOURED = 110             # coloured pixels in a row of a bar (at least)


def _colours(a):
    """(teal mask, red mask) of an RGB array."""
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    teal = (g > r + 45) & (b > r + 30) & (g > 120)
    red = (r > g + 70) & (r > b + 60) & (r > 150)
    return teal, red


def find_bars(frame):
    """[(x0, y0, x1, y1, killer colour, victim colour)] for each kill bar on
    screen, top first, in 1080p coordinates; colours are "teal" / "red"."""
    np = _np()
    x0, y0, x1, y1 = AREA
    a = np.asarray(frame.crop(*AREA), dtype=np.int32)
    teal, red = _colours(a)
    coloured = teal | red
    rows = coloured.sum(axis=1) >= MIN_COLOURED
    bars, y = [], 0
    while y < len(rows):
        if not rows[y]:
            y += 1
            continue
        start = y
        while y < len(rows) and rows[y]:
            y += 1
        h = y - start
        if not BAND_H[0] <= h <= BAND_H[1]:
            continue
        # The middle of the bar: which columns are which colour.
        m0, m1 = start + h // 4, y - h // 4
        t = teal[m0:m1].mean(axis=0)
        r = red[m0:m1].mean(axis=0)
        cols = np.nonzero((t + r) >= 0.3)[0]
        if len(cols) < 120:
            continue
        left, right = int(cols.min()), int(cols.max())
        # The killer's colour is the left end's, the victim's the right end's
        # (the same for a team kill).
        span = max(8, (right - left) // 8)
        killer = "teal" if t[left:left + span].sum() >= r[left:left + span].sum() else "red"
        victim = "teal" if t[right - span:right + 1].sum() >= r[right - span:right + 1].sum() else "red"
        bars.append((x0 + left, y0 + start, x0 + right + 1, y0 + y, killer, victim))
    return bars


# The agent icons on a bar are a strip across the middle of the agent's
# icon, about twice as wide as the bar is tall: the killer's at the left end
# as drawn in the HUD, the victim's after their name, mirrored. (Measured on
# a real bar: icon 66px for a 32px bar, its rows 18-50; the victim's 68px.)
ICON_K = (2.0, 2.1, 2.2)
ICON_ROWS = (0.45, 0.85)   # where the bar's top falls in the icon, as a part of the bar's height


_strips = {}


def _strip_bank(agents, s, oy, h, mirrored):
    """(templates(), [enough pixels]) of rows oy..oy+h of these agents' icons
    at size s: the part of each icon a bar shows."""
    np = _np()
    key = (tuple(agents), s, oy, h, mirrored)
    got = _strips.get(key)
    if got is None:
        rgbs, masks = [], []
        for agent in agents:
            rgb, mask = _agent_icon(agent, s)
            if mirrored:
                rgb, mask = rgb[:, ::-1], mask[:, ::-1]
            rgbs.append(rgb[oy:oy + h].reshape(-1, 3))
            masks.append(mask[oy:oy + h].reshape(-1))
        masks = np.stack(masks)
        got = (templates(np.stack(rgbs), masks), masks.sum(axis=1) >= 150)
        if len(_strips) > 512:
            _strips.clear()
        _strips[key] = got
    return got


def _icon_agent(frame, x, y0, y1, agents, mirrored, reach=10):
    """The agent whose icon starts near x on this bar, from `agents`, or None."""
    np = _np()
    if not agents:
        return None
    h = y1 - y0
    big = max(round(h * k) for k in ICON_K)
    area = np.asarray(frame.crop(x - reach, y0, x + reach + big, y1), dtype=np.float32)
    agents = list(agents)
    best = np.full(len(agents), -1.0)
    for k in ICON_K:
        s = round(h * k)
        # (every 2 px along the bar, the icon's whole width on it)
        starts = [dx for dx in range(0, 2 * reach + 1, 2) if area[:, dx:dx + s].shape[1] == s]
        if not starts:
            continue
        wins = np.stack([area[:, dx:dx + s].reshape(-1, 3) for dx in starts])
        prepared = windows(wins, np.ones(wins.shape[:2]))
        for oy in range(round(h * ICON_ROWS[0]), min(s - h, round(h * ICON_ROWS[1])) + 1, 2):
            bank, enough = _strip_bank(agents, s, oy, h, mirrored)
            if not enough.any():
                continue
            score, _ = ncc_many(None, None, bank, prepared)
            best = np.maximum(best, np.where(enough, score.max(axis=1), -1.0))
    scores = {agent: float(v) for agent, v in zip(agents, best)}
    ranked = sorted(((v, a) for a, v in scores.items()), reverse=True)
    top = ranked[0][0]
    second = ranked[1][0] if len(ranked) > 1 else -1.0
    return ranked[0][1] if top >= 0.6 and top - second >= 0.1 else None


def _gun(frame, x0, y0, x1, y1):
    """(weapon, score) from the white gun on the killer's part of a bar."""
    np = _np()
    from PIL import Image
    strip = frame.crop(x0, y0 + 2, x1, y1 - 2)
    a = np.asarray(strip.convert("L")) > 190
    cols = a.any(axis=0)
    runs, start, last = [], None, None
    for x, lit in enumerate(cols):
        if lit:
            if start is None:
                start = x
            elif x - last > 3:
                runs.append((start, last))
                start = x
            last = x
    if start is not None:
        runs.append((start, last))
    best = (None, 0.0)
    for a0, a1 in runs:
        if a1 - a0 + 1 < 26:
            continue   # name letters, the headshot mark
        # Guns point right here (left on the scoreboard, where the
        # templates come from).
        piece = strip.crop((a0, 0, a1 + 1, strip.height)).transpose(Image.FLIP_LEFT_RIGHT)
        weapon, score = identify_weapon(piece)
        if weapon and score > best[1]:
            best = (weapon, score)
    return best


def read(frame, seats, attackers):
    """[{"killer": (team, slot) or None, "victim": (team, slot) or None,
    "weapon": name or None, "team_kill": bool}] for the bars on screen, top
    (newest) first.

    seats: {(team, slot): agent} for the players whose agents are known;
    attackers: "left" / "right" (which of our teams the red bars are)."""
    return [read_bar(frame, bar, seats, attackers) for bar in find_bars(frame)]


def read_bar(frame, bar, seats, attackers):
    x0, y0, x1, y1, kc, vc = bar
    h = y1 - y0
    team_of = {"red": attackers, "teal": "right" if attackers == "left" else "left"}
    entry = {"killer": None, "victim": None, "weapon": None, "team_kill": kc == vc}
    for role, colour, x, mirrored in (("killer", kc, x0 + 4, False), ("victim", vc, x1 - 10, True)):
        team = team_of[colour]
        agent = _icon_agent(frame, x, y0, y1, sorted({a for (t, _), a in seats.items() if t == team and a}), mirrored)
        if agent:
            # (Two of the same agent on a team can't be told apart.)
            slots = [s for (t, s), a in seats.items() if t == team and a == agent]
            if len(slots) == 1:
                entry[role] = (team, slots[0])
    weapon, score = _gun(frame, x0 + 2 * h, y0, x1 - h // 2, y1)
    if weapon and score >= 0.55:
        entry["weapon"] = game.weapon_name(weapon)
    return entry


class LiveKda:
    """Each player's K/D/A through the round.

    The Tab scoreboard's numbers (read in the buy phase) are the base; on top
    of them go the deaths seen on the top bar (a health bar gone) and the
    kills read off the kill feed. Each death counts once (a player has to be
    seen alive again before they can die again: next round, or a revive),
    and each death gives one kill, so a bar read many times while it's on
    screen counts once."""

    def __init__(self):
        import threading
        self._lock = threading.Lock()
        self.base = {}       # seat -> [kills, deaths, assists] from the scoreboard
        self.extra = {}      # seat -> [kills, deaths, assists] since
        self.life = {}       # seat -> how many times they've been seen coming back to life
        self.dead = {}       # seat -> dead now (as far as the top bar says)
        self.died = {}       # seat -> the life whose death was counted
        self.killed = {}     # seat -> the life whose killer was credited

    def board(self, seat, kills, deaths, assists):
        with self._lock:
            self.base[seat] = [kills, deaths, assists]
            self.extra[seat] = [0, 0, 0]
            if self.dead.get(seat):
                # (the board already has this death, and the kill for it: a
                # kill bar still up, read after this, mustn't add them again)
                life = self.life.get(seat, 0)
                self.died[seat] = self.killed[seat] = life

    def _add(self, seat, i):
        self.extra.setdefault(seat, [0, 0, 0])[i] += 1

    def alive(self, seat, alive):
        """The top bar's say on a seat (already steady). Returns True when a
        new death was counted."""
        with self._lock:
            was_dead = self.dead.get(seat)
            self.dead[seat] = not alive
            if alive:
                if was_dead:
                    self.life[seat] = self.life.get(seat, 0) + 1
                return False
            if was_dead is None:
                return False   # dead when first seen: not a death we saw happen
            return self._death(seat)

    def _death(self, seat):
        life = self.life.get(seat, 0)
        if self.died.get(seat) == life:
            return False
        self.died[seat] = life
        self._add(seat, 1)
        return True

    def kill(self, killer, victim):
        """A kill bar. Counts once per death, and only while the victim is
        dead (an old bar still up when the next round starts doesn't)."""
        with self._lock:
            if not self.dead.get(victim):
                return False
            life = self.life.get(victim, 0)
            if self.killed.get(victim) == life:
                return False
            self.killed[victim] = life
            self._death(victim)
            if killer and killer[0] != victim[0]:
                self._add(killer, 0)
            return True

    def values(self, seat):
        """(kills, deaths, assists), or None before the scoreboard's been read."""
        with self._lock:
            if seat not in self.base:
                return None
            return tuple(b + e for b, e in zip(self.base[seat], self.extra.get(seat, [0, 0, 0])))
