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


if __name__ == "__main__":
    unittest.main()
