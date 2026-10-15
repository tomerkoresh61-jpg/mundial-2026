import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import mundial_2026 as mdl


class ManualResultValidationTest(unittest.TestCase):
    def test_update_result_rejects_same_team_without_mutating(self):
        before_team = copy.deepcopy(mdl.TEAMS["France"])
        before_form = mdl.TEAM_FORM["France"]

        with self.assertRaises(ValueError):
            mdl.update_result("France", "France", 3, 1)

        self.assertEqual(before_team, mdl.TEAMS["France"])
        self.assertEqual(before_form, mdl.TEAM_FORM["France"])

    def test_update_result_rejects_unrealistic_score_without_mutating(self):
        before_france = copy.deepcopy(mdl.TEAMS["France"])
        before_iraq = copy.deepcopy(mdl.TEAMS["Iraq"])
        before_france_form = mdl.TEAM_FORM["France"]
        before_iraq_form = mdl.TEAM_FORM["Iraq"]

        with self.assertRaises(ValueError):
            mdl.update_result("France", "Iraq", mdl.MAX_GOALS_PER_TEAM + 1, 0)

        self.assertEqual(before_france, mdl.TEAMS["France"])
        self.assertEqual(before_iraq, mdl.TEAMS["Iraq"])
        self.assertEqual(before_france_form, mdl.TEAM_FORM["France"])
        self.assertEqual(before_iraq_form, mdl.TEAM_FORM["Iraq"])


if __name__ == "__main__":
    unittest.main()
