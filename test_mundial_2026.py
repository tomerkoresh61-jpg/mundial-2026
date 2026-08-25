import io
import unittest
from contextlib import redirect_stdout

import mundial_2026 as mdl


class EloRatingMultiplierTests(unittest.TestCase):
    def setUp(self):
        self._ratings = dict(mdl.TEAM_RATINGS)

    def tearDown(self):
        mdl.TEAM_RATINGS.clear()
        mdl.TEAM_RATINGS.update(self._ratings)

    def test_expected_goals_consumes_live_elo_drift(self):
        home, away = "France", "Norway"
        mdl.TEAM_RATINGS[home] = mdl.BASE_TEAM_RATINGS[home]
        mdl.TEAM_RATINGS[away] = mdl.BASE_TEAM_RATINGS[away]
        base_home, base_away, base_factors = mdl.expected_goals(home, away, venue="MetLife")

        mdl.TEAM_RATINGS[home] = mdl.BASE_TEAM_RATINGS[home] + 80.0
        mdl.TEAM_RATINGS[away] = mdl.BASE_TEAM_RATINGS[away] - 80.0

        boosted_home, boosted_away, boosted_factors = mdl.expected_goals(home, away, venue="MetLife")

        self.assertEqual(base_factors["elo"], (1.0, 1.0))
        self.assertGreater(boosted_factors["elo"][0], 1.0)
        self.assertLess(boosted_factors["elo"][1], 1.0)
        self.assertGreater(boosted_home, base_home)
        self.assertLess(boosted_away, base_away)


class TournamentPickTests(unittest.TestCase):
    def setUp(self):
        self._ratings = dict(mdl.TEAM_RATINGS)

    def tearDown(self):
        mdl.TEAM_RATINGS.clear()
        mdl.TEAM_RATINGS.update(self._ratings)

    def test_knockout_pick_keeps_likely_regulation_draw_score(self):
        mdl.TEAM_RATINGS["South Africa"] = mdl.BASE_TEAM_RATINGS["South Africa"]
        mdl.TEAM_RATINGS["Qatar"] = mdl.BASE_TEAM_RATINGS["Qatar"]

        buf = io.StringIO()
        with redirect_stdout(buf):
            mdl.predict_match("South Africa", "Qatar", stage="r16", top_n=5)

        pick_lines = [
            line for line in buf.getvalue().splitlines()
            if "TOURNAMENT PICK" in line
        ]
        self.assertEqual(len(pick_lines), 1)
        self.assertIn("South Africa 1-1 Qatar", pick_lines[0])
        self.assertIn("Qatar to advance", pick_lines[0])


if __name__ == "__main__":
    unittest.main()
