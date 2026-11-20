from contextlib import redirect_stdout
from decimal import Decimal
from io import StringIO
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from robosats_bridge import BridgeError, TelegramConnectionError
from robosats_mobile import MobileOffers
from robosats_offers import BUY, book, bond_text, OfferBrowser, run_offer_browser


class OfferTests(TestCase):
    def test_startup_recovers_from_connection_failures_at_each_telegram_step(self):
        for failing_method in ('getWebhookInfo', 'setMyCommands', 'setChatMenuButton', 'sendMessage'):
            with self.subTest(method=failing_method):
                failures = 0

                def telegram(cfg, method, params):
                    nonlocal failures
                    if method == failing_method and failures < 2:
                        failures += 1
                        raise TelegramConnectionError('Temporary disconnect')
                    if method == 'getWebhookInfo':
                        return {'url': ''}
                    if method == 'getUpdates':
                        raise KeyboardInterrupt
                    return True

                output = StringIO()
                with TemporaryDirectory() as directory, redirect_stdout(output):
                    with patch('robosats_offers.time.sleep') as sleep, self.assertRaises(KeyboardInterrupt):
                        run_offer_browser({'chat': '1', 'bot': '99:test', 'port': 9050}, directory,
                                          {'temple': ('Temple', 'http://fixture.onion')},
                                          Mock(), lambda port: port, telegram)
                self.assertEqual(sleep.call_count, 2)
                self.assertEqual(output.getvalue().count('Retrying in 5 seconds'), 1)
                self.assertIn('Telegram connection restored.', output.getvalue())
                self.assertIn('Bridge ready.', output.getvalue())

    def test_startup_still_stops_for_a_competing_listener(self):
        telegram = Mock(side_effect=BridgeError('Telegram reports a competing bot listener or webhook.'))
        with TemporaryDirectory() as directory, patch('robosats_offers.time.sleep') as sleep:
            with self.assertRaisesRegex(BridgeError, 'competing'):
                run_offer_browser({'chat': '1', 'bot': '99:test', 'port': 9050}, directory,
                                  {'temple': ('Temple', 'http://fixture.onion')}, Mock(), lambda port: port, telegram)
        sleep.assert_not_called()

    def test_startup_sends_main_buttons_without_a_menu_tap(self):
        get = Mock()
        send = Mock()

        def telegram(cfg, method, params):
            if method == 'getUpdates':
                raise KeyboardInterrupt
            if method == 'getWebhookInfo':
                return {'url': ''}
            if method == 'sendMessage':
                send(params)
            return True

        with TemporaryDirectory() as directory, self.assertRaises(KeyboardInterrupt):
            run_offer_browser({'chat': '1', 'bot': '99:test', 'port': 9050}, directory,
                              {'temple': ('Temple', 'http://fixture.onion')}, get, lambda port: port, telegram,
                              lambda chat, names, get_book, bot: MobileOffers(
                                  chat, names, get_book, bot, Mock(), Mock(), Mock(),
                                  save_filter=Mock(), alert_book=Mock()))
        ready, menu = [call.args[0] for call in send.call_args_list]
        self.assertTrue(ready['text'].startswith('🤖 RoboSats Bridge Ready'))
        self.assertEqual(menu['text'], '🤖 RoboSats Bridge Menu')
        self.assertEqual(ready['reply_markup'], {'remove_keyboard': True})
        keyboard = menu['reply_markup']['inline_keyboard']
        self.assertEqual([row[0]['text'] for row in keyboard],
                         ['🔎 Browse offers', '🎛️ Offer filters', '🔔 Offer alerts', '↩️ Resume an order'])
        get.assert_not_called()

    def test_polling_reports_outage_once_and_reports_recovery_even_without_updates(self):
        failure = 'Telegram chat bridge connection failed.'
        poll = Mock(side_effect=[BridgeError(failure), BridgeError(failure), [], [], KeyboardInterrupt])

        def telegram(cfg, method, params):
            if method == 'getUpdates':
                return poll()
            if method == 'getWebhookInfo':
                return {'url': ''}
            return True

        output = StringIO()
        with TemporaryDirectory() as directory, redirect_stdout(output), patch('robosats_offers.time.sleep') as sleep:
            with self.assertRaises(KeyboardInterrupt):
                run_offer_browser({'chat': '1', 'bot': '99:test', 'port': 9050}, directory,
                                  {'temple': ('Temple', 'http://fixture.onion')}, Mock(), lambda port: port, telegram)

        self.assertEqual(sleep.call_count, 2)
        lines = output.getvalue().splitlines()
        self.assertEqual(lines[1:], [
            f'{failure} Retrying in 5 seconds.',
            'Telegram connection restored. The bridge is listening again.',
        ])

    def test_sell_alert_book_reads_public_buy_offers_only(self):
        buyer = {'id': 7, 'type': BUY, 'currency': 1, 'payment_method': 'USDT'}
        get = Mock(return_value=Mock(status_code=200, json=Mock(return_value=[
            buyer, {**buyer, 'id': 8, 'type': 1}, {**buyer, 'id': 9, 'has_password': True}])))
        cfg = {'auth': 'fixture', 'offer_currency': 'USD', 'offer_method': 'USDT'}
        self.assertEqual(book(cfg, get, 'lake', BUY), [buyer])
        self.assertIsNone(get.call_args.args[0]['auth'])
        self.assertEqual(get.call_args.args[-1], {'currency': 1, 'type': BUY})

    def test_bond_estimates_use_fixed_sats_or_the_selected_fiat_amount(self):
        fixed = {'is_explicit': True, 'satoshis': 500_000, 'bond_size': '3.00'}
        floating = {'has_range': True, 'min_amount': '100', 'max_amount': '200',
                    'satoshis_now': 400_000, 'bond_size': '2.50'}
        self.assertEqual(bond_text(fixed, Decimal('100')), '3% (~15,000 sats)')
        self.assertEqual(bond_text(floating), '2.5%')
        self.assertEqual(bond_text(floating, Decimal('150')), '2.5% (~7,500 sats)')
        self.assertEqual(bond_text({'amount': 100, 'price': 50_000, 'bond_size': 3},
                                   Decimal('100')), '3% (~6,000 sats)')
        self.assertEqual(bond_text({'bond_size': 3}, Decimal('100')), '3%')
        self.assertEqual(bond_text({}), 'unavailable')

    def test_only_usd_sellers_accepting_usdt_and_uses_no_robot_auth(self):
        get = Mock(return_value=Mock(status_code=200, json=Mock(return_value=[
            {'id': 7, 'type': 1, 'currency': 1, 'payment_method': 'Strike, USDT (TRC20)'},
            {'id': 8, 'type': 1, 'currency': 1, 'payment_method': 'L-USDt'},
            {'id': 9, 'type': 0, 'currency': 1, 'payment_method': 'USDT'},
            {'id': 10, 'type': 1, 'currency': 2, 'payment_method': 'USDT'},
            {'id': 11, 'type': 1, 'currency': 1, 'payment_method': 'Zelle, Strike, Monero, Cash App'},
            {'id': 12, 'type': 1, 'currency': 1, 'payment_method': 'USDTX, USDC'},
        ])))
        self.assertEqual([row['id'] for row in book({'auth': 'secret', 'offer_currency': 'USD', 'offer_method': 'USDT'}, get, 'lake')], [7, 8])
        self.assertEqual(get.call_args.args, ({'auth': None, 'offer_currency': 'USD', 'offer_method': 'USDT', 'coordinator': 'lake'},
                                              '/api/book/', {'currency': 1, 'type': 1}))
        self.assertEqual([row['id'] for row in book({'offer_method': 'USDT'}, get, 'lake')], [7, 8, 10])
        self.assertEqual(get.call_args.args[-1], {'currency': 0, 'type': 1})

    def test_private_owner_can_review_and_missing_offer_is_reported(self):
        telegram = Mock()
        get = Mock(return_value=[{'id': 7, 'amount': '50', 'currency': 1, 'premium': '2.50',
                                  'payment_method': 'Zelle', 'bond_size': 3, 'satoshis_now': 100_000}])
        browser = OfferBrowser(123, {'lake': 'The Big Lake'}, get, telegram)
        callback = {'id': 'fixture', 'data': 'offer:lake:7', 'from': {'id': 456},
                    'message': {'chat': {'type': 'private', 'id': 123}}}
        browser.handle({'callback_query': callback})
        telegram.assert_not_called()
        callback['from']['id'] = 123
        browser.handle({'callback_query': callback})
        self.assertIn('50.00 USD', telegram.call_args.args[1]['text'])
        self.assertIn('Zelle', telegram.call_args.args[1]['text'])
        self.assertIn('Taker bond: 3%\n', telegram.call_args.args[1]['text'])
        get.return_value = []
        browser.handle({'callback_query': callback})
        self.assertIn('no longer', telegram.call_args.args[1]['text'])
