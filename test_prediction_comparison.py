import unittest
from unittest.mock import patch

import prediction_comparison as pc


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class QualifyOddsTests(unittest.TestCase):
    def test_qualify_odds_prefers_bet_id_over_broad_reach_market(self):
        payload = {
            "response": [{
                "bookmakers": [{
                    "name": "book",
                    "bets": [
                        {
                            "id": 999,
                            "name": "Team to Reach the Final",
                            "values": [
                                {"value": "Home", "odd": "10.0"},
                                {"value": "Away", "odd": "1.10"},
                            ],
                        },
                        {
                            "id": 61,
                            "name": "To Qualify",
                            "values": [
                                {"value": "Home", "odd": "2.0"},
                                {"value": "Away", "odd": "1.8"},
                            ],
                        },
                    ],
                }],
            }],
        }

        with patch.object(pc, "API_KEY", "key"), \
                patch.object(pc.requests, "get", return_value=_FakeResponse(payload)):
            result = pc.fetch_qualify_odds(123, "France", "Norway")

        self.assertTrue(result["available"])
        self.assertEqual(result["bet_id"], 61)
        self.assertAlmostEqual(result["p_adv_home"], 0.474, places=3)

    def test_qualify_odds_ignores_zero_or_malformed_odds(self):
        payload = {
            "response": [{
                "bookmakers": [{
                    "name": "book",
                    "bets": [{
                        "id": 61,
                        "name": "To Qualify",
                        "values": [
                            {"value": "Home", "odd": "0"},
                            {"value": "Away", "odd": "bad"},
                        ],
                    }],
                }],
            }],
        }

        with patch.object(pc, "API_KEY", "key"), \
                patch.object(pc.requests, "get", return_value=_FakeResponse(payload)):
            result = pc.fetch_qualify_odds(123, "France", "Norway")

        self.assertFalse(result["available"])


if __name__ == "__main__":
    unittest.main()
