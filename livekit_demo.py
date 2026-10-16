"""Receive remote telephone tracks, transcribe locally, show in the local UI.

No microphone, paid inference API, outgoing call, or cloud agent deployment.
"""
import asyncio
import os
import secrets
import signal
import threading
import time

import server

os.environ['DEMO_PROVIDER'] = 'livekit'


class ReceiverRegistry:
    """Only one receiver task per participant, even if subscription IDs change."""
    def __init__(self):
        self.active = {}

    def start(self, key, track_id, factory):
        existing = self.active.get(key)
        if existing and not existing[1].done():
            return None
        task = factory()
        self.active[key] = (track_id, task)
        return task

    def release(self, key, task):
        current = self.active.get(key)
        if current and current[1] is task:
            del self.active[key]

    def unsubscribe(self, key, track_id):
        current = self.active.get(key)
        if current and current[0] == track_id:
            current[1].cancel()


def status(text):
    server.emit(dict(kind='status', source='livekit', text=text, call=''))
    print(text, flush=True)


async def run():
    try:
        import numpy as np
        from livekit import api, rtc
        from faster_whisper import WhisperModel
    except ImportError:
        raise SystemExit('Install dependencies first: python3 -m pip install -r requirements-livekit.txt')

    required = ['LIVEKIT_URL', 'LIVEKIT_API_KEY', 'LIVEKIT_API_SECRET']
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise SystemExit('Fill these fields in .env: ' + ', '.join(missing))
    room_name = os.environ.get('LIVEKIT_ROOM', 'photon-demo')
    model_name = os.environ.get('WHISPER_MODEL', 'tiny.en')
    language = os.environ.get('TRANSCRIPT_LANGUAGE', 'en')
    port = int(os.environ.get('PORT', '8765'))
    try:
        http = server.ThreadingHTTPServer(('127.0.0.1', port), server.Handler)
    except OSError as exc:
        raise SystemExit(f'Cannot start local web server: {exc}. Stop the old server or change PORT.')
    threading.Thread(target=http.serve_forever, daemon=True).start()
    print(f'Open http://localhost:{port}\nUsername: demo\nPassword: {server.ADMIN}', flush=True)
    status('Loading local Whisper model. First run downloads free model weights; please wait.')
    try:
        model = await asyncio.to_thread(WhisperModel, model_name, device='cpu', compute_type='int8', cpu_threads=4)
    except Exception:
        http.shutdown()
        http.server_close()
        raise SystemExit('Model loading failed. Check internet access to Hugging Face, disk space, and Python dependencies.')

    room = rtc.Room()
    stop = asyncio.Event()
    tasks = set()
    queue = asyncio.Queue(maxsize=8)
    receivers = ReceiverRegistry()
    tone_requested = asyncio.Event()

    async def send_audio(source):
        """Publish generated audio so the room has an actual answering endpoint."""
        tone_frame = 0
        tone_total = 15
        clock = asyncio.get_running_loop()
        next_at = clock.time()
        while not stop.is_set():
            if tone_requested.is_set():
                tone_requested.clear()
                # Allow the new SIP participant time to subscribe to our track.
                tone_frame = -50
            samples = np.zeros(960, dtype=np.int16)
            if tone_frame < 0:
                tone_frame += 1
            elif tone_frame < tone_total:
                t = (np.arange(960) + tone_frame * 960) / 48000.0
                samples = (np.sin(2 * np.pi * 440 * t) * 2000).astype(np.int16)
                tone_frame += 1
            frame = rtc.AudioFrame(data=samples.tobytes(), sample_rate=48000,
                                   num_channels=1, samples_per_channel=960)
            await source.capture_frame(frame)
            next_at += .02
            await asyncio.sleep(max(0, next_at - clock.time()))

    def decode(audio):
        segments, _ = model.transcribe(audio, language=language, beam_size=1,
                                       condition_on_previous_text=False, vad_filter=True)
        return ' '.join(s.text.strip() for s in segments).strip()

    async def worker():
        while True:
            audio, identity, call = await queue.get()
            try:
                text = await asyncio.to_thread(decode, audio)
                if text:
                    server.emit(dict(kind='transcript', source='live', speaker='Caller ' + identity,
                                     text=text, final=True, call=call))
            except Exception:
                status('Local transcription failed for one audio chunk; inspect dependency/model setup.')
            finally:
                queue.task_done()

    def enqueue(chunks, identity, call):
        if not chunks:
            return
        audio = np.concatenate(chunks)
        rms = float(np.sqrt(np.mean(audio * audio)))
        if len(audio) < 4000 or rms < .0003:
            return
        # Amplify quiet telephone audio before the model's own voice detector.
        audio = np.clip(audio * min(20.0, .05 / max(rms, 1e-8)), -1.0, 1.0)
        try:
            queue.put_nowait((audio, identity, call))
        except asyncio.QueueFull:
            status('Transcriber behind: dropped an audio chunk. Try a smaller Whisper model.')

    async def receive(track, participant):
        identity = participant.identity
        call = participant.sid or identity
        stream = rtc.AudioStream(track, sample_rate=16000, num_channels=1)
        status('Telephone audio track subscribed. Speak a short sentence, then pause.')
        chunks = []
        count = 0
        silence = 0
        first = True
        last_meter = 0
        meter_peak = 0.0
        meter_energy = 0.0
        meter_samples = 0
        meter_nonzero = 0
        try:
            async for event in stream:
                audio = np.frombuffer(event.frame.data, dtype=np.int16).astype(np.float32) / 32768.0
                if first:
                    first = False
                    status('Audio frames received from LiveKit — this is actual remote audio, not microphone capture.')
                rms = float(np.sqrt(np.mean(audio * audio))) if len(audio) else 0
                meter_peak = max(meter_peak, float(np.max(np.abs(audio))) if len(audio) else 0)
                meter_energy += float(np.sum(audio * audio))
                meter_samples += len(audio)
                meter_nonzero += int(np.count_nonzero(audio))
                if time.monotonic() - last_meter > 5:
                    last_meter = time.monotonic()
                    avg = (meter_energy / max(1, meter_samples)) ** .5
                    status(f'Audio diagnostic: peak={meter_peak:.6f}, rms={avg:.6f}, nonzero={meter_nonzero}/{meter_samples}')
                    meter_peak, meter_energy, meter_samples, meter_nonzero = 0.0, 0.0, 0, 0
                if rms > .0003 or chunks:
                    chunks.append(audio)
                    count += len(audio)
                    silence = silence + len(audio) if rms < .0003 else 0
                if count >= 16000 * 5 or (count >= 8000 and silence >= 10000):
                    enqueue(chunks, identity, call)
                    chunks, count, silence = [], 0, 0
        finally:
            enqueue(chunks, identity, call)
            await stream.aclose()
            status('Remote audio track ended.')

    @room.on('track_subscribed')
    def subscribed(track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            key = participant.sid or participant.identity
            track_id = publication.sid or track.sid
            task = receivers.start(key, track_id, lambda: asyncio.create_task(receive(track, participant)))
            if task is None:
                return
            tasks.add(task)
            def done(t):
                tasks.discard(t)
                receivers.release(key, t)
                if not t.cancelled() and t.exception():
                    status('Audio receiver stopped unexpectedly; retry call or restart program.')
            task.add_done_callback(done)

    @room.on('track_unsubscribed')
    def unsubscribed(track, publication, participant):
        receivers.unsubscribe(participant.sid or participant.identity, publication.sid or track.sid)

    @room.on('disconnected')
    def disconnected(*args):
        status('Disconnected from LiveKit. Restart program to reconnect.')
        stop.set()

    @room.on('participant_connected')
    def participant_connected(participant):
        status('A remote participant joined the room.')
        sip_status = participant.attributes.get('sip.callStatus', 'not reported')
        status('SIP call status: ' + sip_status)
        tone_requested.set()

    @room.on('participant_attributes_changed')
    def attributes_changed(changed, participant):
        if 'sip.callStatus' in changed:
            status('SIP call status: ' + changed['sip.callStatus'])

    jwt = (api.AccessToken(os.environ['LIVEKIT_API_KEY'], os.environ['LIVEKIT_API_SECRET'])
           .with_identity('local-transcriber-' + secrets.token_hex(4))
           .with_grants(api.VideoGrants(room_join=True, room=room_name,
                                       can_subscribe=True, can_publish=True, can_publish_data=False))
           .to_jwt())
    worker_task = asyncio.create_task(worker())
    sender_task = None
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await room.connect(os.environ['LIVEKIT_URL'], jwt, options=rtc.RoomOptions(auto_subscribe=True))
        source = rtc.AudioSource(48000, 1)
        local_track = rtc.LocalAudioTrack.create_audio_track('generated-answer-audio', source)
        await room.local_participant.publish_track(local_track, rtc.TrackPublishOptions(dtx=False))
        sender_task = asyncio.create_task(send_audio(source))
        status('Generated answer audio published (no computer microphone). Caller should hear a short tone.')
        status('Connected to room ' + room_name + '. Now call your Photon number from iPhone.')
        await stop.wait()
    finally:
        if sender_task:
            sender_task.cancel()
            await asyncio.gather(sender_task, return_exceptions=True)
        for task in list(tasks):
            task.cancel()
        await asyncio.gather(*list(tasks), return_exceptions=True)
        try:
            await asyncio.wait_for(queue.join(), timeout=15)
        except asyncio.TimeoutError:
            pass
        worker_task.cancel()
        await asyncio.gather(worker_task, return_exceptions=True)
        await room.disconnect()
        http.shutdown()
        http.server_close()


if __name__ == '__main__':
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
