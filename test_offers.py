from unittest import TestCase
from unittest.mock import Mock

from robosats_offers import book, OfferBrowser


class OfferTests(TestCase):
    def test_only_usd_sellers_accepting_usdt_and_uses_no_robot_auth(self):
        get = Mock(return_value=Mock(status_code=200, json=Mock(return_value=[
            {'id': 7, 'type': 1, 'currency': 1, 'payment_method': 'Strike, USDT (TRC20)'},
            {'id': 8, 'type': 1, 'currency': 1, 'payment_method': 'L-USDt'},
            {'id': 9, 'type': 0, 'currency': 1, 'payment_method': 'USDT'},
            {'id': 10, 'type': 1, 'currency': 2, 'payment_method': 'USDT'},
            {'id': 11, 'type': 1, 'currency': 1, 'payment_method': 'Zelle, Strike, Monero, Cash App'},
            {'id': 12, 'type': 1, 'currency': 1, 'payment_method': 'USDTX, USDC'},
        ])))
        self.assertEqual([row['id'] for row in book({'auth': 'secret', 'offer_method': 'USDT'}, get, 'lake')], [7, 8])
        self.assertEqual(get.call_args.args, ({'auth': None, 'offer_method': 'USDT', 'coordinator': 'lake'},
                                              '/api/book/', {'currency': 1, 'type': 1}))

    def test_private_owner_can_review_and_missing_offer_is_reported(self):
        telegram = Mock()
        get = Mock(return_value=[{'id': 7, 'amount': '50', 'currency': 1, 'premium': '2.50', 'payment_method': 'Zelle'}])
        browser = OfferBrowser(123, {'lake': 'The Big Lake'}, get, telegram)
        callback = {'id': 'fixture', 'data': 'offer:lake:7', 'from': {'id': 456},
                    'message': {'chat': {'type': 'private', 'id': 123}}}
        browser.handle({'callback_query': callback})
        telegram.assert_not_called()
        callback['from']['id'] = 123
        browser.handle({'callback_query': callback})
        self.assertIn('50.00 USD', telegram.call_args.args[1]['text'])
        self.assertIn('Zelle', telegram.call_args.args[1]['text'])
        get.return_value = []
        browser.handle({'callback_query': callback})
        self.assertIn('no longer', telegram.call_args.args[1]['text'])
