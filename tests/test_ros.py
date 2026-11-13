import datetime
import os
import tempfile
import unittest

from sccbe import ros


def titles(show):
    return [s["title"] for s in show["segments"]]


class BuildTests(unittest.TestCase):
    def test_best_of_three_repeats_maps_and_skips_last_break(self):
        t = ros.starter_template("val", 3)
        show = ros.build_show(t, {"team1": "SCC", "team2": "RIT", "best_of": 3})
        self.assertEqual(titles(show), ["Countdown", "Desk · Casters", "Map 1", "Between maps", "Map 2",
                                        "Between maps", "Map 3", "Wrap-up"])
        self.assertIn("SCC vs RIT", show["segments"][1]["notes"])

    def test_best_of_one(self):
        show = ros.build_show(ros.starter_template("lol", 1), {"best_of": 1})
        self.assertEqual(titles(show), ["Countdown", "Desk · Casters", "Map 1", "Wrap-up"])

    def test_game_of(self):
        self.assertEqual(ros.game_of("VALORANT"), "val")
        self.assertEqual(ros.game_of("League of Legends"), "lol")


class MatchTests(unittest.TestCase):
    def test_pick_next_match(self):
        now = datetime.datetime(2026, 11, 13, 12, 0)
        ms = [{"date": "2026-11-10", "time": "19:00", "team1": "old"},
              {"date": "2026-11-20", "time": "19:00", "team1": "later"},
              {"date": "2026-11-14", "time": "18:00", "team1": "next"}]
        self.assertEqual(ros.pick_match(ms, now)["team1"], "next")
        self.assertEqual(ros.pick_match(ms[:1], now)["team1"], "old")
        self.assertIsNone(ros.pick_match([], now))


class ShowTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.r = ros.RunOfShow(os.path.join(self.dir.name, "ros.json"))
        self.r.save_template(ros.starter_template("val", 3))

    def tearDown(self):
        self.dir.cleanup()

    def test_times_shift_when_running_long(self):
        show = self.r.apply({"game": "VALORANT", "date": "2026-11-13", "time": "19:00"})
        self.r.go(0, now=1000)
        tl = ros.timeline(show, now=1000)
        self.assertEqual(tl[0]["end"], 1000 + 15 * 60)
        late = 1000 + 25 * 60   # countdown ran 10 minutes long
        tl = ros.timeline(self.r.data["show"], now=late)
        self.assertEqual(tl[0]["end"], late)
        self.assertEqual(tl[1]["start"], late)

    def test_series_won_skips_remaining_maps(self):
        self.r.apply({"game": "VALORANT", "best_of": 3})
        for i in range(5):            # through Map 2
            self.r.go(i, scores=[1, 0], now=1000 + i)
        show = self.r.go(5, scores=[2, 0], now=2000)
        self.assertEqual(show["segments"][show["current"]]["title"], "Wrap-up")

    def test_old_scores_dont_skip_a_new_show(self):
        self.r.apply({"game": "VALORANT", "best_of": 3})
        self.r.go(0, scores=[2, 1])
        self.r.go(1, scores=[2, 1])
        show = self.r.go(2, scores=[2, 1])
        self.assertEqual(show["segments"][show["current"]]["title"], "Map 1")

    def test_auto_apply_follows_schedule_until_started(self):
        far = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()
        ms = [{"date": far, "time": "19:00", "team1": "A", "team2": "B", "game": "VALORANT"}]
        self.assertTrue(self.r.auto_apply(ms))
        self.assertFalse(self.r.auto_apply(ms))          # same match: leave it
        self.r.go(0)
        ms[0]["team2"] = "C"
        self.assertFalse(self.r.auto_apply(ms))          # started: leave it
        self.r.reset()
        self.assertTrue(self.r.auto_apply(ms))
        self.r.set_auto(False)
        ms[0]["team2"] = "D"
        self.assertFalse(self.r.auto_apply(ms))

    def test_saved_and_loaded(self):
        self.r.apply({"game": "VALORANT"})
        again = ros.RunOfShow(self.r.path)
        self.assertEqual(len(again.data["templates"]), 1)
        self.assertEqual(titles(again.data["show"]), titles(self.r.data["show"]))


if __name__ == "__main__":
    unittest.main()
