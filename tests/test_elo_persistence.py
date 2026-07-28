import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import auto_sync
import mundial_2026 as mdl


class EloPersistenceTests(TestCase):
    def setUp(self):
        self.original_state_file = mdl.STATE_FILE
        self.original_ratings_file = mdl.RATINGS_FILE
        self.original_ratings = mdl.TEAM_RATINGS.copy()
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        mdl.STATE_FILE = self.original_state_file
        mdl.RATINGS_FILE = self.original_ratings_file
        mdl.TEAM_RATINGS.clear()
        mdl.TEAM_RATINGS.update(self.original_ratings)
        self.tmp.cleanup()

    def test_auto_sync_elo_update_loads_ratings_without_state_file(self):
        temp_dir = Path(self.tmp.name)
        mdl.STATE_FILE = str(temp_dir / "missing-wc2026-state.json")
        mdl.RATINGS_FILE = str(temp_dir / "team_ratings.json")

        saved_ratings = self.original_ratings.copy()
        saved_ratings.update({
            "France": 2000.0,
            "Germany": 1800.0,
            "England": 1999.0,
        })
        with open(mdl.RATINGS_FILE, "w") as f:
            json.dump(saved_ratings, f)

        mdl.TEAM_RATINGS.clear()
        mdl.TEAM_RATINGS.update(self.original_ratings)

        with patch.object(auto_sync, "_notify"):
            auto_sync.update_elo_after_match("France", "Germany", 2, 0)

        with open(mdl.RATINGS_FILE) as f:
            persisted = json.load(f)

        self.assertGreater(mdl.TEAM_RATINGS["France"], 2000.0)
        self.assertEqual(mdl.TEAM_RATINGS["England"], 1999.0)
        self.assertEqual(persisted["England"], 1999.0)
