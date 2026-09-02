import copy
import os
import tempfile
import unittest

import mundial_2026 as mdl


class UpdateResultValidationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig_state_file = mdl.STATE_FILE
        self.orig_teams = copy.deepcopy(mdl.TEAMS)
        self.orig_team_form = copy.deepcopy(mdl.TEAM_FORM)
        self.orig_extra_time = copy.deepcopy(mdl.TEAM_EXTRA_TIME)
        mdl.STATE_FILE = os.path.join(self.tmp.name, "wc2026_state.json")

    def tearDown(self):
        mdl.STATE_FILE = self.orig_state_file
        mdl.TEAMS.clear()
        mdl.TEAMS.update(self.orig_teams)
        mdl.TEAM_FORM.clear()
        mdl.TEAM_FORM.update(self.orig_team_form)
        mdl.TEAM_EXTRA_TIME.clear()
        mdl.TEAM_EXTRA_TIME.update(self.orig_extra_time)
        self.tmp.cleanup()

    def test_negative_goals_do_not_mutate_or_save_state(self):
        before_a = copy.deepcopy(mdl.TEAMS["France"])
        before_b = copy.deepcopy(mdl.TEAMS["Germany"])
        before_form = copy.deepcopy(mdl.TEAM_FORM)

        with self.assertRaisesRegex(ValueError, "non-negative"):
            mdl.update_result("France", "Germany", -1, 2)

        self.assertEqual(before_a, mdl.TEAMS["France"])
        self.assertEqual(before_b, mdl.TEAMS["Germany"])
        self.assertEqual(before_form, mdl.TEAM_FORM)
        self.assertFalse(os.path.exists(mdl.STATE_FILE))

    def test_valid_goals_still_update_and_save_state(self):
        mdl.update_result("France", "Germany", 2, 1)

        self.assertTrue(os.path.exists(mdl.STATE_FILE))
        self.assertNotEqual(self.orig_teams["France"]["attack"], mdl.TEAMS["France"]["attack"])


if __name__ == "__main__":
    unittest.main()
