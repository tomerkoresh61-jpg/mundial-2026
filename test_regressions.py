import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ALLOWED_USER_ID", "42")

import auto_sync
import telegram_bot
from telegram.ext import ConversationHandler


class TelegramConversationResetTests(unittest.TestCase):
    def setUp(self):
        self._old_allowed = telegram_bot.ALLOWED_USER
        self._old_load_state = telegram_bot.mdl._load_state
        telegram_bot.ALLOWED_USER = 42
        telegram_bot.mdl._load_state = lambda: None

    def tearDown(self):
        telegram_bot.ALLOWED_USER = self._old_allowed
        telegram_bot.mdl._load_state = self._old_load_state

    def _callback_update(self, data):
        query = SimpleNamespace(
            data=data,
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        return SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            callback_query=query,
        )

    def test_main_menu_clears_abandoned_update_flow(self):
        context = SimpleNamespace(user_data={"pending": "upd_yellow"})
        result = asyncio.run(
            telegram_bot.on_button(self._callback_update("main"), context)
        )

        self.assertEqual({}, context.user_data)
        self.assertEqual(ConversationHandler.END, result)

    def test_update_menu_cancel_clears_abandoned_update_flow(self):
        context = SimpleNamespace(user_data={"pending": "upd_fitness"})
        result = asyncio.run(
            telegram_bot.on_button(self._callback_update("update_menu"), context)
        )

        self.assertEqual({}, context.user_data)
        self.assertEqual(ConversationHandler.END, result)

    def test_start_command_clears_abandoned_update_flow(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            message=message,
        )
        context = SimpleNamespace(user_data={"pending": "upd_result"})

        result = asyncio.run(telegram_bot.cmd_start(update, context))

        self.assertEqual({}, context.user_data)
        self.assertEqual(ConversationHandler.END, result)


class AutoSyncLivePollingTests(unittest.TestCase):
    def setUp(self):
        self._old_get_live_fixture_ids = auto_sync._get_live_fixture_ids
        self._old_check_scheduled = auto_sync._check_scheduled_fixture_updates
        self._old_process_live = auto_sync._process_live_fixtures
        self._old_live_fixture_ids = set(auto_sync._live_fixture_ids)

    def tearDown(self):
        auto_sync._get_live_fixture_ids = self._old_get_live_fixture_ids
        auto_sync._check_scheduled_fixture_updates = self._old_check_scheduled
        auto_sync._process_live_fixtures = self._old_process_live
        auto_sync._live_fixture_ids.clear()
        auto_sync._live_fixture_ids.update(self._old_live_fixture_ids)

    def test_live_iteration_still_checks_lineups_and_finished_matches(self):
        upcoming = [{
            "fixture_id": 101,
            "home": "A",
            "away": "B",
            "status": "NS",
        }]
        calls = []

        auto_sync._get_live_fixture_ids = lambda: [101]

        def check_scheduled(days=2):
            calls.append(("scheduled", days))
            return upcoming

        def process_live(live_ids, scheduled_fixtures):
            calls.append(("live", list(live_ids), scheduled_fixtures))

        auto_sync._check_scheduled_fixture_updates = check_scheduled
        auto_sync._process_live_fixtures = process_live

        sleep_sec = auto_sync._run_sync_iteration()

        self.assertEqual(auto_sync.LIVE_POLL_SEC, sleep_sec)
        self.assertIn(101, auto_sync._live_fixture_ids)
        self.assertEqual([
            ("scheduled", 2),
            ("live", [101], upcoming),
        ], calls)


if __name__ == "__main__":
    unittest.main()
