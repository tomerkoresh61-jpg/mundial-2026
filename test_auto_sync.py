import unittest
from unittest.mock import patch

import auto_sync


class FinishedMatchSyncTests(unittest.TestCase):
    def setUp(self):
        auto_sync._known_fixture_ids.clear()
        auto_sync._finished_pending_scores.clear()

    def test_finished_match_with_missing_scores_retries_until_scores_arrive(self):
        incomplete = {
            "fixture_id": 12345,
            "status": "FT",
            "home": "France",
            "away": "Norway",
            "home_score": None,
            "away_score": None,
            "stage": "group",
        }
        complete = dict(incomplete, home_score=2, away_score=1)

        with patch.object(auto_sync, "_notify") as notify, \
             patch.object(auto_sync, "update_elo_after_match") as update_elo:
            auto_sync._check_finished_matches([incomplete])
            auto_sync._check_finished_matches([incomplete])

            self.assertNotIn(12345, auto_sync._known_fixture_ids)
            self.assertIn(12345, auto_sync._finished_pending_scores)
            update_elo.assert_not_called()
            self.assertEqual(notify.call_count, 1)

            auto_sync._check_finished_matches([complete])

        update_elo.assert_called_once_with("France", "Norway", 2, 1, stage="group")
        self.assertIn(12345, auto_sync._known_fixture_ids)
        self.assertNotIn(12345, auto_sync._finished_pending_scores)


if __name__ == "__main__":
    unittest.main()
