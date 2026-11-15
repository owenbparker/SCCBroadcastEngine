"""Digits by shape: the game's own digits, learned from the text recognition.

Windows' text recognition reads VALORANT's numbers well next to words but
gets lone digits wrong in its own ways (a "0" read as nothing, "12" as "1").
The game draws each digit the same every time, so once a digit's shape is
known it can be matched directly: no recognition, no surprises.

The bank starts empty and learns as the reader runs: when the text
recognition reads a number the same way twice running, and the cell holds
exactly as many pieces of ink as the number has digits, each piece is kept
as that digit's shape (for that kind of cell: the top bar's score, the
scoreboard's K/D/A). A shape too like another digit's is never kept. Once
every digit in a cell matches a known shape closely (and no other digit
comes near), the bank reads the cell itself.

It's kept in glyphs.json next to the HUD's settings, so it's ready at the
next match. It reads in shadow mode first: what it read goes beside the text
recognition's reading (match.score_shape, a player's kda_shape) and
python -m valhud.replay shows which was right.
"""

import json
import os
import threading

W, H = 12, 18            # a shape's size once scaled (ink 0..1)
KEEP = 6                 # shapes kept per digit and kind (different sizes, blur)
SAME = 0.06              # closer than this to a kept shape: nothing new to learn
MATCH = 0.16             # a piece this close to a digit's shape is that digit
MARGIN = 0.05            # ...and the next-best digit is at least this much further away
CLASH = 0.12             # a new shape this close to another digit's: not kept (a misread)


def _np():
    import numpy as np
    return np


def pieces(cell, level=150):
    """The pieces of light ink in a cell (a PIL image), left to right, each
    as a W x H array of ink, plus (aspect, height share). [] for no ink."""
    np = _np()
    g = np.asarray(cell.convert("L"), np.float32)
    ink = g >= level
    cols = ink.any(axis=0)
    runs, start = [], None
    for x, c in enumerate(list(cols) + [False]):
        if c and start is None:
            start = x
        elif not c and start is not None:
            runs.append((start, x))
            start = None
    boxes = []
    for x0, x1 in runs:
        ys = np.where(ink[:, x0:x1].any(axis=1))[0]
        if ink[:, x0:x1].sum() >= 4 and len(ys):
            boxes.append((x0, x1, int(ys[0]), int(ys[-1]) + 1))
    if not boxes:
        return []
    tallest = max(b[3] - b[2] for b in boxes)
    out = []
    for x0, x1, y0, y1 in boxes:
        if y1 - y0 < tallest * 0.45:
            continue   # (a speck, the credits sign's tail, a separator)
        out.append(_shape(g[y0:y1, x0:x1], level) + ((x1 - x0) / max(1, y1 - y0), (y1 - y0) / max(1, tallest)))
    return out


def _shape(piece, level):
    from PIL import Image
    np = _np()
    p = np.clip((piece - level * 0.6) / max(1.0, 255 - level * 0.6), 0, 1)
    img = Image.fromarray((p * 255).astype(np.uint8), "L").resize((W, H), Image.BILINEAR)
    return (np.asarray(img, np.float32) / 255,)


def _distance(a, b):
    np = _np()
    return float(np.abs(a[0] - b[0]).mean()) + abs(a[1] - b[1]) * 0.3 + abs(a[2] - b[2]) * 0.5


class GlyphBank:
    def __init__(self, path=None):
        self.path = path
        self.shapes = {}        # kind -> digit -> [(array, aspect, tall)]
        self._seen = {}         # (kind, key) -> the text read there last time
        self._lock = threading.Lock()
        self.changed = False
        self.learned = 0
        self.clashes = 0
        if path:
            self.load()

    # --- reading ---------------------------------------------------------------

    def read(self, kind, cell, level=150):
        """The number in a cell by its digits' shapes, or None when a piece
        isn't clearly one known digit."""
        found = pieces(cell, level)
        if not found:
            return None
        bank = self.shapes.get(kind) or {}
        text = ""
        for p in found:
            scores = sorted((min(_distance(p, s) for s in shapes), d) for d, shapes in bank.items() if shapes)
            if not scores or scores[0][0] > MATCH or (len(scores) > 1 and scores[1][0] - scores[0][0] < MARGIN):
                return None
            text += scores[0][1]
        return int(text) if text.isdigit() and len(text) <= 4 else None

    # --- learning ------------------------------------------------------------------

    def offer(self, kind, key, cell, value, level=150):
        """The text recognition read value (an int) in this cell. Learned from
        when it read the same at this place last time too."""
        if value is None:
            return False
        text = str(int(value))
        last, self._seen[(kind, key)] = self._seen.get((kind, key)), text
        if last != text:
            return False
        return self.learn(kind, cell, text, level)

    def learn(self, kind, cell, text, level=150):
        found = pieces(cell, level)
        if len(found) != len(text) or not text.isdigit():
            return False   # (pieces run together, or a digit the recognition missed: can't tell which is which)
        with self._lock:
            bank = self.shapes.setdefault(kind, {})
            for p, d in zip(found, text):
                others = [s for o, shapes in bank.items() if o != d for s in shapes]
                if others and min(_distance(p, s) for s in others) < CLASH:
                    self.clashes += 1
                    return False   # (looks like another digit: the reading was probably wrong)
            added = False
            for p, d in zip(found, text):
                mine = bank.setdefault(d, [])
                if mine and min(_distance(p, s) for s in mine) < SAME:
                    continue
                mine.append(p)
                del mine[:-KEEP]
                added = True
            if added:
                self.learned += 1
                self.changed = True
            return added

    def known(self, kind):
        return sorted(d for d, shapes in (self.shapes.get(kind) or {}).items() if shapes)

    # --- keeping it -----------------------------------------------------------------

    def load(self):
        np = _np()
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            return
        for kind, digits in (raw.get("shapes") or {}).items():
            for d, shapes in digits.items():
                for s in shapes:
                    try:
                        arr = np.array([int(c) / 9 for c in s["ink"]], np.float32).reshape(H, W)
                        self.shapes.setdefault(kind, {}).setdefault(d, []).append((arr, float(s["aspect"]), float(s["tall"])))
                    except (KeyError, ValueError, TypeError):
                        continue

    def save(self):
        if not self.path or not self.changed:
            return
        with self._lock:
            raw = {"version": 1, "size": [W, H], "shapes": {
                kind: {d: [{"ink": "".join(str(min(9, int(round(v * 9)))) for v in s[0].flatten()),
                            "aspect": round(s[1], 3), "tall": round(s[2], 3)} for s in shapes]
                       for d, shapes in digits.items()} for kind, digits in self.shapes.items()}}
            self.changed = False
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(raw, f)
            os.replace(tmp, self.path)
        except OSError:
            self.changed = True
