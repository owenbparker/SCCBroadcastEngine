"""Game Flow (Hardpoint / Hijack): the score over time off the score box."""

import json
import unittest

import numpy as np

from codhud import gameflow
from codhud.gameflow import ScoreFilter, Tracker, hardpoint_summary, read_score, simulate_hardpoint, simulate_hijack


def play(tracker, steps):
    for st in steps:
        tracker.step(*st)
    return tracker.summary()


class FakeOcr:
    """Reads back the number drawn by draw_score (its digits' count of bars)."""

    def __init__(self, text):
        self.text = text
        self.calls = 0

    def words(self, image):
        self.calls += 1
        return [(self.text, 10, 10)] if self.text else []


class ScoreFilterTests(unittest.TestCase):
    def test_only_goes_up_and_drops_misreads(self):
        f = ScoreFilter()
        self.assertEqual(f.update(1.0, (1, 0)), (1, 0))
        self.assertEqual(f.update(1.5, (0, 0)), (1, 0))       # lower: a misread
        self.assertEqual(f.update(2.0, (2, 0)), (2, 0))
        self.assertEqual(f.update(2.5, (200, 0)), (2, 0))     # wild
        self.assertEqual(f.update(3.0, (17, 0)), (2, 0))      # a jump: once isn't enough
        self.assertEqual(f.update(3.5, (17, 0)), (17, 0))     # read the same twice: taken


class HardpointTests(unittest.TestCase):
    def test_a_whole_game(self):
        tr = Tracker(hills=5, map_name="Reactor U92")
        s = play(tr, simulate_hardpoint(seed=4))
        self.assertEqual(tr.state, "final")
        self.assertEqual(s["mode"], "hardpoint")
        self.assertEqual(s["state"], "final")
        self.assertEqual(max(s["score"]), 250)                # (the winning point vanished: still counted)
        self.assertEqual(s["marks"][0], [0, 0])
        self.assertEqual(s["marks"][-1], s["score"])
        self.assertEqual(len(s["per_hill"]), 5)
        # every point is on some hill
        self.assertEqual([sum(p[i] for p in s["per_hill"]) for i in (0, 1)], s["score"])
        self.assertEqual(s["labels"][:6], ["P1", "P2", "P3", "P4", "P5", "P1"])

    def test_hills_by_map(self):
        d = {"times": [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 360, 390, 400],
             "left": [0, 30, 60, 60, 60, 70, 80, 80, 80, 80, 80, 80, 80, 90, 100],
             "right": [0, 0, 0, 30, 60, 60, 60, 90, 120, 150, 180, 210, 240, 240, 240]}
        s = hardpoint_summary(d, 6)
        self.assertEqual(s["marks"], [[0, 0], [60, 0], [60, 60], [80, 60], [80, 120], [80, 180], [80, 240], [100, 240]])
        self.assertEqual(s["labels"], ["P1", "P2", "P3", "P4", "P5", "P6", "P1"])
        self.assertEqual(s["per_hill"][0], [80, 0])           # P1 twice: 60 + 20
        self.assertEqual(s["hill_now"], "P1")

    def test_joining_late_starts_when_the_scores_climb(self):
        tr = Tracker(mode="hardpoint")
        t = 0.0
        for k in range(6):
            t += 1
            tr.step(t, 40 + k, 50, False)
        self.assertEqual(tr.state, "running")
        self.assertEqual(tr.data["left"][0], 43)              # (from the scores on screen)

    def test_search_and_destroy_never_starts(self):
        tr = Tracker()
        t = 0.0
        for score in ((0, 0), (0, 1), (1, 1), (2, 1), (2, 2), (3, 2)):
            for _ in range(20):
                t += 0.5
                tr.step(t, score[0], score[1], False)
        self.assertEqual(tr.summary(), {})                     # (climbing starts a recording, but no mode is ever told)

    def test_off(self):
        tr = Tracker(mode="off")
        self.assertEqual(play(tr, simulate_hardpoint()), {})


class HijackTests(unittest.TestCase):
    def test_a_whole_game(self):
        tr = Tracker(map_name="Sentry")
        s = play(tr, simulate_hijack())
        self.assertEqual(s["mode"], "hijack")
        self.assertEqual(s["state"], "final")
        h1, h2 = s["halves"]
        self.assertEqual([h1[i] + h2[i] for i in (0, 1)], s["score"])
        self.assertGreaterEqual(max(h1), 150)
        # every point came from a score: chunk + runoff
        for team in (0, 1):
            mine = [d for d in s["drives"] if d["team"] == team]
            self.assertEqual(sum(d["total"] for d in mine), s["score"][team])
            self.assertTrue(all(d["chunk"] in (15, 30) and d["total"] == d["chunk"] + d["bonus"] for d in mine))
            st = s["stats"][team]
            self.assertEqual(st["throws"] + st["dunks"], len(mine))
        # each score's runoff is at one moment of the game clock (the timer stood still)
        for d in s["drives"]:
            at = [p for p in s["line"] if p[0] == d["t"]]
            self.assertEqual(max(p[1 + d["team"]] for p in at), d["y1"])
        self.assertLess(len(json.dumps(s)), 20000)

    def test_halftime(self):
        tr = Tracker()
        s = play(tr, simulate_hijack(stop_at_half=True) + [(5000.0, None, None, False)])
        self.assertEqual(tr.state, "halftime")
        self.assertEqual(s["state"], "halftime")
        self.assertIsNone(s["halves"][1])

    def test_a_new_game_keeps_the_last_until_it_starts(self):
        tr = Tracker()
        first = play(tr, simulate_hijack())
        self.assertEqual(tr.summary()["state"], "final")
        tr.step(9000.0, 0, 0, True)
        tr.step(9000.1, 0, 0, True)                          # the next map's countdown
        self.assertEqual(tr.summary()["score"], first["score"])
        tr.step(9005.0, 0, 0, False)
        tr.step(9005.1, 0, 0, False)                         # ... and it's gone: the new game
        self.assertEqual(tr.state, "running")
        self.assertEqual(tr.summary(), {})


class ReadingTests(unittest.TestCase):
    def cell(self, lit=True):
        c = np.full((45, 92, 3), 30, np.uint8)
        if lit:
            c[8:38, 20:30] = 240
            c[8:38, 50:60] = 240
        return c

    def test_score_read_and_cached(self):
        ocr, cache = FakeOcr("1O8"), {}
        self.assertEqual(read_score(self.cell(), ocr, cache, "left"), 108)    # (O read as 0)
        self.assertEqual(read_score(self.cell(), ocr, cache, "left"), 108)
        self.assertEqual(ocr.calls, 1)                                     # the same picture isn't read again

    def test_nothing_there(self):
        self.assertIsNone(read_score(self.cell(lit=False), FakeOcr("5"), {}, "left"))
        self.assertIsNone(read_score(self.cell(), FakeOcr("9999"), {}, "left"))

    def test_lone_digit_read_twice_side_by_side(self):
        class Twice(FakeOcr):
            def words(self, image):
                self.calls += 1
                return [] if self.calls == 1 else [("77", 10, 10)]
        self.assertEqual(read_score(self.cell(), Twice(""), None, None), 7)

    def test_banner_quick_check(self):
        c = self.cell()
        mask = gameflow.banner_mask(c)
        self.assertTrue(gameflow.banner_still(c, mask))
        self.assertFalse(gameflow.banner_still(self.cell(lit=False), mask))


if __name__ == "__main__":
    unittest.main()
