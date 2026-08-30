import unittest

import mundial_2026 as mdl


class PlayerFormRegressionTest(unittest.TestCase):
    def setUp(self):
        self.team = "France"
        self.player = "William Saliba"
        self.original_players = {
            name: data.copy()
            for name, data in mdl.TEAMS[self.team]["players"].items()
        }

    def tearDown(self):
        for name, data in self.original_players.items():
            mdl.TEAMS[self.team]["players"][name].update(data)

    def _reset_france_players(self):
        for data in mdl.TEAMS[self.team]["players"].values():
            data["form"] = 0
            data["fitness"] = 1.0
            data["available"] = True

    def test_positive_defender_form_improves_defensive_multiplier(self):
        self._reset_france_players()
        _, base_def = mdl._squad_multiplier(self.team)

        mdl.TEAMS[self.team]["players"][self.player]["form"] = 2
        _, hot_def = mdl._squad_multiplier(self.team)

        mdl.TEAMS[self.team]["players"][self.player]["form"] = -2
        _, cold_def = mdl._squad_multiplier(self.team)

        self.assertLess(hot_def, base_def)
        self.assertGreater(cold_def, base_def)

    def test_defender_form_moves_opponent_expected_goals_in_right_direction(self):
        self._reset_france_players()
        _, base_norway_xg, _ = mdl.expected_goals("France", "Norway", "Neutral")

        mdl.TEAMS[self.team]["players"][self.player]["form"] = 2
        _, hot_norway_xg, _ = mdl.expected_goals("France", "Norway", "Neutral")

        mdl.TEAMS[self.team]["players"][self.player]["form"] = -2
        _, cold_norway_xg, _ = mdl.expected_goals("France", "Norway", "Neutral")

        self.assertLess(hot_norway_xg, base_norway_xg)
        self.assertGreater(cold_norway_xg, base_norway_xg)


if __name__ == "__main__":
    unittest.main()
