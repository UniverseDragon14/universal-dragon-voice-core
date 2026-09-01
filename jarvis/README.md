# EVE JARVIS - Voice Core

Voice-first personal AI for Nova-Pi (Raspberry Pi 5). Talk to it from phone or
laptop browser. It answers out loud in a real human voice, runs safe Pi
commands, searches the web, and reads/writes files inside a sandbox workspace.

Single-file Flask app. No database. No build step.

## What it does

- **Voice in** - browser Web Speech API (English / Tamil toggle)
- **Voice out** - edge-tts natural voices (default `en-US-AndrewNeural`)
- **Brain** - Groq first (fast, free tier), falls back to Moonshot (Kimi), then OpenAI
- **Tools by voice or text**:
  - `system status` - uptime, load, memory, disk, CPU temp
  - `search <anything>` - web search
  - `run <command>` - allowlisted safe commands only (ls, df, git status...)
  - `read file <name>` / `write file <name>: <content>` / `list files` - sandboxed to workspace
  - `time` / `date`

## Setup on Pi5

```bash
git clone https://github.com/UniverseDragon14/universal-dragon-voice-core.git ~/universal-dragon-voice-core
cd ~/universal-dragon-voice-core/jarvis
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Create the env file:

```bash
cat > ~/.jarvis.env <<'EOF'
JARVIS_TOKEN=change-me
GROQ_API_KEY=gsk_your_key_here
EVE_VOICE=en-US-AndrewNeural
EOF
```

Get a free Groq key at https://console.groq.com/keys
Optional fallbacks: `MOONSHOT_API_KEY`, `OPENAI_API_KEY`.

## Run

Foreground (testing):

```bash
cd ~/universal-dragon-voice-core/jarvis
.venv/bin/python3 eve_jarvis.py
```

As a user service:

```bash
mkdir -p ~/.config/systemd/user
cp jarvis.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now jarvis.service
systemctl --user status jarvis.service
```

Open `http://<pi-ip>:5066` (LAN) or the tunnel URL.

## Notes

- Microphone needs HTTPS in Chrome/Edge - use the Cloudflare tunnel URL
  (`https://jarvis.universaldragon.com`), not the LAN IP.
- Put Cloudflare Access (OTP) in front of the tunnel hostname for the real gate.
- Voices: `en-US-AndrewNeural` (warm male), `en-IN-PrabhatNeural` (Indian male),
  `en-GB-RyanNeural`, `ta-IN-ValluvarNeural` (Tamil). Set via `EVE_VOICE`.
- Safety: command runner has a hard allowlist + blocklist. No sudo, no rm,
  no network installs. File tools are jailed to `~/jarvis_workspace`.
- Port: `JARVIS_PORT` (default 5066).

## Env reference

| Var | Default | Purpose |
|---|---|---|
| `JARVIS_PORT` | 5066 | listen port |
| `JARVIS_TOKEN` | (empty = open!) | web UI login token |
| `EVE_VOICE` | en-US-AndrewNeural | edge-tts voice |
| `JARVIS_WORKSPACE` | ~/jarvis_workspace | file sandbox |
| `GROQ_API_KEY` | - | primary brain |
| `GROQ_MODEL` | openai/gpt-oss-120b | model |
| `MOONSHOT_API_KEY` | - | fallback brain |
| `MOONSHOT_MODEL` | kimi-k2-0905-preview | model |
| `OPENAI_API_KEY` | - | fallback brain |
| `OPENAI_MODEL` | gpt-4o-mini | model |
