"""Opt-in Telegram bridge for coordinator-backed RoboSats text chat."""
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
import time

from robosats_platform import gpg_tool, lock_file


# Mainnet federation relays from the RoboSats v0.8.8 roster.
FEDERATION_RELAYS = (
    'ws://ngdk7ocdzmz5kzsysa3om6du7ycj2evxp2f2olfkyq37htx3gllwp2yd.onion/relay/',
    'ws://4t4jxmivv6uqej6xzx2jx3fxh75gtt65v3szjoqmc4ugdlhipzdat6yd.onion/relay/',
    'ws://librebazovfmmkyi2jekraxsuso3mh622avuuzqpejixdl5dhuhb4tid.onion/relay/',
    'ws://2enoseg66hme76khjjn2qvrhipnzwgwa44mewgrdphrxbhzcxd2vdiqd.onion/relay/',
    'ws://ammannjgzybw4qm2odmci7xgolh5grzijidacjxose5tthm375dcopad.onion/relay/',
    'ws://jvnfeiy3aizcpva6zekd3v6o5kpzduqeeqqihhtudhuqqa7e5jzm7kyd.onion/relay/',
)

class BridgeError(Exception):
    pass


class NostrChat:
    def __init__(self, cfg, key, order, relay):
        self.cfg, self.key, self.order, self.relay = cfg, key, order, relay
        self.node = shutil.which('node')
        if not self.node or self.invoke({'probe': True}) != 'ready':
            raise BridgeError('Nostr dependencies unavailable. Use the quick-start guide to install them.')

    def invoke(self, payload):
        try:
            result = subprocess.run([self.node, str(Path(__file__).with_name('nostr_reply.mjs'))],
                                    input=json.dumps(payload), text=True, encoding='utf-8', capture_output=True, timeout=22)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout if result.returncode == 0 else None

    def request(self, participants, **action):
        own, peer = participants
        payload = {'key': self.key, 'own': own, 'peer': peer, 'order': self.order,
                   'relay': self.relay, 'relays': FEDERATION_RELAYS,
                   'port': self.cfg['port'], **action}
        return self.invoke(payload)

    def send(self, text, participants):
        return self.request(participants, text=text) == 'accepted'

    def receive(self, participants, since):
        raw = self.request(participants, receive=True, since=since)
        if raw is None:
            raise BridgeError('Could not read chat from any Nostr relay through Tor.')
        try:
            return json.loads(raw)
        except ValueError:
            raise BridgeError('Unexpected Nostr chat response.') from None


class ChatKeys:
    def __init__(self, directory, gpg, passphrase, robot):
        self.directory = directory
        self.gpg = gpg
        self.passphrase = passphrase
        self.peer = None
        self.own = self.import_key(robot['public_key'])
        self.invoke(['--import'], robot['encrypted_private_key'].replace('\\', '\n'))
        # Fail early if the Garage Key cannot unlock this robot's signing key.
        self.invoke(['--local-user', self.own, '--detach-sign', '--armor'], 'RoboSats bridge key check', True)

    def invoke(self, flags, data, secret=False):
        args = [self.gpg, '--no-options', '--homedir', self.directory, '--batch', '--yes',
                '--no-tty', '--pinentry-mode', 'loopback', '--status-fd', '2']
        fd = None
        launch_options = {}
        payload = data.encode('utf-8')
        try:
            if secret and os.name == 'nt':
                args += ['--passphrase-fd', '0']
                payload = self.passphrase.encode('utf-8') + b'\n' + payload
            elif secret:
                fd, writer = os.pipe()
                try:
                    os.write(writer, (self.passphrase + '\n').encode())
                finally:
                    os.close(writer)
                args += ['--passphrase-fd', str(fd)]
                launch_options['pass_fds'] = (fd,)
            result = subprocess.run(args + flags, input=payload, capture_output=True,
                                    timeout=15, **launch_options)
        except (OSError, subprocess.TimeoutExpired):
            raise BridgeError('Local GnuPG operation failed.') from None
        finally:
            if fd is not None:
                os.close(fd)
        if result.returncode:
            raise BridgeError('Could not unlock, encrypt, or decrypt the RoboSats chat key or message.')
        return result.stdout, result.stderr.decode(errors='replace').splitlines()

    def import_key(self, armor):
        _, lines = self.invoke(['--import'], armor.replace('\\', '\n'))
        fingerprints = {line.split()[3] for line in lines if line.startswith('[GNUPG:] IMPORT_OK ')}
        if len(fingerprints) != 1:
            raise BridgeError('Expected a single RoboSats public key.')
        return fingerprints.pop()

    def set_peer(self, armor):
        if not isinstance(armor, str) or not armor:
            raise BridgeError('The coordinator did not provide the other trader’s chat key.')
        if self.peer is None:
            self.peer = self.import_key(armor)
            self.peer_armor = armor
        elif self.peer_armor != armor:
            raise BridgeError('The other trader’s chat key changed. Restart and verify it in RoboSats.')
        if self.peer == self.own:
            raise BridgeError('The chat key matches your own robot key.')

    def decrypt(self, encrypted):
        if not isinstance(encrypted, str):
            raise BridgeError('Unrecognized encrypted chat message.')
        plain, lines = self.invoke(['--decrypt'], encrypted.replace('\\', '\n'), True)
        signatures = [line.split() for line in lines if line.startswith('[GNUPG:] VALIDSIG ')]
        if not any(self.peer in (fields[2], fields[-1]) for fields in signatures):
            raise BridgeError('The reply’s signature could not be verified.')
        try:
            return plain.decode('utf-8')
        except UnicodeDecodeError:
            raise BridgeError('The reply is not readable text.') from None

    def sign_invoice(self, invoice):
        signed, _ = self.invoke(['--armor', '--digest-algo', 'SHA512', '--local-user',
                                 self.own, '--clearsign'], invoice + '\n', True)
        message = signed.decode('ascii').replace('\r\n', '\n')
        if not message.startswith('-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA512\n\n'):
            raise BridgeError('Could not create the required SHA512 invoice signature.')
        return message

    def encrypt(self, text):
        encrypted, _ = self.invoke(['--armor', '--trust-model', 'always', '--local-user', self.own,
                                    '--recipient', self.own, '--recipient', self.peer,
                                    '--sign', '--encrypt'], text, True)
        return encrypted.decode('ascii').replace('\r\n', '\n').replace('\n', '\\')


class ChatBridge:
    def __init__(self, cfg, order, name, directory, keys, telegram_call, post_chat, nostr=None):
        self.cfg, self.order, self.name, self.keys = cfg, order, name, keys
        self.telegram_call, self.post_chat = telegram_call, post_chat
        self.nostr = nostr
        self.trade = None
        self.started = math.floor(time.time())
        self.offset = None
        self.chat_id = int(cfg['chat'])
        if self.chat_id <= 0:
            raise BridgeError('Chat bridge requires your private Telegram bot chat.')
        bot_id = re.fullmatch(r'(\d+):[A-Za-z0-9_-]+', cfg['bot'])
        if not bot_id:
            raise BridgeError('Invalid Telegram bot configuration.')
        try:
            self.lock = lock_file(Path(directory) / f'bridge-{bot_id[1]}.lock')
        except BlockingIOError:
            raise BridgeError('Another monitor is using this bot for chat replies.') from None
        try:
            webhook = telegram_call('getWebhookInfo', {})
            if not isinstance(webhook, dict) or webhook.get('url'):
                raise BridgeError('This Telegram bot uses a webhook. Chat bridge requires a bot available for polling.')
        except BaseException:
            self.lock.close()
            raise

    def send_telegram(self, text):
        self.telegram_call('sendMessage', {'chat_id': str(self.chat_id), 'text': text,
                                           'link_preview_options': {'is_disabled': True}})

    def forward(self, messages, peer_key):
        if not messages:
            return
        self.keys.set_peer(peer_key)
        for item in messages:
            try:
                text = self.keys.decrypt(item['message'])
            except (BridgeError, KeyError):
                text = 'Could not verify or display this reply. Open RoboSats to read it.'
            self.send_telegram(f'{self.name} #{self.order} · New reply\n{text[:3000]}')

    def poll_nostr(self, participants, state, persist):
        now = math.floor(time.time())
        since = max(state.setdefault('nostr_since', self.started), now - 7 * 86400)
        seen = state.setdefault('nostr_seen', {})
        for event_id in list(seen):
            if seen[event_id] < since:
                del seen[event_id]
        for reply in self.nostr.receive(participants, since):
            if reply['id'] in seen:
                continue
            self.send_telegram(f'{self.name} #{self.order} · New reply\n{reply["text"][:3000]}')
            seen[reply['id']] = reply['time']
            persist()

    def poll_messages(self, active, peer_key, participants=None):
        update_types = ['message', 'callback_query'] if self.trade else ['message']
        params = {'timeout': 0, 'allowed_updates': update_types}
        if self.offset is not None:
            params['offset'] = self.offset
        updates = self.telegram_call('getUpdates', params)
        if not isinstance(updates, list):
            raise BridgeError('Unexpected Telegram update response.')
        for update in updates:
            self.offset = update['update_id'] + 1
            callback = update.get('callback_query')
            msg = (callback or update).get('message', {})
            sender = (callback or msg).get('from', {})
            text = msg.get('text', '')
            if (msg.get('chat', {}).get('type') != 'private'
                    or msg.get('chat', {}).get('id') != self.chat_id
                    or sender.get('id') != self.chat_id):
                continue
            if callback:
                if self.trade:
                    self.trade.handle(update)
                continue
            if msg.get('date', 0) <= self.started or 'forward_origin' in msg:
                continue
            if self.trade and self.trade.handle(update):
                continue
            if (not isinstance(text, str) or not text.strip()
                    or text.lstrip().startswith('/')):
                continue
            body = text.strip()
            if len(body) > 1000:
                self.send_telegram('Your reply was not sent. Send up to 1,000 characters at a time.')
                continue
            use_nostr = self.nostr is not None and bool(participants)
            if not active or not (peer_key or use_nostr):
                self.send_telegram(f'RoboSats #{self.order}: chat is unavailable. Your reply was not sent.')
                continue
            nostr_ok = use_nostr and self.nostr.send(body, participants)
            api_ok = False
            if peer_key:
                try:
                    self.keys.set_peer(peer_key)
                    encrypted = self.keys.encrypt(body)
                    self.post_chat({'order_id': self.order, 'PGP_message': encrypted})
                    api_ok = True
                except BridgeError:
                    pass
            if nostr_ok:
                self.send_telegram(f'Reply accepted by the Nostr relay for {self.name} #{self.order}.')
            elif api_ok and use_nostr:
                self.send_telegram(f'API accepted your reply for #{self.order}. Nostr delivery is unconfirmed.')
            elif api_ok:
                self.send_telegram(f'Reply sent to {self.name} #{self.order} via the API.')
            else:
                self.send_telegram(f'RoboSats #{self.order}: delivery could not be confirmed. Check the chat before retrying.')


def open_keys(robot, passphrase):
    gpg = gpg_tool('gpg')
    if not gpg:
        raise BridgeError('GnuPG is needed for the chat bridge. See your platform’s setup guide.')
    temp = TemporaryDirectory(prefix='rs-gpg-')
    try:
        return temp, ChatKeys(temp.name, gpg, passphrase, robot)
    except BaseException:
        close_keys(temp)
        raise


def close_keys(temp):
    gpgconf = gpg_tool('gpgconf')
    try:
        if gpgconf:
            subprocess.run([gpgconf, '--homedir', temp.name, '--kill', 'gpg-agent'],
                           capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass
    finally:
        temp.cleanup()
