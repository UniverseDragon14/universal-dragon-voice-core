# NOVA Voice Soul v3

NOVA Voice Soul v3 is the Universal Dragon human-style TTS layer. It is designed for expressive, permission-aware NOVA speech without depending on a single commercial TTS provider.

## Goals

- Natural, human-like voice output
- One consistent NOVA voice identity
- English + Tamil routing
- Emotion/prosody control: neutral, warm, confident, calm, happy, concerned, firm, whisper
- Local-first where practical
- Raspberry Pi 5 as orchestration/runtime controller
- No silent sensitive actions: this service only synthesizes speech
- Streaming-friendly WAV responses
- No voice cloning without clear permission from the voice owner

## Engine strategy

### English — Kokoro
Kokoro is the lightweight local engine. It is suitable as the fast path for English and can run without a large GPU. Voice Soul v3 controls speed and post-processing around the model.

### Tamil — IndicF5
IndicF5 is the high-quality Tamil path. It uses a consented reference voice clip plus its transcript to preserve speaker identity and prosody. Keep several NOVA reference clips for different moods so Tamil output can remain expressive.

IndicF5 can be heavy for a Raspberry Pi 5 CPU. In production, Pi 5 should orchestrate it while the heavy model runs on an approved GPU machine or optimized inference host. The API surface stays the same.

## Voice identity pack

Create a licensed/consented NOVA voice pack:

```
voice_soul_v3/voices/nova_female/
  neutral.wav
  neutral.txt
  warm.wav
  warm.txt
  confident.wav
  confident.txt
  calm.wav
  calm.txt
  happy.wav
  happy.txt
  concerned.wav
  concerned.txt
  firm.wav
  firm.txt
  whisper.wav
  whisper.txt
```

Recommended recordings: clean mono WAV, quiet room, no music, no effects, natural delivery. Use the same consenting speaker for every mood.

## API

### `GET /healthz`
Returns loaded engines and runtime status.

### `POST /v3/speak`

```json
{
  "text": "Aslam, NOVA is ready.",
  "language": "auto",
  "mood": "auto",
  "intensity": 0.72,
  "engine": "auto"
}
```

Response: `audio/wav` with headers describing selected engine, mood and language.

## Install

Create a separate environment so this does not disturb the current Dragon Voice service.

```bash
cd ~/universal-dragon-voice-core/voice_soul_v3
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Kokoro is optional but recommended for the English local path. IndicF5 is optional and should normally live on a stronger inference machine for near-human Tamil.

## Run

```bash
export NOVA_VOICE_HOST=127.0.0.1
export NOVA_VOICE_PORT=8125
.venv/bin/python3 server.py
```

## Security boundary

This service is TTS-only. It does not execute shell commands, control GPIO, send messages, or access files. Action permission and execution remain in the NOVA/Dragon control layer. Voice generation is never proof that an external action succeeded.
