from pathlib import Path
import os
import tempfile
import unittest

from robosats_monitor import load_config, save_config
from robosats_platform import lock_file


class PlatformTests(unittest.TestCase):
    def test_exclusive_lock_releases_on_close(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bridge.lock'
            with lock_file(path):
                with self.assertRaises(BlockingIOError):
                    lock_file(path)
            with lock_file(path):
                self.assertTrue(path.exists())

    def test_settings_round_trip_and_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            cfg = {'garage_key': 'local-fixture-secret', 'chat': 42}
            for expected in (cfg, {**cfg, 'chat': 43}):
                save_config(path, expected)
                self.assertEqual(load_config(path), expected)
            if os.name == 'nt':
                self.assertNotIn('local-fixture-secret', path.read_text())
                self.assertIn('windows_dpapi', path.read_text())
