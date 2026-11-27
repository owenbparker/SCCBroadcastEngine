"""Game Flow: Call of Duty Hardpoint and Hijack's score over time, from the
CoD HUD (which reads the score box all game, see apps/codhud/codhud/gameflow.py).

The "Game flow" data source, for the Game flow graphic:

    {{Game flow!Title}}          HARDPOINT // REACTOR U92
    {{Game flow!Subtitle}}       GAME FLOW / MAP 1
    {{Game flow!Panel title}}    POINTS PER HILL / POINTS PER HALF
    {{Game flow!Status}}         LIVE, HALFTIME or FINAL
    {{Game flow!Left score}} ... {{Game flow!P1 left}}, {{Game flow!1st half left}},
    {{Game flow!Left throws}} / dunks / runoff / avg ...
    {{Game flow!Data}}           everything, for the graphic's Game flow layers

The last game is kept (gameflow.json in the workspace) until the next game
starts or it's cleared.
"""

import json
import os
import threading
import time

MODES = {"hardpoint": "HARDPOINT", "hijack": "HIJACK"}


def _clean(data):
    """What a HUD sent, checked: {} unless it's a Hardpoint or Hijack game."""
    if not isinstance(data, dict) or data.get("mode") not in MODES:
        return {}
    try:
        json.dumps(data)
    except (TypeError, ValueError):
        return {}
    return data


def rows(data):
    data = data or {}
    mode = data.get("mode") or ""
    out = [["Field", "Value"]]
    add = lambda k, v: out.append([k, "" if v is None else str(v)])   # noqa: E731
    title = MODES.get(mode, "GAME FLOW")
    if data.get("map"):
        title += " // " + str(data["map"]).upper()
    add("Mode", mode.title())
    add("Map", data.get("map") or "")
    add("Map number", data.get("map_no") or "")
    add("Title", title if mode else "")
    add("Subtitle", f"GAME FLOW / MAP {data.get('map_no') or 1}" if mode else "")
    add("Panel title", {"hardpoint": "POINTS PER HILL", "hijack": "POINTS PER HALF"}.get(mode, ""))
    add("Status", {"final": "FINAL", "halftime": "HALFTIME", "live": "LIVE"}.get(data.get("state"), ""))
    score = data.get("score") or ["", ""]
    add("Left score", score[0])
    add("Right score", score[1])
    per = data.get("per_hill") or []
    add("Hills", data.get("hills") or (len(per) if per else ""))
    for i in range(6):
        p = per[i] if i < len(per) else ["", ""]
        add(f"P{i + 1} left", p[0])
        add(f"P{i + 1} right", p[1])
    halves = data.get("halves") or [None, None]
    for i, name in enumerate(("1st half", "2nd half")):
        h = halves[i] if i < len(halves) and halves[i] else ["", ""]
        add(f"{name} left", h[0])
        add(f"{name} right", h[1])
    stats = data.get("stats") or [{}, {}]
    for i, side in enumerate(("Left", "Right")):
        st = stats[i] if i < len(stats) else {}
        for k in ("throws", "dunks", "runoff", "avg"):
            add(f"{side} {k}", st.get(k))
    add("Data", json.dumps(data, separators=(",", ":")) if mode else "")
    return out


class GameFlow:
    """The latest Hardpoint / Hijack game flow, kept on disk."""

    def __init__(self, folder):
        self.path = os.path.join(folder, "gameflow.json")
        self.lock = threading.Lock()
        self.data = {}
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = _clean(json.load(f))
        except (OSError, ValueError):
            self.data = {}

    def update(self, data):
        """A HUD's game flow; an empty one ({}: no game yet) keeps the last
        game's. Returns True when it changed."""
        new = _clean(data)
        if not new:
            return False
        with self.lock:
            if new == self.data:
                return False
            self.data = new
            self._save()
        return True

    def clear(self):
        with self.lock:
            self.data = {}
            self._save()

    def _save(self):
        if not self.data:
            if os.path.exists(self.path):
                os.remove(self.path)
            return
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dict(self.data, at=time.time()), f)
        os.replace(tmp, self.path)

    def rows(self):
        with self.lock:
            return rows({k: v for k, v in self.data.items() if k != "at"})
