"""Tactical timeouts read off the screen (2026-11-25). Most fixtures are from
owen's Lotus recording of 2026-11-19 (round 6: the attackers called a
timeout with the Tab scoreboard open): TIMEOUT STARTING IN, then TIMEOUT
ACTIVE with a red countdown bar. active_defenders_tab_closed is owen's
screenshot of 2026-11-25: white words on the defenders' teal panel, the bar
red all the same."""

import os
import tempfile
import unittest

from valhud import game
from valhud.config import Config
from valhud.timeouts import TimeoutWatch

HERE = os.path.dirname(__file__)


def frame(name):
    from PIL import Image
    return Image.open(os.path.join(HERE, "fixtures", "timeout", name))


def make_app(tmp, **cfg):
    from valhud.app import HudApp
    c = Config(os.path.join(tmp, "config.json"))
    c.update(dict({"output_dir": os.path.join(tmp, "out")}, **cfg))
    return HudApp(c)


class ReadTimeoutTests(unittest.TestCase):
    def setUp(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not installed")

    def read(self, name):
        from valhud.reader import Frame, read_timeout
        return read_timeout(Frame(frame(name)))

    def test_starting(self):
        self.assertEqual(self.read("starting_attackers.webp"),
                         {"state": "starting", "caller": "attackers", "seconds": None})

    def test_active_with_seconds_from_the_bar(self):
        r = self.read("active_attackers_40s.webp")   # the bar says 0:40
        self.assertEqual((r["state"], r["caller"]), ("active", "attackers"))
        self.assertTrue(37 <= r["seconds"] <= 42, r)

    def test_last_seconds(self):
        r = self.read("active_ending.webp")          # 0:00 / 0:01: the bar is all but gone
        self.assertEqual(r["state"], "active")
        self.assertLessEqual(r["seconds"], 2)

    def test_tab_closed_defenders(self):
        r = self.read("active_defenders_tab_closed.webp")   # the bar says 0:52
        self.assertEqual((r["state"], r["caller"]), ("active", "defenders"))
        self.assertTrue(50 <= r["seconds"] <= 54, r)

    def test_no_timeout(self):
        self.assertIsNone(self.read("no_timeout_tab.webp"))
        from valhud.reader import Frame, read_timeout
        for path in (("tab_scoreboard.png",), ("tab_scoreboard_rifles.png",), ("spectate", "card_gora46_cypher.webp"),
                     ("agent_select", "locked_00.webp")):
            from PIL import Image
            self.assertIsNone(read_timeout(Frame(Image.open(os.path.join(HERE, "fixtures", *path)))), path)

    def test_side_label_read_by_text_recognition(self):
        from valhud.reader import Frame, read_timeout

        class Ocr:
            def words(self, image):
                return [("DEFENDERS", 10, 10)]
        from unittest import mock
        with mock.patch("valhud.reader.timeout_panel", return_value=None):   # (panel colour unsure)
            r = read_timeout(Frame(frame("active_attackers_40s.webp")), Ocr())
        self.assertEqual(r["caller"], "defenders")

    def test_read_frame_reports_it(self):
        from valhud.reader import read_frame
        self.assertEqual(read_frame(frame("starting_attackers.webp"))["match"]["timeout"]["state"], "starting")
        self.assertIsNone(read_frame(frame("no_timeout_tab.webp"))["match"]["timeout"])


class WatchTests(unittest.TestCase):
    ACTIVE = {"state": "active", "caller": "attackers", "seconds": 50}

    def test_starts_after_two_reads_on_the_calling_team(self):
        w = TimeoutWatch()
        self.assertIsNone(w.step(self.ACTIVE, "right", now=0))
        self.assertEqual(w.step(self.ACTIVE, "right", now=1), ("start", "right"))
        self.assertEqual(w.live(), {"state": "active", "team": "right", "seconds": 50})
        w2 = TimeoutWatch()
        w2.step(dict(self.ACTIVE, caller="defenders"), "right", now=0)
        self.assertEqual(w2.step(dict(self.ACTIVE, caller="defenders"), "right", now=1), ("start", "left"))

    def test_one_frame_is_not_a_timeout(self):
        w = TimeoutWatch()
        w.step(self.ACTIVE, "left", now=0)
        self.assertIsNone(w.step(None, "left", now=1))
        self.assertIsNone(w.step(self.ACTIVE, "left", now=2))
        self.assertEqual(w.live(), {})

    def test_a_missed_frame_doesnt_end_it(self):
        w = TimeoutWatch()
        w.step(self.ACTIVE, "left", now=0)
        w.step(self.ACTIVE, "left", now=1)
        self.assertIsNone(w.step(None, "left", now=2))
        self.assertIsNone(w.step(self.ACTIVE, "left", now=3))
        self.assertIsNone(w.step(None, "left", now=5))
        self.assertEqual(w.step(None, "left", now=7.5), ("end", "left"))
        self.assertEqual(w.live(), {})

    def test_ends_by_the_clock_and_after_the_longest_timeout(self):
        w = TimeoutWatch()
        w.step(self.ACTIVE, "left", now=0)
        w.step(self.ACTIVE, "left", now=1)
        self.assertIsNone(w.check(now=4))
        self.assertEqual(w.check(now=6), ("end", "left"))
        w.step(self.ACTIVE, "left", now=10)
        w.step(self.ACTIVE, "left", now=11)
        self.assertEqual(w.step(self.ACTIVE, "left", now=120), ("end", "left"))
        self.assertIsNone(w.step(self.ACTIVE, "left", now=121))   # (same banner: not a second timeout)
        self.assertIsNone(w.step(self.ACTIVE, "left", now=122))

    def test_caller_unknown_waits(self):
        w = TimeoutWatch()
        w.step({"state": "active", "caller": None, "seconds": 0}, "left", now=0)
        self.assertIsNone(w.step({"state": "active", "caller": None, "seconds": 0}, "left", now=1))
        self.assertEqual(w.step(self.ACTIVE, "left", now=2), ("start", "left"))


class AppTests(unittest.TestCase):
    def reading(self, timeout, attackers="right"):
        return {"source": "screen", "match": {"attackers": attackers, "timeout": timeout}}

    def test_timeout_card_and_one_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp, left={"name": "Saints", "tricode": "SCC"}, right={"name": "Rutgers", "tricode": "RUT"},
                           timeouts={"left": 2, "right": 2})
            app.ingest(self.reading(dict(WatchTests.ACTIVE)))
            app.ingest(self.reading(dict(WatchTests.ACTIVE)))
            cfg = app.config.get()
            self.assertEqual(cfg["timeout_call"], "right")
            self.assertEqual(cfg["timeouts"], {"left": 2, "right": 1})
            f = app.fields
            self.assertEqual((f["TIMEOUT"], f["TIMEOUT SIDE"], f["TIMEOUT TEAM"], f["TIMEOUT TRI-CODE"]),
                             ("ACTIVE", "RIGHT", "Rutgers", "RUT"))
            self.assertEqual((f["TIMEOUT SECONDS"], f["TIMEOUT TIMER"], f["TIMEOUTS RIGHT"], f["TIMEOUTS LEFT"]),
                             (50, "0:50", 1, 2))
            # more frames of the same timeout: none more used
            app.ingest(self.reading(dict(WatchTests.ACTIVE, seconds=30)))
            self.assertEqual(app.config.get()["timeouts"]["right"], 1)
            # over: the card comes down
            app.timeouts.seen_at -= 10
            app.ingest(self.reading(None))
            cfg = app.config.get()
            self.assertEqual((cfg["timeout_call"], cfg["timeouts"]["right"]), ("", 1))
            self.assertEqual(app.fields["TIMEOUT"], "")

    def test_card_put_up_by_hand_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp, timeouts={"left": 2, "right": 1}, timeout_call="left")   # (pressed, one used)
            for _ in range(2):
                app.ingest(self.reading(dict(WatchTests.ACTIVE, caller="defenders")))   # attackers right: left called it
            cfg = app.config.get()
            self.assertEqual((cfg["timeout_call"], cfg["timeouts"]), ("left", {"left": 2, "right": 1}))

    def test_none_left_stays_at_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp, timeouts={"left": 0, "right": 0})
            for _ in range(2):
                app.ingest(self.reading(dict(WatchTests.ACTIVE)))
            self.assertEqual(app.config.get()["timeouts"], {"left": 0, "right": 0})
            self.assertEqual(app.config.get()["timeout_call"], "right")

    def test_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp, auto_timeouts=False, timeouts={"left": 2, "right": 2})
            for _ in range(2):
                app.ingest(self.reading(dict(WatchTests.ACTIVE)))
            cfg = app.config.get()
            self.assertEqual((cfg["timeout_call"], cfg["timeouts"]), ("", {"left": 2, "right": 2}))
            self.assertEqual(app.fields["TIMEOUT SIDE"], "RIGHT")   # (still in the data for graphics)

    def test_observer_pcs_readings_win(self):
        """owen 2026-11-25: read off the observer PC's extra info (its
        spectate loop), not the main reader PC."""
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp, timeouts={"left": 2, "right": 2})
            obs = {"source": "observer", "spectating": {"text": "", "agent": None, "side": None},
                   "timeout": dict(WatchTests.ACTIVE, caller="defenders", attackers="right")}
            app.ingest(obs)
            # this PC's reader sees nothing (another screen): not used while the observer PC reports
            app.ingest(self.reading(None))
            app.ingest(obs)
            cfg = app.config.get()
            self.assertEqual((cfg["timeout_call"], cfg["timeouts"]["left"]), ("left", 1))
            # ...nor its timeout readings
            for _ in range(3):
                app.ingest(self.reading(dict(WatchTests.ACTIVE)))   # attackers (right) calling
            self.assertEqual(app.config.get()["timeouts"]["right"], 2)
            # the observer PC gone quiet: this PC's reader counts again
            app._observer_timeout_at -= 60
            app.timeouts.seen_at -= 60
            app.ingest(self.reading(None))
            self.assertEqual(app.config.get()["timeout_call"], "")
            for _ in range(2):
                app.ingest(self.reading(dict(WatchTests.ACTIVE)))
            self.assertEqual(app.config.get()["timeout_call"], "right")

    def test_fields_without_a_timeout(self):
        state = game.empty_state()
        cfg = Config(os.path.join(tempfile.mkdtemp(), "c.json")).get()
        f = game.fields(state, cfg)
        self.assertEqual((f["TIMEOUT"], f["TIMEOUT SIDE"], f["TIMEOUTS LEFT"], f["TECH PAUSE"]), ("", "", 2, ""))


class TechPauseTests(unittest.TestCase):
    """owen 2026-11-25: the game paused 5 s or more -> Technical pause
    banner; the clock running again 2 s or more -> it goes."""

    def setUp(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not installed")

    def test_clock_face_only_for_m_ss(self):
        from valhud.reader import Frame, clock_face
        self.assertIsNotNone(clock_face(Frame(frame("no_timeout_tab.webp"))))            # 0:27
        self.assertIsNotNone(clock_face(Frame(frame("active_defenders_tab_closed.webp"))))   # 0:37
        # the end of a round: the clock stops on 16.55 for ~7 s (not a pause)
        self.assertIsNone(clock_face(Frame(frame("round_end_clock_16.55.webp"))))

    def faces(self):
        import numpy as np
        return [np.full((40, 90), v, dtype=np.int16) for v in (0, 50, 100, 150, 200, 250)]

    def test_pause_after_five_seconds_and_back_after_two_running(self):
        from valhud.reader import ClockWatch
        f = self.faces()
        w = ClockWatch()
        t = 0.0
        for i in range(3):        # running: a new face every second
            self.assertFalse(w.see(f[i], t))
            t += 1
        last = f[2]
        while t < 7:              # stopped (seen 4 times a second)
            w.see(last, t)
            t += 0.25
        self.assertFalse(w.see(last, 6.5))
        self.assertTrue(w.see(last, 7.1))   # 5 s since it last changed (2.0)
        self.assertTrue(w.see(None, 8))     # (the spike icon, Tab...: stays paused)
        self.assertTrue(w.see(last, 20))
        self.assertTrue(w.see(f[3], 21))    # ticks again...
        self.assertTrue(w.see(f[4], 22))
        self.assertFalse(w.see(f[5], 23))   # ...for 2 s: over

    def test_one_stray_change_doesnt_end_it(self):
        from valhud.reader import ClockWatch
        f = self.faces()
        w = ClockWatch()
        w.see(f[0], 0)
        self.assertTrue(w.see(f[0], 5.5))
        w.see(f[1], 10)                     # one change, then still again
        self.assertTrue(w.see(f[1], 12))
        self.assertTrue(w.see(f[2], 16))    # (too long after the last: starts counting again)
        self.assertTrue(w.see(f[3], 17))
        self.assertFalse(w.see(f[4], 18))

    def test_a_timeout_isnt_a_tech_pause(self):
        from valhud.reader import ClockWatch
        f = self.faces()
        w = ClockWatch()
        w.see(f[0], 0)
        for t in range(1, 60):
            self.assertFalse(w.see(f[0], t, timeout=True))

    def test_app_puts_the_banner_up_and_down(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp)
            on = {"source": "screen", "match": {"attackers": "left", "timeout": None, "tech_pause": True}}
            off = {"source": "screen", "match": {"attackers": "left", "timeout": None, "tech_pause": False}}
            app.ingest(on)
            self.assertTrue(app.config.get()["tech_pause"])
            self.assertEqual(app.fields["TECH PAUSE"], "1")
            app.ingest(off)
            self.assertFalse(app.config.get()["tech_pause"])
            # from the observer PC too
            app.ingest({"source": "observer", "spectating": {"text": ""}, "timeout": None, "tech_pause": True})
            self.assertTrue(app.config.get()["tech_pause"])
            app.ingest({"source": "observer", "spectating": {"text": ""}, "timeout": None, "tech_pause": False})
            self.assertFalse(app.config.get()["tech_pause"])

    def test_app_leaves_one_put_up_by_hand_and_timeouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp, tech_pause=True)
            app.ingest({"source": "screen", "match": {"attackers": "left", "timeout": None, "tech_pause": False}})
            self.assertTrue(app.config.get()["tech_pause"])    # (pressed by hand: stays)
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp, timeout_call="right")
            app.ingest({"source": "screen", "match": {"attackers": "left", "timeout": None, "tech_pause": True}})
            self.assertFalse(app.config.get()["tech_pause"])   # (a timeout's up: that's why it stopped)
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp, auto_tech_pause=False)
            app.ingest({"source": "screen", "match": {"attackers": "left", "timeout": None, "tech_pause": True}})
            self.assertFalse(app.config.get()["tech_pause"])

    def test_banner_comes_down_when_readings_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp)
            app.ingest({"source": "screen", "match": {"attackers": "left", "timeout": None, "tech_pause": True}})
            app._tech_seen_at -= 20
            app.refresh()
            self.assertFalse(app.config.get()["tech_pause"])


if __name__ == "__main__":
    unittest.main()
