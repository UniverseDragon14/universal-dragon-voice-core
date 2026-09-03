# Universal Dragon - Voice Core

Voice-first personal AI for Nova-Pi (Raspberry Pi 5). Say **"Hey Dragon"** or
**"Hey Nova"** - it wakes, listens, answers out loud in a real human voice,
runs safe Pi commands, searches the web, and reads/writes files inside a
sandbox workspace.

Single-file Flask app. No database. No build step.

## What it does

- **Wake word** - "Hey Dragon" / "Hey Nova" hands-free mode (browser tab stays open)
- **Voice in** - browser Web Speech API (English / Tamil toggle)
- **Voice out** - local Kokoro voice server (voice-soul v2, real human voice with mood) first; edge-tts fallback (default `en-US-AndrewNeural`)
- **Brain** - Groq first (fast, free tier), falls back to Moonshot (Kimi), then OpenAI
- **Tools by voice or text**:
  - `system status` - uptime, load, memory, disk, CPU temp
  - `search <anything>` - web search
  - `run <command>` - allowlisted safe commands only (ls, df, git status...)
  - `read file <name>` / `write file <name>: <content>` / `list files` - sandboxed to workspace
  - `time` / `date`

## Wake word mode

Tap **💤 wake word** in the top bar. The tab listens continuously. Say
**"Hey Dragon"** or **"Hey Nova"** - two beeps play, then speak your command.
You can also say it in one shot: "Hey Dragon, system status".

- Wake listening needs the tab open and (on phones) screen awake.
- Chrome/Edge + HTTPS required - use the tunnel URL.
- Wake words are matched in the browser transcript - no audio leaves the Pi
  except the normal speech-recognition stream to the browser engine.

## Setup on Pi5

```bash
git clone https://github.com/UniverseDragon14/universal-dragon-voice-core.git ~/universal-dragon-voice-core
cd ~/universal-dragon-voice-core/dragon
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Create the env file:

```bash
cat > ~/.dragon-voice.env <<'EOF'
DRAGON_TOKEN=change-me
GROQ_API_KEY=gsk_your_key_here
DRAGON_VOICE_TOKEN=your_local_voice_token
DRAGON_VOICE_PROFILE=dragon_deep
EOF
```

Get a free Groq key at https://console.groq.com/keys
Optional fallbacks: `MOONSHOT_API_KEY`, `OPENAI_API_KEY`.

## Run

Foreground (testing):

```bash
cd ~/universal-dragon-voice-core/dragon
.venv/bin/python3 dragon_voice.py
```

As a user service:

```bash
mkdir -p ~/.config/systemd/user
cp dragon-voice.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now dragon-voice.service
systemctl --user status dragon-voice.service
```

Open `http://<pi-ip>:5066` (LAN) or the tunnel URL.

## Notes

- Microphone needs HTTPS in Chrome/Edge - use the Cloudflare tunnel URL
  (`https://dragon.universaldragon.com`), not the LAN IP.
- Put Cloudflare Access (OTP) in front of the tunnel hostname for the real gate.
- Voices: `en-US-AndrewNeural` (warm male), `en-IN-PrabhatNeural` (Indian male),
  `en-GB-RyanNeural`, `ta-IN-ValluvarNeural` (Tamil). Set via `DRAGON_VOICE`.
- Safety: command runner has a hard allowlist + blocklist. No sudo, no rm,
  no network installs. File tools are jailed to `~/dragon_workspace`.
- Local voice: runs against the voice-soul v2 server on port 8124. If
  `DRAGON_VOICE_TOKEN` is set, `/healthz` reports `"local_voice": true` and
  replies come back as WAV from Kokoro; otherwise it silently uses edge-tts.
- Port: `DRAGON_PORT` (default 5066)

## Env reference

| Var | Default | Purpose |
|---|---|---|
| `DRAGON_PORT` | 5066 | listen port |
| `DRAGON_TOKEN` | (empty = open!) | web UI login token |
| `DRAGON_VOICE` | en-US-AndrewNeural | edge-tts fallback voice |
| `DRAGON_VOICE_TOKEN` | (empty = edge only) | local voice server bearer token |
| `DRAGON_LOCAL_VOICE_URL` | http://127.0.0.1:8124 | local voice server (voice-soul v2 / kokoro) |
| `DRAGON_VOICE_PROFILE` | dragon_deep | local voice profile |
| `DRAGON_VOICE_MOOD` | (auto) | local voice mood override |
| `DRAGON_TTS_ENGINE` | auto | `auto` = local first, edge fallback; `local` / `edge` force one |
| `DRAGON_WORKSPACE` | ~/dragon_workspace | file sandbox |
| `GROQ_API_KEY` | - | primary brain |
| `GROQ_MODEL` | openai/gpt-oss-120b | model |
| `MOONSHOT_API_KEY` | - | fallback brain |
| `MOONSHOT_MODEL` | kimi-k2-0905-preview | model |
| `OPENAI_API_KEY` | - | fallback brain |
| `OPENAI_MODEL` | gpt-4o-mini | model |
