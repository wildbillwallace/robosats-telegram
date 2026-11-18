from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import TestCase
from unittest.mock import Mock

from robosats_mobile import MobileOffers, MobileTrade
from robosats_offers import BUY, SELL


def callback(data, sender=123):
    return {'callback_query': {'id': 'fixture', 'data': data, 'from': {'id': sender},
                              'message': {'chat': {'id': 123, 'type': 'private'}}}}


def listing():
    return dict(id=3, currency=1, type=1, amount='25.00', premium='2', bond_size='3',
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=4)).isoformat())


def trade(status, **extra):
    return dict(listing(), is_buyer=True, is_taker=True, status=status, **extra)


class MobileTests(TestCase):
    def test_paid_bond_continues_directly_and_unpaid_bond_keeps_invoice(self):
        for status in (3, 6, 7, 8, 9, 10, 13):
            with self.subTest(status=status):
                bot = Mock()
                row = trade(status, bond_invoice='lnbc' + 'a' * 30, bond_satoshis=500,
                            expires_at='2999-01-01T00:00:00Z')
                browser = MobileOffers(123, {'temple': 'Temple'}, Mock(), bot,
                                       Mock(return_value=row), Mock(), Mock(), True)
                browser.handle(callback('active:temple:3'))
                if status == 3:
                    self.assertIsNone(browser.handoff)
                    self.assertIn('Continue order', str(bot.call_args_list))
                else:
                    self.assertEqual(browser.handoff, ('temple', 3))
                    self.assertFalse(any(call.args[0] == 'sendMessage' for call in bot.call_args_list))

    def test_connected_notice_contains_current_payout_action(self):
        mobile = MobileTrade(123, 3, 'Temple', Mock(), Mock(), Mock(), Mock())
        for status in (6, 8):
            row = trade(status, maker_locked=True, taker_locked=True, invoice_amount=12_000)
            notice = mobile.status_message(row, connected=True)
            self.assertIn('Temple #3 · Connected in Telegram', notice['text'])
            self.assertIn('Your bond is locked.', notice['text'])
            self.assertIn('communicate with the seller', notice['text'])
            self.assertNotIn('Tap Menu', notice['text'])
            self.assertEqual(notice['reply_markup']['inline_keyboard'][0][0]['text'],
                             '⚡ Set up Lightning payout')
        notice = mobile.status_message(trade(10), connected=True)
        self.assertIn('Payment marked sent', notice['text'])
        self.assertNotIn('reply_markup', notice)

    def test_alert_caps_are_directional_and_repeat_scans_do_not_resend(self):
        high = dict(listing(), id=4, premium='3.00')
        low = dict(listing(), id=5, premium='1.00')
        for side, expected in ((SELL, 5), (BUY, 4)):
            with self.subTest(side=side):
                bot, save, take = Mock(), Mock(), Mock()
                browser = MobileOffers(123, {'temple': 'Temple'}, Mock(), bot, Mock(), Mock(), take,
                                       save_filter=save, alert_book=Mock())
                rows = [('temple', dict(row, type=side)) for row in (high, low)]
                browser.deliver_alerts(rows, side, Decimal('2'))
                self.assertEqual(bot.call_args.args[1]['reply_markup']['inline_keyboard'][0][0]['callback_data'],
                                 f'alert:{side}:temple:{expected}')
                browser.deliver_alerts(rows, side, Decimal('2'))
                bot.assert_called_once()
                save.assert_called_once()
                take.assert_not_called()

    def test_owner_sets_sell_alerts_and_can_view_without_taking(self):
        bot = Mock(return_value={'message_id': 17})
        take, save = Mock(), Mock()
        book = Mock(return_value=[dict(listing(), type=BUY)])
        browser = MobileOffers(123, {'temple': 'Temple'}, Mock(), bot, Mock(), Mock(), take,
                               save_filter=save, alert_book=book, alert_urls={'temple': 'http://fixture.onion'})
        browser.handle(callback('alerts:sell'))
        browser.handle(callback('alerts:premium'))
        browser.handle({'message': {'text': '+1.5%', 'from': {'id': 123},
                                    'chat': {'id': 123, 'type': 'private'}, 'reply_to_message': {'message_id': 17}}})
        browser.handle(callback('alerts:enable'))
        self.assertEqual(browser.cfg['offer_alert'], {'side': 'sell', 'premium': '+1.5', 'enabled': True})
        browser.handle(callback('alert:0:temple:3'))
        self.assertIn('http://fixture.onion/order/temple/3', bot.call_args.args[1]['text'])
        self.assertNotIn('Review buy offer', str(bot.call_args.args[1]))
        browser.handle(callback('alerts:pause'))
        self.assertFalse(browser.cfg['offer_alert']['enabled'])
        take.assert_not_called()

    def test_alert_scan_ignores_results_from_before_filters_changed(self):
        from concurrent.futures import Future

        old, new = Future(), Future()
        pool = Mock()
        pool.submit.side_effect = [old, new]
        bot = Mock()
        browser = MobileOffers(123, {'temple': 'Temple'}, Mock(), bot, Mock(), Mock(), Mock(),
                               save_filter=Mock(), alert_book=Mock())
        browser.cfg = {'port': 9050, 'offer_alert': {'enabled': True}}
        browser.poll_alerts(pool)
        browser.cfg['offer_currency'] = 'EUR'
        old.set_result(([('temple', listing())], []))
        browser.poll_alerts(pool)
        bot.assert_not_called()
        self.assertEqual(pool.submit.call_count, 2)
        new.set_result(([('temple', dict(listing(), currency=2))], []))
        browser.poll_alerts(pool)
        self.assertIn('EUR', bot.call_args.args[1]['text'])

    def test_offer_supplies_coordinator_for_robot_lookup(self):
        telegram, take = Mock(), Mock()
        lookup = Mock(return_value=([('CalmOtter', 'fixture-auth', 7, None)], 10))
        has_robot, select = Mock(return_value=False), Mock()
        browser = MobileOffers(123, {'bazaar': 'LibreBazaar', 'lake': 'The Big Lake'},
                               Mock(return_value=[listing()]), telegram, Mock(), Mock(), take,
                               True, list_robots=lookup, select_robot=select, has_robot=has_robot)
        self.assertNotIn('Select robot', str(browser.navigation()))
        browser.handle(callback('offer:bazaar:3'))
        lookup.assert_called_once_with('bazaar', 0)
        prompt = telegram.call_args.args[1]
        self.assertIn('Offer #3 · LibreBazaar', prompt['text'])
        buttons = prompt['reply_markup']['inline_keyboard']
        self.assertEqual(buttons[1][0]['callback_data'], 'robots:bazaar:10:3')
        browser.handle(callback(buttons[0][0]['callback_data']))
        select.assert_called_once_with('bazaar', 'fixture-auth', 7)
        self.assertIn('Review offer #3', str(telegram.call_args.args))
        self.assertIsNone(browser.confirmation)
        has_robot.return_value = True
        browser.handle(callback('offer:bazaar:3'))
        self.assertIsNotNone(browser.confirmation)
        self.assertIn('Choose another robot', str(telegram.call_args.args))
        browser.handle(callback('robots:bazaar:0:3'))
        self.assertIsNone(browser.confirmation)
        take.assert_not_called()

    def test_select_robot_and_resume_an_active_order_from_telegram(self):
        telegram, take, select = Mock(), Mock(), Mock()
        lookup = Mock(return_value=([('RestingFox', 'idle-auth', 4, None),
                                     ('CalmOtter', 'fixture-auth', 7, 3)], 10))
        browser = MobileOffers(123, {'bazaar': 'LibreBazaar'}, Mock(), telegram,
                               Mock(return_value=trade(9)), Mock(), take, True,
                               list_robots=lookup, select_robot=select)
        browser.handle(callback('resume'))
        self.assertIn('Find my order', str(telegram.call_args.args))
        lookup.assert_not_called()
        browser.handle(callback('resume:find'))
        self.assertIn('LibreBazaar', str(telegram.call_args.args))
        browser.handle(callback('robots:bazaar:0'))
        lookup.assert_called_once_with('bazaar', 0)
        keyboard = telegram.call_args.args[1]['reply_markup']['inline_keyboard']
        self.assertEqual(keyboard[0][0]['text'], 'CalmOtter · order #3')
        self.assertNotIn('RestingFox', str(keyboard))
        self.assertNotIn('fixture-auth', str(keyboard))
        choice = keyboard[0][0]['callback_data']
        browser.handle(callback(choice, sender=999))
        select.assert_not_called()
        browser.confirmation = ('old offer',)
        browser.handle(callback(choice))
        select.assert_called_once_with('bazaar', 'fixture-auth', 7)
        self.assertIsNone(browser.confirmation)
        self.assertIn('Open order #3', str(telegram.call_args.args))
        browser.handle(callback('active:bazaar:3'))
        self.assertEqual(browser.handoff, ('bazaar', 3))
        take.assert_not_called()

    def test_phone_filters_choose_currency_payment_and_coordinator(self):
        book, save, take = Mock(return_value=[]), Mock(), Mock()
        bot = Mock(return_value={'message_id': 47})
        browser = MobileOffers(123, {'lake': 'The Big Lake', 'bazaar': 'LibreBazaar'},
                               book, bot, Mock(), Mock(), take, save_filter=save)
        browser.confirmation = ('old',)
        browser.handle(callback('currency:BRL', sender=555))
        save.assert_not_called()
        browser.handle(callback('filters'))
        self.assertIn('all currencies', bot.call_args.args[1]['text'])
        currency_buttons = bot.call_args.args[1]['reply_markup']['inline_keyboard']
        self.assertIn({'text': '🇧🇷 BRL', 'callback_data': 'currency:BRL'}, currency_buttons[2])
        browser.handle(callback('currency:BRL'))
        self.assertIsNone(browser.confirmation)
        saved = bot.call_args.args[1]
        self.assertIn('Current filters · BRL', saved['text'])
        self.assertIn('Once you’ve chosen your filters, tap Browse offers.', saved['text'])
        self.assertEqual(saved['reply_markup']['inline_keyboard'][-1][0]['text'], '🔎 Browse offers')
        browser.handle(callback('payment:custom'))
        browser.handle({'message': {'from': {'id': 123}, 'chat': {'id': 123, 'type': 'private'},
                                    'text': 'Pix', 'reply_to_message': {'message_id': 47}}})
        browser.handle(callback('coordinator:bazaar'))
        self.assertEqual(browser.cfg, {'offer_currency': 'BRL', 'offer_method': 'Pix',
                                       'offer_coordinator': 'bazaar'})
        browser.handle(callback('offers:0'))
        book.assert_called_once_with('bazaar')
        self.assertIn('BRL · Pix · LibreBazaar', bot.call_args.args[1]['text'])
        take.assert_not_called()

    def test_take_is_one_shot_and_shows_bond(self):
        row = listing()
        api = Mock(return_value=trade(3, bond_invoice='lnbc' + 'q' * 30, bond_satoshis=234))
        bot = Mock()
        browser = MobileOffers(123, {'temple': 'Temple'}, Mock(return_value=[row]), bot, Mock(), Mock(), api)
        browser.handle(callback('offer:temple:3'))
        nonce = browser.confirmation[0]
        browser.handle(callback(f'take:{nonce}', sender=321))
        api.assert_not_called()
        browser.handle(callback(f'take:{nonce}'))
        api.assert_called_once_with('temple', row, None)
        self.assertTrue(any(call.args[1].get('text') == 'lnbc' + 'q' * 30 for call in bot.call_args_list))
        browser.handle(callback(f'take:{nonce}'))
        api.assert_called_once()

    def test_release_checks_the_same_unpaid_bond_at_confirmation(self):
        pending = trade(3, is_maker=False, taker_locked=False, bond_invoice='lnbc' + 'q' * 30, bond_satoshis=234)
        for current in (pending, trade(6, taker_locked=True), dict(pending, bond_invoice='lnbc' + 'p' * 30)):
            with self.subTest(status=current['status'], same_attempt=current == pending):
                bot = Mock()
                order = Mock(return_value=current)
                release = Mock(return_value={'id': 3, 'status': 1, 'is_taker': False, 'penalty': 'fixture'})
                browser = MobileOffers(123, {'temple': 'Temple'}, Mock(), bot, order, Mock(), Mock(), release=release)
                browser.show_order('temple', 3, pending)
                button = bot.call_args_list[-2].args[1]['reply_markup']['inline_keyboard'][1][0]
                self.assertEqual(button['text'], 'Release offer')
                browser.handle(callback(button['callback_data']))
                confirm = bot.call_args.args[1]['reply_markup']['inline_keyboard'][0][0]['callback_data']
                release.assert_not_called()
                browser.handle(callback(confirm, sender=999))
                order.assert_not_called()
                browser.handle(callback(confirm))
                order.assert_called_once_with('temple', 3)
                if current == pending:
                    release.assert_called_once_with('temple', 3)
                    self.assertIn('temporary cooldown', bot.call_args.args[1]['text'])
                    browser.handle(callback(confirm))
                    release.assert_called_once()
                else:
                    release.assert_not_called()

    def test_changed_offer_and_resume_do_not_take(self):
        row = listing()
        book = Mock(side_effect=[[row], [dict(row, payment_method='Changed')]])
        take = Mock()
        browser = MobileOffers(123, {'temple': 'Temple'}, book, Mock(),
                               Mock(return_value=trade(8)), Mock(return_value=3), take, True)
        browser.handle(callback('offer:temple:3'))
        browser.handle(callback('take:' + browser.confirmation[0]))
        take.assert_not_called()
        browser.handle(callback('resume'))
        browser.handle(callback('active:temple:3'))
        self.assertEqual(browser.handoff, ('temple', 3))
        take.assert_not_called()

    def test_ranged_offer_requires_matching_reply_and_exact_confirmed_amount(self):
        row = dict(listing(), has_range=True, min_amount='12', max_amount='25')
        take = Mock(return_value=trade(3))
        bot = Mock(return_value={'message_id': 10})
        browser = MobileOffers(123, {'temple': 'Temple'}, Mock(return_value=[row]), bot, Mock(), Mock(), take)
        browser.handle(callback('offer:temple:3'))
        msg = {'text': '21.42', 'from': {'id': 123}, 'chat': {'id': 123, 'type': 'private'}}
        browser.handle({'message': msg})
        self.assertIsNone(browser.confirmation)
        msg['reply_to_message'] = {'message_id': 10}
        browser.handle({'message': msg})
        browser.handle(callback('take:' + browser.confirmation[0]))
        take.assert_called_once_with('temple', row, Decimal('21.42'))

    def test_payout_and_fiat_require_explicit_confirmations(self):
        read = Mock(return_value=trade(8, maker_locked=True, taker_locked=True, invoice_amount=10_000))
        write, sign, bot = Mock(return_value=trade(9)), Mock(return_value='signed'), Mock()
        mobile = MobileTrade(123, 3, 'Temple', read, write, sign, bot)
        mobile.handle({'message': {'text': '/invoice 5000'}})
        mobile.handle({'message': {'text': 'lnbc99500n1' + 'q' * 111}})
        write.assert_not_called()
        mobile.handle(callback('trade:' + mobile.confirmation[0]))
        write.assert_called_once_with({'action': 'update_invoice', 'routing_budget_ppm': 5000, 'invoice': 'signed'})
        write.reset_mock()
        read.return_value = trade(9, escrow_locked=True)
        write.return_value = trade(10)
        mobile.handle(callback('fiat:3'))
        write.assert_not_called()
        nonce = mobile.confirmation[0]
        mobile.handle(callback('trade:' + nonce))
        mobile.handle(callback('trade:' + nonce))
        write.assert_called_once_with({'action': 'confirm'})

    def test_fiat_confirmation_cannot_mark_a_changed_amount_or_unlocked_escrow(self):
        read = Mock(return_value=trade(9, escrow_locked=True))
        write = Mock()
        mobile = MobileTrade(123, 3, 'Temple', read, write, Mock(), Mock())
        mobile.handle(callback('fiat:3'))
        nonce = mobile.confirmation[0]
        read.return_value = dict(trade(9, escrow_locked=True), amount='29.00')
        mobile.handle(callback('trade:' + nonce))
        write.assert_not_called()

    def test_sats_button_converts_and_shows_exact_invoice(self):
        read = Mock(return_value=trade(8, maker_locked=True, taker_locked=True, invoice_amount=1_250_000))
        bot = Mock(return_value={'message_id': 42})
        mobile = MobileTrade(123, 3, 'Temple', read, Mock(), Mock(), bot)
        mobile.handle(callback('fees:sats:3'))
        self.assertIsNone(mobile.invoice_plan)
        reply = {'text': '5500', 'reply_to_message': {'message_id': 42}}
        self.assertTrue(mobile.handle({'message': reply}))
        self.assertEqual(mobile.invoice_plan[:2], (4400, 1_244_500))
        self.assertIn('1,244,500-sat', bot.call_args.args[1]['text'])
        self.assertIn('5,500 sats, 4,400 ppm', bot.call_args.args[1]['text'])

    def test_expired_telegram_spinner_does_not_block_invoice_button(self):
        from unittest.mock import patch
        import robosats_monitor as monitor

        response = Mock(status_code=400, json=Mock(return_value={
            'ok': False, 'description': 'Bad Request: query is too old and response timeout expired or query ID is invalid'}))
        with patch.object(monitor, 'session') as session:
            session.return_value.post.return_value = response
            self.assertIsNone(monitor.bridge_telegram({'port': 1234, 'bot': 'fixture'},
                                                      'answerCallbackQuery', {'callback_query_id': 'fixture'}))

    def test_text_confirmation_matches_prompt_and_cannot_replay(self):
        read = Mock(return_value=trade(9, escrow_locked=True))
        write = Mock(return_value=trade(10))
        mobile = MobileTrade(123, 3, 'Temple', read, write, Mock(), Mock(return_value={'message_id': 17}))
        mobile.handle({'message': {'text': '/sent'}})
        mobile.handle({'message': {'text': 'CONFIRM', 'reply_to_message': {'message_id': 16}}})
        write.assert_not_called()
        reply = {'message': {'text': 'CONFIRM', 'reply_to_message': {'message_id': 17}}}
        mobile.handle(reply)
        mobile.handle(reply)
        write.assert_called_once_with({'action': 'confirm'})

    def test_menu_shows_only_actions_available_at_current_trade_stage(self):
        read = Mock(return_value=trade(9, escrow_locked=True))
        bot, write = Mock(return_value={'message_id': 17}), Mock()
        mobile = MobileTrade(123, 3, 'Temple', read, write, Mock(), bot)
        self.assertTrue(mobile.handle({'message': {'text': '/menu'}}))
        notice = bot.call_args.args[1]
        self.assertIn('Order amount: 25.00 USD', notice['text'])
        self.assertIn('confirm the amount and network', notice['text'])
        self.assertEqual([[button['text'] for button in row] for row in notice['reply_markup']['inline_keyboard']],
                         [['Confirm Sent']])
        self.assertTrue(mobile.handle({'message': {'text': 'Confirm Sent'}}))
        self.assertIn('reply CONFIRM', bot.call_args.args[1]['text'])
        read.return_value = trade(8, maker_locked=True, taker_locked=True, invoice_amount=12_000)
        mobile.handle({'message': {'text': '/menu'}})
        self.assertEqual(bot.call_args.args[1]['reply_markup']['inline_keyboard'][0][0]['text'],
                         '⚡ Set up Lightning payout')
        for row in (trade(7), trade(8, maker_locked=True, taker_locked=False, invoice_amount=12_000), trade(10)):
            read.return_value = row
            mobile.handle({'message': {'text': '/menu'}})
            self.assertNotIn('reply_markup', bot.call_args.args[1])
        write.assert_not_called()

    def test_telegram_is_checked_during_order_wait(self):
        from unittest.mock import patch
        import robosats_monitor as monitor

        now = [0]
        poll = Mock()
        with patch.object(monitor.time, 'monotonic', side_effect=lambda: now[0]), \
             patch.object(monitor.time, 'sleep', side_effect=lambda delay: now.__setitem__(0, now[0] + delay)):
            monitor.wait_for_next_check(10, poll)
        self.assertEqual(poll.call_count, 3)
        self.assertEqual(now[0], 10)

    def test_main_menu_and_old_preview_button_show_only_home_controls(self):
        book, order, active, take, bot = Mock(), Mock(), Mock(), Mock(), Mock()
        browser = MobileOffers(123, {'temple': 'Temple'}, book, bot, order, active, take)
        browser.handle({'message': {'text': '/menu', 'from': {'id': 123},
                                    'chat': {'id': 123, 'type': 'private'}}})
        self.assertIn('Browse offers', str(bot.call_args.args))
        self.assertNotIn('Preview trade keyboard', str(bot.call_args.args))
        browser.handle(callback('preview:keyboard'))
        self.assertIn('Browse offers', str(bot.call_args.args))
        self.assertNotIn('Confirm Sent', str(bot.call_args.args))
        for request in (book, order, active, take):
            request.assert_not_called()

