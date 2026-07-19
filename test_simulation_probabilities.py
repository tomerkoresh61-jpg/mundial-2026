import unittest

import mundial_2026 as mdl


class SimulationProbabilityTests(unittest.TestCase):
    def test_stage_probabilities_are_not_double_counted(self):
        teams = list(mdl.TEAMS)[:8]
        outcomes = iter([
            (teams[0], [teams[0], teams[1]], teams[:4]),
            (teams[4], [teams[4], teams[5]], teams[4:8]),
        ])
        original_sim_tournament = mdl._sim_tournament
        mdl._sim_tournament = lambda: next(outcomes)
        try:
            probs = mdl.simulate_tournament(n=2)
        finally:
            mdl._sim_tournament = original_sim_tournament

        self.assertEqual(sum(p["champion"] for p in probs.values()), 1.0)
        self.assertEqual(sum(p["finalist"] for p in probs.values()), 2.0)
        self.assertEqual(sum(p["semifinal"] for p in probs.values()), 4.0)

        self.assertEqual(probs[teams[0]]["champion"], 0.5)
        self.assertEqual(probs[teams[0]]["finalist"], 0.5)
        self.assertEqual(probs[teams[0]]["semifinal"], 0.5)


if __name__ == "__main__":
    unittest.main()
