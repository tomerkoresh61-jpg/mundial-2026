import unittest

import auto_sync
import mundial_2026


class AutoSyncEloWinnerTest(unittest.TestCase):
    def setUp(self):
        self._ratings = mundial_2026.TEAM_RATINGS.copy()
        self._save_elo_ratings = mundial_2026._save_elo_ratings
        self._notify = auto_sync._notify

        mundial_2026._save_elo_ratings = lambda: None
        auto_sync._notify = lambda text: None
        auto_sync._known_fixture_ids.clear()

    def tearDown(self):
        mundial_2026.TEAM_RATINGS.clear()
        mundial_2026.TEAM_RATINGS.update(self._ratings)
        mundial_2026._save_elo_ratings = self._save_elo_ratings
        auto_sync._notify = self._notify
        auto_sync._known_fixture_ids.clear()

    def test_tied_knockout_uses_api_penalty_winner_for_elo(self):
        mundial_2026.TEAM_RATINGS["France"] = 1900.0
        mundial_2026.TEAM_RATINGS["Argentina"] = 1800.0

        auto_sync.update_elo_after_match(
            "France",
            "Argentina",
            1,
            1,
            stage="r16",
            winner_team="Argentina",
        )

        self.assertLess(mundial_2026.TEAM_RATINGS["France"], 1900.0)
        self.assertGreater(mundial_2026.TEAM_RATINGS["Argentina"], 1800.0)

    def test_finished_match_passes_api_winner_flag_to_elo(self):
        mundial_2026.TEAM_RATINGS["France"] = 1900.0
        mundial_2026.TEAM_RATINGS["Argentina"] = 1800.0

        auto_sync._check_finished_matches([
            {
                "fixture_id": 12345,
                "home": "France",
                "away": "Argentina",
                "stage": "r16",
                "status": "PEN",
                "home_score": 1,
                "away_score": 1,
                "home_winner": False,
                "away_winner": True,
            }
        ])

        self.assertLess(mundial_2026.TEAM_RATINGS["France"], 1900.0)
        self.assertGreater(mundial_2026.TEAM_RATINGS["Argentina"], 1800.0)


if __name__ == "__main__":
    unittest.main()
