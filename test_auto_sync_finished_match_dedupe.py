from datetime import datetime, timezone
import unittest
from unittest.mock import patch

import auto_sync


class FinishedMatchDedupeTests(unittest.TestCase):
    def setUp(self):
        self.orig_known_fixture_ids = set(auto_sync._known_fixture_ids)
        self.orig_known_finished_match_keys = set(auto_sync._known_finished_match_keys)
        auto_sync._known_fixture_ids.clear()
        auto_sync._known_finished_match_keys.clear()

    def tearDown(self):
        auto_sync._known_fixture_ids.clear()
        auto_sync._known_fixture_ids.update(self.orig_known_fixture_ids)
        auto_sync._known_finished_match_keys.clear()
        auto_sync._known_finished_match_keys.update(self.orig_known_finished_match_keys)

    def test_api_fixture_after_hardcoded_fallback_does_not_reapply_elo(self):
        hardcoded = {
            "fixture_id": 10002,
            "source": "hardcoded",
            "status": "FT",
            "home": "South Korea",
            "away": "Czechia",
            "kickoff": datetime(2026, 6, 12, 2, 0, tzinfo=timezone.utc),
            "home_score": 2,
            "away_score": 1,
            "stage": "group",
        }
        api = {
            "fixture_id": 1387888,
            "source": "api",
            "status": "FT",
            "home": "Korea Republic",
            "away": "Czech Republic",
            "kickoff": datetime(2026, 6, 12, 2, 0, tzinfo=timezone.utc),
            "home_score": 2,
            "away_score": 1,
            "stage": "group",
        }

        with (
            patch.object(auto_sync, "_known_teams", return_value=["South Korea", "Czechia"]),
            patch.object(auto_sync, "_notify"),
            patch.object(auto_sync, "update_elo_after_match") as update_elo,
        ):
            auto_sync._check_finished_matches([hardcoded])
            auto_sync._check_finished_matches([api])

        update_elo.assert_called_once_with("South Korea", "Czechia", 2, 1, stage="group")


if __name__ == "__main__":
    unittest.main()
