import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import auto_sync
import mundial_2026 as mdl


class AutoSyncLineupPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_state_file = mdl.STATE_FILE
        self.original_lineups = dict(mdl.LINEUP_CONFIRMED)
        mdl.STATE_FILE = str(Path(self.tmpdir.name) / "wc2026_state.json")
        for team in mdl.LINEUP_CONFIRMED:
            mdl.LINEUP_CONFIRMED[team] = False

    def tearDown(self):
        mdl.STATE_FILE = self.original_state_file
        mdl.LINEUP_CONFIRMED.clear()
        mdl.LINEUP_CONFIRMED.update(self.original_lineups)
        self.tmpdir.cleanup()

    def test_confirmed_lineup_survives_state_reload(self):
        lineups = [{
            "team": {"name": "France"},
            "startXI": [{"player": {"name": "Kylian Mbappe"}}],
            "substitutes": [],
        }]

        with mock.patch.object(auto_sync, "_get_fixture_lineups", return_value=lineups):
            self.assertTrue(auto_sync._process_lineups(12345))

        with open(mdl.STATE_FILE) as f:
            saved = json.load(f)
        self.assertTrue(saved["lineup_confirmed"]["France"])

        mdl.LINEUP_CONFIRMED["France"] = False
        mdl._load_state()

        self.assertTrue(mdl.LINEUP_CONFIRMED["France"])


if __name__ == "__main__":
    unittest.main()
