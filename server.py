"""Local telephone transcription lab. Python standard library only."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from xml.etree.ElementTree import Element, SubElement, tostring

ROOT = Path(__file__).resolve().parent
for line in (ROOT / '.env').read_text().splitlines() if (ROOT / '.env').exists() else []:
    if line.strip() and not line.lstrip().startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('\"\''))
ADMIN = os.environ.get('DEMO_PASSWORD') or secrets.token_urlsafe(18)
PUBLIC = os.environ.get('PUBLIC_BASE_URL', '').rstrip('/')
TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
SELLER = os.environ.get('SELLER_PHONE', '')
LOCK = threading.Lock()
EVENTS = []
SEEN = set()
RUNNING = False

def emit(event):
    with LOCK:
        event['receivedAt'] = time.time()
        EVENTS.append(event)
        del EVENTS[:-1000]

def consume(data):
    key = (data.get('CallSid'), data.get('TranscriptionSid'), data.get('SequenceId'))
    with LOCK:
        if key[2] and key in SEEN:
            return
        if key[2]:
            SEEN.add(key)
            if len(SEEN) > 10000:
                SEEN.clear()
    kind = data.get('TranscriptionEvent', 'unknown')
    if kind == 'transcription-content':
        content = json.loads(data.get('TranscriptionData', '{}'))
        text = content.get('transcript', '')
        if not isinstance(text, str):
            raise ValueError('Invalid transcript')
        emit(dict(kind='transcript', text=text, final=str(data.get('Final', 'true')).lower() == 'true',
                  speaker='Customer' if data.get('Track') == 'inbound_track' else 'Seller',
                  call=data.get('CallSid', ''), source='live'))
    else:
        emit(dict(kind='status', text=kind, call=data.get('CallSid', ''), source='live',
                  error=data.get('TranscriptionError', data.get('ErrorMessage', ''))))

def voice_xml():
    if not (PUBLIC.startswith('https://') and TOKEN and re.fullmatch(r'\+[1-9]\d{7,14}', SELLER)):
        raise ValueError('Set PUBLIC_BASE_URL (https), TWILIO_AUTH_TOKEN, and SELLER_PHONE (+countrycode).')
    root = Element('Response')
    SubElement(root, 'Say').text = 'This demo transcribes the call live. Please continue only if you agree.'
    start = SubElement(root, 'Start')
    SubElement(start, 'Transcription', statusCallbackUrl=PUBLIC + '/twilio/transcription',
               track='both_tracks', partialResults='true', languageCode='en-US',
               inboundTrackLabel='customer', outboundTrackLabel='seller')
    dial = SubElement(root, 'Dial', timeout='25', answerOnBridge='true')
    SubElement(dial, 'Number', url=PUBLIC + '/twilio/notice', method='POST').text = SELLER
    SubElement(root, 'Say').text = 'The call has ended.'
    return tostring(root, encoding='utf-8', xml_declaration=True)

def simulate():
    global RUNNING
    call = 'SIM-' + secrets.token_hex(3)
    emit(dict(kind='status', source='simulation', text='Simulation started — no phone audio', call=call))
    try:
        for speaker, sentence in [('Seller', 'Hi! What would you like to know about the product?'),
                                  ('Customer', 'That seems a little expensive.'),
                                  ('Seller', 'What budget did you have in mind?'),
                                  ('Customer', 'I need to ask my family first.')]:
            words = sentence.split()
            for n in range(2, len(words), 2):
                emit(dict(kind='transcript', source='simulation', speaker=speaker,
                          text=' '.join(words[:n]), final=False, call=call))
                time.sleep(.35)
            emit(dict(kind='transcript', source='simulation', speaker=speaker, text=sentence, final=True, call=call))
            time.sleep(.7)
        emit(dict(kind='status', source='simulation', text='Simulation finished', call=call))
    finally:
        RUNNING = False

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Do not log transcripts, phone numbers, or Authorization headers.

    def reply(self, code, body, mime='application/json'):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def auth(self):
        expected = 'Basic ' + base64.b64encode(('demo:' + ADMIN).encode()).decode()
        if hmac.compare_digest(self.headers.get('Authorization', ''), expected):
            return True
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="Local phone demo"')
        self.send_header('Content-Length', '0')
        self.end_headers()
        return False

    def do_GET(self):
        if not self.auth():
            return
        path = urlsplit(self.path).path
        if path == '/':
            return self.reply(200, (ROOT / 'index.html').read_bytes(), 'text/html; charset=utf-8')
        if path == '/api/state':
            with LOCK:
                events = list(EVENTS)
            provider = os.environ.get('DEMO_PROVIDER', 'twilio')
            configured = all(os.environ.get(k) for k in ['LIVEKIT_URL', 'LIVEKIT_API_KEY', 'LIVEKIT_API_SECRET']) if provider == 'livekit' else bool(PUBLIC and TOKEN and SELLER)
            return self.reply(200, dict(events=events, configured=configured, provider=provider, running=RUNNING))
        self.reply(404, dict(error='Not found'))

    def do_POST(self):
        global RUNNING
        path = urlsplit(self.path).path
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size < 0 or size > 65536:
                return self.reply(413, dict(error='Request too large'))
            raw = self.rfile.read(size)
            if path.startswith('/twilio/'):
                data = parse_qs(raw.decode(), keep_blank_values=True)
                # Exact public URL and all form values are required by Twilio signature verification.
                value = PUBLIC + self.path
                for key in sorted(data):
                    for item in sorted(set(data[key])):
                        value += key + item
                sig = base64.b64encode(hmac.new(TOKEN.encode(), value.encode(), hashlib.sha1).digest()).decode()
                if not TOKEN or not PUBLIC or not hmac.compare_digest(sig, self.headers.get('X-Twilio-Signature', '')):
                    return self.reply(403, dict(error='Invalid Twilio signature'))
                if path == '/twilio/voice':
                    emit(dict(kind='status', text='Incoming call; connecting seller', source='live', call=data.get('CallSid', [''])[0]))
                    return self.reply(200, voice_xml(), 'application/xml')
                if path == '/twilio/notice':
                    return self.reply(200, b'<Response><Say>This demo transcribes the call live. Hang up if you do not agree.</Say></Response>', 'application/xml')
                if path == '/twilio/transcription':
                    consume({k: v[0] for k, v in data.items()})
                    return self.reply(200, b'', 'text/plain')
                return self.reply(404, dict(error='Not found'))
            if not self.auth():
                return
            if self.headers.get('X-Demo-Action') != '1':
                return self.reply(403, dict(error='Missing action header'))
            if path == '/api/simulate':
                with LOCK:
                    if RUNNING:
                        return self.reply(409, dict(error='Simulation already running'))
                    RUNNING = True
                threading.Thread(target=simulate, daemon=True).start()
                return self.reply(200, dict(ok=True))
            if path == '/api/clear':
                with LOCK:
                    EVENTS.clear()
                return self.reply(200, dict(ok=True))
            self.reply(404, dict(error='Not found'))
        except (ValueError, UnicodeError, TypeError) as exc:
            self.reply(400, dict(error=str(exc)))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8765'))
    print(f'Open http://localhost:{port}\nUsername: demo\nPassword: {ADMIN}', flush=True)
    print('Local lab only. No phone call has been placed. Press Ctrl+C to stop.', flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
