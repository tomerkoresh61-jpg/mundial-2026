import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_USER_ID", "1")

import telegram_bot as bot


class _FakeCallbackQuery:
    def __init__(self, data):
        self.data = data
        self.answer = AsyncMock()
        self.edit_message_text = AsyncMock()


class _FakeUpdate:
    def __init__(self, data):
        self.effective_user = SimpleNamespace(id=1)
        self.callback_query = _FakeCallbackQuery(data)


class TelegramBotSimulationTests(unittest.IsolatedAsyncioTestCase):
    async def test_simulate_callback_runs_model_job_off_event_loop(self):
        update = _FakeUpdate("simulate")
        context = SimpleNamespace(user_data={})
        probs = {
            "France": {"champion": 0.6},
            "Brazil": {"champion": 0.4},
        }

        with (
            patch.object(bot.mdl, "_load_state"),
            patch.object(bot, "_run_model_job", new_callable=AsyncMock) as run_job,
        ):
            run_job.return_value = probs

            await bot.on_button(update, context)

        run_job.assert_awaited_once_with(bot.mdl.simulate_tournament)
        self.assertEqual(update.callback_query.edit_message_text.await_count, 2)

    async def test_bonus_callback_runs_combined_model_job_off_event_loop(self):
        update = _FakeUpdate("bonus")
        context = SimpleNamespace(user_data={})
        team, team_data = next(iter(bot.mdl.TEAMS.items()))
        player = next(iter(team_data["players"]))
        probs = {team: {"champion": 1.0}}
        scorers = [(player, 1.0)]

        with (
            patch.object(bot.mdl, "_load_state"),
            patch.object(bot, "_run_model_job", new_callable=AsyncMock) as run_job,
        ):
            run_job.return_value = (probs, scorers)

            await bot.on_button(update, context)

        run_job.assert_awaited_once_with(bot._build_bonus_predictions)
        self.assertEqual(update.callback_query.edit_message_text.await_count, 2)

    def test_build_bonus_predictions_reuses_tournament_probs_for_scorers(self):
        probs = {"France": {"champion": 1.0}}
        scorers = [("Mbappe", 1.0)]

        with (
            patch.object(bot.mdl, "simulate_tournament", return_value=probs) as simulate,
            patch.object(bot.mdl, "predict_top_scorers", return_value=scorers) as top_scorers,
        ):
            self.assertEqual(bot._build_bonus_predictions(), (probs, scorers))

        simulate.assert_called_once_with()
        top_scorers.assert_called_once_with(probs)


if __name__ == "__main__":
    unittest.main()
