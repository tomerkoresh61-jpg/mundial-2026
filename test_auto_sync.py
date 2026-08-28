import unittest

import auto_sync
import mundial_2026 as mdl


def _lineup_side(team, starters=11, malformed=False):
    if malformed:
        start_xi = [{"player": {}} for _ in range(starters)]
    else:
        start_xi = [{"player": {"name": f"{team} Starter {i}"}} for i in range(starters)]
    return {
        "team": {"name": team},
        "startXI": start_xi,
        "substitutes": [{"player": {"name": f"{team} Sub"}}],
    }


class AutoSyncLineupTests(unittest.TestCase):
    def setUp(self):
        self._old_get_fixture_lineups = auto_sync._get_fixture_lineups
        self._old_notify = auto_sync._notify
        self._old_lineups = dict(mdl.LINEUP_CONFIRMED)
        self._old_sent_events = set(auto_sync._sent_events)
        mdl.LINEUP_CONFIRMED.clear()
        auto_sync._sent_events.clear()
        auto_sync._notify = lambda text: None

    def tearDown(self):
        auto_sync._get_fixture_lineups = self._old_get_fixture_lineups
        auto_sync._notify = self._old_notify
        mdl.LINEUP_CONFIRMED.clear()
        mdl.LINEUP_CONFIRMED.update(self._old_lineups)
        auto_sync._sent_events.clear()
        auto_sync._sent_events.update(self._old_sent_events)

    def test_empty_lineup_payload_is_not_confirmed(self):
        auto_sync._get_fixture_lineups = lambda fixture_id: [
            _lineup_side("France", starters=0),
        ]

        confirmed = auto_sync._process_lineups(12345)

        self.assertFalse(confirmed)
        self.assertNotIn("France", mdl.LINEUP_CONFIRMED)
        self.assertNotIn("12345:lineup:France", auto_sync._sent_events)

    def test_malformed_lineup_entries_are_not_confirmed_or_crashing(self):
        auto_sync._get_fixture_lineups = lambda fixture_id: [
            _lineup_side("France", starters=11, malformed=True),
        ]

        confirmed = auto_sync._process_lineups(12345)

        self.assertFalse(confirmed)
        self.assertNotIn("France", mdl.LINEUP_CONFIRMED)

    def test_full_starting_xi_confirms_lineup(self):
        auto_sync._get_fixture_lineups = lambda fixture_id: [
            _lineup_side("France"),
        ]

        confirmed = auto_sync._process_lineups(12345)

        self.assertTrue(confirmed)
        self.assertTrue(mdl.LINEUP_CONFIRMED["France"])
        self.assertIn("12345:lineup:France", auto_sync._sent_events)


if __name__ == "__main__":
    unittest.main()
