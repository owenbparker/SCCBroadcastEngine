"""The agent matching (portraits on the top bar and Tab scoreboard, kill
feed icons, the observer card) is done as a few matrix products
(reader.ncc_many). It must give the same scores as comparing each template
at each place one at a time (the old way, kept here as the reference),
which took up to seconds a frame and held the whole app up."""

import os
import random
import time
import unittest

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def reference_identify(crop, sizes, slack=3, agents=None, kind=None):
    from valhud import game, reader
    np = reader._np()
    c = np.asarray(crop, dtype=np.float32)
    H, W = c.shape[:2]
    out = []
    for agent in agents or game.AGENTS:
        best = -1.0
        for ref in reader._agent_refs(agent, kind):
            h, w = ref.shape[:2]
            for dy in range(0, H - h + 1):
                for dx in range(0, W - w + 1):
                    best = max(best, reader._ncc(c[dy:dy + h, dx:dx + w].ravel(), ref.ravel()))
        for s in sizes:
            rgb, mask = reader._agent_icon(agent, s)
            for dy in range(-slack, slack + 1):
                for dx in range(-slack, slack + 1):
                    y0, x0 = max(0, dy), max(0, dx)
                    y1, x1 = min(H, dy + s), min(W, dx + s)
                    if y1 - y0 < 10 or x1 - x0 < 10:
                        continue
                    m = mask[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
                    if m.sum() < 120:
                        continue
                    v = reader._ncc(c[y0:y1, x0:x1][m].ravel(), rgb[y0 - dy:y1 - dy, x0 - dx:x1 - dx][m].ravel())
                    best = max(best, v)
        out.append((round(best, 3), agent))
    out.sort(reverse=True)
    return out


class MatchingTests(unittest.TestCase):
    def test_ncc_many_is_ncc(self):
        from valhud import reader
        np = reader._np()
        rng = np.random.RandomState(4)
        win = rng.randint(0, 255, (6, 50, 3)).astype(float)
        inside = (rng.rand(6, 50) > 0.2).astype(float)
        win *= inside[..., None]
        rgb = rng.randint(0, 255, (3, 50, 3)).astype(float)
        mask = (rng.rand(3, 50) > 0.3).astype(float)
        got, count = reader.ncc_many(win, inside, reader.templates(rgb, mask))
        for a in range(3):
            for o in range(6):
                m = (mask[a] * inside[o]) > 0
                self.assertAlmostEqual(got[a, o], reader._ncc(win[o][m].ravel(), rgb[a][m].ravel()), places=9)
                self.assertEqual(count[a, o], m.sum())

    def test_flat_is_zero(self):
        from valhud import reader
        np = reader._np()
        got, _ = reader.ncc_many(np.full((1, 20, 3), 7.0), np.ones((1, 20)),
                                 reader.templates(np.random.RandomState(1).rand(1, 20, 3) * 255, np.ones((1, 20))))
        self.assertEqual(got[0, 0], 0.0)

    def test_identify_agent_same_as_one_at_a_time(self):
        from PIL import Image
        from valhud import game, reader
        frame = reader.Frame(Image.open(os.path.join(FIXTURES, "tab_scoreboard.png")).convert("RGB"))
        rng = random.Random(7)
        crops = [("top", reader.top_portrait(frame, side, slot)) for side, slot in (("left", 1), ("right", 3))]
        crops += [("row", reader.row_cell(frame, side, r, "portrait")) for side, r in (("left", 0), ("right", 4))]
        # an icon pasted off to one side, hanging off the crop's edge
        icon = Image.open(os.path.join(reader.WEB_DIR, "hud", "Resources", "Agentes", "Sage", "Sage.png"))
        bg = Image.new("RGB", (46, 46), (40, 60, 80))
        icon = icon.convert("RGBA").resize((44, 44))
        bg.paste(icon, (5, -2), icon)
        crops.append(("top", bg))
        for kind, crop in crops:
            sizes = (40, 42) if kind == "top" else (32, 34, 36)
            agents = sorted(rng.sample(game.AGENTS, 6)) + ["Sage", "Chamber", "Neon"]
            want = reference_identify(crop, sizes, agents=agents, kind=kind)
            got = reader.identify_agent(crop, sizes, agents=agents, kind=kind)
            self.assertEqual(dict((a, v) for v, a in got), dict((a, v) for v, a in want))

    def test_a_scoreboard_frame_is_quick(self):
        # (it was over 5 s with no agents known, over 0.5 s with them known)
        from PIL import Image
        from valhud import reader
        img = Image.open(os.path.join(FIXTURES, "tab_scoreboard.png")).convert("RGB")
        reader.read_frame(img, None, {})
        t = time.perf_counter()
        reader.read_frame(img, None, {})
        self.assertLess(time.perf_counter() - t, 2.0)
