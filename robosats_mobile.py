"""Telegram take confirmations and handoff to an existing buyer order."""
import re
import secrets
import time

from robosats_bridge import BridgeError
from robosats_offers import (BRIDGE_MENU_TITLE, BROWSE_OFFERS_LABEL, BUY, CURRENCIES, OFFER_FILTERS_LABEL,
                             OfferBrowser, SELL, collect_books, currency_code, decimal, filter_label,
                             offer_text, unexpired)

RESUMABLE = {6, 7, 8, 9, 10, 11, 13, 15, 16}


def terms(row):
    fields = ('id', 'currency', 'type', 'amount', 'has_range', 'min_amount', 'max_amount',
              'payment_method', 'bond_size', 'expires_at', 'is_explicit')
    return tuple(row.get(field) for field in fields) + (
        row.get('satoshis') if row.get('is_explicit') else decimal(row.get('premium')),
    )


def owns_trade(row, order):
    return (row.get('id') == order and row.get('is_taker') is True
            and (row.get('is_buyer') is True or (row.get('status') == 3 and row.get('type') == SELL)))


def unpaid_take(row, order_id):
    return (owns_trade(row, order_id) and row.get('status') == 3 and row.get('is_maker') is False
            and row.get('taker_locked') is False and unexpired(row))


class MobileOffers(OfferBrowser):
    def __init__(self, chat, names, get_book, telegram, order, active, take, chat_enabled=False, *,
                 save_filter=None, list_robots=None, select_robot=None, has_robot=None, release=None,
                 alert_book=None, alert_urls=None):
        super().__init__(chat, names, get_book, telegram)
        self.order, self.active, self.take = order, active, take
        self.chat_enabled = chat_enabled
        self.save_filter = save_filter
        self.list_robots, self.select_robot = list_robots, select_robot
        self.has_robot = has_robot
        self.release = release
        self.alert_book = alert_book
        self.alert_urls = alert_urls or {}
        self.alert_prompt = None
        self.alert_scan = None
        self.alert_watch = None
        self.next_alert_scan = 0
        self.robot_choices = {}
        self.payment_prompt = None
        self.review = self.confirmation = self.last_take = self.handoff = None
        self.release_prompt = None

    def current_offer(self, alias, order_id):
        if self.cfg.get('offer_coordinator') not in (None, alias):
            return None
        return next((row for row in self.get_book(alias)
                     if row['id'] == order_id and unexpired(row)), None)

    def navigation(self):
        buttons = [{'text': BROWSE_OFFERS_LABEL, 'callback_data': 'offers:0'},
                   {'text': '↩️ Resume an order', 'callback_data': 'resume'}]
        if self.save_filter:
            buttons.insert(1, {'text': OFFER_FILTERS_LABEL, 'callback_data': 'filters'})
        if self.alert_book:
            buttons.insert(2, {'text': '🔔 Offer alerts', 'callback_data': 'alerts'})
        if self.last_take:
            alias, order_id = self.last_take
            buttons.append({'text': 'Check last take', 'callback_data': f'active:{alias}:{order_id}'})
        return [[button] for button in buttons]

    def show_robots(self, alias, start, offer_id=None):
        self.review = self.confirmation = None
        self.robot_choices.clear()
        robots, next_start = self.list_robots(alias, start)
        if offer_id is None:
            robots = [robot for robot in robots if type(robot[3]) is int and robot[3] > 0]
        buttons = []
        for nickname, auth, index, order in robots:
            choice = secrets.token_hex(8)
            self.robot_choices[choice] = (alias, nickname, auth, index, order, offer_id)
            label = f'{nickname} · order #{order}' if type(order) is int and order > 0 else nickname
            buttons.append([{'text': label, 'callback_data': f'robot:{choice}'}])
        offer_suffix = f':{offer_id}' if offer_id is not None else ''
        if next_start is not None:
            buttons.append([{'text': 'Find more robots', 'callback_data': f'robots:{alias}:{next_start}{offer_suffix}'}])
        if not robots:
            buttons.append([{'text': 'Search again', 'callback_data': f'robots:{alias}:{start}{offer_suffix}'}])
        if offer_id is None:
            heading = f'Find an active order · {self.names[alias]}'
            instructions = 'Choose the order you want to resume.' if robots else 'No active orders in this batch.'
        else:
            heading = f'Offer #{offer_id} · {self.names[alias]}'
            instructions = 'Choose a Garage robot for this offer.' if robots else (
                'No registered robots in this batch. Try Find more robots. '
                'For a fresh robot, open the offer in RoboSats with that robot, then search again.')
        self.send(f'{heading}\n{instructions}', buttons + self.navigation())

    def handle_robot_selection(self, data):
        if not self.chat_enabled or not self.list_robots or not self.select_robot:
            return False
        if data == 'resume:find':
            self.review = self.confirmation = None
            self.robot_choices.clear()
            self.send('Which coordinator has the order you want to resume?',
                      [[{'text': name, 'callback_data': f'robots:{alias}:0'}]
                       for alias, name in self.names.items()] + self.navigation())
        elif data == 'robots':
            self.resume()
        elif (lookup := re.fullmatch(r'robots:([a-z]+):([0-9]{1,10})(?::([0-9]{1,18}))?', data)) and lookup[1] in self.names:
            start = int(lookup[2])
            if start < 2**31:
                self.show_robots(lookup[1], start, int(lookup[3]) if lookup[3] else None)
        elif data.startswith('robot:'):
            robot = self.robot_choices.get(data[6:])
            if robot is None:
                self.send('This robot choice expired. Reopen the offer or tap Resume an order.', self.navigation())
            else:
                alias, nickname, auth, index, order, offer_id = robot
                self.select_robot(alias, auth, index)
                self.robot_choices.clear()
                self.review = self.confirmation = None
                buttons = []
                if type(order) is int and order > 0:
                    buttons.append([{'text': f'Open order #{order}', 'callback_data': f'active:{alias}:{order}'}])
                    verb = 'already has' if offer_id is not None else 'has'
                    text = f'{nickname} {verb} order #{order} at {self.names[alias]}.'
                elif offer_id is not None:
                    buttons.append([{'text': f'Review offer #{offer_id}', 'callback_data': f'offer:{alias}:{offer_id}'}])
                    text = f'Using {nickname} for offer #{offer_id}.'
                else:
                    text = 'No active order was found for this robot.'
                if offer_id is not None:
                    buttons.append([{'text': 'Choose another robot', 'callback_data': f'robots:{alias}:0:{offer_id}'}])
                self.send(text, buttons + self.navigation())
        else:
            return False
        return True

    def show_filters(self):
        currencies = [{'text': f'{flag} {code}', 'callback_data': f'currency:{code}'}
                      for code, flag in (('USD', '🇺🇸'), ('EUR', '🇪🇺'), ('GBP', '🇬🇧'), ('CAD', '🇨🇦'),
                                         ('MXN', '🇲🇽'), ('BRL', '🇧🇷'), ('AUD', '🇦🇺'))]
        coordinators = [[{'text': name, 'callback_data': f'coordinator:{alias}'}]
                        for alias, name in self.names.items()]
        self.send(f'Current filters · {filter_label(self.cfg, self.names)}\n'
                  'Once you’ve chosen your filters, tap Browse offers.\n'
                  'Send /currency for the full currency list.',
                  [[{'text': 'All currencies', 'callback_data': 'currency:ANY'}], currencies[:4], currencies[4:],
                   [{'text': 'Any payment method', 'callback_data': 'payment:any'},
                    {'text': 'Set payment method', 'callback_data': 'payment:custom'}],
                   [{'text': 'All coordinators', 'callback_data': 'coordinator:all'}]]
                  + coordinators + [[{'text': BROWSE_OFFERS_LABEL, 'callback_data': 'offers:0'}]])

    def change_filter(self, key, value):
        self.save_filter(key, value)
        self.cfg[key] = value
        self.payment_prompt = None
        self.review = self.confirmation = None
        self.filter_label = filter_label(self.cfg, self.names)
        self.show_filters()

    def filter_command(self, text):
        if not self.save_filter or not isinstance(text, str):
            return False
        command, _, value = text.strip().partition(' ')
        value = value.strip()
        if command == '/filters':
            self.show_filters()
        elif command == '/currency':
            code = value.upper()
            if code == 'ANY' or code in CURRENCIES:
                self.change_filter('offer_currency', code)
            else:
                self.send('Send /currency followed by a code. Available currencies:\nANY, '
                          + ', '.join(sorted(CURRENCIES)), self.navigation())
        elif command == '/payment':
            if not value or len(value) > 60:
                self.send('Send /payment followed by a method of up to 60 characters, or /payment any.',
                          self.navigation())
            else:
                self.change_filter('offer_method', '' if value.casefold() == 'any' else value)
        else:
            return False
        return True

    def show_alerts(self):
        settings = self.cfg.get('offer_alert', {})
        selling = settings.get('side') == 'sell'
        direction = 'Sell sats' if selling else 'Buy sats'
        limit_name = 'Minimum' if selling else 'Maximum'
        limit = settings.get('premium')
        enabled = settings.get('enabled', False)
        label = f'{limit_name} premium: {limit}%' if limit is not None else 'Any premium'
        self.send(f'Offer alerts · {"On" if enabled else "Off"}\n'
                  f'{direction} · {filter_label(self.cfg, self.names)} · {label}\n'
                  'Alerts use your current offer filters. Keep the bridge running with Tor connected.',
                  [[{'text': 'Buy sats', 'callback_data': 'alerts:buy'},
                    {'text': 'Sell sats', 'callback_data': 'alerts:sell'}],
                   [{'text': f'Set {limit_name.lower()} premium', 'callback_data': 'alerts:premium'},
                    {'text': 'Any premium', 'callback_data': 'alerts:any'}],
                   [{'text': '⏸️ Pause alerts' if enabled else '🔔 Turn on alerts',
                     'callback_data': 'alerts:pause' if enabled else 'alerts:enable'}],
                   [{'text': OFFER_FILTERS_LABEL, 'callback_data': 'filters'}]])

    def change_alert(self, **changes):
        settings = {**self.cfg.get('offer_alert', {}), **changes}
        self.save_filter('offer_alert', settings)
        self.cfg['offer_alert'] = settings
        self.alert_prompt = None
        self.show_alerts()

    def alert_action(self, data):
        if data in {'alerts:buy', 'alerts:sell'}:
            side = data.split(':')[1]
            if side != self.cfg.get('offer_alert', {}).get('side', 'buy'):
                self.change_alert(side=side, premium=None)
            else:
                self.show_alerts()
        elif data == 'alerts:premium':
            label = 'minimum' if self.cfg.get('offer_alert', {}).get('side') == 'sell' else 'maximum'
            prompt = self.telegram('sendMessage', {'chat_id': self.chat,
                'text': f'Reply with your {label} premium as a percentage, such as 2 or -0.5.',
                'reply_markup': {'force_reply': True}})
            self.alert_prompt = prompt['message_id']
        elif data == 'alerts:any':
            self.change_alert(premium=None)
        elif data in {'alerts:enable', 'alerts:pause'}:
            self.change_alert(enabled=data == 'alerts:enable')
        else:
            self.show_alerts()

    def poll_alerts(self, executor):
        settings = self.cfg.get('offer_alert', {})
        if self.alert_book is None or not settings.get('enabled'):
            self.alert_watch = None
            return
        watch = {key: self.cfg.get(key) for key in ('offer_coordinator', 'offer_currency', 'offer_method', 'port')
                 if key in self.cfg}
        side = BUY if settings.get('side') == 'sell' else SELL
        limit = decimal(settings.get('premium'))
        criteria = (watch, side, limit)
        now = time.monotonic()
        if self.alert_scan is not None:
            if not self.alert_scan.done():
                return
            scan, self.alert_scan = self.alert_scan, None
            rows, _ = scan.result()
            if criteria == self.alert_watch:
                self.deliver_alerts(rows, side, limit)
        if criteria != self.alert_watch or now >= self.next_alert_scan:
            selected = watch.get('offer_coordinator')
            aliases = [selected] if selected in self.names else self.names
            self.alert_watch = criteria
            self.next_alert_scan = now + 60
            self.alert_scan = executor.submit(collect_books, aliases,
                                              lambda alias: self.alert_book(watch, alias, side))

    def deliver_alerts(self, rows, side, limit):
        seen = {key: expiry for key, expiry in self.cfg.get('seen_offer_alerts', {}).items()
                if unexpired({'expires_at': expiry})}
        sent = 0
        for alias, row in rows:
            key = f'{alias}:{row["id"]}'
            if key in seen or not unexpired(row):
                continue
            price = decimal(row.get('premium'))
            if limit is not None and (price is None or (price > limit if side == SELL else price < limit)):
                continue
            self.send('🔔 Matching offer\n' + offer_text(row, self.names[alias]),
                      [[{'text': '🔎 View offer', 'callback_data': f'alert:{side}:{key}'}],
                       [{'text': '⏸️ Pause alerts', 'callback_data': 'alerts:pause'}]])
            seen[key] = row['expires_at']
            self.cfg['seen_offer_alerts'] = seen
            self.save_filter('seen_offer_alerts', seen)
            sent += 1
            if sent >= 5:
                break

    def show_alert_offer(self, side, alias, order_id):
        cfg = {**self.cfg, 'offer_currency': 'ANY', 'offer_method': ''}
        row = next((row for row in self.alert_book(cfg, alias, side)
                    if row['id'] == order_id and unexpired(row)), None)
        if row is None:
            self.send('That offer is no longer available.', self.navigation())
        elif side == BUY:
            details = offer_text(row, self.names[alias])
            if alias in self.alert_urls:
                url = f'{self.alert_urls[alias]}/order/{alias}/{order_id}'
                details += f'\nTo sell your sats, open this offer in RoboSats through Tor.\n{url}'
            else:
                details += f'\nFind offer #{order_id} at {self.names[alias]} in RoboSats to sell your sats.'
            self.telegram('sendMessage', {'chat_id': self.chat, 'text': details,
                                          'link_preview_options': {'is_disabled': True},
                                          'reply_markup': {'inline_keyboard': self.navigation()}})
        else:
            self.send(offer_text(row, self.names[alias]),
                      [[{'text': 'Review buy offer', 'callback_data': f'offer:{alias}:{order_id}'}]] + self.navigation())

    def review_offer(self, alias, order_id):
        self.review = self.confirmation = None
        row = self.current_offer(alias, order_id)
        if not row:
            self.send('This offer is no longer available.', self.navigation())
            return
        if self.chat_enabled and self.list_robots and self.has_robot and not self.has_robot(alias):
            self.show_robots(alias, 0, order_id)
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
        description = offer_text(row, self.names[alias], selected_amount=amount)
        if row.get('is_explicit'):
            description += f'\nFixed offer: {row.get("satoshis")} sats'
        buttons = [[{'text': f'Confirm take · {amount:,.2f} {currency_code(row)}', 'callback_data': f'take:{nonce}'}]]
        if self.chat_enabled and self.list_robots and self.select_robot:
            buttons.append([{'text': 'Choose another robot', 'callback_data': f'robots:{alias}:0:{row["id"]}'}])
        self.send(f'{description}\n\nYou selected {amount:,.2f} {currency_code(row)}. '
                  'RoboSats returns the exact bond invoice after you confirm.',
                  buttons + self.navigation())

    def show_order(self, alias, order_id, row):
        self.release_prompt = None
        if not owns_trade(row, order_id):
            self.send('The saved robot is not the buyer taking this order.', self.navigation())
            return
        status = row.get('status')
        invoice, sats = row.get('bond_invoice'), row.get('bond_satoshis')
        if (status == 3 and isinstance(invoice, str) and re.fullmatch(r'lnbc[0-9a-z]{20,2000}', invoice.lower())
                and type(sats) is int and sats > 0 and unexpired(row)):
            buttons = [[{'text': 'Continue order', 'callback_data': f'active:{alias}:{order_id}'}]]
            if self.release and unpaid_take(row, order_id):
                button = 'release:' + secrets.token_hex(12)
                self.release_prompt = (button, alias, order_id, invoice, time.monotonic() + 120)
                buttons.append([{'text': 'Release offer', 'callback_data': button}])
            self.send(f'⚡ {self.names[alias]} #{order_id} · {sats:,}-sat bond\n'
                      'Copy the Lightning invoice below into your wallet to lock your bond. Then tap Continue order.',
                      buttons)
            self.telegram('sendMessage', {'chat_id': self.chat, 'text': invoice})
        elif status in RESUMABLE:
            label = 'Continue on phone' if self.chat_enabled else 'Start status alerts'
            self.send(f'{self.names[alias]} #{order_id} is ready to resume.',
                      [[{'text': label, 'callback_data': f'handoff:{alias}:{order_id}'}]])
        else:
            self.send('There is no payable bond or resumable buyer trade for that order.', self.navigation())

    def handle_release(self, data):
        saved = self.release_prompt
        if not saved or data != saved[0] or time.monotonic() >= saved[4]:
            self.send('That release button expired. Check the order again.', self.navigation())
            return
        self.release_prompt = None
        _, alias, order_id, invoice, deadline = saved
        if data.startswith('release:'):
            button = 'release-confirm:' + secrets.token_hex(12)
            self.release_prompt = (button, alias, order_id, invoice, deadline)
            self.send(f'Release {self.names[alias]} offer #{order_id}? Confirm only if you haven’t tried to pay the '
                      'bond invoice. RoboSats may temporarily pause this robot from making or taking orders.',
                      [[{'text': 'Confirm release', 'callback_data': button}],
                       [{'text': 'Keep offer', 'callback_data': f'active:{alias}:{order_id}'}]])
            return
        try:
            current = self.order(alias, order_id)
            if not unpaid_take(current, order_id) or current.get('bond_invoice') != invoice:
                raise BridgeError('The bond or offer changed. Check the current order before continuing.')
            row = self.release(alias, order_id)
            if (row.get('id') != order_id or row.get('status') != 1
                    or row.get('is_taker') is not False):
                raise BridgeError('RoboSats did not confirm the release. Check the current order.')
        except BridgeError as exc:
            self.send(str(exc), self.navigation())
            return
        if self.last_take == (alias, order_id):
            self.last_take = None
        message = f'Released offer #{order_id}.'
        if row.get('penalty'):
            message += ' RoboSats reports a temporary cooldown for this robot.'
        self.send(message, self.navigation())

    def handle(self, update):
        callback = update.get('callback_query')
        message = (callback or update).get('message', {})
        sender = (callback or message).get('from', {})
        if (sender.get('id') != self.chat or message.get('chat', {}).get('id') != self.chat
                or message.get('chat', {}).get('type') != 'private'):
            return
        if not callback:
            text = message.get('text')
            if text == '/menu':
                self.send(BRIDGE_MENU_TITLE, self.navigation())
                return
            if self.filter_command(text):
                return
            if self.alert_prompt is not None and message.get('reply_to_message', {}).get('message_id') == self.alert_prompt:
                value = text.strip() if isinstance(text, str) else ''
                if re.fullmatch(r'[+-]?[0-9]{1,4}(?:\.[0-9]{1,4})?%?', value):
                    self.change_alert(premium=value.removesuffix('%'))
                else:
                    self.send('Use a number such as 2 or -0.5. Reply to the premium question to try again.', [])
                return
            if self.payment_prompt is not None and message.get('reply_to_message', {}).get('message_id') == self.payment_prompt:
                self.filter_command('/payment ' + text if isinstance(text, str) else '/payment')
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
            manual = re.fullmatch(r'/resume ([a-z]+) ([0-9]{1,18})', text or '')
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
        if self.alert_book:
            if data == 'alerts' or data.startswith('alerts:'):
                self.alert_action(data)
                return
            alert = re.fullmatch(r'alert:([01]):([a-z]+):([0-9]{1,18})', data)
            if alert and alert[2] in self.names:
                try:
                    self.show_alert_offer(int(alert[1]), alert[2], int(alert[3]))
                except (ValueError, BridgeError):
                    self.send('Could not refresh that offer. Try again in a moment.', self.navigation())
                return
        if data.startswith(('release:', 'release-confirm:')):
            if self.release:
                self.handle_release(data)
            return
        try:
            if self.handle_robot_selection(data):
                return
        except BridgeError as exc:
            self.send(str(exc), self.navigation())
            return
        if self.save_filter:
            if data == 'filters':
                self.show_filters()
                return
            if data.startswith('currency:') and self.filter_command('/currency ' + data[9:]):
                return
            if data == 'payment:any':
                self.change_filter('offer_method', '')
                return
            if data == 'payment:custom':
                self.review = self.confirmation = None
                prompt = self.telegram('sendMessage', {'chat_id': self.chat,
                    'text': 'Reply with a payment method as it appears on RoboSats, such as SEPA, Pix, or USDT.',
                    'reply_markup': {'force_reply': True}})
                self.payment_prompt = prompt['message_id']
                return
            if data.startswith('coordinator:'):
                alias = data[12:]
                if alias == 'all' or alias in self.names:
                    self.change_filter('offer_coordinator', None if alias == 'all' else alias)
                return
        if data == 'preview:keyboard':
            self.send(BRIDGE_MENU_TITLE, self.navigation())
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
        message = 'Choose an active order.' if buttons else 'No active orders found on your saved robots.'
        if self.chat_enabled and self.list_robots and self.select_robot:
            buttons.append([{'text': 'Find my order', 'callback_data': 'resume:find'}])
        self.send(message, buttons + self.navigation())


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
                    'Tap Menu to check your order. Once seller chat opens, type a message here to contact the seller.',
            'reply_markup': {'remove_keyboard': True},
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
        self.send(f'⚡ Create a {count:,}-sat Lightning payout invoice for #{self.order_id} '
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
        self.confirm(f'Confirm only after you’ve sent the agreed payment for #{self.order_id}. '
                     f'Order amount: {amount:,.2f} {currency_code(row)}.',
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

    def status_message(self, row):
        status = row.get('status')
        text = f'{self.name} #{self.order_id} · {row.get("status_message", "Check current order state")}'
        buttons = []
        if status == 7:
            text = (f'{self.name} #{self.order_id} · Waiting for the seller to lock your purchased sats in escrow.\n'
                    'Your payout invoice is accepted. No action needed from you yet.')
        if status in {6, 8}:
            try:
                self.invoice_size(row, 0)
            except BridgeError:
                pass
            else:
                text += '\nRoboSats is ready for your Lightning payout invoice.'
                buttons.append({'text': '⚡ Set up Lightning payout', 'callback_data': f'invoice:{self.order_id}'})
        if status == 9 and row.get('escrow_locked') is True:
            amount = decimal(row.get('amount'))
            if amount is not None and amount > 0:
                text = (f'{self.name} #{self.order_id} · Ready for payment\n'
                        f'Order amount: {amount:,.2f} {currency_code(row)}. Seller escrow is locked.\n'
                        'Agree on payment details with the seller in chat. If paying with crypto, confirm the amount and network. '
                        'Pay using the agreed method, then tap Confirm Sent.')
                buttons.append({'text': 'Confirm Sent', 'callback_data': f'fiat:{self.order_id}'})
        if status == 10:
            text = f'{self.name} #{self.order_id} · Payment marked sent. Waiting for the seller to release escrow.'
        if status == 14:
            text = f'✅ {self.name} #{self.order_id} · Trade completed successfully'
        message = {'text': text}
        if buttons:
            message['reply_markup'] = {'inline_keyboard': [[button] for button in buttons]}
        return message

    def status(self):
        self.telegram('sendMessage', {'chat_id': self.chat, **self.status_message(self.current())})

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
        if text in {'/menu', '/trade', 'Trade status'}:
            try:
                self.status()
            except BridgeError as exc:
                self.send(str(exc))
            return True
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

