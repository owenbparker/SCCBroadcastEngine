"""Map bans and picks for Call of Duty: the CDL veto for a best of 3, 5 or 7,
and what the map picks / map bans graphics (/map-bans) show.

The veto is the Call of Duty League's (callofdutyleague.com > Competitive
Settings > Map veto process, updated November 10th, 2026). Each mode has its
own bans and picks; Team A and Team B are chosen before the veto (the higher
seed chooses). The best of 3 is the Challengers one (the CDL doesn't play
one).

The control panel keeps it in config["map_bans"]:
    game        "mw4" (Modern Warfare 4, CDL 2027) or "bo7" (Black Ops 7, CDL
                2026): which maps and which third mode (Hijack / Overload)
    pools       {mode: [maps]} (a mode left out: the game's current pool)
    custom      maps added by hand (any name), for the pools
    team_a      "left" or "right"
    bo3, bo5, bo7   {"steps": [{"map"} ...]}: each step's map, in order
    results     {"<game n>": {"left": score, "right": score, "winner": side}}
                the maps played (the picks board's scores and winner logos)
    tournament_logo   the GFX Engine's Global tournament logo (logos/...), shown
                      under the maps until they're picked

Map art: pictures added on the Map bans page (data/codhud/maps), else the
ones that come with the HUD (web/mapbans/maps), else the map's name.
"""

import base64
import os
import re

from .config import DATA_DIR, WEB_DIR

MODES = {"hp": "Hardpoint", "snd": "Search & Destroy", "hij": "Hijack"}

GAMES = {
    # CDL 2027 (Modern Warfare 4): the pool from the CDL's Competitive Settings,
    # updated November 10th, 2026.
    "mw4": {"name": "Modern Warfare 4 (CDL 2027)", "third": "Hijack",
            "maps": ["Cachette", "Coal", "Lithium", "Lotus", "Mumbai", "Munition", "Nautical", "Reactor U92",
                     "Rooftops", "Sentry", "Silkworm", "Transit 213"],
            "pools": {"hp": ["Lotus", "Lithium", "Munition", "Reactor U92", "Rooftops", "Sentry"],
                      "snd": ["Coal", "Lotus", "Munition", "Reactor U92", "Rooftops", "Silkworm"],
                      "hij": ["Lotus", "Lithium", "Munition"]}},
    # CDL 2026 (Black Ops 7): the pool at Champs (July 2026).
    "bo7": {"name": "Black Ops 7 (CDL 2026)", "third": "Overload",
            "maps": ["Blackheart", "Cliff Town", "Colossus", "Den", "Exposure", "Fringe", "Gridlock", "Hacienda",
                     "Plaza", "Raid", "Sake", "Scar"],
            "pools": {"hp": ["Colossus", "Den", "Gridlock", "Hacienda", "Sake", "Scar"],
                      "snd": ["Den", "Fringe", "Gridlock", "Hacienda", "Raid", "Sake"],
                      "hij": ["Den", "Exposure", "Gridlock", "Scar"]}},
}

# Which mode each game of the series is.
MODE_ORDER = {3: ["hp", "snd", "hij"], 5: ["hp", "snd", "hij", "hp", "snd"],
              7: ["hp", "snd", "hij", "hp", "snd", "hij", "snd"]}

# The veto, mode by mode: (action, whose turn, mode, the game it decides,
# who picks the side on it). "decider": the one map of that mode left.
ORDER = {
    3: [("ban", "A", "hp", None, None), ("ban", "B", "hp", None, None), ("pick", "A", "hp", 1, "B"),
        ("ban", "B", "snd", None, None), ("ban", "A", "snd", None, None), ("pick", "B", "snd", 2, "A"),
        ("ban", "A", "hij", None, None), ("pick", "B", "hij", 3, "A")],
    5: [("ban", "A", "hp", None, None), ("ban", "B", "hp", None, None), ("pick", "A", "hp", 1, "B"),
        ("pick", "B", "hp", 4, "A"),
        ("ban", "B", "snd", None, None), ("ban", "A", "snd", None, None), ("pick", "B", "snd", 2, "A"),
        ("pick", "A", "snd", 5, "B"),
        ("ban", "A", "hij", None, None), ("ban", "B", "hij", None, None), ("decider", None, "hij", 3, "B")],
    7: [("ban", "A", "hp", None, None), ("pick", "A", "hp", 1, "B"), ("pick", "B", "hp", 4, "A"),
        ("ban", "A", "snd", None, None), ("pick", "B", "snd", 2, "A"), ("pick", "A", "snd", 5, "B"),
        ("pick", "A", "snd", 7, "A"),
        ("ban", "A", "hij", None, None), ("pick", "A", "hij", 3, "B"), ("decider", None, "hij", 6, "A")],
}

ART_DIR = os.path.join(DATA_DIR, "maps")                 # added on the Map bans page
BUILTIN_ART_DIR = os.path.join(WEB_DIR, "mapbans", "maps")
ART_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def fmt(bo):
    """3, 5 or 7 (a best of 1 or 9 has no CDL veto: the nearest one)."""
    try:
        n = int(str(bo).lower().lstrip("bo") or 5)
    except ValueError:
        n = 5
    return 3 if n <= 3 else 7 if n >= 7 else 5


def game(cfg):
    g = ((cfg.get("map_bans") or {}).get("game") or "mw4")
    return g if g in GAMES else "mw4"


def mode_name(cfg, mode):
    return GAMES[game(cfg)]["third"] if mode == "hij" else MODES[mode]


def all_maps(cfg):
    """Every map that can go in a pool: the game's and the ones added by hand."""
    mb = cfg.get("map_bans") or {}
    out = list(GAMES[game(cfg)]["maps"])
    for m in mb.get("custom") or []:
        m = clean_name(m)
        if m and m.lower() not in {x.lower() for x in out}:
            out.append(m)
    return out


def clean_name(name):
    return re.sub(r"[^\w .'&-]+", "", str(name or "")).strip()[:40]


def pools(cfg):
    """{mode: [maps]}: the saved pools, or the game's current ones."""
    mb = cfg.get("map_bans") or {}
    saved = mb.get("pools") or {}
    known = all_maps(cfg)
    out = {}
    for mode in MODES:
        chosen = saved.get(mode)
        if isinstance(chosen, list):
            out[mode] = [m for m in known if m in chosen]
        else:
            out[mode] = list(GAMES[game(cfg)]["pools"][mode])
    return out


def team_a(cfg):
    return "right" if (cfg.get("map_bans") or {}).get("team_a") == "right" else "left"


def steps(cfg, bo):
    """The veto's steps, filled in: who, what, which mode, the map and the
    game it decides. A decider is the one map of its mode left once the
    others are banned and picked (or the one set by hand)."""
    n = fmt(bo)
    a = team_a(cfg)
    b = "right" if a == "left" else "left"
    who = {"A": a, "B": b}
    pool = pools(cfg)
    known = set(all_maps(cfg))
    saved = ((cfg.get("map_bans") or {}).get(f"bo{n}") or {}).get("steps") or []
    out = []
    for i, (action, turn, mode, game_n, side) in enumerate(ORDER[n]):
        s = saved[i] if i < len(saved) and isinstance(saved[i], dict) else {}
        m = s.get("map") if s.get("map") in known else ""
        out.append({"n": i + 1, "action": action, "team": who[turn] if turn else None, "mode": mode,
                    "mode_name": mode_name(cfg, mode), "game": game_n, "map": m,
                    "side_team": who[side] if side else None})
    for st in out:
        if st["action"] == "decider" and not st["map"]:
            used = {x["map"] for x in out if x["mode"] == st["mode"] and x is not st and x["map"]}
            left = [m for m in pool[st["mode"]] if m not in used]
            if len(left) == 1:
                st["map"] = left[0]
                st["auto"] = True
    return out


def games(cfg, bo):
    """The series, game by game: its mode, the map picked for it, who picked
    it, and its result."""
    n = fmt(bo)
    results = (cfg.get("map_bans") or {}).get("results") or {}
    by_game = {s["game"]: s for s in steps(cfg, n) if s["game"]}
    out = []
    for i, mode in enumerate(MODE_ORDER[n], 1):
        st = by_game.get(i) or {}
        r = results.get(str(i)) or {}
        score = {side: _score(r.get(side)) for side in ("left", "right")}
        winner = r.get("winner") if r.get("winner") in ("left", "right") else None
        if not winner and score["left"] is not None and score["right"] is not None and score["left"] != score["right"]:
            winner = "left" if score["left"] > score["right"] else "right"
        out.append({"n": i, "mode": mode, "mode_name": mode_name(cfg, mode), "map": st.get("map") or "",
                    "picked_by": st.get("team") if st.get("action") == "pick" else None,
                    "decider": st.get("action") == "decider", "score": score, "winner": winner,
                    "done": bool(winner)})
    return out


def _score(v):
    if v in (None, ""):
        return None
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return None


def view(cfg, bo, primary="#D50537"):
    """What the graphics show."""
    n = fmt(bo)
    match = cfg.get("match") or {}
    teams = {side: {k: (match.get(side) or {}).get(k) or "" for k in ("name", "tricode", "logo", "color")}
             for side in ("left", "right")}
    st = steps(cfg, n)
    gs = games(cfg, n)
    for x in st + gs:
        x["art"] = art_url(x["map"]) if x["map"] else ""
    # The bans strip: each team's bans by mode (Team A on top).
    a = team_a(cfg)
    b = "right" if a == "left" else "left"
    bans = {side: {mode: next((s for s in st if s["action"] == "ban" and s["team"] == side and s["mode"] == mode), None)
                   for mode in MODES} for side in (a, b)}
    return {"format": n, "teams": teams, "team_a": a, "team_b": b, "steps": st, "games": gs,
            "bans": [{"team": side, "cells": [dict(bans[side][m] or {}, mode=m, mode_name=mode_name(cfg, m),
                                                   none=bans[side][m] is None) for m in MODES]}
                     for side in (a, b)],
            "modes": [{"id": m, "name": mode_name(cfg, m)} for m in MODES],
            "primary": primary, "tournament_logo": (cfg.get("map_bans") or {}).get("tournament_logo") or ""}


def panel(cfg):
    """What the control panel's Map bans page needs."""
    return {"games": {k: v["name"] for k, v in GAMES.items()}, "game": game(cfg), "maps": all_maps(cfg),
            "game_maps": GAMES[game(cfg)]["maps"], "current_pools": GAMES[game(cfg)]["pools"],
            "pools": pools(cfg), "modes": {m: mode_name(cfg, m) for m in MODES}, "team_a": team_a(cfg),
            "art": {m: art_url(m) for m in all_maps(cfg) if art_path(m)},
            "own_art": [m for m in all_maps(cfg) if _find(ART_DIR, m)],
            "bo3": steps(cfg, 3), "bo5": steps(cfg, 5), "bo7": steps(cfg, 7),
            "games3": games(cfg, 3), "games5": games(cfg, 5), "games7": games(cfg, 7)}


# --- map art ------------------------------------------------------------------

def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")


def _find(folder, name):
    s = slug(name)
    if not s or not os.path.isdir(folder):
        return None
    for ext in ART_EXTS:
        p = os.path.join(folder, s + ext)
        if os.path.isfile(p):
            return p
    return None


def art_path(name):
    """The map's picture: one added here, else the HUD's own."""
    return _find(ART_DIR, name) or _find(BUILTIN_ART_DIR, name)


def art_url(name):
    p = art_path(name)
    if not p:
        return ""
    return f"/map-art/{slug(name)}?v={int(os.path.getmtime(p))}"


def art_by_slug(s):
    s = slug(s)
    for folder in (ART_DIR, BUILTIN_ART_DIR):
        p = _find(folder, s)
        if p:
            return p
    return None


def save_art(name, data_url):
    """A picture for a map, from the control panel (a data: URL); "" takes the
    added one away (the HUD's own, if it has one, is used again)."""
    s = slug(clean_name(name))
    if not s:
        raise ValueError("which map?")
    os.makedirs(ART_DIR, exist_ok=True)
    for ext in ART_EXTS:
        p = os.path.join(ART_DIR, s + ext)
        if os.path.isfile(p) and data_url:
            continue
        if os.path.isfile(p):
            os.remove(p)
    if not data_url:
        return ""
    m = re.fullmatch(r"data:image/(png|jpeg|webp);base64,(.+)", data_url, re.S)
    if not m:
        raise ValueError("send the picture as a PNG, JPG or WebP image")
    ext = {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}[m.group(1)]
    blob = base64.b64decode(m.group(2))
    tmp = os.path.join(ART_DIR, s + ext + ".tmp")
    with open(tmp, "wb") as f:
        f.write(blob)
    for e in ART_EXTS:   # (the old picture, in another format)
        old = os.path.join(ART_DIR, s + e)
        if e != ext and os.path.isfile(old):
            os.remove(old)
    os.replace(tmp, os.path.join(ART_DIR, s + ext))
    return art_url(name)
