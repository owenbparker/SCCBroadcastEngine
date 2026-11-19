"""Auto sides: one player's in-game name a team puts the teams on their sides
by themselves (owen, 2026-11-19: "type in the in game name of one player per
team, then it would automatically move the team logos, series wins")."""

import os
import tempfile
import unittest

from valhud.config import Config
from valhud.teamsides import AutoSides


def make_app(tmp, **cfg):
    from valhud.app import HudApp
    c = Config(os.path.join(tmp, "config.json"))
    c.update(dict({"output_dir": os.path.join(tmp, "out")}, **cfg))
    app = HudApp(c)
    app.riot.stop()
    return app


SAINTS, RUTGERS = "St. Clair Saints", "Rutgers University"


class VerdictTests(unittest.TestCase):
    cfg = {"left": {"name": SAINTS}, "right": {"name": RUTGERS}, "team_igns": {"stclairsaints": "Bearrett"}}

    def test_one_name_says_which_side(self):
        a = AutoSides()
        self.assertEqual(a.verdict({"left": ["Bearrett", "xela"], "right": ["albin"]}, self.cfg), "same")
        self.assertEqual(a.verdict({"left": ["albin", "HelicoptaMonl<E"], "right": ["Instxnct", "Bearrett"]}, self.cfg), "swapped")
        # text recognition slips a letter; a Riot ID has its tag
        self.assertEqual(a.verdict({"left": [], "right": ["Bearett"]}, self.cfg), "swapped")
        self.assertEqual(a.verdict({"left": ["Bearrett#NA1"], "right": []}, self.cfg), "same")
        self.assertIsNone(a.verdict({"left": ["woddy"], "right": ["albin"]}, self.cfg))

    def test_nothing_typed_nothing_known(self):
        a = AutoSides()
        self.assertIsNone(a.verdict({"left": ["Bearrett"], "right": []}, {"left": {"name": SAINTS}, "right": {"name": RUTGERS}}))

    def test_gfx_engine_roster_ids(self):
        a = AutoSides()
        a.set_roster(RUTGERS, [{"name": "Albin", "ign": "albin"}, {"name": "Cano", "ign": "Cano#RU"}])
        cfg = {"left": {"name": SAINTS}, "right": {"name": RUTGERS}}
        self.assertEqual(a.verdict({"left": ["Cano"], "right": []}, cfg), "swapped")

    def test_swaps_only_after_several_reads(self):
        a = AutoSides()
        seen = {"left": ["albin"], "right": ["Bearrett"]}
        self.assertEqual([a.in_match(seen, self.cfg, t) for t in (0, 1, 2, 3)], [False, False, True, False])


class AppTests(unittest.TestCase):
    def test_match_names_swap_the_teams(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp, left={"name": SAINTS, "tricode": "SCC", "wins": 1}, right={"name": RUTGERS, "tricode": "RUT", "wins": 0},
                           attack_first="left")
            app.set_team_ign("left", "Bearrett")
            app.set_team_ign("right", "albin")
            for _ in range(3):
                app.ingest({"source": "screen", "match": {"round": 2, "score": {"left": 1, "right": 0}},
                            "players": [{"team": "left", "slot": 1, "name": "albin", "agent": "Sova"},
                                        {"team": "right", "slot": 1, "name": "Bearrett", "agent": "Viper"}]})
            cfg = app.config.get()
            self.assertEqual((cfg["left"]["name"], cfg["left"]["wins"], cfg["right"]["name"], cfg["right"]["wins"]),
                             (RUTGERS, 0, SAINTS, 1))
            self.assertEqual(cfg["attack_first"], "right")
            # the typed names stay with their teams; the next reads say "same"
            snap = app.snapshot()["auto_sides"]
            self.assertEqual((snap["left"]["ign"], snap["right"]["ign"]), ("albin", "Bearrett"))
            for _ in range(5):
                app.ingest({"source": "screen", "match": {"round": 3, "score": {"left": 1, "right": 1}},
                            "players": [{"team": "left", "slot": 1, "name": "albin", "agent": "Sova"},
                                        {"team": "right", "slot": 1, "name": "Bearrett", "agent": "Viper"}]})
            self.assertEqual(app.config.get()["left"]["name"], RUTGERS)

    def test_agent_select_turns_who_attacks_first_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp, left={"name": SAINTS}, right={"name": RUTGERS}, attack_first="left")
            app.set_team_ign("left", "Bearrett")
            # Saints are the defenders: they don't attack first.
            app.ingest({"source": "screen", "agent_select": {"active": True, "players": [
                {"team": "defenders", "slot": 1, "agent": "Viper", "locked": True, "name": "Bearrett"},
                {"team": "attackers", "slot": 1, "agent": "Sova", "locked": True, "name": "albin"}]}})
            self.assertEqual(app.config.get()["attack_first"], "right")
            v = app.agent_select.view([])["players"]
            self.assertEqual((v["left"][0]["name"], v["right"][0]["name"]), ("Bearrett", "albin"))

    def test_off_when_switched_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp, left={"name": SAINTS}, right={"name": RUTGERS}, auto_sides=False)
            app.set_team_ign("left", "Bearrett")
            for _ in range(5):
                app.ingest({"source": "screen", "match": {"round": 2},
                            "players": [{"team": "right", "slot": 1, "name": "Bearrett", "agent": "Viper"}]})
            self.assertEqual(app.config.get()["left"]["name"], SAINTS)


if __name__ == "__main__":
    unittest.main()


class AgentSelectSourcesTests(unittest.TestCase):
    """Last night (2026-11-18, maps 1-2) one team's cards stayed "?" most of
    agent select while names were up: once the Riot Client had a team, the
    screen's reading of it was shut out, even when the Riot Client showed
    none of that team's agents."""

    def test_screen_takes_a_team_the_riot_client_shows_no_agents_for(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp, attack_first="left")
            riot = {"source": "riot", "agent_select": {"active": True, "players": [
                {"team": "left", "slot": i + 1, "agent": "", "locked": False, "name": n}
                for i, n in enumerate(["Bearrett", "Tillo", "woddy", "xela", "Instxnct"])]}}
            screen = {"source": "screen", "agent_select": {"active": True, "players": [
                {"team": "attackers", "slot": i + 1, "agent": a, "locked": True, "name": n}
                for i, (a, n) in enumerate([("Fade", "Instxnct"), ("Neon", "xela"), ("Sova", "woddy"), ("Omen", "Tilo"), ("Viper", "")])]}}
            app.ingest(riot)
            for _ in range(2):
                app.ingest(screen)
                app.ingest(riot)
            v = app.agent_select.view([])["players"]["left"]
            self.assertEqual([p["agent"] for p in v], ["Fade", "Neon", "Sova", "Omen", "Viper"])
            # The Riot Client's exact names, matched by the names read off the screen.
            self.assertEqual([p["name"] for p in v][:4], ["Instxnct", "xela", "woddy", "Tillo"])

    def test_riot_client_keeps_a_team_it_sees_as_well(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp, attack_first="left")
            app.ingest({"source": "riot", "agent_select": {"active": True, "players": [
                {"team": "left", "slot": 1, "agent": "Jett", "locked": True, "name": "TenZ"},
                {"team": "left", "slot": 2, "agent": "Sova", "locked": True, "name": "Boaster"}]}})
            for _ in range(3):
                app.ingest({"source": "screen", "agent_select": {"active": True, "players": [
                    {"team": "attackers", "slot": 1, "agent": "Sova", "locked": True, "name": "Boastr"},
                    {"team": "attackers", "slot": 2, "agent": "Jett", "locked": True, "name": "TenZ"}]}})
            v = app.agent_select.view([])["players"]["left"]
            self.assertEqual([(p["agent"], p["name"]) for p in v[:2]], [("Jett", "TenZ"), ("Sova", "Boaster")])

    def test_screen_names_snap_to_known_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp, attack_first="left", left={"name": RUTGERS}, right={"name": SAINTS})
            app.autosides.set_roster(RUTGERS, [{"ign": "HelicoptaMonke67#RU"}, {"ign": "snappypikachu69"}, {"ign": "albin"}])
            app.ingest({"source": "screen", "agent_select": {"active": True, "players": [
                {"team": "attackers", "slot": 1, "agent": "Cypher", "name": "HelicoptaMonl<E"},
                {"team": "attackers", "slot": 2, "agent": "Omen", "name": "snappypikachL"},
                {"team": "attackers", "slot": 3, "agent": "Sova", "name": "al"},
                {"team": "attackers", "slot": 4, "agent": "Neon", "name": "somebodyelse"}]}})
            v = app.agent_select.view([])["players"]["left"]
            self.assertEqual([p["name"] for p in v[:4]], ["HelicoptaMonke67", "snappypikachu69", "al", "somebodyelse"])
