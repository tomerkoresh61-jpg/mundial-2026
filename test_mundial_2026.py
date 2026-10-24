import contextlib
import io
import unittest

import mundial_2026 as mdl


class TopScorerEmptyCandidatesTest(unittest.TestCase):
    def setUp(self):
        self._availability = {
            player: pdata["available"]
            for team in mdl.TEAMS.values()
            for player, pdata in team["players"].items()
        }

    def tearDown(self):
        for team in mdl.TEAMS.values():
            for player, pdata in team["players"].items():
                pdata["available"] = self._availability[player]

    def _disable_top_scorer_candidates(self):
        for team in mdl.TEAMS.values():
            for pdata in team["players"].values():
                if pdata.get("goals_rate", 0) > 0.10:
                    pdata["available"] = False

    def test_predict_top_scorers_returns_empty_when_no_candidates(self):
        self._disable_top_scorer_candidates()

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = mdl.predict_top_scorers(n=3)

        self.assertEqual(result, [])
        self.assertIn("No available top-scorer candidates", output.getvalue())

    def test_bonus_predictions_handles_empty_top_scorer_result(self):
        original_simulate = mdl.simulate_tournament
        original_predict = mdl.predict_top_scorers
        try:
            teams = list(mdl.TEAMS)[:2]
            mdl.simulate_tournament = lambda: {
                teams[0]: {"champion": 0.6, "finalist": 0.7, "semifinal": 0.8},
                teams[1]: {"champion": 0.4, "finalist": 0.5, "semifinal": 0.6},
            }
            mdl.predict_top_scorers = lambda tournament_probs=None, n=20_000: []

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                mdl.bonus_predictions()

            self.assertIn("unavailable (no eligible players)", output.getvalue())
        finally:
            mdl.simulate_tournament = original_simulate
            mdl.predict_top_scorers = original_predict


if __name__ == "__main__":
    unittest.main()
