"""The SCC graphics that come with the engine (starter/), and keeping a
workspace's copies of them up to date.

When the engine has newer versions of the SCC graphics, a workspace that
still has a graphic exactly as an older version shipped it (not changed in
Composer) gets the new one in its place, with any files it needs. A graphic
that was changed is left alone; Outputs > Workspace can still add the SCC
graphics a workspace doesn't have.

starter/project.json keeps, for each graphic, the signatures of the
versions shipped before ("pack_history": {name: [signature, ...]}), and
the graphics added to the pack since the first ("pack_new"): a workspace
made from the pack gets each of those once (if it was deleted, it stays
deleted).
"""

import copy
import hashlib
import json
import os
import shutil
import time

from . import export
from .log import log
from .project import new_id


def signature(comp):
    """What a graphic looks like (everything but its id)."""
    body = {k: v for k, v in comp.items() if k != "id"}
    return hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def _read(starter):
    try:
        with open(os.path.join(starter, "project.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return {}


def copy_files(comp, starter, ws):
    """The files a graphic from the pack uses, into the workspace (if not there)."""
    used = set()
    export._walk_assets(comp, used)
    for rel in used:
        src = os.path.join(starter, rel)
        dest = ws.asset_path(rel)
        if dest and os.path.isfile(src) and not os.path.exists(dest):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)


# The text colours the SCC graphics were made with, and the Global colour each
# follows now (set in Control): white is the primary, the golds the secondary.
TEXT_COLOURS = {"#ffffff": "{{Global!Text primary}}", "#ffc52a": "{{Global!Text secondary}}", "#eda81f": "{{Global!Text secondary}}"}
LOOP_TINT = "{{Global!BG loop colour}}"


def link_colours(comp):
    """A graphic's text in the design's white or gold follows Global's text
    colours, and the full-screen picture under a tinted background loop takes
    the loop's colour too. Returns True if anything changed."""
    changed = False
    layers = comp.get("layers") or []
    for i, l in enumerate(layers):
        if l.get("type") == "text":
            to = TEXT_COLOURS.get(str(l.get("color") or "").strip().lower())
            if to:
                l["color"] = to
                changed = True
        elif (l.get("type") == "video" and l.get("tint") == LOOP_TINT and i > 0):
            under = layers[i - 1]
            if (under.get("type") == "image" and not under.get("tint") and not under.get("recolor")
                    and under.get("x", 0) <= 0 and under.get("y", 0) <= 0
                    and under.get("x", 0) + under.get("w", 0) >= 1920 and under.get("y", 0) + under.get("h", 0) >= 1080):
                under["tint"] = LOOP_TINT
                changed = True
    return changed


# Team stats: each side's bars and lines under its name and its stats header
# in that team's colour (Global's Left / Right colour), not the gold / white,
# and the line between the scores always white.
TEAM_BARS = {
    "assets/Team stats/Rectangle 4.png": "{{Global!Left color}}",
    "assets/Team stats/Rectangle 5 copy.png": "{{Global!Left color}}",
    "assets/Team stats/Rectangle 3 copy 10.png": "{{Global!Left color}}",
    "assets/Team stats/Rectangle 4 copy.png": "{{Global!Right color}}",
    "assets/Team stats/Rectangle 5 copy 2.png": "{{Global!Right color}}",
    "assets/Team stats/Rectangle 3 copy 11.png": "{{Global!Right color}}",
    # (the line between the two scores: always white)
    "assets/Team stats/Line 1.png": "#ffffff",
}


def link_team_bars(comp):
    """The Team stats bars follow the teams' colours. Returns True if anything changed."""
    changed = False
    for l in comp.get("layers") or []:
        to = TEAM_BARS.get(l.get("src") or "")
        if to and l.get("type") == "image" and not l.get("recolor") and not l.get("tint"):
            l["recolor"] = to
            changed = True
    return changed


def upgrade(ws, starter):
    """Brings the workspace's untouched SCC graphics up to date. Returns their names."""
    project = _read(starter) if starter else {}
    history = project.get("pack_history") or {}
    done = []
    if history:
        latest = {c["name"]: c for c in project.get("compositions", [])}
        with ws.lock:
            comps = ws.data["compositions"]
            seen = list(ws.data.get("pack_seen") or [])
            # (only for workspaces made from the pack: an empty one stays empty)
            from_pack = any(c.get("name") in latest for c in comps)
            for name in project.get("pack_new") or []:
                if name in seen or name not in latest:
                    continue
                seen.append(name)
                if from_pack and not any(c.get("name") == name for c in comps):
                    fresh = copy.deepcopy(latest[name])
                    fresh["id"] = new_id("c")
                    copy_files(fresh, starter, ws)
                    comps.append(fresh)
                    done.append(name)
            if seen != list(ws.data.get("pack_seen") or []):
                ws.data["pack_seen"] = seen
                ws.changed()
            for i, comp in enumerate(comps):
                new = latest.get(comp.get("name"))
                if not new or signature(comp) not in history.get(comp["name"], []):
                    continue
                if signature(comp) == signature(new):
                    continue
                fresh = copy.deepcopy(new)
                fresh["id"] = comp["id"]
                copy_files(fresh, starter, ws)
                comps[i] = fresh
                done.append(comp["name"])
            # The caster names and handles have their own colour now (before, they
            # took the secondary's); Global's text colour starts as the secondary,
            # so changed copies look the same.
            for comp in comps:
                for l in comp.get("layers") or []:
                    if l.get("type") == "text" and l.get("color") == "{{Global!Caster secondary}}":
                        l["color"] = "{{Global!Caster text}}"
                        if comp["name"] not in done:
                            done.append(comp["name"])
            # Graphics taken out of the pack: the untouched copies go.
            removed = set(project.get("pack_removed") or [])
            keep = [c for c in comps if not (c.get("name") in removed and signature(c) in history.get(c["name"], []))]
            if len(keep) != len(comps):
                done += [c["name"] for c in comps if c not in keep]
                comps[:] = keep
            # What the graphics now share, for a workspace that never set it.
            g = ws.data.get("global") or {}
            pg = project.get("global") or {}
            changed_global = False
            if not g.get("sponsors") and not g.get("sponsor_epoch") and pg.get("sponsors"):
                for sp in pg["sponsors"]:
                    copy_files({"src": sp["logo"]}, starter, ws)
                g["sponsors"] = copy.deepcopy(pg["sponsors"])
                changed_global = True
            # A newer set of sponsors, for a workspace that still has the pack's old one.
            old_set = {"assets/sponsors/Subway.png", "assets/sponsors/NAC Esports.png"}
            if pg.get("sponsor_set", 1) > 1 and g.get("sponsors") and all(sp.get("logo") in old_set for sp in g["sponsors"]):
                for sp in pg["sponsors"]:
                    copy_files({"src": sp["logo"]}, starter, ws)
                g["sponsors"] = copy.deepcopy(pg["sponsors"])
                g["sponsor_epoch"] = round(time.time(), 3)
                changed_global = True
            if "ticker" not in g and pg.get("ticker"):
                g["ticker"] = list(pg["ticker"])
                changed_global = True
            if "schedule" not in g and pg.get("schedule"):
                g["schedule"] = copy.deepcopy(pg["schedule"])
                changed_global = True
            if changed_global:
                ws.data["global"] = g
            if done or changed_global:
                ws.changed()
    # Text colours from Control, and the backdrop following the loop's
    # colour: once for each workspace, every graphic in it (after the update
    # above, so an older untouched copy is still recognised).
    with ws.lock:
        if not ws.data.get("colours_linked"):
            ws.data["colours_linked"] = 1
            done += [c["name"] for c in ws.data["compositions"] if link_colours(c) and c["name"] not in done]
            ws.changed()
    # The Team stats bars in the teams' colours: once for each workspace (a
    # bar set back by hand afterwards stays).
    with ws.lock:
        if not ws.data.get("team_bars_linked"):
            ws.data["team_bars_linked"] = 1
            done += [c["name"] for c in ws.data["compositions"] if link_team_bars(c) and c["name"] not in done]
            ws.changed()
    if done:
        log(f"Brought {len(done)} SCC graphic(s) up to date (or took out the ones the pack no longer has)")
    return done
