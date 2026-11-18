import unittest
from pathlib import Path
from unittest.mock import call, patch

from robosats_monitor import bind_robot, lookup_robot, pair_telegram, robot_signing_token
from robosats_offers import amount, book


class SetupTests(unittest.TestCase):
    def test_normal_launch_starts_phone_mode_without_terminal_menu(self):
        from tempfile import TemporaryDirectory
        from robosats_monitor import main

        with TemporaryDirectory() as directory:
            config = Path(directory) / 'settings.json'
            config.touch()
            with patch('sys.argv', ['robosats_monitor.py', '--config', str(config)]), \
                 patch('sys.stdin.isatty', return_value=True), \
                 patch('robosats_monitor.load_config', return_value={'port': 9050}), \
                 patch('robosats_monitor.browse_offers') as browse, \
                 patch('robosats_monitor.interactive') as terminal:
                self.assertEqual(main(), 0)
            browse.assert_called_once()
            self.assertTrue(browse.call_args.kwargs['prompt_for_garage'])
            terminal.assert_not_called()

    def test_launcher_can_unlock_garage_for_one_run_or_save_it(self):
        from types import SimpleNamespace
        from robosats_monitor import browse_offers

        cfg = {'port': 9050}
        args = SimpleNamespace(config=Path('test-settings'), unlock=False)

        for key, answer in (('', ''), ('fixture-key', ''), ('fixture-key', 'y')):
            with self.subTest(entered=bool(key), answer=answer), \
                 patch('robosats_monitor.session_garage_seed', return_value=None), \
                 patch('robosats_monitor.read_garage_key', return_value=key) as read, \
                 patch('robosats_monitor.decode_garage_key', return_value=b'fixture-seed'), \
                 patch('robosats_monitor.load_config', return_value=cfg), \
                 patch('robosats_monitor.save_config') as save, \
                 patch('robosats_offers.run_offer_browser', return_value=None) as launch, \
                 patch('builtins.input', return_value=answer), patch('builtins.print'):
                browse_offers(args, cfg, prompt_for_garage=True)
                read.assert_called_once_with(allow_empty=True)
                browser = launch.call_args.args[-1](1, {}, None, None)
                self.assertEqual(browser.chat_enabled, bool(key))
                if answer == 'y':
                    save.assert_called_once_with(args.config, {**cfg, 'garage_key': key})
                else:
                    save.assert_not_called()

    def test_pairing_requires_the_expected_private_chat_and_code(self):
        def update(number, sender, chat, kind, text):
            return {
                'update_id': number,
                'message': {'from': {'id': sender}, 'chat': {'id': chat, 'type': kind}, 'text': text},
            }

        rows = [update(1, 24, 24, 'private', 'wrong'),
                update(2, 24, 24, 'group', 'sample'),
                update(3, 25, 25, 'private', 'sample'),
                update(4, 24, 24, 'private', 'sample')]
        with patch('robosats_monitor.secrets.token_hex', return_value='sample'), \
                patch('robosats_monitor.bridge_telegram',
                      side_effect=[{'id': 99, 'username': 'example_bot'}, {'url': ''}, rows]), \
                patch('builtins.print'):
            self.assertEqual(pair_telegram({'bot': '99:test'}, expected_chat=24), 24)

    def test_euro_filter_and_labels(self):
        from types import SimpleNamespace

        rows = [
            {'id': 10, 'type': 1, 'currency': 2, 'payment_method': 'SEPA', 'amount': 50},
            {'id': 11, 'type': 1, 'currency': 1, 'payment_method': 'SEPA'},
            {'id': 12, 'type': 1, 'currency': 2, 'payment_method': 'Cash'},
        ]

        def get(runtime, endpoint, params):
            self.assertIsNone(runtime['auth'])
            self.assertEqual(endpoint, '/api/book/')
            self.assertEqual(params, {'currency': 2, 'type': 1})
            return SimpleNamespace(status_code=200, json=lambda: rows)

        offers = book({'auth': 'test', 'offer_currency': 'EUR', 'offer_method': 'sepa'}, get, 'temple')
        self.assertEqual([row['id'] for row in offers], [10])
        self.assertEqual(amount(offers[0]), '50.00 EUR')


class RobotSelectionTests(unittest.TestCase):
    def test_pick_by_nickname_and_keep_other_coordinator(self):
        cfg = {'port': 9050, 'auth': 'ancient-temple-credential'}
        path = Path('example-settings.json')

        def robot(runtime, auth):
            self.assertEqual(runtime['coordinator'], 'lake')
            self.assertEqual(runtime['port'], 9100)
            return {'Token 0': {'nickname': 'BrightHeron', 'active_order_id': 42},
                    'Token 7': {'nickname': 'CalmOtter'}}.get(auth)

        with patch('robosats_monitor.choose_coordinator', return_value='lake'), \
             patch('robosats_monitor.session_garage_seed', return_value=b'test'), \
             patch('robosats_monitor.tor_port', return_value=9100), \
             patch('robosats_monitor.garage_authorization', side_effect=lambda _, i: f'Token {i}'), \
             patch('robosats_monitor.lookup_robot', side_effect=robot), \
             patch('robosats_monitor.save_config') as save, \
             patch('builtins.input', return_value='calmotter'), patch('builtins.print') as display:
            bind_robot(path, cfg)
        save.assert_called_once_with(path, cfg)
        self.assertEqual(cfg['auth'], 'ancient-temple-credential')
        self.assertEqual(cfg['coordinator_auth'], {'lake': 'Token 7'})
        self.assertEqual(cfg['robot_slots'], {'lake': 7})
        display.assert_any_call('  BrightHeron · active order #42')

    def test_search_more_then_accept_single_robot_with_enter(self):
        cfg = {'port': 9050}
        with patch('robosats_monitor.choose_coordinator', return_value='temple'), \
             patch('robosats_monitor.session_garage_seed', return_value=b'test'), \
             patch('robosats_monitor.tor_port', return_value=9050), \
             patch('robosats_monitor.garage_authorization', side_effect=lambda _, i: f'Token {i}'), \
             patch('robosats_monitor.lookup_robot',
                   side_effect=lambda _, auth: {'nickname': 'LateBee'} if auth == 'Token 12' else None), \
             patch('robosats_monitor.save_config'), patch('builtins.print'), \
             patch('builtins.input', side_effect=['/more', '']) as ask:
            bind_robot(Path('example-settings.json'), cfg)
        self.assertEqual(ask.call_args_list, [call('Robot nickname: '), call('Press Enter to use LateBee: ')])
        self.assertEqual(cfg['auth'], 'Token 12')

    def test_unregistered_lookup_is_read_only_and_skipped(self):
        from types import SimpleNamespace

        runtime = {'coordinator': 'lake', 'port': 9050}
        response = SimpleNamespace(status_code=400, json=lambda: {'error_code': 7001})
        with patch('robosats_monitor.coordinator_get', return_value=response) as get:
            self.assertIsNone(lookup_robot(runtime, 'Token example'))
        get.assert_called_once_with({**runtime, 'auth': 'Token example'}, '/api/robot/', {})

    def test_signing_uses_saved_slot_beyond_the_default_search(self):
        cfg = {'coordinator': 'lake', 'auth': 'Token confirmed', 'robot_slots': {'lake': 123}}
        with patch('robosats_monitor.garage_robot_token', return_value='confirmed') as derive, \
             patch('robosats_monitor.robot_authorization', side_effect=lambda token: f'Token {token}'):
            self.assertEqual(robot_signing_token(cfg, b'test', interactive_search=False), 'confirmed')
        derive.assert_called_once_with(b'test', 123)
