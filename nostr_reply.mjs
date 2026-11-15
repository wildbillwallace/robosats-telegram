import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { getEventHash, getPublicKey, nip44, nip59, verifyEvent } from 'nostr-tools';
import { SocksProxyAgent } from 'socks-proxy-agent';
import WebSocket from 'ws';

export function wrapReply({ key, own, peer, order, text, relay }) {
  const secret = new Uint8Array(Buffer.from(key, 'hex'));
  const pubkey = /^[0-9a-f]{64}$/;
  if (!pubkey.test(key) || !pubkey.test(peer) || getPublicKey(secret) !== own || peer === own) {
    throw new Error('Robot identity does not match the order');
  }
  const event = {
    kind: 14, created_at: Math.ceil(Date.now() / 1000), content: text,
    tags: [['order_id', order], ['p', peer, relay], ['p', own, relay]],
  };
  return [peer, own].map(recipient => nip59.wrapEvent(event, secret, recipient));
}

export function readReply(wrap, { key, own, peer, order, since }) {
  try {
    const secret = new Uint8Array(Buffer.from(key, 'hex'));
    if (wrap.kind !== 1059 || !verifyEvent(wrap) ||
        !wrap.tags.some(([name, value]) => name === 'p' && value === own)) return;
    const open = event => JSON.parse(nip44.v2.decrypt(
      event.content, nip44.v2.utils.getConversationKey(secret, event.pubkey)));
    const seal = open(wrap);
    if (seal.kind !== 13 || seal.pubkey !== peer || !verifyEvent(seal)) return;
    const reply = open(seal);
    if (reply.kind !== 14 || reply.pubkey !== peer || getEventHash(reply) !== reply.id ||
        !Number.isSafeInteger(reply.created_at) || reply.created_at < since ||
        reply.created_at > Date.now() / 1000 + 300 ||
        !reply.tags.some(([name, value]) => name === 'order_id' && value === order)) return;
    const recipients = reply.tags.filter(([name]) => name === 'p').map(tag => tag[1]);
    if (!recipients.includes(own) || recipients.some(value => value !== own && value !== peer)) return;
    return { id: reply.id, time: reply.created_at, text: reply.content };
  } catch {
    return;
  }
}

export function receive(url, input, options) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url, options);
    const messages = new Map();
    const timer = setTimeout(() => finish(new Error('Relay response timed out')), 12_000);
    let done = false;
    function finish(error) {
      if (done) return;
      done = true;
      clearTimeout(timer);
      if (error) reject(error); else resolve([...messages.values()]);
      ws.terminate();
    }
    ws.on('error', finish);
    ws.on('close', () => finish(new Error('Relay disconnected')));
    ws.on('open', () => ws.send(JSON.stringify(['REQ', 'trade', {
      kinds: [1059], '#p': [input.own], since: Math.max(0, input.since - 2 * 86400 - 300),
    }])));
    ws.on('message', data => {
      let frame;
      try { frame = JSON.parse(data.toString()); } catch { return; }
      if (!Array.isArray(frame) || frame[1] !== 'trade') return;
      if (frame[0] === 'EOSE') return finish();
      if (frame[0] === 'CLOSED') return finish(new Error('Relay closed subscription'));
      if (frame[0] === 'EVENT') {
        const reply = readReply(frame[2], input);
        if (reply) messages.set(reply.id, reply);
      }
    });
  });
}

export function publish(url, events, options) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url, options);
    const pending = new Set(events.map(event => event.id));
    const timer = setTimeout(() => finish(new Error('Relay acknowledgment timed out')), 18_000);
    function finish(error) {
      clearTimeout(timer);
      if (error) reject(error); else resolve();
      ws.terminate();
    }
    ws.on('error', finish);
    ws.on('close', () => finish(new Error('Relay disconnected')));
    ws.on('open', () => {
      for (const event of events) ws.send(JSON.stringify(['EVENT', event]));
    });
    ws.on('message', data => {
      let reply;
      try { reply = JSON.parse(data.toString()); } catch { return; }
      if (!Array.isArray(reply) || reply[0] !== 'OK' || !pending.has(reply[1])) return;
      if (reply[2] !== true) return finish(new Error('Relay rejected the message'));
      pending.delete(reply[1]);
      if (!pending.size) finish();
    });
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const input = JSON.parse(readFileSync(0, 'utf8'));
    if (input.probe === true) {
      process.stdout.write('ready');
    } else {
      const relays = [...new Set(input.relays)];
      if (!relays.length || relays.length > 6 ||
          !relays.every(url => /^ws:\/\/[a-z2-7]{56}\.onion\/relay\/$/.test(url)) ||
          !relays.includes(input.relay) || !Number.isInteger(input.port) ||
          input.port < 1 || input.port > 65535) throw new Error();
      const secret = new Uint8Array(Buffer.from(input.key, 'hex'));
      if (!/^[0-9a-f]{64}$/.test(input.key) || !/^[0-9a-f]{64}$/.test(input.peer) ||
          getPublicKey(secret) !== input.own || input.peer === input.own) throw new Error();
      const agent = new SocksProxyAgent(`socks5h://127.0.0.1:${input.port}`);
      const options = { agent, followRedirects: false, maxPayload: 64 * 1024 };
      if (input.receive) {
        if (!Number.isSafeInteger(input.since) || input.since <= 0) throw new Error();
        const results = await Promise.allSettled(relays.map(url => receive(url, input, options)));
        const available = results.filter(result => result.status === 'fulfilled');
        if (!available.length) throw new Error();
        const unique = new Map(available.flatMap(result => result.value).map(reply => [reply.id, reply]));
        process.stdout.write(JSON.stringify([...unique.values()].sort((a, b) => a.time - b.time)));
      } else {
        const events = wrapReply(input);
        await Promise.any(relays.map(url => publish(url, events, options)));
        process.stdout.write('accepted');
      }
    }
  } catch {
    process.exitCode = 1;
  }
}
