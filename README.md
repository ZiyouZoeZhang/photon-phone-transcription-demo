# Photon phone transcription demo

An iPhone calls a Photon number; Photon routes SIP into a LiveKit room; a local Python program transcribes the remote telephone audio using faster-whisper. The computer microphone is never captured. A generated audio track and short tone complete the answering side of the call.

## Baseline checkpoint

- Real Photon → LiveKit → local audio → transcript flow manually tested on macOS.
- Current English model: base.en, CPU/int8; tester-observed latency about 4 seconds.
- Recognition remains imperfect. Duplicate-subscription regression tests pass; retest on real calls after changes.
- Only a single caller is validated. Two-person bridging and sales-response generation are not implemented.

## Quick start

Python 3.11/3.12 recommended; original Mac used Python 3.13.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-livekit.txt
cp livekit.env.example .env
```

In .env, set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET and your own DEMO_PASSWORD. API keys must belong to the same project as the WebSocket URL. Keep LIVEKIT_ROOM=photon-demo to match the Direct dispatch rule.

```bash
python3 livekit_demo.py
```

Open http://localhost:8765; username demo, password from .env. Wait for Connected to room photon-demo, then call your Photon number and speak English. First run downloads free model weights. Pause at sentence boundaries. Export transcript downloads final text. Run text simulation is scripted text only.

## Cloud configuration

1. Photon beta: project → SMS number → Voice profile.
2. LiveKit: inbound SIP trunk accepting the Photon number, with SIP username/password authentication.
3. Photon inbound target: sip:+YOUR_PHOTON_NUMBER@YOUR_LIVEKIT_SIP_HOST; use the trunk credentials, not API keys.
4. LiveKit: Direct dispatch rule scoped to that trunk, destination photon-demo.
5. Start the local program before placing a test call.

## Integration

server.emit() receives actual recognized speech as:

```json
{"kind":"transcript","source":"live","speaker":"Caller <identity>","text":"That seems expensive.","final":true,"call":"<participant-sid>"}
```

emit() adds receivedAt (Unix seconds). Only final=true and source=live should feed the response agent. Text is a chunk result, not necessarily a complete sentence. call currently identifies a participant, not the carrier call ID. Labels do not infer seller/customer roles. The browser polls /api/state every 650ms with HTTP Basic authentication.

## Files

- livekit_demo.py: working RTC and local recognition path.
- server.py / index.html: local viewer, events, JSON export. server.py also retains an earlier Twilio alternative; it is unnecessary for LiveKit. Do not run both entry points at once.
- livekit.env.example: safe configuration template.
- requirements-tested.txt: installed top-level package versions, not a full lockfile.
- LIVEKIT-START.md: Chinese setup guide.
- docs/IMPROVEMENTS.md: next latency/accuracy experiments.

## Tests

```bash
python3 -m unittest -v test_server.py test_receivers.py
```

Offline tests cover signatures, callback parsing, simulation, receiver duplication/lifecycle. HTTP tests skip if sockets are forbidden. Speech quality, telephony and latency require real tests.

## Scope, privacy and cost

Local recognition needs no paid inference key. Photon beta and LiveKit Build have allowances: check remaining quota in the dashboards. Code enables no paid plan, automatic recharge, outgoing PSTN call, or paid inference. Carrier call charges still depend on your mobile plan.

Get agreement before transcribing. The generated tone is a connectivity test, not a spoken consent notice. Audio is not saved. Transcript history is in memory (1000 events max) until restart; export explicitly saves JSON. This is a single-user local development server, not production software. Keep .env, call recordings and transcripts out of Git.
