import unittest
from unittest.mock import patch

from robosats_monitor import pair_telegram
from robosats_offers import amount, book


class SetupTests(unittest.TestCase):
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
