import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import auto_sync
import mundial_2026 as mdl


def _lineup(team: str) -> dict:
    return {
        "team": {"name": team},
        "startXI": [{"player": {"name": f"{team} Starter"}}],
        "substitutes": [{"player": {"name": f"{team} Sub"}}],
    }


class AutoSyncTest(unittest.TestCase):
    def setUp(self):
        auto_sync._lineup_checked.clear()
        auto_sync._lineups_by_fixture.clear()
        auto_sync._sent_events.clear()
        mdl.LINEUP_CONFIRMED.clear()

    def tearDown(self):
        auto_sync._lineup_checked.clear()
        auto_sync._lineups_by_fixture.clear()
        auto_sync._sent_events.clear()
        mdl.LINEUP_CONFIRMED.clear()

    def test_normalize_api_venue_names_to_model_keys(self):
        cases = {
            "Estadio Azteca": "Azteca",
            "MetLife Stadium": "MetLife",
            "AT&T Stadium": "ATT",
            "BC Place": "BCPlace",
            "Estadio Guadalajara": "Akron",
        }
        for api_name, model_key in cases.items():
            with self.subTest(api_name=api_name):
                self.assertEqual(auto_sync._normalize_venue_name(api_name), model_key)

    def test_check_upcoming_lineups_retries_until_both_sides_confirmed(self):
        fixture_id = 12345
        kickoff = datetime.now(timezone.utc) + timedelta(minutes=30)
        fixture = {
            "fixture_id": fixture_id,
            "home": "Mexico",
            "away": "South Africa",
            "kickoff": kickoff,
        }
        responses = [
            [_lineup("Mexico")],
            [_lineup("Mexico"), _lineup("South Africa")],
        ]

        with patch.object(auto_sync, "_get_fixture_lineups", side_effect=responses):
            auto_sync._check_upcoming_lineups([fixture])
            self.assertNotIn(fixture_id, auto_sync._lineup_checked)
            self.assertEqual(auto_sync._lineups_by_fixture[fixture_id], {"Mexico"})

            auto_sync._check_upcoming_lineups([fixture])
            self.assertIn(fixture_id, auto_sync._lineup_checked)
            self.assertEqual(
                auto_sync._lineups_by_fixture[fixture_id],
                {"Mexico", "South Africa"},
            )


if __name__ == "__main__":
    unittest.main()
