import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import auto_sync


class CheckUpcomingLineupsTest(unittest.TestCase):
    def setUp(self):
        auto_sync._lineup_checked.clear()

    def tearDown(self):
        auto_sync._lineup_checked.clear()

    def test_skips_hardcoded_synthetic_fixture_ids(self):
        fixture = {
            "fixture_id": 10001,
            "kickoff": datetime.now(timezone.utc) + timedelta(minutes=15),
            "source": "hardcoded",
        }

        with patch("auto_sync._process_lineups", return_value=True) as process:
            auto_sync._check_upcoming_lineups([fixture])

        process.assert_not_called()
        self.assertNotIn(10001, auto_sync._lineup_checked)

    def test_polls_api_fixture_ids_inside_lineup_window(self):
        fixture = {
            "fixture_id": 123456,
            "kickoff": datetime.now(timezone.utc) + timedelta(minutes=15),
            "source": "api",
        }

        with patch("auto_sync._process_lineups", return_value=True) as process:
            auto_sync._check_upcoming_lineups([fixture])

        process.assert_called_once_with(123456)
        self.assertIn(123456, auto_sync._lineup_checked)


if __name__ == "__main__":
    unittest.main()
