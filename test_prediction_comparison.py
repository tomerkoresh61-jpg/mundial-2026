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


class QualifyOddsMappingTests(unittest.TestCase):
    def test_one_sided_team_label_match_uses_remaining_value_for_other_side(self):
        payload = {
            "response": [{
                "bookmakers": [{
                    "name": "book",
                    "bets": [{
                        "id": 61,
                        "name": "To Qualify",
                        "values": [
                            {"value": "Portugal", "odd": "1.80"},
                            {"value": "Korea Republic", "odd": "2.00"},
                        ],
                    }],
                }],
            }],
        }

        with patch.object(pc, "API_KEY", "key"), \
                patch.object(pc.requests, "get", return_value=_FakeResponse(payload)):
            result = pc.fetch_qualify_odds(
                123, home="South Korea", away="Portugal")

        self.assertTrue(result["available"])
        self.assertAlmostEqual(result["p_adv_home"], 0.474, places=3)
        self.assertAlmostEqual(result["p_adv_away"], 0.526, places=3)


if __name__ == "__main__":
    unittest.main()
