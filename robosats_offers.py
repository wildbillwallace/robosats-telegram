"""Browse public BTC sell offers from a private Telegram chat."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import time

from robosats_bridge import BridgeError, telegram_bot_id
from robosats_platform import keep_awake, lock_file


BUY, SELL = 0, 1  # Direction of the maker's offer.
PAGE = 8
BRIDGE_MENU_TITLE = '🤖 RoboSats Bridge Menu'
BROWSE_OFFERS_LABEL = '🔎 Browse offers'
OFFER_FILTERS_LABEL = '🎛️ Offer filters'
CURRENCIES = {
    code: int(number) for number, code in
    json.loads(Path(__file__).with_name('currencies.json').read_text()).items()
    if code not in {'BTC', 'XAU'}
}
CURRENCY_CODES = {number: code for code, number in CURRENCIES.items()}


def filters(cfg):
    return cfg.get('offer_currency', 'ANY'), cfg.get('offer_method', '')


def filter_label(cfg, names):
    currency, method = filters(cfg)
    return ' · '.join((currency if currency != 'ANY' else 'all currencies',
                      method or 'any payment method',
                      names.get(cfg.get('offer_coordinator'), 'all coordinators')))


def currency_code(row):
    return CURRENCY_CODES.get(row.get('currency'), 'currency unknown')


def matches_filters(row, cfg, maker_side=SELL):
    currency, method = filters(cfg)
    methods = row.get('payment_method')
    if (row.get('currency') not in CURRENCY_CODES
            or (currency != 'ANY' and row.get('currency') != CURRENCIES[currency]) or row.get('type') != maker_side
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


def book(cfg, get, coordinator, maker_side=SELL):
    response = get({**cfg, 'coordinator': coordinator, 'auth': None}, '/api/book/',
                   {'currency': CURRENCIES.get(filters(cfg)[0], 0), 'type': maker_side})
    data = response.json()
    if response.status_code == 404 and isinstance(data, dict) and 'not_found' in data:
        return []
    if response.status_code != 200 or not isinstance(data, list):
        raise ValueError('Could not read this coordinator’s public book.')
    return [row for row in data if isinstance(row, dict) and type(row.get('id')) is int and row['id'] > 0
            and matches_filters(row, cfg, maker_side)]


def unexpired(row):
    try:
        date = datetime.fromisoformat(row['expires_at'].replace('Z', '+00:00'))
        return date.tzinfo is not None and date > datetime.now(timezone.utc)
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


def collect_books(aliases, get_book):
    rows, unavailable = [], []
    with ThreadPoolExecutor(max_workers=6) as pool:
        books = {alias: pool.submit(get_book, alias) for alias in aliases}
        for alias, result in books.items():
            try:
                rows.extend((alias, row) for row in result.result())
            except (ValueError, BridgeError):
                unavailable.append(alias)
    return rows, unavailable


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


def bond_text(row, selected_amount=None):
    percent = decimal(row.get('bond_size'))
    if percent is None or not 0 < percent <= 100:
        return 'unavailable'
    digits = format(percent, 'f')
    label = (digits.rstrip('0').rstrip('.') if '.' in digits else digits) + '%'
    if selected_amount is None:
        return label
    if row.get('is_explicit') is True:
        trade_sats = decimal(row.get('satoshis'))
    else:
        reference_amount = decimal(row.get('max_amount' if row.get('has_range') else 'amount'))
        quote = decimal(row.get('satoshis_now'))
        price = decimal(row.get('price'))
        if quote is not None and quote > 0 and reference_amount is not None and reference_amount > 0:
            trade_sats = (selected_amount / reference_amount) * quote
        elif price is not None and price > 0:
            trade_sats = (selected_amount / price) * 100_000_000
        else:
            trade_sats = None
    if trade_sats is None or trade_sats <= 0:
        return label
    estimate = int(int(trade_sats) * percent / 100)
    return f'{label} (~{estimate:,} sats)'


def offer_text(row, name, selected_amount=None):
    method = ' '.join(str(row.get('payment_method') or 'Unspecified').split())[:200]
    expires = row.get('expires_at')
    try:
        expires = datetime.fromisoformat(str(expires).replace('Z', '+00:00')).astimezone(timezone.utc).strftime('%b %d %H:%M UTC')
    except ValueError:
        expires = 'Unavailable'
    direction = 'Sell' if row.get('type') == BUY else 'Buy'
    return (f'{direction} BTC · {name} #{row["id"]}\n'
            f'Amount: {amount(row)}\nPremium: {premium(row)}\nTaker bond: {bond_text(row, selected_amount)}\n'
            f'Payment: {method}\n'
            f'Offer expires: {expires}')


class OfferBrowser:
    def __init__(self, chat, names, get_book, telegram):
        self.chat, self.names, self.get_book, self.telegram = chat, names, get_book, telegram
        self.filter_label = ''
        self.cfg = {}

    def send(self, text, buttons):
        self.telegram('sendMessage', {'chat_id': self.chat, 'text': text,
                      'reply_markup': {'inline_keyboard': buttons}})

    def list_offers(self, page):
        selected = self.cfg.get('offer_coordinator')
        aliases = [selected] if selected in self.names else list(self.names)
        rows, unavailable = collect_books(aliases, self.get_book)
        def sort_key(item):
            value = decimal(item[1].get('premium'))
            return (value is None, value if value is not None else Decimal(0), item[0], item[1]['id'])
        rows.sort(key=sort_key)
        last = max(0, (len(rows) - 1) // PAGE)
        page = min(page, last)
        buttons = [[{'text': f'{amount(row)} · {premium(row)} · Bond {bond_text(row)} · {self.names[alias]} #{row["id"]}',
                     'callback_data': f'offer:{alias}:{row["id"]}'}]
                   for alias, row in rows[page * PAGE:(page + 1) * PAGE]]
        nav = [{'text': '🔄 Refresh', 'callback_data': f'offers:{page}'}]
        if page:
            nav.insert(0, {'text': '‹ Back', 'callback_data': f'offers:{page - 1}'})
        if page < last:
            nav.append({'text': 'Next ›', 'callback_data': f'offers:{page + 1}'})
        text = (f'Buy BTC · {len(rows)} offers · page {page + 1}/{last + 1}'
                if rows else 'No matching BTC sell offers are available right now.')
        if self.filter_label:
            text += '\n' + self.filter_label
        if unavailable:
            text += '\nCould not reach: ' + ', '.join(self.names[alias] for alias in unavailable)
        controls = [[{'text': OFFER_FILTERS_LABEL, 'callback_data': 'filters'}]] if self.cfg else []
        self.send(text, buttons + [nav] + controls)

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
        self.send(description, [[{'text': BROWSE_OFFERS_LABEL, 'callback_data': 'offers:0'}]])


def run_offer_browser(cfg, directory, coordinators, get, tor_port, telegram, make_browser=OfferBrowser):
    chat = int(cfg['chat'])
    bot_id = telegram_bot_id(cfg)
    if chat <= 0:
        raise BridgeError('Offers require a configured private Telegram bot chat.')
    try:
        lock = lock_file(Path(directory) / f'bridge-{bot_id}.lock')
    except BlockingIOError:
        raise BridgeError('Stop the other Telegram chat monitor before browsing offers.') from None
    with lock:
        cfg['port'] = tor_port(cfg['port'])
        hook = telegram(cfg, 'getWebhookInfo', {})
        if not isinstance(hook, dict) or hook.get('url'):
            raise BridgeError('Telegram offer browsing requires a bot available for polling.')
        menu_enabled = False
        try:
            telegram(cfg, 'setMyCommands', {
                'scope': {'type': 'chat', 'chat_id': chat},
                'commands': [{'command': 'menu', 'description': 'Show bridge controls'}],
            })
            telegram(cfg, 'setChatMenuButton', {'chat_id': chat, 'menu_button': {'type': 'commands'}})
            menu_enabled = True
        except BridgeError:
            print('Could not set Telegram’s Menu button. You can still send /menu in your bot chat.', flush=True)
        browser = make_browser(chat, {alias: pair[0] for alias, pair in coordinators.items()},
                               lambda alias: book(cfg, get, alias), lambda method, params: telegram(cfg, method, params))
        browser.cfg = cfg
        browser.filter_label = filter_label(cfg, browser.names)
        with keep_awake():
            buttons = browser.navigation() if hasattr(browser, 'navigation') else [[
                {'text': BROWSE_OFFERS_LABEL, 'callback_data': 'offers:0'}]]
            status = f'🤖 RoboSats Bridge Ready · {browser.filter_label}'
            if hasattr(browser, 'chat_enabled') and not browser.chat_enabled:
                status += '\nUnlock your Garage Key on the computer for robot selection, trade chat, and payout.'
            if menu_enabled:
                telegram(cfg, 'sendMessage', {'chat_id': chat,
                                              'text': status + '\nUse Menu → Show bridge controls to reopen the buttons.',
                                              'reply_markup': {'remove_keyboard': True}})
                browser.send(BRIDGE_MENU_TITLE, buttons)
            else:
                browser.send(status, buttons)
            print('Bridge ready. Continue in your private Telegram bot chat. Ctrl+C stops.', flush=True)
            offset = None
            executor = ThreadPoolExecutor(max_workers=1)
            try:
                while True:
                    try:
                        cfg['port'] = tor_port(cfg['port'])
                        if hasattr(browser, 'poll_alerts'):
                            browser.poll_alerts(executor)
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
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
