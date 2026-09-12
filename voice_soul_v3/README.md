# NOVA Voice Soul v3

Review-first human-style TTS foundation for Universal Dragon / NOVA.

## Goal

Provide a consistent NOVA voice for English, Tamil and natural Tamil/English code-switching while keeping voice synthesis separate from command execution.

Target identity: `nova_young_female_v2` — youthful-adult, bright, warm, intelligent, Sri Lankan-Tamil-first with light South-Indian influence. This is a **style target**, not a claim of exact regional authenticity. Public recordings may inform general prosody analysis only; speaker-identity training requires original, licensed or clearly consented adult reference audio.

## Trust boundary

Voice Soul v3 is **TTS only**.

It does not:

- run shell commands
- control GPIO
- write user files
- send messages
- change accounts
- claim that external actions succeeded

Those capabilities, if added later, belong behind a separate permission + verification layer.

## Service

`server.py` exposes:

- `GET /healthz`
- `POST /v3/speak`

Default bind:

```text
127.0.0.1:8125
```

Optional bearer protection is configured with `NOVA_VOICE_TOKEN`.

## Routing

Current design:

- English -> Kokoro adapter
- Tamil -> IndicF5 adapter using consented NOVA reference recordings
- Mood/prosody shaping -> `emotion.py`

Supported moods:

`neutral`, `warm`, `confident`, `calm`, `happy`, `concerned`, `firm`, `whisper`

## Reference voice pack

Expected root:

```text
voice_soul_v3/voices/nova_female/
```

The intended pack can contain paired reference audio/text for each approved mood. Do not commit private or unlicensed recordings to a public repository.

## Hardware reality

Pi 5 is the local controller/orchestrator. Do not assume every high-quality neural TTS model will be responsive enough on Pi 5 itself. Kokoro is intended as the lighter route. IndicF5 may require an approved stronger inference host depending on measured latency and memory use. Treat runtime placement as **unverified until benchmarked on the actual hardware**.

## Conversation bridge

The public website should not call this TTS service directly. The intended path is:

```text
website -> authenticated NOVA Bridge :8130 -> brain -> Voice Soul v3 :8125
```

See `../nova_bridge/README.md`.

The bridge remains conversation-only and does not expose hardware or action tools.

## Development status

This work lives on the draft `nova-voice-soul-v3` branch / PR. Website integration is bridge-ready, but real Pi deployment, Tamil model runtime, regional-accent quality and end-to-end browser audio are not considered verified until tested on the actual deployment path.
