from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import TestCase
from unittest.mock import Mock

from robosats_mobile import MobileOffers, MobileTrade


def callback(data, sender=123):
    return {'callback_query': {'id': 'fixture', 'data': data, 'from': {'id': sender},
                              'message': {'chat': {'id': 123, 'type': 'private'}}}}


def listing():
    return dict(id=3, currency=1, type=1, amount='25.00', premium='2', bond_size='3',
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=4)).isoformat())


def trade(status, **extra):
    return dict(listing(), is_buyer=True, is_taker=True, status=status, **extra)


class MobileTests(TestCase):
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
        browser.handle(callback('handoff:temple:3'))
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

    def test_keyboard_buttons_send_text_controls_without_submitting_payment(self):
        read = Mock(return_value=trade(9, escrow_locked=True))
        bot, write = Mock(return_value={'message_id': 17}), Mock()
        mobile = MobileTrade(123, 3, 'Temple', read, write, Mock(), bot)
        mobile.show_controls()
        keyboard = bot.call_args.args[1]['reply_markup']['keyboard']
        self.assertEqual(keyboard[1][0]['text'], 'Confirm Sent')
        self.assertTrue(mobile.handle({'message': {'text': 'Trade status'}}))
        self.assertTrue(mobile.handle({'message': {'text': 'Confirm Sent'}}))
        self.assertIn('reply CONFIRM', bot.call_args.args[1]['text'])
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

    def test_preview_uses_trade_keyboard_with_no_coordinator_actions(self):
        book, order, active, take, bot = Mock(), Mock(), Mock(), Mock(), Mock()
        browser = MobileOffers(123, {'temple': 'Temple'}, book, bot, order, active, take)
        browser.handle(callback('preview:keyboard'))
        keyboard = bot.call_args.args[1]['reply_markup']['keyboard']
        self.assertEqual(keyboard[1][0]['text'], 'Confirm Sent')
        browser.handle({'message': {'text': 'Confirm Sent', 'from': {'id': 123},
                                    'chat': {'id': 123, 'type': 'private'}}})
        self.assertIn('Preview only', bot.call_args.args[1]['text'])
        for request in (book, order, active, take):
            request.assert_not_called()

