#!/usr/bin/env python3
"""RoboSats taker monitor with optional Telegram text chat."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import secrets
import shutil
from tempfile import NamedTemporaryFile
import sys
import subprocess
from urllib.parse import urlencode
import time
import requests
from robosats_auth import decode_garage_key, garage_authorization, garage_robot_token, robot_authorization
from robosats_bridge import BridgeError, ChatBridge, NostrChat, TelegramConnectionError, close_keys, open_keys
from robosats_platform import keep_awake, lock_file, protect_settings, settings_directory, unprotect_settings

ONION = 'http://ngdk7ocdzmz5kzsysa3om6du7ycj2evxp2f2olfkyq37htx3gllwp2yd.onion'
COORDINATORS = {
    # Mainnet onion addresses from RoboSats frontend/static/federation.json.
    'temple': ('Temple of Sats', ONION),
    'lake': ('The Big Lake', 'http://4t4jxmivv6uqej6xzx2jx3fxh75gtt65v3szjoqmc4ugdlhipzdat6yd.onion'),
    'bazaar': ('LibreBazaar', 'http://librebazovfmmkyi2jekraxsuso3mh622avuuzqpejixdl5dhuhb4tid.onion'),
    'freeport': ('FreePort', 'http://2enoseg66hme76khjjn2qvrhipnzwgwa44mewgrdphrxbhzcxd2vdiqd.onion'),
    'ammanaya': ('Ammanaya', 'http://ammannjgzybw4qm2odmci7xgolh5grzijidacjxose5tthm375dcopad.onion'),
    'gumpellite': ('Gumpellite', 'http://jvnfeiy3aizcpva6zekd3v6o5kpzduqeeqqihhtudhuqqa7e5jzm7kyd.onion'),
}

HOME = settings_directory()
LABELS = dict(enumerate([
    'Waiting for maker bond', 'Public', 'Paused', 'Waiting for taker bond',
    'Cancelled', 'Expired', 'Waiting for escrow and buyer invoice',
    'Waiting for seller escrow', 'Waiting for buyer invoice',
    'Ready for fiat — open RoboSats', 'Fiat marked sent', 'In dispute',
    'Collaboratively cancelled', 'Sending satoshis', 'RoboSats reports the trade completed successfully',
    'Lightning routing failed', 'Waiting for dispute resolution',
    'Maker lost dispute', 'Taker lost dispute']))
TERMINAL = {4, 5, 12, 14, 17, 18}
CHAT_STATUSES = {9, 10, 11, 16}
ROBOT_SEARCH_BATCH = 10

class MonitorError(Exception):
    pass

class RobotMismatch(MonitorError):
    pass

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                            prefix='.settings-', delete=False) as out:
        temp = Path(out.name)
    try:
        with temp.open('w', encoding='utf-8') as out:
            json.dump(value, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def save_config(path, value):
    save(path, protect_settings(value) if os.name == 'nt' else value)


def prompt_auth(config, order, remember_seed):
    while True:
        value = getpass.getpass('RoboSats Garage Key (robo1...) or Authorization header: ').strip()
        # Some terminal paste modes wrap clipboard input in control sequences.
        value = value.removeprefix('\x1b[200~').removesuffix('\x1b[201~').strip()
        if re.fullmatch(r'Token [!-~]+', value):
            return value
        value = ''.join(value.strip('\"\'`“”').split())
        try:
            seed = decode_garage_key(value)
            remember_seed(seed)
            break
        except ValueError as exc:
            print(f'{exc} Try pasting again, or press Ctrl+C to stop.', file=sys.stderr)
    return find_order_auth(seed, config, order, extend_search=True)


def pair_telegram(cfg, expected_chat=None, timeout=120):
    bot = bridge_telegram(cfg, 'getMe', {})
    if (not isinstance(bot, dict) or bot.get('id') != int(cfg['bot'].split(':')[0])
            or not isinstance(bot.get('username'), str)
            or not re.fullmatch(r'[A-Za-z0-9_]+', bot['username'])):
        raise MonitorError('Telegram could not verify the bot ID in that token.')
    hook = bridge_telegram(cfg, 'getWebhookInfo', {})
    if not isinstance(hook, dict) or hook.get('url'):
        raise MonitorError('Use a dedicated bot with no webhook.')
    code = secrets.token_hex(4)
    print(f'On Telegram, open https://t.me/{bot["username"]}, tap Start, and send this code: {code}', flush=True)
    deadline = time.monotonic() + timeout
    params = {'timeout': 8, 'allowed_updates': ['message']}
    while time.monotonic() < deadline:
        for update in bridge_telegram(cfg, 'getUpdates', params):
            params['offset'] = update['update_id'] + 1
            msg = update.get('message', {})
            chat = msg.get('chat', {})
            chat_id = chat.get('id')
            if (chat.get('type') == 'private' and type(chat_id) is int and chat_id > 0
                    and msg.get('from', {}).get('id') == chat_id
                    and (expected_chat is None or expected_chat == chat_id)
                    and msg.get('text', '').strip() == code):
                return chat_id
    raise MonitorError('Pairing timed out. Run setup again and send the new code from your own private chat.')


def read_garage_key(allow_empty=False):
    prompt = ('RoboSats Garage Key (robo1…) [Enter to browse and preview]: '
              if allow_empty else 'RoboSats Garage Key (robo1…): ')
    while True:
        value = getpass.getpass(prompt).strip()
        value = ''.join(value.removeprefix('\x1b[200~').removesuffix('\x1b[201~').split()).lower()
        if allow_empty and not value:
            return ''
        try:
            decode_garage_key(value)
        except ValueError as exc:
            if not allow_empty:
                raise MonitorError(str(exc)) from None
            print(f'{exc} Try again, or press Enter to skip.', file=sys.stderr)
        else:
            return value


def setup(path, *, ask_garage=True):
    if path.exists():
        raise MonitorError('Setup is already complete. Use Settings in the terminal menu.')
    print('In Telegram, open the verified @BotFather bot and send /newbot, or use a bot you already own.')
    bot = getpass.getpass('Telegram bot token (includes the bot ID): ').strip()
    if not re.fullmatch(r'\d+:[A-Za-z0-9_-]+', bot):
        raise MonitorError('Expected the full BotFather token including the colon.')
    chat = input('Your numeric private Telegram chat ID [Enter to discover it]: ').strip()
    if chat and not re.fullmatch(r'[1-9][0-9]{0,18}', chat):
        raise MonitorError('Enter a positive private chat ID or press Enter.')
    proxy = input('Local Tor SOCKS port [Enter for automatic detection]: ').strip() or '9050'
    if not proxy.isascii() or not proxy.isdecimal() or not 1 <= int(proxy) <= 65535:
        raise MonitorError('Invalid Tor port.')
    cfg = {'bot': bot, 'port': int(proxy)}
    runtime = {**cfg, 'port': tor_port(cfg['port'])}
    cfg['chat'] = pair_telegram(runtime, int(chat) if chat else None)
    print(f'Telegram chat ID verified: {cfg["chat"]}')
    if ask_garage and input('Save your Garage Key locally now? [y/N]: ').strip().lower() in {'y', 'yes'}:
        cfg['garage_key'] = read_garage_key()
    bridge_telegram(runtime, 'sendMessage', {'chat_id': cfg['chat'],
                    'text': 'Setup complete. This test did not access a RoboSats order.'})
    save_config(path, cfg)
    print(f'Settings saved locally in {path}.')


def socks_listens(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1) as conn:
            conn.sendall(b'\x05\x01\x00')
            with conn.makefile('rb') as reply:
                return reply.read(2) == b'\x05\x00'
    except OSError:
        return False


def brave_tor_ports():
    if os.name == 'nt':
        # Brave's Tor component has a versioned tor-...-brave-... process name.
        command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                   "$tor = @(Get-Process -Name 'tor-*-brave-*' -ErrorAction SilentlyContinue); "
                   "if ($tor.Count) { Get-NetTCPConnection -State Listen -LocalAddress 127.0.0.1 "
                   "-OwningProcess $tor.Id -ErrorAction SilentlyContinue | "
                   "Select-Object -ExpandProperty LocalPort }"]
    else:
        command = ['/usr/sbin/lsof', '-nP', '-a', '-c', 'tor', '-iTCP', '-sTCP:LISTEN', '-Fpcn']
    try:
        result = subprocess.run(command, capture_output=True, encoding='ascii', errors='replace', timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return
    if os.name == 'nt':
        for line in result.stdout.splitlines():
            if re.fullmatch(r'[0-9]{1,5}', line.strip()) and 1 <= int(line) <= 65535:
                yield int(line)
        return
    brave = False
    for line in result.stdout.splitlines():
        if line.startswith('c'):
            brave = re.fullmatch(r'ctor-.*-brave-.*', line.lower()) is not None
        if brave and (match := re.fullmatch(r'n127\.0\.0\.1:(\d+)', line)):
            yield int(match[1])


def tor_port(preferred):
    tried = set()
    for candidate_ports in ((preferred, 9050, 9150), brave_tor_ports()):
        for port in candidate_ports:
            if port not in tried and socks_listens(port):
                return port
            tried.add(port)
    raise MonitorError('Tor is unavailable. Open a Brave Tor window or Tor Browser, wait for it to '
                       'connect, and keep it open. For a custom Tor setup, check the SOCKS port in Settings.')


def session(port):
    s = requests.Session()
    s.trust_env = False
    s.proxies = {p: f'socks5h://127.0.0.1:{port}' for p in ('http', 'https')}
    return s

def snapshot(response, order, include_peer=False, include_trade=False):
    try:
        data = response.json()
    except ValueError:
        raise MonitorError('Coordinator returned non-JSON data.') from None
    if not isinstance(data, dict):
        raise MonitorError('Unexpected coordinator response.')
    if response.status_code == 400 and data.get('error_code') == 1043:
        return {'status': 4, 'escrow_locked': None}
    if response.status_code in {401, 403} or (response.status_code == 400 and data.get('error_code') == 7001):
        raise RobotMismatch('The saved RoboSats robot cannot access this order.')
    if response.status_code != 200:
        raise MonitorError(f'Order request failed (HTTP {response.status_code}); check Tor, order and identity.')
    if data.get('id') != order or data.get('is_taker') is not True or data.get('is_participant') is not True:
        raise RobotMismatch('Response does not confirm this identity is the taker for this order.')
    status = data.get('status')
    if type(status) is not int or status not in LABELS or type(data.get('escrow_locked')) is not bool:
        raise MonitorError('Unrecognized status/escrow schema; check the API before continuing.')
    state = {'status': status, 'escrow_locked': data['escrow_locked']}
    if include_trade and data.get('is_buyer') is True:
        state['trade_details'] = data
    if include_peer and status in CHAT_STATUSES:
        state['peer'] = data.get('maker_nick')
        keys = (data.get('taker_nostr_pubkey'), data.get('maker_nostr_pubkey'))
        if all(isinstance(key, str) and re.fullmatch(r'[0-9a-f]{64}', key) and int(key, 16) for key in keys):
            state['nostr_participants'] = keys
    return state

def coordinator_request(cfg, endpoint, params, chat_payload=None, *, order_payload=None):
    name, onion = COORDINATORS[cfg.get('coordinator', 'temple')]
    url = onion + endpoint + ('?' + urlencode(params) if params else '')
    # Feed the credential through stdin so it stays out of process arguments.
    header = ''
    if cfg.get('auth'):
        header = 'header = ' + json.dumps('Authorization: ' + cfg['auth']) + '\n'
    if sum(payload is not None for payload in (chat_payload, order_payload)) > 1:
        raise MonitorError('Unexpected POST destination.')
    if any(payload is not None for payload in (chat_payload, order_payload)):
        if chat_payload is not None and endpoint == '/api/chat/':
            payload = chat_payload
        elif (order_payload is not None and endpoint == '/api/order/' and cfg.get('auth')
              and type(params.get('order_id')) is int
              and (order_payload.get('action') in {'take', 'update_invoice', 'confirm'}
                   or order_payload == {'action': 'cancel', 'cancel_status': 1})):
            payload = order_payload
        else:
            raise MonitorError('Unexpected POST destination.')
        header += 'header = "Content-Type: application/json"\n'
        header += 'data = ' + json.dumps(json.dumps(payload)) + '\n'
    try:
        result = subprocess.run(
            [shutil.which('curl') or '/usr/bin/curl', '-q', '--config', '-', '--silent', '--show-error',
             '--socks5-hostname', f"127.0.0.1:{int(cfg['port'])}", '--noproxy', '',
             '--max-time', '45', '--write-out', '\n%{http_code}', url],
            input=header, capture_output=True, text=True, encoding='utf-8', timeout=50)
    except (OSError, subprocess.TimeoutExpired):
        raise MonitorError('Order connection through Tor timed out or could not start.') from None
    if result.returncode:
        if result.returncode == 28:
            raise MonitorError(f'{name} did not respond through Tor in time. Try again.')
        raise MonitorError(f'Order connection through Tor failed (curl {result.returncode}).')
    body, _, code = result.stdout.rpartition('\n')
    response = requests.Response()
    response.status_code = int(code)
    response._content = body.encode('utf-8')
    return response


def coordinator_get(cfg, endpoint, params):
    return coordinator_request(cfg, endpoint, params)


def lookup_robot(runtime, authorization):
    response = coordinator_get({**runtime, 'auth': authorization}, '/api/robot/', {})
    try:
        data = response.json()
    except ValueError:
        raise MonitorError('Coordinator returned an unreadable robot response.') from None
    if not isinstance(data, dict):
        raise MonitorError('Coordinator returned an unexpected robot response.')
    if response.status_code == 400 and data.get('error_code') == 7001:
        return None
    if response.status_code != 200:
        raise MonitorError(f'Robot lookup failed (HTTP {response.status_code}).')
    return data


def find_order_auth(seed, config, order, extend_search=False):
    runtime = {**config, 'port': tor_port(config['port'])}
    print(f'Looking for active order #{order} in your Garage…', flush=True)
    for index in range(2**31 if extend_search else ROBOT_SEARCH_BATCH):
        if index and index % ROBOT_SEARCH_BATCH == 0:
            if input('No match yet. Search for more robots? [y/N]: ').strip().lower() not in {'y', 'yes'}:
                break
        auth = garage_authorization(seed, index)
        data = lookup_robot(runtime, auth)
        if data is not None and data.get('active_order_id') == order:
            print(f'Found the robot for order #{order}.')
            return auth
    raise MonitorError('No active match found. Verify the order number, coordinator, and Garage Key.')


def fetch(cfg, order, include_peer=False, include_trade=False):
    response = coordinator_get(cfg, '/api/order/', {'order_id': order})
    return snapshot(response, order, include_peer, include_trade)


def poll_chat(cfg, order, peer, state, initial=False, bridge=None, forward=True):
    if not isinstance(peer, str) or not peer:
        raise MonitorError('Order data did not identify the other chat participant.')
    offset = state.get('chat_offset', 0)
    response = coordinator_get(cfg, '/api/chat/', {'order_id': order, 'offset': offset})
    if response.status_code != 200:
        raise MonitorError(f'Chat check failed (HTTP {response.status_code}).')
    try:
        data = response.json()
        messages = data.get('messages') if isinstance(data, dict) else None
        if not isinstance(messages, list):
            raise ValueError
        high = offset
        incoming = []
        for item in messages:
            index, nick = item['index'], item['nick']
            if type(index) is not int or not isinstance(nick, str):
                raise ValueError
            high = max(high, index)
            if index > offset and nick == peer:
                incoming.append(item)
    except (ValueError, KeyError, TypeError):
        raise MonitorError('Unrecognized chat response.') from None
    peer_key = data.get('peer_pubkey')
    if forward and bridge is not None and not (initial and offset == 0):
        bridge.forward(sorted(incoming, key=lambda item: item['index']), peer_key)
    state['chat_offset'] = high
    if forward and bridge is None and incoming and not (initial and offset == 0):
        name = COORDINATORS[cfg.get('coordinator', 'temple')][0]
        state['pending'].append(f'New RoboSats reply for {name} #{order}. Open RoboSats to read it.')
    return peer_key


def telegram(s, cfg, message):
    params = {**(message if isinstance(message, dict) else {'text': message}), 'chat_id': cfg['chat']}
    try:
        r = s.post('https://api.telegram.org/bot' + cfg['bot'] + '/sendMessage',
                   json=params,
                   timeout=(20, 45), allow_redirects=False)
        body = r.json()
        if r.status_code != 200 or not isinstance(body, dict) or body.get('ok') is not True:
            raise MonitorError('Telegram delivery failed; check bot access, chat ID or rate limits.')
    except (requests.RequestException, ValueError):
        raise MonitorError('Telegram connection failed; notification remains queued.') from None

def message(order, state, initial=False, name='RoboSats'):
    if state['status'] == 7:
        return (f'{name} #{order} · Waiting for the seller to lock your purchased sats in escrow.\n'
                'Your payout invoice is accepted. No action needed from you yet.')
    if state['status'] == 14:
        return f'{name} #{order} · Trade completed successfully ✅'
    prefix = 'Monitoring started' if initial else 'Order changed'
    text = f'{prefix}: {name} #{order}\n{LABELS[state["status"]]}'
    if state['escrow_locked']:
        text += '\nSeller escrow is locked. Open RoboSats to review the next step.'
    return text

def enqueue(state, current, order, name='RoboSats', *, notice=None):
    if current != state.get('observed'):
        state['pending'].append({'stage': current, 'notice': notice} if notice else
                                message(order, current, state.get('observed') is None, name))
        state['observed'] = current

def flush(state, path, sender):
    while state['pending']:
        sender(state['pending'][0])
        state['pending'].pop(0)
        save(path, state)

def poll_trade_updates(bridge, active, peer_key, participants):
    try:
        if bridge.poll_messages(active, peer_key, participants) is not False:
            bridge.announce_seller_chat(active, peer_key, participants)
    except BridgeError as exc:
        print(str(exc), flush=True)


def wait_for_next_check(delay, poll=None):
    if poll is None:
        time.sleep(delay)
        return
    deadline = time.monotonic() + delay
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 3:
            if remaining > 0:
                time.sleep(remaining)
            return
        time.sleep(3)
        poll()


def run(args, cfg, bridge=None):
    if args.command != 'run':
        cfg['port'] = tor_port(cfg['port'])
    if args.command == 'telegram-test':
        telegram(session(cfg['port']), cfg, 'RoboSats monitor test — Telegram delivery works. No order was accessed.')
        print('Test message delivered. Confirm it appears on your phone.')
        return
    name = COORDINATORS[args.coordinator][0]
    if args.command == 'check':
        current = fetch(cfg, args.order)
        print(message(args.order, current, True, name))
        print('Authenticated GET succeeded. No Telegram message sent.')
        return
    statepath = args.config.parent / f'{args.coordinator}-{args.order}.json'
    try:
        lock = lock_file(statepath.with_suffix('.lock'))
    except BlockingIOError:
        raise MonitorError('Another monitor is already running for this order.') from None
    with lock:
        state = json.loads(statepath.read_text()) if statepath.exists() else {'observed': None, 'pending': []}
        trade = bridge.trade if bridge is not None else None
        connecting = trade is not None

        def send_pending(item):
            if isinstance(item, dict):
                # A queued action can outlive the trade stage during an outage.
                if trade is None or item['stage'] != state['observed']:
                    return
                if failures:
                    raise MonitorError('Waiting for a fresh order status before sending trade actions.')
                item = item['notice']
            telegram(session(cfg['port']), cfg, item)

        failures = 0
        print(f'Monitoring {name} #{args.order} every {args.interval}s through Tor. Ctrl-C stops.')
        while True:
            try:
                cfg['port'] = tor_port(cfg['port'])
                current = fetch(cfg, args.order, include_peer=True, include_trade=trade is not None)
                peer = current.pop('peer', None)
                participants = current.pop('nostr_participants', None)
                trade_details = current.pop('trade_details', None)
                if state.pop('outage', False):
                    state['pending'].append(f'{name} #{args.order}: order monitoring connection recovered.')
                changed = current != state.get('observed')
                notice = (trade.status_message(trade_details, connected=connecting)
                          if trade_details is not None and (changed or connecting) else None)
                if connecting and notice is not None and not changed:
                    state['pending'].append({'stage': current, 'notice': notice})
                enqueue(state, current, args.order, name, notice=notice)
                if notice is not None:
                    connecting = False
                failures = 0
                peer_key = None
                if current['status'] in CHAT_STATUSES:
                    if 'chat_baseline' not in state:
                        state['chat_baseline'] = True
                    try:
                        peer_key = poll_chat(cfg, args.order, peer, state, initial=state['chat_baseline'],
                                             bridge=bridge, forward=not (bridge and bridge.nostr and participants))
                        state['chat_baseline'] = False
                        if state.pop('chat_error', None):
                            print('Coordinator chat checks recovered.', flush=True)
                    except (MonitorError, BridgeError) as exc:
                        print(str(exc), flush=True)
                        state['chat_error'] = state.get('chat_error', 0) + 1
                        if state['chat_error'] == 3:
                            state['pending'].append(f'{name} #{args.order}: private chat checks are failing. Open RoboSats to check for replies.')
                else:
                    # If we saw the order before chat opened, the first message is new.
                    state.setdefault('chat_baseline', False)
                if bridge is not None:
                    poll_trade_updates(bridge, current['status'] in {9, 10}, peer_key, participants)
                if current['status'] in CHAT_STATUSES:
                    if bridge and bridge.nostr and participants:
                        try:
                            bridge.poll_nostr(participants, state, lambda: save(statepath, state))
                            if state.pop('nostr_error', None):
                                print('Nostr chat checks recovered.', flush=True)
                        except BridgeError as exc:
                            print(str(exc), flush=True)
                            state['nostr_error'] = state.get('nostr_error', 0) + 1
                            if state['nostr_error'] == 3:
                                state['pending'].append(f'{name} #{args.order}: Nostr chat checks are failing. Check RoboSats for replies.')
            except MonitorError as exc:
                failures += 1
                print(str(exc), flush=True)
                if failures >= 3 and not state.get('outage'):
                    state['outage'] = True
                    state['pending'].append(f'{name} #{args.order}: order checks are failing. Open RoboSats and check manually.')
            save(statepath, state)
            try:
                flush(state, statepath, send_pending)
            except MonitorError as exc:
                print(str(exc), flush=True)
            if failures == 0 and state['observed']['status'] in TERMINAL and not state['pending']:
                print('Terminal order status delivered; monitor stopped.')
                return
            poll = None
            if bridge is not None and failures == 0 and current['status'] not in TERMINAL:
                poll = lambda: poll_trade_updates(bridge, current['status'] in {9, 10}, peer_key, participants)
            wait_for_next_check(min(300, args.interval * (2 ** min(failures, 3))), poll)


def saved_auth(config, coordinator):
    if coordinator == 'temple':
        return config.get('auth')
    return config.get('coordinator_auth', {}).get(coordinator)


def set_saved_auth(config, coordinator, auth):
    if coordinator == 'temple':
        config['auth'] = auth
    else:
        config.setdefault('coordinator_auth', {})[coordinator] = auth


def load_config(path):
    if not path.exists():
        raise MonitorError('First run only: use python robosats_monitor.py setup to save your Telegram and Tor settings.')
    if os.name != 'nt' and path.stat().st_mode & 0o077:
        raise MonitorError('Config permissions must be owner-only (chmod 600).')
    data = json.loads(path.read_text(encoding='utf-8'))
    return unprotect_settings(data) if os.name == 'nt' else data


def bridge_telegram(cfg, method, params):
    is_ack = method == 'answerCallbackQuery'
    try:
        r = session(cfg['port']).post('https://api.telegram.org/bot' + cfg['bot'] + '/' + method,
                                      json=params, timeout=(2, 2) if is_ack else (10, 20),
                                      allow_redirects=False)
        # Acknowledging the Telegram spinner is independent of handling the tap.
        if is_ack:
            return None
        data = r.json()
        if r.status_code == 409:
            raise BridgeError('Telegram reports a competing bot listener or webhook.')
        if r.status_code != 200 or not isinstance(data, dict) or data.get('ok') is not True:
            raise BridgeError(f'Telegram chat bridge request failed (HTTP {r.status_code}).')
        return data.get('result')
    except (requests.RequestException, ValueError):
        if is_ack:
            return None
        raise TelegramConnectionError('Telegram chat bridge connection failed.') from None


def bridge_chat_post(cfg, payload):
    try:
        r = coordinator_request(cfg, '/api/chat/', {}, chat_payload=payload)
    except MonitorError:
        raise BridgeError('Chat delivery is unconfirmed.') from None
    try:
        accepted = r.status_code == 200 and r.json() == {}
    except ValueError:
        accepted = False
    if not accepted:
        raise BridgeError('Chat post failed.')


def session_garage_seed(config_path, seed=None):
    if seed is not None:
        return seed
    key = load_config(config_path).get('garage_key')
    return decode_garage_key(key) if key else None


def choose_coordinator():
    aliases = list(COORDINATORS)
    print('\nSelect a RoboSats coordinator')
    for index, alias in enumerate(aliases, 1):
        print(f'{index}. {COORDINATORS[alias][0]}')
    print('Press Enter to go back.')
    choices = {str(index): alias for index, alias in enumerate(aliases, 1)}
    while True:
        choice = input(f'Enter a coordinator number (1–{len(aliases)}): ').strip()
        if not choice or choice in choices:
            return choices.get(choice)
        print('Enter a coordinator number from the list.')


def bind_robot(path, cfg):
    alias = choose_coordinator()
    if alias is None:
        return
    name = COORDINATORS[alias][0]
    seed = session_garage_seed(path) or decode_garage_key(read_garage_key())
    runtime = {**cfg, 'coordinator': alias, 'port': tor_port(cfg['port'])}
    robots = {}
    for start in range(0, 2**31, ROBOT_SEARCH_BATCH):
        print(f'Looking for robots registered with {name}…', flush=True)
        for nickname, auth, index, order in registered_robots(runtime, seed, start):
            robots[nickname.casefold()] = (nickname, auth, index, order)

        if not robots:
            print(f'No robots found yet. If this is your first time using {name}, open your robot there in RoboSats first.')
        for nickname, auth, _, order in robots.values():
            notes = []
            if auth == saved_auth(cfg, alias):
                notes.append('saved')
            if type(order) is int and order > 0:
                notes.append(f'active order #{order}')
            suffix = ' · ' + ' · '.join(notes) if notes else ''
            print(f'  {nickname}{suffix}')

        single = next(iter(robots)) if len(robots) == 1 else None
        print('Enter /more to search for more robots or /back to return.')
        while True:
            prompt = f'Press Enter to use {robots[single][0]}: ' if single else 'Robot nickname: '
            choice = input(prompt).strip().casefold() or single
            if choice == '/back':
                return
            if choice == '/more':
                break
            if choice in robots:
                nickname, auth, index, _ = robots[choice]
                set_saved_auth(cfg, alias, auth)
                cfg.setdefault('robot_slots', {})[alias] = index
                save_config(path, cfg)
                print(f'Selected {nickname} for {name}.')
                return
            print('Enter a nickname shown above, /more, or /back.')


def registered_robots(runtime, seed, start):
    for index in range(start, min(start + ROBOT_SEARCH_BATCH, 2**31)):
        auth = garage_authorization(seed, index)
        data = lookup_robot(runtime, auth)
        if data is None:
            continue
        nickname = data.get('nickname')
        if not isinstance(nickname, str) or not nickname or not nickname.isprintable():
            raise MonitorError('The coordinator did not return a readable robot nickname.')
        yield nickname, auth, index, data.get('active_order_id')


def settings(path, cfg):
    from robosats_offers import CURRENCIES, filter_label, filters

    while True:
        currency, method = filters(cfg)
        names = {alias: name for alias, (name, _) in COORDINATORS.items()}
        print('\nBridge settings')
        print(f'Offer filters: {filter_label(cfg, names)}')
        print(f'Tor SOCKS port: {cfg["port"]}')
        print('1. Offer filters (also available in Telegram)\n2. Select a robot for phone trading\n'
              '3. Save or remove Garage Key\n4. Tor SOCKS port\nPress Enter to go back.')
        choice = input('Enter a settings option (1–4): ').strip()
        if not choice:
            return
        if choice == '1':
            currency = input(f'Currency code [{currency}], or ? to list: ').strip().upper() or currency
            if currency == '?':
                print('ANY, ' + ', '.join(sorted(CURRENCIES)))
                continue
            if currency != 'ANY' and currency not in CURRENCIES:
                print('Unknown currency code.')
                continue
            method = input('Payment method text [Enter for any]: ').strip()
            if len(method) > 60:
                print('Use a payment method filter of 60 characters or fewer.')
                continue
            cfg['offer_currency'], cfg['offer_method'] = currency, method
        elif choice == '2':
            try:
                bind_robot(path, cfg)
            except (MonitorError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
            continue
        elif choice == '3':
            if input('Save or remove? [s/r]: ').strip().lower() == 'r':
                cfg.pop('garage_key', None)
            else:
                cfg['garage_key'] = read_garage_key()
        elif choice == '4':
            port = input('Tor SOCKS port: ').strip()
            if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
                print('Invalid port.')
                continue
            cfg['port'] = int(port)
        else:
            print('Choose an option from the menu.')
            continue
        save_config(path, cfg)


def robot_signing_token(cfg, seed=None, interactive_search=True):
    try:
        if seed is None:
            value = getpass.getpass('Garage Key to unlock this robot’s signing key: ')
            seed = decode_garage_key(''.join(value.strip().split()))
        slot = cfg.get('robot_slots', {}).get(cfg.get('coordinator'))
        if type(slot) is int and 0 <= slot < 2**31:
            token = garage_robot_token(seed, slot)
            if robot_authorization(token) == cfg['auth']:
                return token
        for index in range(2**31):
            if index and index % 100 == 0:
                if not interactive_search or input('No matching signing key found yet. Search for more robots? [y/N]: ').strip().lower() != 'y':
                    raise BridgeError('No matching robot key found.')
            token = garage_robot_token(seed, index)
            if robot_authorization(token) == cfg['auth']:
                return token
        else:
            raise BridgeError('No matching robot key found.')
    except (ValueError, ImportError, OSError):
        raise BridgeError('Could not unlock the saved robot’s signing key.') from None


def start_bridge(args, cfg, seed=None, interactive_search=True):
    token = robot_signing_token(cfg, seed, interactive_search)
    try:
        response = coordinator_get(cfg, '/api/robot/', {})
        robot = response.json()
        if response.status_code != 200 or not all(isinstance(robot.get(key), str) and robot[key]
                   for key in ('public_key', 'encrypted_private_key')):
            raise BridgeError('The coordinator did not return the robot’s chat keys.')
        temp, keys = open_keys(robot, token)
    except (MonitorError, ValueError, AttributeError, ImportError, OSError):
        raise BridgeError('Could not unlock the active robot’s chat keys.') from None
    try:
        _, onion = COORDINATORS[args.coordinator]
        relay = onion.replace('http://', 'ws://', 1) + '/relay/'
        secret = hashlib.sha256(hashlib.sha512(token.encode('utf-8')).digest()).hexdigest()
        nostr = NostrChat(cfg, secret, f'{args.coordinator}/{args.order}', relay)
        bridge = ChatBridge(cfg, args.order, COORDINATORS[args.coordinator][0], args.config.parent,
                            keys, lambda method, params: bridge_telegram(cfg, method, params),
                            lambda payload: bridge_chat_post(cfg, payload), nostr=nostr)
        from robosats_mobile import MobileTrade
        bridge.trade = MobileTrade(int(cfg['chat']), args.order, bridge.name,
            lambda: mobile_request(cfg, '/api/order/', {'order_id': args.order}),
            lambda payload: mobile_request(cfg, '/api/order/', {'order_id': args.order}, payload),
            keys.sign_invoice, lambda method, params: bridge_telegram(cfg, method, params))
        return temp, bridge
    except BaseException:
        close_keys(temp)
        raise


def interactive(args):
    if not args.config.exists():
        setup(args.config)
    config = load_config(args.config)
    while True:
        print('\nRoboSats Telegram Bridge\n1. Browse offers on Telegram\n2. Monitor an existing order\n'
              '3. Settings\n4. Send Telegram test\nPress Enter to quit.')
        choice = input('Enter a menu option (1–4): ').strip()
        if not choice:
            return
        if choice == '1':
            browse_offers(args, config)
            return
        if choice == '2':
            order = input('RoboSats order number: ').strip().removeprefix('#')
            if re.fullmatch(r'[0-9]{1,18}', order) and int(order) > 0:
                args.order = int(order)
                args.coordinator = choose_coordinator()
                if args.coordinator is not None:
                    break
                continue
            print('Enter the numeric order number shown in RoboSats.')
        elif choice == '3':
            settings(args.config, config)
        elif choice == '4':
            args.command = 'telegram-test'
            run(args, {**config})
        else:
            print('Choose an option from the menu.')
    args.command = 'run'
    port = tor_port(config['port'])
    auth = saved_auth(config, args.coordinator)
    runtime = {**config, 'coordinator': args.coordinator, 'port': port, 'auth': auth}
    if auth:
        print('Checking the order with your saved robot…', flush=True)
        try:
            current = fetch(runtime, args.order)
        except RobotMismatch:
            auth = None
    garage_seed = None

    def remember_seed(seed):
        nonlocal garage_seed
        garage_seed = seed

    if not auth:
        garage_seed = session_garage_seed(args.config)
        if garage_seed is not None:
            auth = find_order_auth(garage_seed, runtime, args.order, extend_search=True)
        else:
            auth = prompt_auth(runtime, args.order, remember_seed)
        runtime['auth'] = auth
        current = fetch(runtime, args.order)
        # Reload before writing to retain settings changed in another terminal.
        config = load_config(args.config)
        set_saved_auth(config, args.coordinator, auth)
        save_config(args.config, config)
    print(message(args.order, current, True, COORDINATORS[args.coordinator][0]), flush=True)
    with keep_awake():
        bridge = temp = None
        try:
            if current['status'] not in TERMINAL and input('Enable Telegram chat for this order? Telegram will receive readable replies. [y/N]: ').strip().lower() in {'y', 'yes'}:
                try:
                    temp, bridge = start_bridge(args, runtime, session_garage_seed(args.config, garage_seed))
                except BridgeError as exc:
                    print(f'{exc} Continuing with alerts only.', flush=True)
                else:
                    print(f'Chat enabled. In your private Telegram bot chat, type a normal message to reply to order #{args.order}.', flush=True)
            garage_seed = None
            run(args, runtime, bridge)
        finally:
            if bridge is not None:
                bridge.lock.close()
                close_keys(temp)


def browse_offers(args, cfg, *, prompt_for_garage=False):
    from robosats_mobile import MobileOffers, terms
    from robosats_offers import book, matches_filters, run_offer_browser

    garage_seed = session_garage_seed(args.config)
    if garage_seed is None and args.unlock:
        garage_seed = decode_garage_key(read_garage_key())
    elif garage_seed is None and prompt_for_garage:
        print('To trade from your phone, use the Garage Key you backed up in RoboSats. Enter it here on this computer.')
        key = read_garage_key(allow_empty=True)
        if key:
            garage_seed = decode_garage_key(key)
            if input('Save this Garage Key on this computer for next time? [y/N]: ').strip().lower() in {'y', 'yes'}:
                save_config(args.config, {**load_config(args.config), 'garage_key': key})

    def public_get(runtime, path, params):
        try:
            return coordinator_get(runtime, path, params)
        except MonitorError as exc:
            raise BridgeError(str(exc)) from None

    def alert_book(settings, alias, side):
        return book(settings, public_get, alias, side)

    def discover_port(port):
        try:
            return tor_port(port)
        except MonitorError as exc:
            raise BridgeError(str(exc)) from None

    def runtime_for(alias):
        auth = saved_auth(cfg, alias)
        if not auth:
            raise BridgeError(f'No robot selected for {COORDINATORS[alias][0]}. '
                              'Reopen the offer or tap Resume an order in Telegram.')
        return {**cfg, 'coordinator': alias, 'auth': auth}

    def active(alias):
        return mobile_request(runtime_for(alias), '/api/robot/', {}).get('active_order_id')

    def order(alias, order_id):
        return mobile_request(runtime_for(alias), '/api/order/', {'order_id': order_id})

    def release(alias, order_id):
        # The unpaid taker sees status 3. The underlying coordinator order must still be public (1).
        return mobile_request(runtime_for(alias), '/api/order/', {'order_id': order_id},
                              {'action': 'cancel', 'cancel_status': 1})

    def take(alias, reviewed, amount):
        order_id = reviewed['id']
        candidate = runtime_for(alias)
        if garage_seed is not None:
            robot_signing_token(candidate, garage_seed, interactive_search=False)
        if active(alias):
            raise BridgeError('This robot already has an active trade. Tap Resume an order to continue it.')
        current = order(alias, order_id)
        if (current.get('id') != order_id or current.get('status') != 1 or current.get('type') != 1
                or current.get('is_participant') is not False or not matches_filters(current, cfg)
                or cfg.get('offer_coordinator') not in (None, alias)):
            raise BridgeError('This offer is no longer available to this robot.')
        if 'premium_now' in current:
            current['premium'] = current['premium_now']
        if terms(current) != terms(reviewed):
            raise BridgeError('The live terms changed. Review the offer again.')
        payload = {'action': 'take'}
        if amount is not None:
            payload['amount'] = format(amount, '.2f')
        return mobile_request(candidate, '/api/order/', {'order_id': order_id}, payload)

    def save_filter(key, value):
        saved = load_config(args.config)
        saved[key] = value
        save_config(args.config, saved)

    def list_robots(alias, start):
        if garage_seed is None:
            raise BridgeError('Unlock your Garage Key on the computer to select a robot.')
        try:
            robots = list(registered_robots({**cfg, 'coordinator': alias}, garage_seed, start))
            next_start = start + ROBOT_SEARCH_BATCH
            return robots, next_start if next_start < 2**31 else None
        except MonitorError as exc:
            raise BridgeError(str(exc)) from None

    def select_robot(alias, auth, index):
        try:
            saved = load_config(args.config)
            set_saved_auth(saved, alias, auth)
            saved.setdefault('robot_slots', {})[alias] = index
            save_config(args.config, saved)
        except (OSError, MonitorError):
            raise BridgeError('Could not save the selected robot on your computer.') from None
        set_saved_auth(cfg, alias, auth)
        cfg.setdefault('robot_slots', {})[alias] = index

    alert_urls = {alias: address for alias, (_, address) in COORDINATORS.items()}
    while True:
        handoff = run_offer_browser(cfg, args.config.parent, COORDINATORS, public_get, discover_port,
            bridge_telegram, lambda chat, names, get_book, telegram:
            MobileOffers(chat, names, get_book, telegram, order, active, take, garage_seed is not None,
                         save_filter=save_filter, list_robots=list_robots, select_robot=select_robot,
                         has_robot=lambda alias: bool(saved_auth(cfg, alias)), release=release,
                         alert_book=alert_book, alert_urls=alert_urls))
        if not handoff:
            return
        args.coordinator, args.order = handoff
        args.command = 'run'
        run_handoff(args, runtime_for(args.coordinator), garage_seed)


def mobile_request(cfg, endpoint, params, payload=None):
    try:
        response = coordinator_request(cfg, endpoint, params, order_payload=payload)
        result = response.json()
    except (ValueError, MonitorError):
        if payload:
            raise BridgeError('The action could not be confirmed. Check the current order before retrying.') from None
        raise BridgeError('Could not read the current RoboSats status.') from None
    if response.status_code == 200 and isinstance(result, dict):
        return result
    if payload:
        if response.status_code >= 500:
            raise BridgeError('The action could not be confirmed. Check the current order before retrying.')
        error = result.get('bad_invoice') if isinstance(result, dict) else None
        if isinstance(error, str) and error.startswith('The invoice hinted private routes'):
            raise BridgeError('That invoice exceeded the routing budget. Use /invoice PPM to review a different budget.')
        code = result.get('error_code') if isinstance(result, dict) else None
        if type(code) is int:
            raise BridgeError(f'RoboSats declined the action (error {code}). Check the current order.')
        raise BridgeError(f'RoboSats declined the action (HTTP {response.status_code}). Check the current order.')
    raise BridgeError(f'Could not read RoboSats status (HTTP {response.status_code}).')


def run_handoff(args, cfg, garage_seed):
    with keep_awake():
        bridge = temp = None
        try:
            if garage_seed is not None:
                try:
                    temp, bridge = start_bridge(args, cfg, garage_seed, interactive_search=False)
                except BridgeError as exc:
                    bridge_telegram(cfg, 'sendMessage', {'chat_id': cfg['chat'], 'text': f'{exc} Continuing with status alerts.'})
            run(args, cfg, bridge)
        finally:
            if bridge is not None:
                bridge.lock.close()
                close_keys(temp)


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', nargs='?', choices=['setup', 'settings', 'check', 'telegram-test', 'offers', 'terminal-menu'])
    p.add_argument('--coordinator', choices=COORDINATORS)
    p.add_argument('--order', type=int)
    p.add_argument('--interval', type=int, default=30)
    p.add_argument('--config', type=Path)
    p.add_argument('--unlock', action='store_true', help='enter your Garage Key locally for this session')
    args = p.parse_args()
    if args.interval < 15 or (args.command == 'check' and (not args.order or args.order < 1 or not args.coordinator)):
        p.error('Use an interval of at least 15 seconds. The check command requires --coordinator and a positive --order.')
    try:
        if args.config is None:
            args.config = HOME / 'config.json'
        if args.command in (None, 'offers'):
            prompt_for_garage = args.command is None and sys.stdin.isatty()
            if not args.config.exists():
                setup(args.config, ask_garage=not prompt_for_garage)
            browse_offers(args, load_config(args.config), prompt_for_garage=prompt_for_garage)
        elif args.command == 'terminal-menu':
            interactive(args)
        elif args.command == 'setup':
            setup(args.config)
        else:
            config = load_config(args.config)
            if args.command == 'settings':
                settings(args.config, config)
            else:
                if args.command == 'check':
                    config['auth'] = saved_auth(config, args.coordinator)
                    if not config['auth']:
                        raise MonitorError('Select a robot for that coordinator in Settings first.')
                    config['coordinator'] = args.coordinator
                run(args, config)
    except (KeyboardInterrupt, EOFError):
        print('\nStopped.')
    except (MonitorError, BridgeError) as exc:
        print(f'Stopped: {exc}', file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, ImportError):
        # Never dump a request URL, header, response body or secret-bearing traceback.
        print('Stopped: configuration or service check failed. Verify local config, Tor and credentials.', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
