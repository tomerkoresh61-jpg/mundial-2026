import unittest

import mundial_2026 as mdl


class TeamLookupTests(unittest.TestCase):
    def test_arbitrary_substring_does_not_resolve_team(self):
        self.assertIsNone(mdl.find_team("rica", quiet=True))

    def test_word_prefix_partials_still_resolve(self):
        self.assertEqual(mdl.find_team("Bosnia", quiet=True), "Bosnia and Herzegovina")
        self.assertEqual(mdl.find_team("Verde", quiet=True), "Cape Verde")
        self.assertEqual(mdl.find_team("DR C", quiet=True), "DR Congo")

    def test_alias_and_accent_resolution_still_work(self):
        self.assertEqual(mdl.find_team("Curaçao", quiet=True), "Curacao")
        self.assertEqual(mdl.find_team("Korea Republic", quiet=True), "South Korea")


if __name__ == "__main__":
    unittest.main()
