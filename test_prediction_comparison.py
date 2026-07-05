import unittest
from unittest.mock import patch

import prediction_comparison as pc


class BettingOddsTests(unittest.TestCase):
    def test_requires_fixture_id_before_fetching_odds(self):
        with patch.object(pc, "API_KEY", "test-key"), patch.object(pc.requests, "get") as get:
            result = pc.fetch_betting_odds(home="France", away="Norway")

        self.assertFalse(result["available"])
        self.assertIn("fixture id required", result["reason"])
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
