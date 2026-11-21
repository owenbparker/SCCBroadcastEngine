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


if __name__ == "__main__":
    unittest.main()
