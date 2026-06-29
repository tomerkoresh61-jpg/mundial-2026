import os
import tempfile
import unittest
from unittest.mock import patch

import auto_sync
import mundial_2026


class AutoSyncDedupeTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.orig_sync_state_file = auto_sync.SYNC_STATE_FILE
        self.orig_sync_state_loaded = auto_sync._sync_state_loaded
        auto_sync.SYNC_STATE_FILE = os.path.join(self.tmpdir.name, "auto_sync_state.json")
        auto_sync._sync_state_loaded = False
        auto_sync._known_fixture_ids.clear()
        auto_sync._sent_events.clear()

    def tearDown(self):
        auto_sync.SYNC_STATE_FILE = self.orig_sync_state_file
        auto_sync._sync_state_loaded = self.orig_sync_state_loaded
        auto_sync._known_fixture_ids.clear()
        auto_sync._sent_events.clear()
        self.tmpdir.cleanup()

    def _simulate_restart(self):
        auto_sync._known_fixture_ids.clear()
        auto_sync._sent_events.clear()
        auto_sync._sync_state_loaded = False

    def test_yellow_card_event_not_replayed_after_restart(self):
        event = {
            "type": "Card",
            "detail": "Yellow Card",
            "player": {"name": "API Player"},
            "time": {"elapsed": 42},
        }

        with (
            patch.object(auto_sync, "_get_fixture_events", return_value=[event]),
            patch.object(auto_sync, "_known_teams", return_value=[]),
            patch.object(auto_sync, "_fuzzy_player", return_value="Known Player"),
            patch.object(auto_sync, "_notify"),
            patch.object(mundial_2026, "add_yellow_card") as add_yellow,
        ):
            mundial_2026.YELLOW_CARDS.clear()
            auto_sync._process_events(12345, "Home", "Away")
            self._simulate_restart()
            auto_sync._process_events(12345, "Home", "Away")

        self.assertEqual(add_yellow.call_count, 1)

    def test_finished_fixture_elo_not_replayed_after_restart(self):
        fixture = {
            "fixture_id": 54321,
            "status": "FT",
            "home": "Spain",
            "away": "Brazil",
            "home_score": 2,
            "away_score": 1,
            "stage": "group",
        }

        with (
            patch.object(auto_sync, "_notify"),
            patch.object(auto_sync, "update_elo_after_match") as update_elo,
        ):
            auto_sync._check_finished_matches([fixture])
            self._simulate_restart()
            auto_sync._check_finished_matches([fixture])

        update_elo.assert_called_once_with("Spain", "Brazil", 2, 1, stage="group")


if __name__ == "__main__":
    unittest.main()
