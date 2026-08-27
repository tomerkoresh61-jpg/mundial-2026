import unittest
from unittest.mock import patch

import mundial_2026 as mdl


class ApplyMatchWearTest(unittest.TestCase):
    def setUp(self):
        self.team = "France"
        self.player = "Kylian Mbappe"
        self.player_data = mdl.TEAMS[self.team]["players"][self.player]
        self.original_fitness = self.player_data.get("fitness", 1.0)
        self.original_available = self.player_data["available"]

    def tearDown(self):
        self.player_data["fitness"] = self.original_fitness
        self.player_data["available"] = self.original_available

    def test_match_wear_does_not_increase_fitness_below_floor(self):
        self.player_data["available"] = True
        self.player_data["fitness"] = 0.20

        with patch.object(mdl, "_save_state"):
            mdl.apply_match_wear(self.team)

        self.assertEqual(self.player_data["fitness"], 0.20)

    def test_match_wear_still_applies_floor_for_normal_degradation(self):
        self.player_data["available"] = True
        self.player_data["fitness"] = 0.32

        with patch.object(mdl, "_save_state"):
            mdl.apply_match_wear(self.team)

        self.assertEqual(self.player_data["fitness"], 0.30)


if __name__ == "__main__":
    unittest.main()
