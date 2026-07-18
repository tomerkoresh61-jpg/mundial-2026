import os
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_USER_ID", "1")

import auto_sync
import telegram_bot


class ApiFixtureHandlingTest(unittest.TestCase):
    def test_stage_from_round_handles_third_place_before_final(self):
        cases = {
            "3rd Place Final": "3rd",
            "Third Place Play-off": "3rd",
            "Bronze Final": "3rd",
            "8th Finals": "r16",
            "16th Finals": "r32",
            "Quarter-finals": "qf",
            "Semi-finals": "sf",
            "Final": "final",
        }

        for round_name, expected in cases.items():
            with self.subTest(round_name=round_name):
                self.assertEqual(auto_sync._stage_from_round(round_name), expected)

    def test_fixture_not_started_rejects_stale_ns_kickoffs(self):
        now = datetime(2026, 7, 18, 11, 0, tzinfo=timezone.utc)

        self.assertFalse(telegram_bot._fixture_not_started({
            "status": "NS",
            "kickoff": now - timedelta(minutes=1),
        }, now))
        self.assertTrue(telegram_bot._fixture_not_started({
            "status": "NS",
            "kickoff": now + timedelta(minutes=1),
        }, now))
        self.assertFalse(telegram_bot._fixture_not_started({
            "status": "1H",
            "kickoff": now + timedelta(minutes=1),
        }, now))


if __name__ == "__main__":
    unittest.main()
