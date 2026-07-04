import unittest

import mundial_2026 as mdl


class LineupConfirmationTests(unittest.TestCase):
    def setUp(self):
        self._old_lineups = dict(mdl.LINEUP_CONFIRMED)
        mdl.LINEUP_CONFIRMED.clear()

    def tearDown(self):
        mdl.LINEUP_CONFIRMED.clear()
        mdl.LINEUP_CONFIRMED.update(self._old_lineups)

    def test_legacy_team_flag_is_not_reused_for_scoped_match(self):
        mdl.LINEUP_CONFIRMED["Brazil"] = True

        self.assertTrue(mdl.is_lineup_confirmed("Brazil"))
        self.assertFalse(
            mdl.is_lineup_confirmed("Brazil", opponent="Haiti", fixture_id=1002)
        )
        self.assertFalse(mdl.is_lineup_confirmed("Brazil", opponent="Haiti"))

    def test_confirmation_is_scoped_to_current_fixture_and_opponent(self):
        mdl.mark_lineup_confirmed("Brazil", opponent="Morocco", fixture_id=1001)

        self.assertTrue(
            mdl.is_lineup_confirmed("Brazil", opponent="Morocco", fixture_id=1001)
        )
        self.assertFalse(
            mdl.is_lineup_confirmed("Brazil", opponent="Haiti", fixture_id=1002)
        )
        self.assertFalse(
            mdl.is_lineup_confirmed("Brazil", opponent="Morocco", fixture_id=1002)
        )

    def test_new_confirmation_replaces_previous_match_context(self):
        mdl.mark_lineup_confirmed("Brazil", opponent="Morocco", fixture_id=1001)
        mdl.mark_lineup_confirmed("Brazil", opponent="Haiti", fixture_id=1002)

        self.assertFalse(
            mdl.is_lineup_confirmed("Brazil", opponent="Morocco", fixture_id=1001)
        )
        self.assertTrue(
            mdl.is_lineup_confirmed("Brazil", opponent="Haiti", fixture_id=1002)
        )


if __name__ == "__main__":
    unittest.main()
