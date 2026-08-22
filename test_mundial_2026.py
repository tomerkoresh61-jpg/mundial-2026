import unittest

import mundial_2026 as mdl


class HeadToHeadMultiplierTest(unittest.TestCase):
    def test_h2h_edges_preserve_documented_orientation(self):
        self.assertEqual(mdl._h2h_multiplier("Germany", "England"), (1.05, 0.96))
        self.assertEqual(mdl._h2h_multiplier("England", "Germany"), (0.96, 1.05))

    def test_expected_goals_uses_oriented_h2h_factor(self):
        _, _, factors = mdl.expected_goals("South Korea", "Germany")
        self.assertEqual(factors["h2h"], (1.04, 0.97))


if __name__ == "__main__":
    unittest.main()
