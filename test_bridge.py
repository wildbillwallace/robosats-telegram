import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from robosats_bridge import BridgeError, ChatBridge, close_keys, open_keys
from robosats_monitor import poll_trade_updates


class BridgeTests(unittest.TestCase):
    def test_seller_chat_notice_requires_active_order_and_chat_route(self):
        for peer_key, participants in [('api-key', None), (None, ('own', 'peer'))]:
            with self.subTest(peer_key=peer_key), TemporaryDirectory() as directory:
                def telegram(method, params):
                    if method == 'getUpdates':
                        return []
                    return {'url': ''}

                tg, post = Mock(side_effect=telegram), Mock()
                bridge = ChatBridge({'chat': '123', 'bot': '555:test'}, 42, 'Temple',
                                    directory, Mock(), tg, post, Mock())
                with bridge.lock:
                    poll_trade_updates(bridge, False, peer_key, participants)
                    poll_trade_updates(bridge, True, None, None)
                    self.assertFalse(any(call.args[0] == 'sendMessage' for call in tg.call_args_list))
                    poll_trade_updates(bridge, True, peer_key, participants)
                    poll_trade_updates(bridge, True, peer_key, participants)
                    messages = [call.args[1] for call in tg.call_args_list if call.args[0] == 'sendMessage']
                    self.assertEqual(len(messages), 1)
                    self.assertEqual(messages[0]['chat_id'], '123')
                    self.assertIn('Temple #42 · Seller chat is open', messages[0]['text'])
                    post.assert_not_called()

    def test_seller_chat_notice_can_retry_after_telegram_error(self):
        with TemporaryDirectory() as directory:
            tg = Mock(side_effect=[{'url': ''}, BridgeError('Temporary Telegram error'), {}])
            bridge = ChatBridge({'chat': '123', 'bot': '555:test'}, 42, 'Temple',
                                directory, Mock(), tg, Mock())
            with bridge.lock:
                with self.assertRaises(BridgeError):
                    bridge.announce_seller_chat(True, 'api-key', None)
                bridge.announce_seller_chat(True, 'api-key', None)
                bridge.announce_seller_chat(True, 'api-key', None)
                self.assertEqual(tg.call_count, 3)

    def test_only_current_private_owner_plain_text_sends(self):
        def update(number, sender=123, chat_type='private', date=1001, text='Hey, I’ll be home in 30 minutes.'):
            return {'update_id': number, 'message': {'from': {'id': sender},
                    'chat': {'id': 123, 'type': chat_type}, 'date': date, 'text': text}}

        with TemporaryDirectory() as directory:
            tg = Mock(side_effect=[{'url': ''}, [update(1, sender=555), update(2, chat_type='group'),
                        update(3, date=999), update(4, text='/start'),
                        update(5), {**update(6), 'message': {**update(6)['message'], 'forward_origin': {}}}], {}])
            keys = Mock()
            keys.encrypt.return_value = 'encrypted'
            post = Mock()
            bridge = ChatBridge({'chat': '123', 'bot': '555:test'}, 42, 'Temple', directory, keys, tg, post)
            try:
                bridge.started = 1000
                bridge.poll_messages(True, 'peer-key')
                post.assert_called_once_with({'order_id': 42, 'PGP_message': 'encrypted'})
                keys.encrypt.assert_called_once_with('Hey, I’ll be home in 30 minutes.')
                self.assertEqual(bridge.offset, 7)
            finally:
                bridge.lock.close()

    def test_nostr_reply_can_send_without_api_chat_key(self):
        update = {'update_id': 1, 'message': {'chat': {'id': 123, 'type': 'private'},
                  'from': {'id': 123}, 'date': 1001, 'text': 'Back soon'}}
        with TemporaryDirectory() as directory:
            tg = Mock(side_effect=[{'url': ''}, [update], {}])
            post = Mock()
            nostr = Mock()
            nostr.send.return_value = True
            bridge = ChatBridge({'chat': '123', 'bot': '555:test'}, 42, 'Temple',
                                directory, Mock(), tg, post, nostr)
            try:
                bridge.started = 1000
                bridge.poll_messages(True, None, ('own', 'peer'))
                nostr.send.assert_called_once_with('Back soon', ('own', 'peer'))
                post.assert_not_called()
                self.assertIn('accepted by the Nostr relay', tg.call_args.args[1]['text'])
            finally:
                bridge.lock.close()

    def test_nostr_only_reply_replay_does_not_forward_twice(self):
        import json
        import time

        now = int(time.time())
        nostr = Mock()
        nostr.receive.return_value = [{'id': 'abc', 'time': now, 'text': 'Nostr only'}]
        with TemporaryDirectory() as directory:
            tg = Mock(return_value={'url': ''})
            bridge = ChatBridge({'chat': '123', 'bot': '555:test'}, 42, 'Temple',
                                directory, Mock(), tg, Mock(), nostr)
            try:
                saved = Mock()
                state = {}
                bridge.poll_nostr(('own', 'peer'), state, saved)
                bridge.poll_nostr(('own', 'peer'), json.loads(json.dumps(state)), saved)
                self.assertEqual(tg.call_count, 2)
                self.assertIn('Nostr only', tg.call_args.args[1]['text'])
                self.assertNotIn('Nostr only', json.dumps(state))
                saved.assert_called_once()
            finally:
                bridge.lock.close()

    @unittest.skipUnless(shutil.which('gpg'), 'GnuPG is required')
    def test_signed_encrypted_round_trip_with_throwaway_keys(self):
        def make_robot(directory, nickname):
            args = ['gpg', '--no-options', '--homedir', directory, '--batch', '--yes',
                    '--pinentry-mode', 'loopback', '--passphrase', 'test-passphrase']

            def gpg(*flags):
                return subprocess.run(args + list(flags), capture_output=True, check=True).stdout.decode()

            gpg('--quick-generate-key', nickname, 'ed25519', 'sign', '1d')
            listing = gpg('--with-colons', '--fingerprint', nickname)
            fingerprint = next(line.split(':')[9] for line in listing.splitlines() if line.startswith('fpr:'))
            gpg('--quick-add-key', fingerprint, 'cv25519', 'encr', '1d')
            return {'public_key': gpg('--armor', '--export', fingerprint),
                    'encrypted_private_key': gpg('--armor', '--export-secret-keys', fingerprint)}

        source_a = TemporaryDirectory()
        source_b = TemporaryDirectory()
        loaded = []
        try:
            a = make_robot(source_a.name, 'Test Alpha <a@example.test>')
            b = make_robot(source_b.name, 'Test Beta <b@example.test>')
            for robot in [a, b]:
                loaded.append(open_keys(robot, 'test-passphrase'))
            keys_a, keys_b = [item[1] for item in loaded]
            keys_a.set_peer(b['public_key'])
            keys_b.set_peer(a['public_key'])
            self.assertEqual(keys_b.decrypt(keys_a.encrypt('See you in 30 minutes.')).strip(),
                             'See you in 30 minutes.')
        finally:
            for directory in [source_a, source_b] + [item[0] for item in loaded]:
                close_keys(directory)


if __name__ == '__main__':
    unittest.main()
