import datetime
import json
import os
import socket
import tempfile
import urllib.error
import urllib.request
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


class GraphicRowsTests(unittest.TestCase):
    def test_now_next_later_and_the_next_map(self):
        self.assertEqual(ros.graphic_rows(None), [["Shown", ""]])
        show = ros.build_show(ros.starter_template("val", 3), {"game": "VALORANT", "date": "2026-11-13", "time": "20:30", "best_of": 3})
        rows = dict(ros.graphic_rows(show, now=0))
        self.assertEqual((rows["Shown"], rows["Now text"], rows["Next text"], rows["Next map in"]),
                         ("1", "", "NEXT - COUNTDOWN", "MAP 1 IN"))
        at = datetime.datetime.fromtimestamp(int(rows["Next map at"])).strftime("%H:%M")
        self.assertEqual(at, "20:30")
        show["current"] = 2          # Map 1 being played
        rows = dict(ros.graphic_rows(show, now=0))
        self.assertEqual((rows["Now text"], rows["Next text"], rows["Later text"], rows["Next map"], rows["Map"]),
                         ("NOW - MAP 1", "NEXT - BETWEEN MAPS", "LATER - MAP 2", "MAP 2", "1"))
        self.assertTrue(rows["Next time"].endswith(("AM", "PM")))


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

    def test_first_map_starts_at_the_match_time(self):
        show = self.r.apply({"game": "VALORANT", "date": "2026-11-13", "time": "20:30", "best_of": 3})
        tl = ros.timeline(show, now=0)
        at = lambda t: datetime.datetime.fromtimestamp(t).strftime("%H:%M")  # noqa: E731
        self.assertEqual([s["title"] for s in show["segments"]][2], "Map 1")
        self.assertEqual(at(tl[2]["start"]), "20:30")      # the match block
        self.assertEqual(at(tl[0]["start"]), "20:05")      # countdown 15 + casters 10 before it
        self.assertEqual(at(tl[1]["start"]), "20:20")
        self.assertEqual(at(tl[3]["start"]), "21:10")      # after a 40 min map

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



class ShareTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.a = ros.RunOfShow(os.path.join(self.dir, "a.json"))
        self.b = ros.RunOfShow(os.path.join(self.dir, "b.json"))
        self.t = self.a.save_template(ros.starter_template("val", 3))

    def test_export_then_import_on_another_pc(self):
        doc = self.a.export(source="CONTROL-PC")
        self.assertEqual(doc["format"], "scc-ros")
        got = ros.read_doc(json.dumps(doc))
        self.assertEqual(self.b.clashes(got), [])
        r = self.b.import_templates(got)
        self.assertEqual(r, {"added": [self.t["name"]], "replaced": []})
        self.assertEqual(self.b.data["templates"][0]["blocks"], self.t["blocks"])

    def test_name_taken_replace_keeps_its_id(self):
        mine = self.b.save_template(dict(ros.starter_template("val", 3), blocks=[]))
        got = ros.read_doc(json.dumps(self.a.export()))
        self.assertEqual(self.b.clashes(got), [self.t["name"]])
        r = self.b.import_templates(got, "replace")
        self.assertEqual(r["replaced"], [self.t["name"]])
        self.assertEqual(len(self.b.data["templates"]), 1)
        self.assertEqual(self.b.data["templates"][0]["id"], mine["id"])
        self.assertEqual(len(self.b.data["templates"][0]["blocks"]), 3)

    def test_name_taken_keep_both(self):
        got = ros.read_doc(json.dumps(self.a.export()))
        self.b.import_templates(got)
        self.b.import_templates(got, "keep")
        self.b.import_templates(got, "keep")
        names = [t["name"] for t in self.b.data["templates"]]
        self.assertEqual(names, [self.t["name"], self.t["name"] + " 2", self.t["name"] + " 3"])
        self.assertEqual(len({t["id"] for t in self.b.data["templates"]}), 3)

    def test_export_some(self):
        other = self.a.save_template(ros.starter_template("lol", 1))
        doc = self.a.export([other["id"]])
        self.assertEqual([t["name"] for t in doc["templates"]], [other["name"]])

    def test_bad_files(self):
        for bad in ("not json", "{}", '{"format": "scc-ros", "templates": []}', b"\x00\x01"):
            with self.assertRaises(ValueError):
                ros.read_doc(bad)
        with self.assertRaises(ValueError):
            ros.read_doc({"format": "scc-ros", "version": 99, "templates": [self.t]})
        self.assertEqual(len(ros.read_doc(self.t)), 1)   # a bare template is fine too

    def test_send_over_the_network(self):
        from sccbe import rosnet
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        old = rosnet.NET_PORT
        rosnet.NET_PORT = port
        httpd = rosnet.start(self.b, port)
        try:
            self.assertEqual(rosnet.hello(rosnet.address("127.0.0.1"))["templates"], 0)
            r = rosnet.send("127.0.0.1", self.a.export(), "replace")
            self.assertEqual(r["added"], [self.t["name"]])
            self.assertEqual(self.b.data["received"]["names"], [self.t["name"]])
            again = rosnet.send("http://127.0.0.1:8770/", self.a.export(), "replace")
            self.assertEqual(again["replaced"], [self.t["name"]])
            with self.assertRaises(ValueError):
                rosnet.send("127.0.0.1", {"format": "nope"}, "replace")
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/ros/receive", data=b"x", headers={"Content-Type": "text/plain"})
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=3)
            self.assertEqual(e.exception.code, 415)
        finally:
            rosnet.NET_PORT = old
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
