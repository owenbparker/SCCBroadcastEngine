"""Which of the HUD's teams is which in agent select and in the Riot
Client's roster.

Both only say DEFENDERS / ATTACKERS (Blue / Red): which HUD team that is
comes from "who attacks first" in the control panel. Set wrong (or left from
the last map), every name and agent lands under the other team. So:

  - the players' names seen on each team (in the match, typed in the
    control panel) are kept by team name, and an agent select whose names
    belong to the other team says the sides are the other way round;
  - in the match, the top bar says which team attacks: in rounds 1-12 that's
    the team that attacked first;
  - the Riot Client's roster is checked against the agents on the top bar.
"""

import re

from .game import SIDES

FLIP = {"left": "right", "right": "left"}


def norm(name):
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def _close(a, b):
    """Names that are the same player (text recognition cuts or slips a
    letter; the Riot ID has no team tag)."""
    import difflib
    if len(a) < 3 or len(b) < 3:
        return a == b
    return a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a)) or \
        difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


class Rosters:
    """Player names seen on each team, by team name."""

    def __init__(self):
        self.names = {}   # team name (normalised) -> set of player names (normalised)

    def learn(self, state, cfg):
        for p in state.get("players") or []:
            team = (cfg.get(p.get("team")) or {}).get("name")
            if team and len(norm(p.get("name"))) >= 3:
                self.names.setdefault(norm(team), set()).add(norm(p["name"]))
        for side in SIDES:
            team = (cfg.get(side) or {}).get("name")
            for typed in (cfg.get("player_names") or {}).get(side) or []:
                if team and len(norm(typed)) >= 3:
                    self.names.setdefault(norm(team), set()).add(norm(typed))

    def _hits(self, names, team):
        known = self.names.get(norm(team)) or set()
        return sum(1 for n in names if any(_close(norm(n), k) for k in known))

    def flipped(self, reading, cfg):
        """True when an agent select reading's names (teams "left" / "right")
        are the other team's players; False when they're this team's; None
        when it can't be told."""
        by_side = {side: [p.get("name") for p in reading.get("players") or []
                          if p.get("team") == side and len(norm(p.get("name"))) >= 3] for side in SIDES}
        teams = {side: (cfg.get(side) or {}).get("name") for side in SIDES}
        if not all(teams.values()) or norm(teams["left"]) == norm(teams["right"]):
            return None
        same = sum(self._hits(by_side[side], teams[side]) for side in SIDES)
        other = sum(self._hits(by_side[side], teams[FLIP[side]]) for side in SIDES)
        if other >= 2 and other >= same + 2:
            return True
        if same >= 2 and same >= other + 2:
            return False
        return None


def swap_reading(reading):
    """An agent select reading with its teams the other way round."""
    out = dict(reading)
    out["players"] = [dict(p, team=FLIP.get(p.get("team"), p.get("team"))) for p in reading.get("players") or []]
    return out


def roster_flipped(roster, state):
    """True when the Riot Client's roster (by team, from who attacks first)
    has the teams the other way round from the agents on the top bar."""
    have = {side: {p["agent"] for p in state["players"] if p["team"] == side and p.get("agent")} for side in SIDES}
    riot = {side: {q.get("agent") for q in (roster.get(side) or []) if q.get("agent")} for side in SIDES}
    same = sum(len(have[s] & riot[s]) for s in SIDES)
    other = sum(len(have[s] & riot[FLIP[s]]) for s in SIDES)
    return other >= 3 and other > same


class AttackFirst:
    """Who attacked first, from the top bar: the attacking team in rounds
    1-12 (a 5v5). Returns the side once the same has been read several
    times running, else None."""

    NEEDED = 6

    def __init__(self):
        self.side, self.count = None, 0

    def seen(self, attackers, round_no):
        if attackers not in SIDES or not isinstance(round_no, int) or not 1 <= round_no <= 12:
            return None
        if attackers == self.side:
            self.count += 1
        else:
            self.side, self.count = attackers, 1
        return self.side if self.count >= self.NEEDED else None


def _ign(name):
    """A name to compare: the Riot ID's tag left off ("Bearrett#NA1" -> "bearrett")."""
    return norm(str(name or "").split("#")[0])


class AutoSides:
    """Puts the teams on their sides by themselves: one player's in-game name
    a team (typed on the Teams page, kept by team name so it stays with the
    team when sides swap or the next match loads) and the in-game IDs of the
    team's roster in the GFX Engine's Teams tab.

    verdict() says whether the names seen on each side are the right team's
    ("same"), the other team's ("swapped"), or can't be told (None)."""

    NEEDED = 3        # in-match reads in a row that say "swapped" before the teams swap
    HOLD = 15.0       # seconds after a swap before another

    def __init__(self):
        self.global_igns = {}   # team name (normalised) -> the GFX Engine roster's in-game IDs
        self._wrong, self._swapped_at = 0, float("-inf")
        self.status = ""        # what it last did, for the control panel

    def set_roster(self, team_name, players):
        team = norm(team_name)
        if team:
            self.global_igns[team] = [str(p.get("ign") or "").strip() for p in players
                                      if isinstance(p, dict) and str(p.get("ign") or "").strip()]

    @staticmethod
    def typed(cfg, side):
        team = norm((cfg.get(side) or {}).get("name"))
        return str((cfg.get("team_igns") or {}).get(team) or "").strip() if team else ""

    def known(self, cfg):
        """{"left": {names}, "right": {names}}, or None when nothing's known."""
        teams = {side: norm((cfg.get(side) or {}).get("name")) for side in SIDES}
        if not all(teams.values()) or teams["left"] == teams["right"]:
            return None
        out = {}
        for side in SIDES:
            names = {_ign(self.typed(cfg, side))} | {_ign(n) for n in self.global_igns.get(teams[side]) or []}
            out[side] = {n for n in names if len(n) >= 3}
        both = out["left"] & out["right"]   # (a name on both rosters tells nothing)
        out = {side: out[side] - both for side in SIDES}
        return out if out["left"] or out["right"] else None

    def verdict(self, by_side, cfg):
        """by_side: {"left": [names seen], "right": [...]}."""
        known = self.known(cfg)
        if not known:
            return None

        def hits(names, keys):
            return sum(1 for n in names or [] if len(_ign(n)) >= 3 and any(_close(_ign(n), k) for k in keys))

        same = hits(by_side.get("left"), known["left"]) + hits(by_side.get("right"), known["right"])
        other = hits(by_side.get("left"), known["right"]) + hits(by_side.get("right"), known["left"])
        if other and not same or other >= same + 2:
            return "swapped"
        if same and not other or same >= other + 2:
            return "same"
        return None

    def in_match(self, by_side, cfg, now):
        """A read of the match's names: True when the teams should swap sides
        now (the other team's names seen on each side several reads running)."""
        v = self.verdict(by_side, cfg)
        if v == "same":
            self._wrong = 0
            return False
        if v != "swapped" or now - self._swapped_at < self.HOLD:
            return False
        self._wrong += 1
        if self._wrong < self.NEEDED:
            return False
        self._wrong, self._swapped_at = 0, now
        return True
