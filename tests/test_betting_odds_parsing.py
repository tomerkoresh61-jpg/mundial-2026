import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import prediction_comparison as pc


class BettingOddsParsingTest(unittest.TestCase):
    def test_match_winner_odds_with_missing_odd_are_unavailable(self):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "errors": [],
                    "response": [
                        {
                            "bookmakers": [
                                {
                                    "name": "BadBook",
                                    "bets": [
                                        {
                                            "id": 1,
                                            "values": [
                                                {"value": "Home"},
                                                {"value": "Draw", "odd": "3.5"},
                                                {"value": "Away", "odd": "2.2"},
                                            ],
                                        }
                                    ],
                                }
                            ]
                        }
                    ],
                }

        with patch.object(pc, "API_KEY", "test-key"), patch.object(pc.requests, "get", return_value=Response()):
            result = pc.fetch_betting_odds(fixture_id=123, home="France", away="Norway")

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "Could not parse odds structure")


if __name__ == "__main__":
    unittest.main()
