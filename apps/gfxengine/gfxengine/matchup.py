"""One player in the spotlight, and two players head to head.

"Spotlight" (the Head Chicklet lower third): one player picked in Control
from either team in Global ("left 2"), with their headshot, name, flag,
team and game:

    {{Spotlight!Name}}, {{Spotlight!Headshot}}, {{Spotlight!Line}} (SCC VALORANT)...

"Head to head" (the Head to Head board): a player from each team, the top
one by the game's stats unless one is picked in Control, with four of
their numbers side by side (the game's own: VALORANT K/D/A, ADR or first
kills, KP%, ACS):

    {{Head to head!Left name}}, {{Head to head!Left headshot}},
    {{Head to head!Row 1 title}}, {{Head to head!Left row 1}} ...
"""

import re

from .stats import _kd, _show, _values

SIDES = ("left", "right")
# The four rows for each game; "adr|fk": ADR when the HUD reports it, else first kills.
ROWS = {"valorant": ("kda", "adr|fk", "kp", "acs"), "lol": ("kda", "cs", "kp", "dmg"),
        "rl": ("goals", "saves", "assists", "score"), "overwatch": ("kda", "dmg", "kp", "healing"),
        "cod": ("kda", "dmg", "kp", "kd")}
TITLES = {"kda": "K/D/A", "adr": "ADR", "fk": "FK", "kp": "KP%", "acs": "ACS", "cs": "CS", "dmg": "DMG",
          "healing": "HEAL", "kd": "K/D", "goals": "GOALS", "saves": "SAVES", "assists": "AST", "score": "SCORE"}
EMPTY = {"kda": "0/0/0", "kp": "0%", "kd": "0.00"}
PICK = re.compile(r"^(left|right) ([1-9]|10)$")


def clean_spotlight(v):
    v = str(v or "")
    return v if PICK.match(v) else "left 1"


def clean_h2h(v):
    v = v if isinstance(v, dict) else {}
    out = {}
    for side in SIDES:
        x = str(v.get(side) or "auto")
        out[side] = x if re.match(r"^([1-9]|10)$", x) else "auto"
    return out


def _player(team, n):
    players = (team or {}).get("players") or []
    return players[n - 1] if 0 < n <= len(players) else None


def _game_name(game):
    return {"League of Legends": "LEAGUE", "Rocket League": "ROCKET LEAGUE", "Call of Duty": "CALL OF DUTY",
            "Super Smash Bros. Ultimate": "SMASH"}.get(game, game or "")


def spotlight_rows(g, find, flag):
    """find(side) -> that side's team from the team list (or None); flag(country) -> its flag."""
    pick = clean_spotlight(g.get("spotlight"))
    side, n = pick.split()
    team = find(side) or {}
    gt = g[side]
    p = _player(team, int(n)) or {"name": "", "ign": "", "country": "", "photo": ""}
    short = gt.get("short") or team.get("short") or gt.get("name") or ""
    game = _game_name(team.get("game") or gt.get("game") or "")
    return [["Field", "Value"], ["Pick", pick], ["Side", side], ["Name", p["name"] or p["ign"]], ["ID", p["ign"]],
            ["Headshot", p["photo"]], ["Country", p["country"]], ["Flag", flag(p["country"]) if p["country"] else ""],
            ["Team", gt.get("name") or team.get("name", "")], ["Team short", short],
            ["Team logo", gt.get("logo") or team.get("logo", "")], ["Team color", gt.get("color", "")],
            ["Game", game], ["Line", " ".join(x for x in (short, game) if x)]] + _names(find)


def _names(find):
    """Both teams' players, for Control's pickers: "Left player 1"..."""
    out = []
    for side in SIDES:
        players = (find(side) or {}).get("players") or []
        out += [[f"{side.title()} player {n}", p.get("name") or p.get("ign") or ""] for n, p in enumerate(players[:10], 1)]
    return out


def _rank(game, p):
    v = _values(game, p)
    first = v.get(ROWS.get(game, ROWS["valorant"])[-1])   # (ACS, damage... when it's a number)
    return ((first if isinstance(first, int) else p["stats"][0]), p["stats"][0], p["stats"][2], -p["stats"][1])


def _value(key, game, p, team_kills):
    if p is None:
        return EMPTY.get(key, "0")
    v = _values(game, p)
    if key == "kp":
        k, _, a = p["stats"]
        return f"{round(100 * (k + a) / team_kills)}%" if team_kills else "0%"
    if key == "kd":
        return _kd(p["stats"][0], p["stats"][1])
    return _show(key, v.get(key, ""))


def h2h_rows(g, stats, find, ign_match):
    """stats: the game's stats (stats.read's dict, or None). find(side) -> the
    side's team; ign_match(team, name) -> the roster player the game calls name."""
    picks = clean_h2h(g.get("h2h"))
    game = (stats or {}).get("game") or "valorant"
    keys = []
    for k in ROWS.get(game, ROWS["valorant"]):
        if "|" in k:
            a, b = k.split("|")
            players = [p for side in SIDES for p in ((stats or {}).get(side) or {}).get("players", []) if p["name"]]
            k = a if any((p.get("values") or {}).get(a) not in (None, "") for p in players) else b
        keys.append(k)
    out = [["Field", "Value"], ["Game", game], ["Status", "LIVE" if stats else ""]]
    out += [[f"Row {i + 1} title", TITLES.get(k, k.upper())] for i, k in enumerate(keys)]
    for side in SIDES:
        S = side.title()
        team = find(side) or {}
        gt = g[side]
        sp = [p for p in ((stats or {}).get(side) or {}).get("players", []) if p["name"]]
        team_kills = sum(p["stats"][0] for p in sp)
        pick = picks[side]
        roster_p, stat_p = None, None
        if pick == "auto":
            if sp:
                stat_p = max(sp, key=lambda p: _rank(game, p))
                roster_p = ign_match(team, stat_p["name"])
            else:
                roster_p = _player(team, 1)
        else:
            roster_p = _player(team, int(pick))
            if roster_p:
                ids = {x.lower() for x in (roster_p.get("ign"), roster_p.get("name")) if x}
                stat_p = next((p for p in sp if p["name"].lower() in ids), None)
            elif int(pick) <= len(sp):
                stat_p = sp[int(pick) - 1]
        roster_p = roster_p or {}
        name = roster_p.get("name") or roster_p.get("ign") or (stat_p or {}).get("name", "")
        out += [[f"{S} name", name], [f"{S} ID", roster_p.get("ign") or (stat_p or {}).get("name", "")],
                [f"{S} headshot", roster_p.get("photo", "")], [f"{S} role", (stat_p or {}).get("character", "")],
                [f"{S} team", gt.get("name") or team.get("name", "")],
                [f"{S} team short", gt.get("short") or team.get("short", "") or gt.get("name", "")],
                [f"{S} team logo", gt.get("logo") or team.get("logo", "")], [f"{S} pick", pick]]
        out += [[f"{S} row {i + 1}", _value(k, game, stat_p, team_kills)] for i, k in enumerate(keys)]
    return out
