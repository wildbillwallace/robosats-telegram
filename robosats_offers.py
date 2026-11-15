"""Browse public BTC sell offers from a private Telegram chat."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import time

from robosats_bridge import BridgeError
from robosats_platform import keep_awake, lock_file


SELL = 1  # The maker sells BTC. The user buys it.
PAGE = 8
CURRENCIES = {
    code: int(number) for number, code in
    json.loads(Path(__file__).with_name('currencies.json').read_text()).items()
    if code not in {'BTC', 'XAU'}
}
CURRENCY_CODES = {number: code for code, number in CURRENCIES.items()}


def filters(cfg):
    return cfg.get('offer_currency', 'USD'), cfg.get('offer_method', '')


def currency_code(row):
    return CURRENCY_CODES.get(row.get('currency'), 'currency unknown')


def matches_filters(row, cfg):
    currency, method = filters(cfg)
    methods = row.get('payment_method')
    if (row.get('currency') != CURRENCIES[currency] or row.get('type') != SELL
            or row.get('has_password') is True):
        return False
    if not method:
        return True
    return (isinstance(methods, str)
            and re.search(r'(?<!\w)' + re.escape(method) + r'(?!\w)', methods, re.IGNORECASE) is not None)


def decimal(value):
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def book(cfg, get, coordinator):
    response = get({**cfg, 'coordinator': coordinator, 'auth': None}, '/api/book/',
                   {'currency': CURRENCIES[filters(cfg)[0]], 'type': SELL})
    data = response.json()
    if response.status_code == 404 and isinstance(data, dict) and 'not_found' in data:
        return []
    if response.status_code != 200 or not isinstance(data, list):
        raise ValueError('Could not read this coordinator’s public book.')
    return [row for row in data if isinstance(row, dict) and type(row.get('id')) is int and row['id'] > 0
            and matches_filters(row, cfg)]


def amount(row):
    low = decimal(row.get('min_amount' if row.get('has_range') else 'amount'))
    high = decimal(row.get('max_amount')) if row.get('has_range') else None
    if low is None:
        return 'Amount unavailable'
    if high is not None and high != low:
        return f'{low:,.2f}–{high:,.2f} {currency_code(row)}'
    return f'{low:,.2f} {currency_code(row)}'


def premium(row):
    value = decimal(row.get('premium'))
    return f'{value:+.2f}%' if value is not None else 'premium unavailable'


def offer_text(row, name):
    method = ' '.join(str(row.get('payment_method') or 'Unspecified').split())[:200]
    expires = row.get('expires_at')
    try:
        expires = datetime.fromisoformat(str(expires).replace('Z', '+00:00')).astimezone(timezone.utc).strftime('%b %d %H:%M UTC')
    except ValueError:
        expires = 'Unavailable'
    return (f'Buy BTC · {name} #{row["id"]}\n'
            f'Amount: {amount(row)}\nPremium: {premium(row)}\nPayment: {method}\n'
            f'Offer expires: {expires}')


class OfferBrowser:
    def __init__(self, chat, names, get_book, telegram):
        self.chat, self.names, self.get_book, self.telegram = chat, names, get_book, telegram
        self.filter_label = ''

    def send(self, text, buttons):
        self.telegram('sendMessage', {'chat_id': self.chat, 'text': text,
                      'reply_markup': {'inline_keyboard': buttons}})

    def list_offers(self, page):
        rows = []
        unavailable = []
        for alias, name in self.names.items():
            try:
                rows += [(alias, row) for row in self.get_book(alias)]
            except (ValueError, BridgeError):
                unavailable.append(name)
        def sort_key(item):
            value = decimal(item[1].get('premium'))
            return (value is None, value if value is not None else Decimal(0), item[0], item[1]['id'])
        rows.sort(key=sort_key)
        last = max(0, (len(rows) - 1) // PAGE)
        page = min(page, last)
        buttons = [[{'text': f'{amount(row)} · {premium(row)} · {self.names[alias]} #{row["id"]}',
                     'callback_data': f'offer:{alias}:{row["id"]}'}]
                   for alias, row in rows[page * PAGE:(page + 1) * PAGE]]
        nav = [{'text': 'Refresh', 'callback_data': f'offers:{page}'}]
        if page:
            nav.insert(0, {'text': '‹ Back', 'callback_data': f'offers:{page - 1}'})
        if page < last:
            nav.append({'text': 'Next ›', 'callback_data': f'offers:{page + 1}'})
        text = (f'Buy BTC · {len(rows)} offers · page {page + 1}/{last + 1}'
                if rows else 'No matching BTC sell offers are available right now.')
        if self.filter_label:
            text += '\n' + self.filter_label
        if unavailable:
            text += '\nCould not reach: ' + ', '.join(unavailable)
        self.send(text, buttons + [nav])

    def handle(self, update):
        message = update.get('message', {})
        callback = update.get('callback_query')
        sender = message.get('from', {})
        if callback:
            sender = callback.get('from', {})
            message = callback.get('message', {})
        chat = message.get('chat', {})
        if (sender.get('id') != self.chat or chat.get('id') != self.chat or chat.get('type') != 'private'):
            return
        if not callback:
            if message.get('text') in {'/start', '/offers'}:
                self.list_offers(0)
            return
        self.telegram('answerCallbackQuery', {'callback_query_id': callback['id']})
        data = callback.get('data', '')
        match = re.fullmatch(r'offers:([0-9]{1,6})', data)
        if match:
            self.list_offers(int(match[1]))
            return
        match = re.fullmatch(r'offer:([a-z]+):([0-9]{1,18})', data)
        if not match or match[1] not in self.names:
            return
        alias, order = match[1], int(match[2])
        try:
            row = next((row for row in self.get_book(alias) if row['id'] == order), None)
            description = offer_text(row, self.names[alias]) if row else 'That offer is no longer in the public book.'
        except (ValueError, BridgeError):
            description = 'Could not refresh this offer. Try again.'
        self.send(description, [[{'text': 'Browse offers', 'callback_data': 'offers:0'}]])


def run_offer_browser(cfg, directory, coordinators, get, tor_port, telegram, make_browser=OfferBrowser):
    chat = int(cfg['chat'])
    bot_id = re.fullmatch(r'(\d+):[A-Za-z0-9_-]+', cfg['bot'])
    if chat <= 0 or not bot_id:
        raise BridgeError('Offers require a configured private Telegram bot chat.')
    try:
        lock = lock_file(Path(directory) / f'bridge-{bot_id[1]}.lock')
    except BlockingIOError:
        raise BridgeError('Stop the other Telegram chat monitor before browsing offers.') from None
    with lock:
        cfg['port'] = tor_port(cfg['port'])
        hook = telegram(cfg, 'getWebhookInfo', {})
        if not isinstance(hook, dict) or hook.get('url'):
            raise BridgeError('Telegram offer browsing requires a bot available for polling.')
        browser = make_browser(chat, {alias: pair[0] for alias, pair in coordinators.items()},
                               lambda alias: book(cfg, get, alias), lambda method, params: telegram(cfg, method, params))
        currency, method = filters(cfg)
        browser.filter_label = f'{currency} · {method or "any payment method"}'
        with keep_awake():
            buttons = browser.navigation() if hasattr(browser, 'navigation') else [[
                {'text': 'Browse offers', 'callback_data': 'offers:0'}]]
            browser.send(f'Buy BTC · {browser.filter_label}', buttons)
            print('Telegram offer browsing is running. Ctrl+C stops.', flush=True)
            offset = None
            while True:
                try:
                    cfg['port'] = tor_port(cfg['port'])
                    params = {'timeout': 10, 'allowed_updates': ['message', 'callback_query']}
                    if offset is not None:
                        params['offset'] = offset
                    for update in telegram(cfg, 'getUpdates', params):
                        offset = update['update_id'] + 1
                        browser.handle(update)
                        if getattr(browser, 'handoff', None):
                            return browser.handoff
                except BridgeError as exc:
                    print(str(exc), flush=True)
                    time.sleep(5)
