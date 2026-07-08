import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:ABC")
os.environ.setdefault("ALLOWED_USER_ID", "1")

import telegram_bot as bot


class FakeQuery:
    def __init__(self):
        self.text = None
        self.reply_markup = None
        self.parse_mode = None

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
        self.text = text
        self.reply_markup = reply_markup
        self.parse_mode = parse_mode


class UpcomingFixtureTests(unittest.IsolatedAsyncioTestCase):
    async def test_tbd_knockout_fixture_renders_schedule_card_without_prediction(self):
        fixture = {
            "fixture_id": 10076,
            "home": "TBD-R32-4A",
            "away": "TBD-R32-4B",
            "venue": "Neutral",
            "stage": "R32",
            "kickoff": datetime.now(timezone.utc) + timedelta(hours=3),
            "status": "NS",
            "source": "hardcoded",
        }
        query = FakeQuery()

        with mock.patch("auto_sync.get_upcoming_fixtures", return_value=[fixture]):
            with mock.patch.object(
                bot,
                "build_match_card",
                side_effect=AssertionError("prediction should be skipped"),
            ):
                await bot._show_upcoming(query, days=1)

        self.assertIn("*TBD-R32-4A* 🆚 *TBD-R32-4B*", query.text)
        self.assertIn("הקבוצות עדיין לא נקבעו", query.text)
        self.assertNotIn("שגיאה בחיזוי", query.text)


if __name__ == "__main__":
    unittest.main()
