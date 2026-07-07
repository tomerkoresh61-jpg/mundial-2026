import unittest
from unittest.mock import patch

import auto_sync
import mundial_2026 as mdl


class AutoSyncEloTests(unittest.TestCase):
    def test_update_elo_after_match_resolves_api_team_aliases(self):
        tracked = ("South Korea", "Czechia")
        original = {team: mdl.TEAM_RATINGS[team] for team in tracked}

        try:
            with patch.object(auto_sync, "_notify"), patch.object(mdl, "_save_elo_ratings"):
                auto_sync.update_elo_after_match(
                    "Korea Republic",
                    "Czech Republic",
                    2,
                    1,
                    stage="group",
                )

            self.assertGreater(mdl.TEAM_RATINGS["South Korea"], original["South Korea"])
            self.assertLess(mdl.TEAM_RATINGS["Czechia"], original["Czechia"])
            self.assertNotIn("Korea Republic", mdl.TEAM_RATINGS)
            self.assertNotIn("Czech Republic", mdl.TEAM_RATINGS)
        finally:
            mdl.TEAM_RATINGS.update(original)


if __name__ == "__main__":
    unittest.main()
