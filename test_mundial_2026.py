import unittest

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


if __name__ == "__main__":
    unittest.main()
