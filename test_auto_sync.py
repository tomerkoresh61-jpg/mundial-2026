import unittest

import auto_sync


class LiveFixtureFilteringTests(unittest.TestCase):
    def test_live_fixture_ids_query_and_filter_to_world_cup(self):
        calls = []

        def fake_get(endpoint, params):
            calls.append((endpoint, params))
            return {
                "response": [
                    {
                        "fixture": {"id": 101},
                        "league": {"id": auto_sync.LEAGUE_ID, "season": auto_sync.SEASON},
                    },
                    {
                        "fixture": {"id": 202},
                        "league": {"id": 253, "season": auto_sync.SEASON},
                    },
                    {
                        "fixture": {"id": 303},
                        "league": {"id": auto_sync.LEAGUE_ID, "season": auto_sync.SEASON - 4},
                    },
                ]
            }

        original_get = auto_sync._get
        try:
            auto_sync._get = fake_get
            self.assertEqual(auto_sync._get_live_fixture_ids(), [101])
        finally:
            auto_sync._get = original_get

        self.assertEqual(calls, [("fixtures", {"live": str(auto_sync.LEAGUE_ID)})])

    def test_world_cup_fixture_accepts_api_responses_without_season(self):
        self.assertTrue(
            auto_sync._is_world_cup_fixture(
                {"fixture": {"id": 101}, "league": {"id": auto_sync.LEAGUE_ID}}
            )
        )

    def test_world_cup_fixture_rejects_non_world_cup_league(self):
        self.assertFalse(
            auto_sync._is_world_cup_fixture(
                {"fixture": {"id": 202}, "league": {"id": 253, "season": auto_sync.SEASON}}
            )
        )


if __name__ == "__main__":
    unittest.main()
