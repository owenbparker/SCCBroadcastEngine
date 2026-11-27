"""Game flow (Hardpoint / Hijack) and the primary colour."""

import copy
import json
import os
import tempfile
import unittest

import numpy as np

from codhud import gameflow
from codhud.app import primary_colour
from codhud.config import DEFAULTS, Config
from codhud.gameflow import Game, GameFlowReader


def play_hardpoint(game, start=0.0, rate=(1, 0)):
    """A Hardpoint game read every half second: each hill one team scores a point a second."""
    t, score = start, [0, 0]
    game.begin(start, 1)
    while game.state == "running" and t < start + 2000:
        t += 0.5
        hill = int((t - start - 0.01) // 60)
        if (t * 2) % 2 == 0:     # (a point a second)
            score[hill % 2] += 1
        game.step(t, score[0], score[1])
    return t


class GameTests(unittest.TestCase):
    def test_hardpoint_to_250(self):
        g = Game("hardpoint")
        play_hardpoint(g)
        self.assertEqual(g.state, "finished")
        self.assertEqual(max(g.tr.last), 250)
        totals = gameflow.hill_totals(g.data)
        # each hill: 60 points to one team
        self.assertEqual(totals[1], (60, 0))
        self.assertEqual(totals[2], (60, 60))
        per = gameflow.hill_points(totals, 5)
        self.assertEqual(len(per), 5)
        self.assertEqual(sum(a for a, _ in per), g.tr.last[0])
        self.assertEqual(sum(b for _, b in per), g.tr.last[1])

    def test_misread_is_ignored(self):
        tr = gameflow.Tracker()
        self.assertEqual(tr.update(1.0, (1, 0)), (1, 0))
        self.assertEqual(tr.update(1.5, (81, 0)), (1, 0))      # (a misread: far too big a jump)
        self.assertEqual(tr.update(2.0, (2, None)), (2, 0))    # (one side unread: kept)
        self.assertEqual(tr.update(2.5, (17, 0)), (2, 0))      # (a throw: read twice before it's taken)
        self.assertEqual(tr.update(3.0, (17, 0)), (17, 0))
        self.assertEqual(tr.update(3.5, (5, 0)), (17, 0))      # (scores never go down)

    def test_last_point_vanishes(self):
        g = Game("hardpoint")
        g.begin(0.0, 1)
        g.tr.last = [249, 100]
        g.tr.changed_at = [0.0, 0.0]
        g.step(10.0, 249, 100)
        g.step(10.5, None, 100)
        g.step(11.0, None, 100)
        self.assertEqual(g.state, "finished")
        self.assertEqual(g.data["left"][-1], 250)

    def test_hijack_halves_and_drives(self):
        g = Game("hijack")
        g.begin(0.0, 1)
        t, s = 0.0, [0, 0]

        def tick(dt=0.5):
            nonlocal t
            t += dt
            return g.step(t, s[0], s[1])
        for _ in range(20):
            tick()
        s[0] += 30                 # a dunk at 10 s...
        tick(); tick()
        for _ in range(20):        # ...and 20 runoff points, the game timer stopped
            s[0] += 1
            tick(1.0)
        clock_in_drive = g.clock(t)
        for _ in range(8):
            tick()
        self.assertIsNone(g.drive)
        self.assertAlmostEqual(g.paused, 21.0, delta=1.5)
        self.assertLess(clock_in_drive, 12)
        d = gameflow.find_drives(g.data["times"], g.data["left"], g.data["right"], g.data["half"])
        self.assertEqual(len(d), 1)
        self.assertEqual((d[0]["chunk"], d[0]["total"], d[0]["bonus"]), (30, 50, 20))
        # the first half's timer runs out: halftime, then the second half from 4:00
        while g.state == "running":
            tick(5.0)
        self.assertEqual(g.state, "halftime")
        self.assertEqual(g.data["times"][-1], 240.0)
        g.countdown_gone(t + 30)
        self.assertEqual((g.state, g.half), ("running", 2))
        self.assertEqual(g.data["times"][-1], 240.0)
        t += 30
        s[1] += 15
        for _ in range(3):
            tick()
        s[0], s[1] = 300, s[1]
        for _ in range(4):
            tick(1.0)
        v = gameflow.view(g, {"map": "Lotus"})
        self.assertEqual(v["per_half"][0], [50, 0])
        self.assertEqual(v["stats"][1]["throws"], 1)

    def test_scores_climbing_start_the_game(self):
        g = Game("hardpoint")
        for k, pair in enumerate([(10, 4), (11, 4), (12, 4), (12, 5)]):
            g.step(float(k), *pair)
        self.assertEqual(g.state, "running")
        self.assertEqual(g.data["left"][0], 12)     # (joined part way: from the scores on screen)

    def test_saved_and_loaded(self):
        g = Game("hijack")
        g.begin(0.0, 1)
        g.step(1.0, 15, 0)
        g.step(1.5, 15, 0)
        g.meta = {"map": "Lotus", "map_no": 2}
        back = Game.from_dict(json.loads(json.dumps(g.to_dict())))
        self.assertEqual(back.data, g.data)
        self.assertEqual(back.meta["map"], "Lotus")
        self.assertEqual(gameflow.view(back, {})["map_no"], 2)

    def test_demo_hardpoint_is_the_example(self):
        v = gameflow.view(gameflow.demo_game("hardpoint"), {"map": "Reactor U92"})
        self.assertEqual(v["per_hill"], [[40, 43], [27, 45], [49, 39], [31, 60], [6, 63]])
        self.assertEqual(v["labels"][1:6], ["P1", "P2", "P3", "P4", "P5"])
        h = gameflow.view(gameflow.demo_game("hijack"), {})
        self.assertTrue(h["finished"])
        self.assertEqual(h["score"], [267, 308])

    def test_reading(self):
        self.assertEqual(gameflow.number("1O7"), 107)
        self.assertEqual(gameflow.number("I5"), 15)
        self.assertIsNone(gameflow.number("6:11"))
        self.assertIsNone(gameflow.number("999"))
        self.assertEqual(gameflow.mode_of("CDL HARDPOINT"), "hardpoint")
        self.assertEqual(gameflow.mode_of("HIJACK"), "hijack")
        self.assertEqual(gameflow.mode_of("TEAM DEATHMATCH"), "")
        self.assertIsNone(gameflow.mode_of(""))
        self.assertTrue(gameflow.is_starting("STARTING IN"))
        self.assertTrue(gameflow.is_starting("STARTlNG lN"))
        self.assertFalse(gameflow.is_starting("ROUND 2"))


class FakeOcr:
    """Answers what the test says is on screen: the countdown's words, the mode's, the two scores."""

    def __init__(self):
        self.screen = {"countdown": "", "mode": "CDL HARDPOINT", "left": None, "right": None}
        self.score_calls = 0

    def words(self, image):
        w, h = image.size
        if w > 700:                       # (the mode row, the widest)
            return [(self.screen["mode"], 10, 10)]
        if w > h * 2.5:                   # (the countdown banner)
            return [(self.screen["countdown"], 10, 10)] if self.screen["countdown"] else []
        side = "left" if self.score_calls % 2 == 0 else "right"
        self.score_calls += 1
        v = self.screen[side]
        return [] if v is None else [(str(v), 10, 10)]


def frame_with_banner(on):
    f = np.zeros((1080, 1920, 3), dtype=np.uint8)
    if on:
        f[260:280, 890:1030] = 255
        f[265:275, 900:1020:6] = 0
    return f


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.r = GameFlowReader(os.path.join(self.dir, "gameflow"), meta=lambda: {"map": "Lotus", "map_no": 3})
        self.ocr = FakeOcr()
        self.r._ocr, self.r._tried = self.ocr, True
        self.gf = copy.deepcopy(DEFAULTS["gameflow"])

    def look(self, t, banner=False, left=None, right=None):
        self.ocr.screen.update(countdown="STARTING IN" if banner else "", left=left, right=right)
        self.ocr.score_calls = 0
        return self.r.read(frame_with_banner(banner), self.gf, t)

    def test_countdown_starts_the_clock_then_game_kept(self):
        self.look(0.0, banner=True, left=0, right=0)
        self.look(0.5, banner=True, left=0, right=0)
        self.assertEqual(self.r.game.state, "countdown")
        self.assertEqual(self.r.game.mode, "hardpoint")
        for k in range(10):
            self.look(0.6 + k * 0.1, banner=True)
        self.look(1.7, banner=False, left=0, right=0)
        self.look(1.8, banner=False, left=0, right=0)
        g = self.r.game
        self.assertEqual(g.state, "running")
        self.assertAlmostEqual(g.t_start, 1.6, places=2)     # between the last picture with it and the first without
        self.assertEqual(g.meta, {"map": "Lotus", "map_no": 3})
        t, s = 2.0, [0, 0]
        while g.state == "running" and t < 1000:
            t += 0.5
            if (t * 2) % 2 == 0:
                s[int((t - 1.61) // 60) % 2] += 1
            self.look(t, left=s[0], right=s[1])
        self.assertEqual(g.state, "finished")
        games = self.r.games()
        self.assertEqual(len(games), 1)
        self.assertEqual(max(games[0]["score"]), 250)
        # (a restart keeps the game)
        again = GameFlowReader(os.path.join(self.dir, "gameflow"))
        self.assertEqual(again.game.data["left"][-1], g.data["left"][-1])
        # New game: waiting again, the last one still in the list
        self.r.clear()
        self.assertIsNone(self.r.game)
        self.assertEqual(len(self.r.games()), 1)
        shown = self.r.load_game(games[0]["id"])
        self.assertEqual(shown.meta["map"], "Lotus")

    def test_other_modes_not_tracked(self):
        self.ocr.screen["mode"] = "SEARCH AND DESTROY"
        self.look(0.0, banner=True)
        self.look(0.5, banner=True)
        self.assertIsNone(self.r.game)
        self.assertIn("isn't Hardpoint or Hijack", self.r.status)

    def test_start_by_hand(self):
        self.r.start_now("hijack")
        self.assertEqual((self.r.game.mode, self.r.game.state), ("hijack", "running"))
        self.r.end_now()
        self.assertEqual(self.r.game.state, "finished")


class PrimaryColourTests(unittest.TestCase):
    def test_default_is_the_green(self):
        self.assertEqual(primary_colour(copy.deepcopy(DEFAULTS)), "#00542C")

    def test_own_and_global(self):
        cfg = copy.deepcopy(DEFAULTS)
        cfg["overlay"]["colour"] = "#7a1fd6"
        self.assertEqual(primary_colour(cfg), "#7A1FD6")
        cfg["overlay"]["global_colour"] = True
        self.assertEqual(primary_colour(cfg), "#7A1FD6")    # (no Global colour seen yet)
        cfg["overlay"]["global_accent"] = "#ffc52a"
        self.assertEqual(primary_colour(cfg), "#FFC52A")
        cfg["overlay"]["colour"] = "nonsense"
        cfg["overlay"]["global_colour"] = False
        self.assertEqual(primary_colour(cfg), "#00542C")

    def test_old_settings_keep_everything(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        old = copy.deepcopy(DEFAULTS)
        del old["gameflow"]
        for k in ("colour", "global_colour", "global_accent"):
            del old["overlay"][k]
        old["match"]["left"]["name"] = "KEEP ME"
        old["overlay"]["plates"] = False
        with open(path, "w", encoding="utf-8") as f:
            json.dump(old, f)
        c = Config(path).get()
        self.assertEqual(c["match"]["left"]["name"], "KEEP ME")
        self.assertFalse(c["overlay"]["plates"])
        self.assertEqual(c["overlay"]["colour"], "#00542C")
        self.assertEqual(c["gameflow"]["mode"], "auto")


if __name__ == "__main__":
    unittest.main()


class WindowsOcrTests(unittest.TestCase):
    """The scores and the mode read off real score boxes (Windows only: its text recognition)."""

    def test_scores_read(self):
        from PIL import Image
        from codhud.names import WindowsOcr
        try:
            ocr = WindowsOcr()
        except Exception as e:
            self.skipTest(f"no Windows text recognition: {e}")
        here = os.path.join(os.path.dirname(__file__), "fixtures")
        for name, want, mode in (("codcaster-top.png", (24, 20), ""), ("cdl-top.png", (58, 196), "")):
            im = Image.open(os.path.join(here, name)).convert("RGB")
            full = Image.new("RGB", (1920, 1080))
            full.paste(im.resize((1920, round(im.height * 1920 / im.width))), (0, 0))
            frame = np.asarray(full)
            got = tuple(gameflow.read_score(frame, gameflow.DEFAULT_BOXES[k], ocr) for k in ("left", "right"))
            text = gameflow.read_text(frame, gameflow.DEFAULT_BOXES["mode"], ocr)
            print(f"\ngame flow read {name}: {got}, mode {text!r}")
            self.assertEqual(got, want)
            self.assertEqual(gameflow.mode_of(text), mode)
