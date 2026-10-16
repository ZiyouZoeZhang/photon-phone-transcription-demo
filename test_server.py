import base64
import hashlib
import hmac
import json
import io
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree
import server as app

class DemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.PUBLIC = 'https://unit.example'
        app.TOKEN = 'unit-secret'
        app.SELLER = '+12025550123'
        try:
            cls.http = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        except PermissionError:
            raise unittest.SkipTest('Environment prohibits listening sockets; run locally in Terminal.')
        cls.base = 'http://127.0.0.1:' + str(cls.http.server_port)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()

    def setUp(self):
        with app.LOCK:
            app.EVENTS.clear()
            app.SEEN.clear()

    def request(self, path, data=None, signed=False, auth=False):
        headers = {}
        if auth:
            headers['Authorization'] = 'Basic ' + base64.b64encode(('demo:' + app.ADMIN).encode()).decode()
            headers['X-Demo-Action'] = '1'
        if signed:
            value = app.PUBLIC + path + ''.join(k + str(data[k]) for k in sorted(data))
            headers['X-Twilio-Signature'] = base64.b64encode(hmac.new(app.TOKEN.encode(), value.encode(), hashlib.sha1).digest()).decode()
        body = urlencode(data).encode() if data is not None else None
        return urlopen(Request(self.base + path, data=body, headers=headers), timeout=3)

    def test_unauthorized_ui(self):
        with self.assertRaises(HTTPError) as result:
            self.request('/api/state')
        self.assertEqual(result.exception.code, 401)

    def test_unsigned_webhook(self):
        with self.assertRaises(HTTPError) as result:
            self.request('/twilio/voice', {})
        self.assertEqual(result.exception.code, 403)

    def test_signed_voice_xml(self):
        with self.request('/twilio/voice', {'CallSid': 'CA-test'}, signed=True) as response:
            root = ElementTree.fromstring(response.read())
        self.assertEqual(root.find('Dial/Number').text, app.SELLER)
        self.assertEqual(root.find('Start/Transcription').get('track'), 'both_tracks')
        self.assertEqual(root.find('Start/Transcription').get('statusCallbackUrl'), app.PUBLIC + '/twilio/transcription')

    def test_signed_callback_and_dedup(self):
        data = dict(CallSid='CA-test', TranscriptionSid='GT-test', SequenceId='1',
                    TranscriptionEvent='transcription-content', Track='inbound_track', Final='true',
                    TranscriptionData=json.dumps({'transcript': '<hello> & welcome'}))
        for _ in range(2):
            with self.request('/twilio/transcription', data, signed=True) as r:
                self.assertEqual(r.status, 200)
        self.assertEqual(len(app.EVENTS), 1)
        self.assertEqual(app.EVENTS[0]['speaker'], 'Customer')
        self.assertEqual(app.EVENTS[0]['text'], '<hello> & welcome')
        self.assertTrue(app.EVENTS[0]['final'])

    def test_partial(self):
        app.consume(dict(TranscriptionEvent='transcription-content', Track='outbound_track', Final='false',
                         TranscriptionData='{"transcript":"Hello"}'))
        self.assertFalse(app.EVENTS[-1]['final'])
        self.assertEqual(app.EVENTS[-1]['speaker'], 'Seller')

    def test_simulation(self):
        with self.request('/api/simulate', {}, auth=True) as r:
            self.assertEqual(r.status, 200)
        deadline = time.monotonic() + 15
        while app.RUNNING and time.monotonic() < deadline:
            time.sleep(.1)
        self.assertFalse(app.RUNNING)
        finals = [e for e in app.EVENTS if e.get('final')]
        self.assertEqual(len(finals), 4)
        self.assertTrue(all(e['source'] == 'simulation' for e in finals))
        with self.request('/api/state', auth=True) as r:
            self.assertEqual(len(json.load(r)['events']), len(app.EVENTS))

class OfflineTests(unittest.TestCase):
    def setUp(self):
        app.PUBLIC = 'https://unit.example'
        app.TOKEN = 'unit-secret'
        app.SELLER = '+12025550123'
        app.EVENTS.clear()
        app.SEEN.clear()

    def handler(self, path, data, signed=True):
        handler = object.__new__(app.Handler)
        handler.path = path
        raw = urlencode(data).encode()
        value = app.PUBLIC + path + ''.join(k + str(data[k]) for k in sorted(data))
        signature = base64.b64encode(hmac.new(app.TOKEN.encode(), value.encode(), hashlib.sha1).digest()).decode()
        handler.headers = {'Content-Length': str(len(raw)), 'X-Twilio-Signature': signature if signed else ''}
        handler.rfile = io.BytesIO(raw)
        result = []
        handler.reply = lambda *args: result.append(args)
        handler.do_POST()
        return result[0]

    def test_voice_and_notice(self):
        code, body, _ = self.handler('/twilio/voice', {'CallSid':'CA1'})
        self.assertEqual(code, 200)
        root = ElementTree.fromstring(body)
        self.assertEqual(root.find('Dial/Number').text, app.SELLER)
        self.assertEqual(root.find('Start/Transcription').get('partialResults'), 'true')
        self.assertEqual(self.handler('/twilio/notice', {})[0], 200)

    def test_signature_rejection(self):
        self.assertEqual(self.handler('/twilio/voice', {}, False)[0], 403)

    def test_content_and_duplicate(self):
        data = dict(CallSid='CA1', TranscriptionSid='GT1', SequenceId='3',
                    TranscriptionEvent='transcription-content', Track='inbound_track', Final='true',
                    TranscriptionData='{"transcript":"Too expensive"}')
        self.assertEqual(self.handler('/twilio/transcription', data)[0], 200)
        self.handler('/twilio/transcription', data)
        self.assertEqual(len(app.EVENTS), 1)
        self.assertEqual(app.EVENTS[0]['speaker'], 'Customer')
        self.assertTrue(app.EVENTS[0]['final'])

    def test_malformed_callback(self):
        data = dict(TranscriptionEvent='transcription-content', TranscriptionData='{')
        self.assertEqual(self.handler('/twilio/transcription', data)[0], 400)

    def test_partial_and_error(self):
        app.consume(dict(TranscriptionEvent='transcription-content', Track='outbound_track',
                         Final='false', TranscriptionData='{"transcript":"Hello"}'))
        self.assertEqual(app.EVENTS[-1]['speaker'], 'Seller')
        self.assertFalse(app.EVENTS[-1]['final'])
        app.consume(dict(TranscriptionEvent='transcription-error', ErrorMessage='Engine unavailable'))
        self.assertEqual(app.EVENTS[-1]['error'], 'Engine unavailable')

    def test_auth(self):
        h = object.__new__(app.Handler)
        h.headers = {'Authorization': 'Basic ' + base64.b64encode(('demo:' + app.ADMIN).encode()).decode()}
        self.assertTrue(h.auth())
        h.headers = {}
        result = []
        h.send_response = lambda code: result.append(code)
        h.send_header = lambda *args: None
        h.end_headers = lambda: None
        self.assertFalse(h.auth())
        self.assertEqual(result, [401])

    def test_simulation(self):
        from unittest.mock import patch
        with patch.object(app.time, 'sleep'):
            app.simulate()
        finals = [e for e in app.EVENTS if e.get('final')]
        self.assertEqual(len(finals), 4)
        self.assertTrue(all(e['source'] == 'simulation' for e in finals))

if __name__ == '__main__':
    unittest.main()
