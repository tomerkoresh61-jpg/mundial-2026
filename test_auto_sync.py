import unittest
from unittest.mock import patch

import auto_sync
import mundial_2026 as mdl


class ExtraTimeDetectionTests(unittest.TestCase):
    def setUp(self):
        auto_sync._sent_events.clear()

    def _process_goal(self, status, elapsed):
        calls = []
        event = {
            "type": "Goal",
            "detail": "Normal Goal",
            "player": {"name": "Kylian Mbappe"},
            "time": {"elapsed": elapsed, "extra": None},
        }
        with patch.object(auto_sync, "_get_fixture_events", return_value=[event]), \
                patch.object(auto_sync, "_notify"), \
                patch.object(mdl, "mark_extra_time", side_effect=calls.append):
            auto_sync._process_events(12345, "France", "Norway", status)
        return calls

    def test_second_half_stoppage_time_does_not_mark_aet(self):
        self.assertEqual(self._process_goal("2H", 92), [])

    def test_extra_time_status_marks_aet(self):
        self.assertEqual(self._process_goal("ET", 92), ["France", "Norway"])


if __name__ == "__main__":
    unittest.main()
