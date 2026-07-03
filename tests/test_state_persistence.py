import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

import mundial_2026 as mdl


class StatePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.original_state_file = mdl.STATE_FILE
        self.team = next(iter(mdl.TEAMS))
        self.player = next(iter(mdl.TEAMS[self.team]["players"]))
        self.original_available = mdl.TEAMS[self.team]["players"][self.player]["available"]

    def tearDown(self):
        mdl.STATE_FILE = self.original_state_file
        mdl.TEAMS[self.team]["players"][self.player]["available"] = self.original_available

    def _write_state(self, path, available):
        path.write_text(json.dumps({
            "availability": {self.player: available},
            "teams": {},
            "player_form": {},
            "player_fitness": {},
            "team_form": {},
            "yellow_cards": {},
            "extra_time": {},
            "lineup_confirmed": {},
        }))

    def test_load_state_waits_for_inflight_mutation_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            mdl.STATE_FILE = str(state_path)
            self._write_state(state_path, True)
            mdl.TEAMS[self.team]["players"][self.player]["available"] = True

            mutation_started = threading.Event()
            release_mutation = threading.Event()

            def mutate_and_save():
                with mdl._STATE_LOCK:
                    mdl.TEAMS[self.team]["players"][self.player]["available"] = False
                    mutation_started.set()
                    release_mutation.wait(timeout=1)
                    mdl._save_state()

            mutator = threading.Thread(target=mutate_and_save)
            loader = threading.Thread(target=mdl._load_state)

            mutator.start()
            self.assertTrue(mutation_started.wait(timeout=1))
            loader.start()
            time.sleep(0.05)
            self.assertTrue(loader.is_alive())

            release_mutation.set()
            mutator.join(timeout=1)
            loader.join(timeout=1)

            self.assertFalse(mdl.TEAMS[self.team]["players"][self.player]["available"])
            saved = json.loads(state_path.read_text())
            self.assertFalse(saved["availability"][self.player])

    def test_invalid_state_file_does_not_crash_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            mdl.STATE_FILE = str(state_path)
            state_path.write_text("{invalid")
            mdl.TEAMS[self.team]["players"][self.player]["available"] = False

            mdl._load_state()

            self.assertFalse(mdl.TEAMS[self.team]["players"][self.player]["available"])


if __name__ == "__main__":
    unittest.main()
