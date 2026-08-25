import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import auto_sync
import mundial_2026 as mdl


class ExtraTimeDetectionTests(unittest.TestCase):
    def setUp(self):
        auto_sync._sent_events.clear()

    def _process_goal(self, status, elapsed):
        calls = []
        event = {
            "type": "Goal",
            "detail": "Normal Goal",
            "player": {"name": "Kylian Mbappe"},
            "time": {"elapsed": elapsed, "extra": None},
        }
        with patch.object(auto_sync, "_get_fixture_events", return_value=[event]), \
                patch.object(auto_sync, "_notify"), \
                patch.object(mdl, "mark_extra_time", side_effect=calls.append):
            auto_sync._process_events(12345, "France", "Norway", status)
        return calls

    def test_second_half_stoppage_time_does_not_mark_aet(self):
        self.assertEqual(self._process_goal("2H", 92), [])

    def test_extra_time_status_marks_aet(self):
        self.assertEqual(self._process_goal("ET", 92), ["France", "Norway"])


class FinishedFixtureLookbackTests(unittest.TestCase):
    def test_default_upcoming_excludes_past_but_sync_lookback_includes_finished(self):
        now = datetime.now(timezone.utc)
        fixtures = [
            {
                "fixture_id": 1,
                "home": "France",
                "away": "Norway",
                "kickoff": now - timedelta(minutes=30),
                "status": "FT",
            },
            {
                "fixture_id": 2,
                "home": "Brazil",
                "away": "Morocco",
                "kickoff": now + timedelta(hours=1),
                "status": "NS",
            },
        ]

        with patch.object(auto_sync, "API_KEY", ""), \
                patch.object(auto_sync, "_load_hardcoded_fixtures", return_value=fixtures):
            default_ids = [f["fixture_id"] for f in auto_sync.get_upcoming_fixtures(days=1)]
            sync_ids = [
                f["fixture_id"]
                for f in auto_sync.get_upcoming_fixtures(days=1, include_past_hours=2)
            ]

        self.assertEqual(default_ids, [2])
        self.assertEqual(sync_ids, [1, 2])


class TeamScopedPlayerResolutionTests(unittest.TestCase):
    def setUp(self):
        auto_sync._sent_events.clear()

    def test_card_event_does_not_apply_player_from_other_fixture_team(self):
        event = {
            "type": "Card",
            "detail": "Yellow Card",
            "team": {"name": "Norway"},
            "player": {"name": "Kylian Mbappe"},
            "time": {"elapsed": 12, "extra": None},
        }

        with patch.object(auto_sync, "_get_fixture_events", return_value=[event]), \
                patch.object(auto_sync, "_notify"), \
                patch.object(mdl, "add_yellow_card") as add_yellow:
            auto_sync._process_events(23456, "France", "Norway", "1H")

        add_yellow.assert_not_called()


if __name__ == "__main__":
    unittest.main()
