import unittest

import mundial_2026 as mdl


class HeadToHeadMultiplierTest(unittest.TestCase):
    def test_h2h_edges_preserve_documented_orientation(self):
        self.assertEqual(mdl._h2h_multiplier("Germany", "England"), (1.05, 0.96))
        self.assertEqual(mdl._h2h_multiplier("England", "Germany"), (0.96, 1.05))

    def test_expected_goals_uses_oriented_h2h_factor(self):
        _, _, factors = mdl.expected_goals("South Korea", "Germany")
        self.assertEqual(factors["h2h"], (1.04, 0.97))


class EloDeltaMultiplierTest(unittest.TestCase):
    def test_baseline_elo_is_neutral(self):
        self.assertEqual(mdl._elo_delta_multiplier("France"), (1.0, 1.0))

    def test_live_elo_delta_changes_expected_goals(self):
        old_rating = mdl.TEAM_RATINGS["France"]
        try:
            base_france_xg, base_brazil_xg, _ = mdl.expected_goals("France", "Brazil")
            mdl.TEAM_RATINGS["France"] = mdl.INITIAL_TEAM_RATINGS["France"] + 120

            france_xg, brazil_xg, factors = mdl.expected_goals("France", "Brazil")

            self.assertGreater(factors["elo_attack"][0], 1.0)
            self.assertLess(factors["elo_defense"][0], 1.0)
            self.assertGreater(france_xg, base_france_xg)
            self.assertLess(brazil_xg, base_brazil_xg)
        finally:
            mdl.TEAM_RATINGS["France"] = old_rating


if __name__ == "__main__":
    unittest.main()
