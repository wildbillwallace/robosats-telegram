from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from robosats_monitor import load_config, save_config
import robosats_platform as platform
from robosats_platform import keep_awake, lock_file


class PlatformTests(unittest.TestCase):
    def test_caffeinate_released_on_interruption(self):
        process = Mock()
        with patch.object(platform.os, 'name', 'posix'), \
             patch.object(platform.shutil, 'which', return_value='/usr/bin/caffeinate'), \
             patch.object(platform.subprocess, 'Popen', return_value=process) as launch:
            with self.assertRaises(KeyboardInterrupt), keep_awake():
                launch.assert_called_once_with(['/usr/bin/caffeinate', '-i', '-w', str(os.getpid())])
                process.terminate.assert_not_called()
                raise KeyboardInterrupt
        process.terminate.assert_called_once()
        process.wait.assert_called_once()

    @unittest.skipUnless(os.name == 'nt', 'Windows power request integration test')
    def test_windows_power_request_released_on_interruption(self):
        import ctypes

        set_state = ctypes.windll.kernel32.SetThreadExecutionState
        set_state.argtypes = (ctypes.c_uint32,)
        set_state.restype = ctypes.c_uint32
        continuous, system = platform.ES_CONTINUOUS, platform.ES_SYSTEM_REQUIRED
        previous = set_state(continuous)
        self.assertNotEqual(previous, 0)
        try:
            with self.assertRaises(KeyboardInterrupt), keep_awake():
                active = set_state(continuous | system)
                self.assertEqual(active & system, system)
                raise KeyboardInterrupt
            released = set_state(continuous)
            self.assertNotEqual(released, 0)
            self.assertEqual(released & system, 0)
        finally:
            set_state(continuous | previous)

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
