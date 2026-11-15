import assert from 'node:assert/strict';
import test from 'node:test';
import { getPublicKey, nip59, verifyEvent } from 'nostr-tools';
import { WebSocketServer } from 'ws';
import { publish, readReply, receive, wrapReply } from './nostr_reply.mjs';

const key = '01'.repeat(32);
const peerKey = new Uint8Array(Buffer.from('02'.repeat(32), 'hex'));
const own = getPublicKey(new Uint8Array(Buffer.from(key, 'hex')));
const peer = getPublicKey(peerKey);
const relay = 'ws://example.invalid/relay/';
const input = { key, own, peer, relay, order: 'temple/123', text: 'Back in 30 minutes.' };

test('recipient can open a signed reply with the expected sender, order and tags', () => {
  const [recipient, sender] = wrapReply(input);
  for (const [event, secret] of [[recipient, peerKey], [sender, new Uint8Array(Buffer.from(key, 'hex'))]]) {
    assert.ok(verifyEvent(event));
    const reply = nip59.unwrapEvent(event, secret);
    assert.equal(reply.pubkey, own);
    assert.equal(reply.kind, 14);
    assert.equal(reply.content, input.text);
    assert.deepEqual(reply.tags, [['order_id', input.order], ['p', peer, relay], ['p', own, relay]]);
  }
  assert.throws(() => wrapReply({ ...input, own: peer }));
});

test('publish requires positive acknowledgments for both encrypted copies', async () => {
  const server = new WebSocketServer({ host: '127.0.0.1', port: 0 });
  const seen = [];
  let accept = true;
  await new Promise(resolve => server.once('listening', resolve));
  server.on('connection', socket => socket.on('message', data => {
    const [type, event] = JSON.parse(data.toString());
    assert.equal(type, 'EVENT');
    seen.push(event.id);
    socket.send(JSON.stringify(['OK', event.id, accept, '']));
  }));
  try {
    const url = `ws://127.0.0.1:${server.address().port}`;
    const events = wrapReply(input);
    await publish(url, events);
    assert.deepEqual(seen, events.map(event => event.id));
    accept = false;
    await assert.rejects(publish(url, wrapReply(input)), /rejected/);
  } finally {
    for (const socket of server.clients) socket.terminate();
    await new Promise(resolve => server.close(resolve));
  }
});

const incoming = { ...input, key: '02'.repeat(32), own: peer, peer: own,
  since: Math.floor(Date.now() / 1000) - 30 };

test('incoming replies reject tampering, another trader, and another order', () => {
  const [reply] = wrapReply(input);
  assert.equal(readReply(reply, incoming).text, input.text);
  assert.equal(readReply({ ...JSON.parse(JSON.stringify(reply)), sig: '0'.repeat(128) }, incoming), undefined);
  assert.equal(readReply(reply, { ...incoming, order: 'temple/456' }), undefined);
  assert.equal(readReply(reply, { ...incoming, peer: peer }), undefined);
  const forged = nip59.wrapEvent({ kind: 14, content: 'wrong author', tags: [['order_id', input.order], ['p', peer]] }, peerKey, peer);
  assert.equal(readReply(forged, incoming), undefined);
});

test('subscription fetches a Nostr-only reply again after reconnect for persistent deduplication', async () => {
  const server = new WebSocketServer({ host: '127.0.0.1', port: 0 });
  await new Promise(resolve => server.once('listening', resolve));
  const [reply] = wrapReply(input);
  server.on('connection', socket => socket.on('message', data => {
    const [action, sub, filter] = JSON.parse(data.toString());
    assert.equal(action, 'REQ');
    assert.deepEqual(filter['#p'], [peer]);
    assert.ok(filter.since <= reply.created_at);
    for (const event of [reply, reply]) socket.send(JSON.stringify(['EVENT', sub, event]));
    socket.send(JSON.stringify(['EOSE', sub]));
  }));
  const url = `ws://127.0.0.1:${server.address().port}`;
  try {
    const first = await receive(url, incoming);
    assert.equal(first.length, 1);
    assert.equal(first[0].text, input.text);
    assert.deepEqual(await receive(url, incoming), first);
  } finally {
    for (const socket of server.clients) socket.terminate();
    await new Promise(resolve => server.close(resolve));
  }
});
