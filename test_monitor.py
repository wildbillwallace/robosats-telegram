import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import requests
import robosats_monitor as m

class Tests(unittest.TestCase):
    def response(self, status=7, escrow=False, http=200, **extra):
        r = Mock(status_code=http)
        r.json.return_value = dict(id=876543, is_taker=True, is_participant=True,
                                   status=status, escrow_locked=escrow, **extra)
        return r

    def test_taker_escrow(self):
        self.assertEqual(m.snapshot(self.response(9, True), 876543), {'status':9, 'escrow_locked':True})

    def test_reject_wrong_identity_and_schema(self):
        for change in [{'id':1}, {'is_taker':False}, {'is_participant':False},
                       {'status':99}, {'status':True}, {'escrow_locked':'true'}]:
            r=self.response(); r.json.return_value.update(change)
            with self.assertRaises(m.MonitorError): m.snapshot(r,876543)

    def test_cancel_error(self):
        r=Mock(status_code=400); r.json.return_value={'error_code':1043}
        self.assertEqual(m.snapshot(r,876543)['status'],4)

    def test_http_and_invalid_json(self):
        for http in [301,401,403,404,429,500]:
            with self.assertRaises(m.MonitorError): m.snapshot(self.response(http=http),876543)
        r=self.response(); r.json.side_effect=ValueError('secret')
        with self.assertRaises(m.MonitorError) as c: m.snapshot(r,876543)
        self.assertNotIn('secret',str(c.exception))

    def test_get_only_and_no_redirect(self):
        payload = json.dumps(self.response().json.return_value) + '\n200'
        with patch.object(m.subprocess, 'run', return_value=Mock(returncode=0, stdout=payload)) as run:
            m.fetch({'auth':'Token private-test', 'port':9050}, 876543)
        args, kwargs = run.call_args
        command = args[0]
        self.assertEqual(command[-1], m.ONION + '/api/order/?order_id=876543')
        self.assertIn('127.0.0.1:9050', command)
        self.assertNotIn('--location', command)
        self.assertNotIn('private-test', str(command))
        self.assertIn('Authorization: Token private-test', kwargs['input'])

    def test_tor_dns_no_environment_proxy(self):
        s=m.session(9050)
        self.assertFalse(s.trust_env)
        self.assertEqual(s.proxies['https'],'socks5h://127.0.0.1:9050')

    def test_changes_restart_retry(self):
        state={'observed':None,'pending':[]}
        first={'status':7,'escrow_locked':False}
        m.enqueue(state, first,876543); m.enqueue(state, first,876543)
        self.assertEqual(len(state['pending']),1)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'state.json'; m.save(p,state)
            state=json.loads(p.read_text()); m.enqueue(state,first,876543)
            self.assertEqual(len(state['pending']),1)
            bad=Mock(side_effect=m.MonitorError('offline'))
            with self.assertRaises(m.MonitorError): m.flush(state,p,bad)
            self.assertEqual(len(state['pending']),1)
            m.enqueue(state,{'status':7,'escrow_locked':True},876543)
            self.assertEqual(len(state['pending']),2)
            good=Mock(); m.flush(state,p,good)
            self.assertEqual(good.call_count,2)
            self.assertEqual(json.loads(p.read_text())['pending'],[])
            if os.name != 'nt':
                self.assertEqual(p.stat().st_mode & 0o777,0o600)

    def test_initial_already_locked(self):
        self.assertIn('escrow is locked',m.message(876543,{'status':9,'escrow_locked':True},True))

    def test_telegram_failure_and_secret_redaction(self):
        s=Mock(); s.post.side_effect=requests.ConnectionError('secret URL')
        with self.assertRaises(m.MonitorError) as c:
            m.telegram(s,{'bot':'secret','chat':'1'},'test')
        self.assertNotIn('secret',str(c.exception))
        s.post.side_effect=None; s.post.return_value=Mock(status_code=200)
        s.post.return_value.json.return_value={'ok':False}
        with self.assertRaises(m.MonitorError): m.telegram(s,{'bot':'secret','chat':'1'},'test')

    def test_telegram_separate_auth(self):
        s=Mock(); s.post.return_value=Mock(status_code=200)
        s.post.return_value.json.return_value={'ok':True}
        m.telegram(s,{'bot':'test','chat':'1','auth':'PRIVATE'},'safe')
        _,kw=s.post.call_args
        self.assertNotIn('headers',kw)
        self.assertNotIn('PRIVATE',str(kw))
        self.assertFalse(kw['allow_redirects'])

    def test_chat_ignores_history_and_own_messages_and_never_saves_contents(self):
        state = {'pending': []}
        reply = Mock(status_code=200)
        with patch.object(m, 'coordinator_get', return_value=reply) as get:
            reply.json.return_value = {'messages': [{'index': 2, 'nick': 'seller', 'message': 'private'}]}
            m.poll_chat({}, 876543, 'seller', state, initial=True)
            self.assertEqual(state, {'pending': [], 'chat_offset': 2})
            reply.json.return_value = {'messages': [{'index': 3, 'nick': 'buyer', 'message': 'private'}]}
            m.poll_chat({}, 876543, 'seller', state)
            self.assertFalse(state['pending'])
            reply.json.return_value = {'messages': [{'index': 4, 'nick': 'seller', 'message': 'private'}]}
            m.poll_chat({}, 876543, 'seller', state)
            self.assertEqual(get.call_args.args[-1]['offset'], 3)
            m.poll_chat({}, 876543, 'seller', state)
        self.assertEqual(len(state['pending']), 1)
        self.assertNotIn('private', state['pending'][0])
        self.assertEqual(state['chat_offset'], 4)

    @unittest.skipIf(os.name == 'nt', 'Brave port discovery is macOS-specific')
    def test_old_port_replaced_by_new_brave_socks_port(self):
        listeners = 'p1\nctor\nn127.0.0.1:9999\np2\nctor-darwin-brave-0\nn127.0.0.1:51000\nn127.0.0.1:51001\n'
        with patch.object(m.subprocess, 'run', return_value=Mock(stdout=listeners)), \
             patch.object(m, 'socks_listens', side_effect=[False, False, False, False, True]) as probe:
            self.assertEqual(m.tor_port(58999), 51001)
        self.assertEqual([call.args[0] for call in probe.call_args_list], [58999, 9050, 9150, 51000, 51001])

if __name__=='__main__': unittest.main()
