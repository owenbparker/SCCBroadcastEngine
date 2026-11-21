"""The reader's game-rules checks (2026-11-21): K/D/A off a Tab scoreboard
read from an older frame than the top bar's deaths, rules a board reading
has to pass, names kept per map."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class BoardTimingTests(unittest.TestCase):
    """From owen's Lotus recording (2026-11-19): the full read takes about a
    second, so its Tab board is from before a death the fast loop has just
    counted. That used to show 10 -> 11 -> 10 deaths, and lose the death."""

    def test_death_after_the_boards_frame_stays(self):
        from valhud.killfeed import LiveKda
        k = LiveKda()
        v = ("left", 3)
        k.board(v, 17, 10, 5, at=100.0)
        k.alive(v, True, at=100.0)
        k.alive(v, False, at=1664.1)          # dies (top bar)
        self.assertEqual(k.values(v), (17, 11, 5))
        k.board(v, 18, 10, 5, at=1663.4)      # the board's frame: before the death, one more kill
        self.assertEqual(k.values(v), (18, 11, 5))
        k.board(v, 18, 11, 5, at=1667.0)      # next board has the death itself
        self.assertEqual(k.values(v), (18, 11, 5))

    def test_death_just_before_the_frame_isnt_counted_twice(self):
        from valhud.killfeed import LiveKda
        k = LiveKda()
        v = ("right", 2)
        k.board(v, 3, 4, 1, at=10.0)
        k.alive(v, True, at=10.0)
        k.alive(v, False, at=50.3)            # first seen gone a little after the board's frame...
        k.board(v, 3, 5, 1, at=50.0)          # ...but the board already has it
        self.assertEqual(k.values(v), (3, 5, 1))

    def test_shown_numbers_dont_drop_on_one_board(self):
        from valhud.killfeed import LiveKda
        k = LiveKda()
        v = ("right", 2)
        k.board(v, 3, 4, 1, at=10.0)
        k.alive(v, True, at=10.0)
        k.alive(v, False, at=50.0)
        self.assertEqual(k.values(v), (3, 5, 1))
        k.board(v, 3, 4, 1, at=60.0)          # one board says 4 (late, or the top bar was wrong)
        self.assertEqual(k.values(v), (3, 5, 1))
        k.board(v, 3, 4, 1, at=62.0)          # two running: it was wrong
        self.assertEqual(k.values(v), (3, 4, 1))


class BoardRulesTests(unittest.TestCase):
    def test_more_deaths_than_rounds_is_turned_away_once(self):
        from valhud.killfeed import LiveKda
        k = LiveKda()
        v = ("left", 1)
        self.assertTrue(k.board(v, 2, 3, 0, at=1.0, rounds=5))
        self.assertFalse(k.board(v, 2, 13, 0, at=2.0, rounds=5))   # "3" read as "13"
        self.assertEqual(k.values(v), (2, 3, 0))
        self.assertEqual(k.rejected, 1)
        self.assertTrue(k.board(v, 2, 3, 0, at=3.0, rounds=5))

    def test_going_down_needs_two_reads(self):
        from valhud.killfeed import LiveKda
        k = LiveKda()
        v = ("left", 1)
        k.board(v, 11, 3, 0, at=1.0)
        self.assertFalse(k.board(v, 1, 3, 0, at=2.0))    # "11" read as "1"
        self.assertEqual(k.values(v), (11, 3, 0))
        self.assertTrue(k.board(v, 1, 3, 0, at=3.0))     # read the same again: a real correction
        self.assertEqual(k.values(v)[0], 11)             # (shown numbers hold for one more board)
        k.board(v, 1, 3, 0, at=4.0)
        self.assertEqual(k.values(v), (1, 3, 0))


class FlickerTests(unittest.TestCase):
    def test_a_bar_hidden_for_a_moment_isnt_a_second_death(self):
        from valhud import reader
        from valhud.killfeed import LiveKda
        r = object.__new__(reader.ScreenReader)
        r.kda, r._dead_reads = LiveKda(), {}
        seat = ("left", 1)
        r.kda.board(seat, 0, 0, 0, at=0.0)
        t = 1.0

        def read(alive, n):
            nonlocal t
            for _ in range(n):
                r._count_deaths([{"team": "left", "slot": 1, "alive": alive}], now=t)
                t += 0.1
        read(True, 10)
        read(False, 5)      # dies
        self.assertEqual(r.kda.values(seat)[1], 1)
        read(True, 3)       # the spot flickers (0.3 s)...
        read(False, 5)
        self.assertEqual(r.kda.values(seat)[1], 1)
        read(True, 300)     # next round
        read(False, 5)
        self.assertEqual(r.kda.values(seat)[1], 2)


class NameKeeperTests(unittest.TestCase):
    """Names off owen's Lotus recording (2026-11-19): one player read as
    "yoogee", "yoog ee" and "y oog ee", another as "f4ngz" and "SPHI f4ngz"."""

    def test_spaces_and_tags_dont_change_the_name(self):
        from valhud.reader import NameKeeper
        k, a, b = NameKeeper(), ("right", 1), ("left", 1)
        for text in ["yoogee", "yoogee", "yoog ee", "y oog ee", "yoog ee", "yoog ee", "yoog ee", "yoogee"]:
            k.offer(a, text)
            if k.name(a):
                self.assertEqual(k.name(a), "yoogee")
        for text in ["f4ngz", "f4ngz", "SPHI f4ngz", "SPHI f4ngz", "f4ngz"]:
            k.offer(b, text)
        self.assertEqual(k.name(b), "f4ngz")

    def test_tag_on_the_first_readings_comes_off(self):
        from valhud.reader import NameKeeper
        k, a = NameKeeper(), ("left", 1)
        k.offer(a, "SPHI f4ngz")
        k.offer(a, "SPHI f4ngz")
        self.assertEqual(k.name(a), "SPHI f4ngz")
        k.offer(a, "f4ngz")
        self.assertEqual(k.name(a), "f4ngz")

    def test_a_locked_name_needs_many_reads_to_change(self):
        from valhud.reader import NameKeeper
        k, a = NameKeeper(), ("left", 2)
        for _ in range(5):
            k.offer(a, "chronicle")
        for _ in range(3):
            k.offer(a, "Juw")                 # a few misplaced reads
        k.offer(a, "chr")                     # cut short
        self.assertEqual(k.name(a), "chronicle")
        for _ in range(NameKeeper.CHANGE):
            k.offer(a, "Juw")
        self.assertEqual(k.name(a), "Juw")


class ReadingHealthTests(unittest.TestCase):
    def test_line_says_good_or_what_to_fix(self):
        from valhud.reader import ReadingHealth
        h = ReadingHealth()
        for i in range(10):
            h.frame("match", now=100 + i)
            h.read(0.7, now=100 + i)
        self.assertEqual(h.info(now=110)["line"], "Reading check: good. Full read 0.7 s.")
        h.held["score"] += 2
        self.assertIn("Misreads held back this map: 2 score.", h.info(now=110)["line"])
        for i in range(10):
            h.read(2.5, now=111 + i)
        info = h.info(now=121)
        self.assertTrue(info["warn"])
        self.assertIn("separate programs", info["line"])
        h.new_map()
        self.assertEqual(h.held["score"], 0)

    def test_window_not_found_and_black_frames(self):
        from valhud.reader import ReadingHealth
        h = ReadingHealth()
        for i in range(10):
            h.frame("none", now=i)
        self.assertIn("Game window", h.info(now=10)["line"])
        h = ReadingHealth()
        for i in range(10):
            h.frame("black" if i % 2 else "match", now=i)
        self.assertIn("black", h.info(now=10)["line"])

    def test_score_jump_is_counted_as_held(self):
        from valhud import reader
        r = object.__new__(reader.ScreenReader)
        r.health = reader.ReadingHealth()

        def offer(left, right):
            u = {"match": {"score": {"left": left, "right": right}}}
            r._steady_score(u)
            return u["match"].get("score")
        offer(12, 11)
        offer(12, 11)
        self.assertIsNone(offer(1, 1))      # "12-11" read as "1-1"
        self.assertEqual(r.health.held["score"], 1)
        self.assertEqual(len(r._held_now), 1)


class RiotPresenceTests(unittest.TestCase):
    def test_presence_old_and_new_layouts(self):
        import base64
        import json
        from valhud import riotclient

        def pres(private, puuid="me"):
            return {"presences": [{"puuid": "someone", "product": "valorant", "private": ""},
                                  {"puuid": puuid, "product": "valorant",
                                   "private": base64.b64encode(json.dumps(private).encode()).decode().rstrip("=")}]}
        old = pres({"sessionLoopState": "INGAME", "provisioningFlow": "CustomGame", "matchMap": "/Game/Maps/Jam/Jam",
                    "partyOwnerMatchScoreAllyTeam": 7, "partyOwnerMatchScoreEnemyTeam": 3})
        self.assertEqual(riotclient.presence_of(old, "me"),
                         {"state": "INGAME", "flow": "CustomGame", "map": "Lotus", "ally": 7, "enemy": 3})
        new = pres({"matchPresenceData": {"sessionLoopState": "PREGAME", "provisioningFlow": "CustomGame"},
                    "partyPresenceData": {"partyOwnerMatchScoreAllyTeam": 0, "partyOwnerMatchScoreEnemyTeam": 0}})
        self.assertEqual(riotclient.presence_of(new, "me")["state"], "PREGAME")
        self.assertIsNone(riotclient.presence_of(new, "other"))
        self.assertIsNone(riotclient.presence_of({"presences": [{"puuid": "me", "product": "valorant",
                                                                  "private": "%%%"}]}, "me"))

    def test_region_from_the_riot_clients_own_region(self):
        from valhud import riotclient
        self.assertEqual(riotclient.region_from_locale({"region": "NA", "locale": "en_US"}), ("na", "na"))
        self.assertEqual(riotclient.region_from_locale({"region": "LAS"}), ("latam", "na"))
        self.assertEqual(riotclient.region_from_locale({"region": "EUW"}), ("eu", "eu"))
        self.assertIsNone(riotclient.region_from_locale({}))


if __name__ == "__main__":
    unittest.main()
