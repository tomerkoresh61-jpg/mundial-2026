import importlib
import json
import os
import tempfile
import unittest

import auto_sync
import mundial_2026


class SuspensionLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mdl = importlib.reload(mundial_2026)
        self.mdl.STATE_FILE = os.path.join(self.tmp.name, "state.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_match_suspension_clears_after_next_team_result(self):
        player = "Son Heung-min"

        self.mdl.suspend_player(player)

        self.assertFalse(self.mdl.TEAMS["South Korea"]["players"][player]["available"])
        self.assertEqual(
            self.mdl.SUSPENDED_NEXT_MATCH,
            {player: {"team": "South Korea", "matches_remaining": 1}},
        )

        self.mdl.update_result("South Korea", "Czechia", 1, 0)

        self.assertTrue(self.mdl.TEAMS["South Korea"]["players"][player]["available"])
        self.assertNotIn(player, self.mdl.SUSPENDED_NEXT_MATCH)
        with open(self.mdl.STATE_FILE) as f:
            state = json.load(f)
        self.assertEqual(state["suspended_next_match"], {})
        self.assertTrue(state["availability"][player])

    def test_live_card_suspension_survives_current_match_result(self):
        player = "Son Heung-min"

        self.mdl.suspend_player(player, starts_after_current_match=True)
        self.mdl.update_result("South Korea", "Czechia", 1, 0)

        self.assertFalse(self.mdl.TEAMS["South Korea"]["players"][player]["available"])
        self.assertEqual(
            self.mdl.SUSPENDED_NEXT_MATCH,
            {player: {"team": "South Korea", "matches_remaining": 1}},
        )

        self.mdl.update_result("South Korea", "Germany", 0, 2)

        self.assertTrue(self.mdl.TEAMS["South Korea"]["players"][player]["available"])
        self.assertNotIn(player, self.mdl.SUSPENDED_NEXT_MATCH)

    def test_injury_does_not_clear_after_next_team_result(self):
        player = "Kim Min-jae"

        self.mdl.injure_player(player)
        self.mdl.update_result("South Korea", "Czechia", 1, 0)

        self.assertFalse(self.mdl.TEAMS["South Korea"]["players"][player]["available"])
        self.assertNotIn(player, self.mdl.SUSPENDED_NEXT_MATCH)

    def test_second_yellow_records_one_match_suspension(self):
        player = "Son Heung-min"

        self.mdl.add_yellow_card(player)
        self.mdl.add_yellow_card(player)

        self.assertFalse(self.mdl.TEAMS["South Korea"]["players"][player]["available"])
        self.assertEqual(
            self.mdl.SUSPENDED_NEXT_MATCH,
            {player: {"team": "South Korea", "matches_remaining": 1}},
        )

    def test_finished_aet_match_marks_extra_time_fatigue(self):
        sync = importlib.reload(auto_sync)
        sync._known_fixture_ids.clear()
        sync._notify = lambda text: None
        sync.update_elo_after_match = lambda *args, **kwargs: None

        sync._check_finished_matches([{
            "fixture_id": 12345,
            "home": "Brazil",
            "away": "Germany",
            "status": "AET",
            "home_score": 2,
            "away_score": 1,
            "stage": "r16",
        }])

        self.assertTrue(self.mdl.TEAM_EXTRA_TIME["Brazil"])
        self.assertTrue(self.mdl.TEAM_EXTRA_TIME["Germany"])
        with open(self.mdl.STATE_FILE) as f:
            state = json.load(f)
        self.assertEqual(
            state["extra_time"],
            {"Brazil": True, "Germany": True},
        )


if __name__ == "__main__":
    unittest.main()
