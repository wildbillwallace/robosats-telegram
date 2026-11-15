"""Telegram take confirmations and handoff to an existing buyer order."""
from datetime import datetime, timezone
import re
import secrets
import time

from robosats_bridge import BridgeError
from robosats_offers import OfferBrowser, SELL, currency_code, decimal, offer_text

RESUMABLE = {6, 7, 8, 9, 10, 11, 13, 15, 16}


TRADE_CONTROLS = {
    'Trade status': 'Shows the current order and next step.',
    'Lightning payout': 'Opens invoice setup and lets you choose the routing budget.',
    'Confirm Sent': 'Opens a second confirmation after you have paid the seller.',
}


def trade_keyboard():
    return {
        'keyboard': [[{'text': 'Trade status'}, {'text': 'Lightning payout'}],
                     [{'text': 'Confirm Sent'}]],
        'resize_keyboard': True,
        'is_persistent': True,
    }


def terms(row):
    fields = ('id', 'currency', 'type', 'amount', 'has_range', 'min_amount', 'max_amount',
              'payment_method', 'bond_size', 'expires_at', 'is_explicit')
    return tuple(row.get(field) for field in fields) + (
        row.get('satoshis') if row.get('is_explicit') else decimal(row.get('premium')),
    )


def unexpired(row):
    try:
        date = datetime.fromisoformat(row['expires_at'].replace('Z', '+00:00'))
        return date.tzinfo is not None and date > datetime.now(timezone.utc)
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


def owns_trade(row, order):
    return (row.get('id') == order and row.get('is_taker') is True
            and (row.get('is_buyer') is True or (row.get('status') == 3 and row.get('type') == SELL)))


class MobileOffers(OfferBrowser):
    def __init__(self, chat, names, get_book, telegram, order, active, take, chat_enabled=False):
        super().__init__(chat, names, get_book, telegram)
        self.order, self.active, self.take = order, active, take
        self.chat_enabled = chat_enabled
        self.review = self.confirmation = self.last_take = self.handoff = None

    def current_offer(self, alias, order_id):
        return next((row for row in self.get_book(alias)
                     if row['id'] == order_id and unexpired(row)), None)

    def navigation(self):
        buttons = [{'text': 'Browse offers', 'callback_data': 'offers:0'},
                   {'text': 'Resume desktop order', 'callback_data': 'resume'},
                   {'text': 'Preview trade keyboard', 'callback_data': 'preview:keyboard'}]
        if self.last_take:
            alias, order_id = self.last_take
            buttons.append({'text': 'Check last take', 'callback_data': f'active:{alias}:{order_id}'})
        return [[button] for button in buttons]

    def review_offer(self, alias, order_id):
        self.review = self.confirmation = None
        row = self.current_offer(alias, order_id)
        if not row:
            self.send('This offer is no longer available.', self.navigation())
            return
        if row.get('has_range'):
            result = self.telegram('sendMessage', {'chat_id': self.chat,
                'text': offer_text(row, self.names[alias]) + '\n\nReply to this message with your amount, e.g. 50.00.',
                'reply_markup': {'force_reply': True}})
            self.review = (alias, row, result['message_id'], time.monotonic() + 300)
        else:
            self.confirm_offer(alias, row, decimal(row.get('amount')))

    def confirm_offer(self, alias, row, amount):
        if amount is None or not 0 < amount < 10**10 or amount != amount.quantize(decimal('0.01')):
            self.send('Enter a positive amount with up to two decimal places.', self.navigation())
            return
        if row.get('has_range'):
            lo, hi = decimal(row.get('min_amount')), decimal(row.get('max_amount'))
            if lo is None or hi is None or not lo <= amount <= hi:
                self.send('That amount is outside the offer range. Choose the offer again.', self.navigation())
                return
        bond = decimal(row.get('bond_size'))
        if bond is None or bond <= 0:
            self.send('The coordinator did not show a valid bond percentage.', self.navigation())
            return
        nonce = secrets.token_hex(12)
        self.confirmation = (nonce, alias, row, amount, time.monotonic() + 120)
        description = offer_text(row, self.names[alias])
        if row.get('is_explicit'):
            description += f'\nFixed offer: {row.get("satoshis")} sats'
        self.send(f'{description}\n\nYou selected {amount:,.2f} {currency_code(row)}. Bond: {bond}% of trade sats. '
                  'RoboSats returns the exact bond invoice after you confirm.',
                  [[{'text': f'Confirm take · {amount:,.2f} {currency_code(row)}', 'callback_data': f'take:{nonce}'}]] + self.navigation())

    def show_order(self, alias, order_id, row):
        if not owns_trade(row, order_id):
            self.send('The saved robot is not the buyer taking this order.', self.navigation())
            return
        status = row.get('status')
        invoice, sats = row.get('bond_invoice'), row.get('bond_satoshis')
        if (status == 3 and isinstance(invoice, str) and re.fullmatch(r'lnbc[0-9a-z]{20,2000}', invoice.lower())
                and type(sats) is int and sats > 0 and unexpired(row)):
            self.send(f'{self.names[alias]} #{order_id} · {sats:,}-sat bond\n'
                      'Copy the Lightning invoice below into your wallet to lock your bond. Then tap Continue order.',
                      [[{'text': 'Continue order', 'callback_data': f'active:{alias}:{order_id}'}]])
            self.telegram('sendMessage', {'chat_id': self.chat, 'text': invoice})
        elif status in RESUMABLE:
            label = 'Continue on phone' if self.chat_enabled else 'Start status alerts'
            self.send(f'{self.names[alias]} #{order_id} is ready to resume.',
                      [[{'text': label, 'callback_data': f'handoff:{alias}:{order_id}'}]])
        else:
            self.send('There is no payable bond or resumable buyer trade for that order.', self.navigation())

    def handle(self, update):
        callback = update.get('callback_query')
        message = (callback or update).get('message', {})
        sender = (callback or message).get('from', {})
        if (sender.get('id') != self.chat or message.get('chat', {}).get('id') != self.chat
                or message.get('chat', {}).get('type') != 'private'):
            return
        if not callback:
            text = message.get('text')
            if isinstance(text, str) and text in TRADE_CONTROLS:
                self.send(f'Preview only. {text}: {TRADE_CONTROLS[text]}', self.navigation())
                return
            if self.review and message.get('reply_to_message', {}).get('message_id') == self.review[2]:
                alias, row, _, deadline = self.review
                self.review = None
                if deadline > time.monotonic() and isinstance(text, str) and re.fullmatch(r'[0-9]{1,10}(?:\.[0-9]{1,2})?', text.strip()):
                    self.confirm_offer(alias, row, decimal(text.strip()))
                else:
                    self.send('Open the offer again and enter the amount.', self.navigation())
                return
            if text == '/resume':
                self.resume()
                return
            manual = re.fullmatch(r'/resume (temple|lake) ([0-9]{1,18})', text or '')
            if manual and manual[1] in self.names:
                alias, order_id = manual[1], int(manual[2])
                try:
                    self.show_order(alias, order_id, self.order(alias, order_id))
                except BridgeError as exc:
                    self.send(str(exc), self.navigation())
                return
            return super().handle(update)
        data = callback.get('data', '')
        if data.startswith('offers:'):
            self.review = self.confirmation = None
            return super().handle(update)
        self.telegram('answerCallbackQuery', {'callback_query_id': callback['id']})
        if data == 'preview:keyboard':
            self.telegram('sendMessage', {
                'chat_id': self.chat,
                'text': 'Keyboard preview. Try the buttons beside the typing box. '
                        'No order is connected and these buttons only explain what they do.',
                'reply_markup': trade_keyboard(),
            })
            return
        if data == 'resume':
            self.resume()
            return
        if data.startswith('take:'):
            self.submit_take(data[5:])
            return
        match = re.fullmatch(r'(offer|active|handoff):([a-z]+):([0-9]{1,18})', data)
        if not match or match[2] not in self.names:
            return
        action, alias, order_id = match[1], match[2], int(match[3])
        try:
            if action == 'offer':
                self.review_offer(alias, order_id)
            else:
                row = self.order(alias, order_id)
                if action == 'handoff' and owns_trade(row, order_id) and row.get('status') in RESUMABLE:
                    self.handoff = (alias, order_id)
                else:
                    self.show_order(alias, order_id, row)
        except (ValueError, BridgeError) as exc:
            self.send(str(exc), self.navigation())

    def submit_take(self, nonce):
        saved = self.confirmation
        if not saved or saved[0] != nonce or saved[4] <= time.monotonic():
            self.send('That confirmation expired or was already used. Review the offer again.', self.navigation())
            return
        self.confirmation = None
        _, alias, reviewed, amount, _ = saved
        order_id = reviewed['id']
        try:
            fresh = self.current_offer(alias, order_id)
            if not fresh or terms(fresh) != terms(reviewed):
                self.send('The offer changed or expired. Review the current terms before taking it.', self.navigation())
                return
            self.last_take = (alias, order_id)
            row = self.take(alias, fresh, amount if fresh.get('has_range') else None)
        except (ValueError, BridgeError) as exc:
            self.send(str(exc), self.navigation())
            return
        self.show_order(alias, order_id, row)

    def resume(self):
        buttons = []
        for alias, name in self.names.items():
            try:
                order_id = self.active(alias)
            except BridgeError:
                continue
            if type(order_id) is int and order_id > 0:
                buttons.append([{'text': f'{name} #{order_id}', 'callback_data': f'active:{alias}:{order_id}'}])
        self.send('Choose an active order on your saved robot.' if buttons else
                  'No active order found on your saved robots. If you already opened one on desktop, use /resume temple ORDER_ID or /resume lake ORDER_ID.',
                  buttons + self.navigation())


class MobileTrade:
    def __init__(self, chat, order_id, name, read, write, sign, telegram):
        self.chat, self.order_id, self.name = chat, order_id, name
        self.read, self.write, self.sign, self.telegram = read, write, sign, telegram
        self.invoice_plan = self.confirmation = self.budget_prompt = None

    def send(self, text, buttons=()):
        params = {'chat_id': self.chat, 'text': text}
        if buttons:
            params['reply_markup'] = {'inline_keyboard': [[button] for button in buttons]}
        return self.telegram('sendMessage', params)

    def show_controls(self):
        return self.telegram('sendMessage', {
            'chat_id': self.chat,
            'text': f'Telegram is connected to {self.name} #{self.order_id}. '
                    'Use the buttons next to the typing box, or type normally to chat when it opens.',
            'reply_markup': trade_keyboard(),
        })

    def current(self):
        row = self.read()
        if not owns_trade(row, self.order_id):
            raise BridgeError('The saved robot is not the buyer taking this order.')
        return row

    def invoice_size(self, row, ppm):
        from robosats_invoice import payout_amount
        gross = row.get('invoice_amount')
        if (row.get('status') not in {6, 8} or row.get('is_swap') is True
                or row.get('maker_locked') is not True
                or row.get('taker_locked') is not True or type(gross) is not int or gross <= 0):
            raise BridgeError('RoboSats is not ready for a buyer payout invoice. Check /trade.')
        return payout_amount(gross, ppm)

    def plan_invoice(self, value, unit='ppm'):
        row = self.current()
        gross = self.invoice_size(row, 0)
        if unit == 'sats' and value >= gross:
            raise BridgeError('The routing budget must be smaller than the payout.')
        ppm = (value * 1_000_000 + gross // 2) // gross if unit == 'sats' else value
        if not 1 <= ppm <= 100_001:
            raise BridgeError('The routing budget must convert to between 1 and 100001 ppm (about 10% max).')
        count = self.invoice_size(row, ppm)
        self.budget_prompt = None
        self.confirmation = None
        self.invoice_plan = (ppm, count, time.monotonic() + 600)
        self.send(f'Create a {count:,}-sat Lightning payout invoice for #{self.order_id} '
                  f'(routing allowance: {gross - count:,} sats, {ppm:,} ppm), then paste it here.',
                  [{'text': 'Change budget in sats', 'callback_data': f'fees:sats:{self.order_id}'},
                   {'text': 'Change budget in ppm', 'callback_data': f'fees:ppm:{self.order_id}'}])

    def confirm(self, description, action):
        nonce = secrets.token_hex(12)
        self.confirmation = None
        msg = self.send(description + '\nTap Confirm or reply CONFIRM to this message.',
                        [{'text': 'Confirm', 'callback_data': f'trade:{nonce}'}])
        self.confirmation = (nonce, action, time.monotonic() + 120,
                             msg.get('message_id') if isinstance(msg, dict) else None)

    def prepare_sent(self):
        row = self.current()
        if row.get('status') != 9 or row.get('escrow_locked') is not True:
            raise BridgeError('RoboSats is not waiting for you to send fiat. Check /trade.')
        amount = decimal(row.get('amount'))
        if amount is None or amount <= 0:
            raise BridgeError('Could not verify the trade amount. Check RoboSats.')
        self.confirm(f'Confirm only after you have sent {amount:,.2f} {currency_code(row)} for #{self.order_id} in your payment app.',
                     {'action': 'confirm', 'amount': amount, 'currency': row.get('currency')})

    def submit_confirmation(self, nonce):
        saved = self.confirmation
        if not saved or nonce != saved[0] or saved[2] <= time.monotonic():
            raise BridgeError('That confirmation expired or was already used. Check /trade.')
        self.confirmation = None
        action = saved[1]
        row = self.current()
        if action['action'] == 'confirm':
            if (row.get('status') != 9 or row.get('escrow_locked') is not True
                    or decimal(row.get('amount')) != action['amount']
                    or row.get('currency') != action['currency']):
                raise BridgeError('Order state changed. Check /trade.')
            payload = {'action': 'confirm'}
        else:
            ppm = action['routing_budget_ppm']
            if self.invoice_size(row, ppm) != action['sats']:
                raise BridgeError('The payout amount changed. Start again with /invoice.')
            payload = {'action': 'update_invoice', 'routing_budget_ppm': ppm,
                       'invoice': self.sign(action['invoice'])}
        result = self.write(payload)
        expected = {10, 13, 14} if payload['action'] == 'confirm' else {7, 9}
        if not owns_trade(result, self.order_id) or result.get('status') not in expected:
            raise BridgeError('RoboSats did not report the expected state. Check /trade before retrying.')
        self.send('RoboSats accepted the update. Use /trade for the current status.')

    def status(self):
        row = self.current()
        status = row.get('status')
        text = f'{self.name} #{self.order_id} · {row.get("status_message", "Check current order state")}'
        buttons = []
        if status in {6, 8} and row.get('invoice_amount'):
            buttons.append({'text': 'Set up Lightning payout', 'callback_data': f'invoice:{self.order_id}'})
        if status == 9 and row.get('escrow_locked') is True:
            buttons.append({'text': 'Confirm Sent', 'callback_data': f'fiat:{self.order_id}'})
        self.send(text, buttons)

    def handle(self, update):
        """Return true if the update is a control or an invoice, rather than seller chat."""
        callback = update.get('callback_query')
        if callback:
            data = callback.get('data', '')
            if not data.startswith(('invoice:', 'fiat:', 'trade:', 'status:', 'fees:')):
                return True
            self.telegram('answerCallbackQuery', {'callback_query_id': callback['id']})
            try:
                if data == f'status:{self.order_id}':
                    self.status()
                elif data == f'invoice:{self.order_id}':
                    self.plan_invoice(1000)
                elif data in {f'fees:sats:{self.order_id}', f'fees:ppm:{self.order_id}'}:
                    unit = data.split(':')[1]
                    prompt = self.telegram('sendMessage', {'chat_id': self.chat,
                        'text': f'Reply with your routing budget in {unit}, using a whole number.',
                        'reply_markup': {'force_reply': True}})
                    self.invoice_plan = self.confirmation = None
                    self.budget_prompt = (prompt['message_id'], unit, time.monotonic() + 300)
                elif data == f'fiat:{self.order_id}':
                    self.prepare_sent()
                elif data.startswith('trade:'):
                    self.submit_confirmation(data[6:])
            except BridgeError as exc:
                self.send(str(exc))
            return True

        message = update.get('message', {})
        text = message.get('text')
        if not isinstance(text, str):
            return False
        text = text.strip()
        in_reply_to = message.get('reply_to_message', {})
        if text in {'/sent', 'Confirm Sent'} or text.upper() == 'CONFIRM':
            try:
                if text in {'/sent', 'Confirm Sent'}:
                    self.prepare_sent()
                elif (self.confirmation and self.confirmation[3] is not None
                      and in_reply_to.get('message_id') == self.confirmation[3]):
                    self.submit_confirmation(self.confirmation[0])
                else:
                    self.send('Use Telegram’s Reply gesture on the current confirmation message and type CONFIRM.')
            except BridgeError as exc:
                self.send(str(exc))
            return True
        budget = self.budget_prompt
        if budget and in_reply_to.get('message_id') == budget[0]:
            try:
                if budget[2] <= time.monotonic() or not re.fullmatch(r'[0-9]{1,10}', text):
                    raise BridgeError('Use a whole number while the fee prompt is open.')
                self.plan_invoice(int(text), budget[1])
            except BridgeError as exc:
                self.send(str(exc))
            return True
        # An old or unrelated fee reply should not become a seller message.
        if in_reply_to.get('text', '').startswith('Reply with your routing budget in '):
            self.send('That fee prompt is no longer active. Use /invoice to start again.')
            return True
        if text in {'/trade', 'Trade status'}:
            try:
                self.status()
            except BridgeError as exc:
                self.send(str(exc))
            return True
        if text in {'/invoice', 'Lightning payout'} or text.startswith('/invoice '):
            try:
                match = re.fullmatch(r'/invoice(?: ([0-9]{1,10})(?: (sats|ppm))?)?',
                                     '/invoice' if text == 'Lightning payout' else text)
                if not match:
                    raise BridgeError('Use /invoice, /invoice 5500 sats, or /invoice 4500 ppm.')
                self.plan_invoice(int(match[1]) if match[1] else 1000, match[2] or 'ppm')
            except BridgeError as exc:
                self.send(str(exc))
            return True
        if re.match(r'(?i)^(lightning:)?lnbc', text):
            from robosats_invoice import invoice_msats
            plan = self.invoice_plan
            try:
                if not plan or plan[2] <= time.monotonic():
                    raise BridgeError('Use /invoice to start a payout invoice. Nothing was sent to the trader.')
                ppm, sats, _ = plan
                invoice = re.sub(r'(?i)^lightning:', '', text)
                if len(invoice) > 3500 or invoice_msats(invoice) != sats * 1000:
                    raise BridgeError(f'Use a Lightning invoice for exactly {sats:,} sats.')
                self.confirm(f'Submit this {sats:,}-sat Lightning invoice to #{self.order_id}? Budget: {ppm:,} ppm.',
                             {'action': 'update_invoice', 'routing_budget_ppm': ppm, 'sats': sats, 'invoice': invoice})
                self.invoice_plan = None
            except (ValueError, BridgeError) as exc:
                self.send(str(exc))
            return True
        return False

