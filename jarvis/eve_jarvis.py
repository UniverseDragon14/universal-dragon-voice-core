#!/usr/bin/env python3
"""
EVE JARVIS - Voice Core for Nova-Pi
Single-file Flask app: browser voice UI (Web Speech ASR) + LLM brain router
+ edge-tts voice output + safe local tools.

Run:
    python3 eve_jarvis.py
Env:
    JARVIS_PORT       (default 5066)
    JARVIS_TOKEN      (login token for the web UI; empty = open, not recommended)
    EVE_VOICE         (edge-tts voice, default en-US-AndrewNeural)
    JARVIS_WORKSPACE  (file sandbox, default ~/jarvis_workspace)
    GROQ_API_KEY      (primary brain)
    GROQ_MODEL        (default openai/gpt-oss-120b)
    MOONSHOT_API_KEY  (fallback brain)
    MOONSHOT_MODEL    (default kimi-k2-0905-preview)
    OPENAI_API_KEY    (fallback brain)
    OPENAI_MODEL      (default gpt-4o-mini)
"""

import asyncio
import logging
import os
import re
import shlex
import subprocess
import threading
import time
import uuid
from pathlib import Path
from functools import wraps

import requests
from flask import Flask, jsonify, request, send_file, session

try:
    import edge_tts
    HAS_TTS = True
except Exception:
    HAS_TTS = False

# ---------------- config ----------------
PORT = int(os.environ.get("JARVIS_PORT", "5066"))
TOKEN = os.environ.get("JARVIS_TOKEN", "").strip()
VOICE = os.environ.get("EVE_VOICE", "en-US-AndrewNeural")
WORKSPACE = Path(os.environ.get("JARVIS_WORKSPACE", str(Path.home() / "jarvis_workspace"))).resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)
TTS_DIR = Path("/tmp/jarvis_tts")
TTS_DIR.mkdir(exist_ok=True)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
MOONSHOT_API_KEY = os.environ.get("MOONSHOT_API_KEY", "").strip()
MOONSHOT_MODEL = os.environ.get("MOONSHOT_MODEL", "kimi-k2-0905-preview")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

BRAIN_TIMEOUT = 45
HISTORY_MAX = 20
RUN_TIMEOUT = 15
MAX_OUT = 4000

logging.basicConfig(level=logging.INFO, format="[JARVIS] %(message)s")
log = logging.getLogger("jarvis")

app = Flask(__name__)
app.secret_key = os.urandom(32)

HISTORY = []
HLOCK = threading.Lock()

SYSTEM_PROMPT = (
    "You are JARVIS, the personal AI inside Nova-Pi, a Raspberry Pi 5 homelab "
    "run by Aslam (Universal Dragon). Speak like a loyal, sharp, slightly witty "
    "companion - natural spoken English or Tanglish if the user mixes Tamil. "
    "Keep replies SHORT (1-3 sentences) because they are spoken aloud. "
    "No markdown, no bullet lists, no emojis in replies. "
    "Call him Aslam or boss occasionally, not every line. "
    "If a tool output is given, summarize it naturally, do not read raw dumps. "
    "If you do not know something, say so straight."
)

# ---------------- auth ----------------

def require_auth(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not TOKEN:
            return fn(*a, **kw)
        if session.get("ok"):
            return fn(*a, **kw)
        if request.path.startswith("/api/"):
            return jsonify({"error": "auth required"}), 401
        return LOGIN_PAGE, 401
    return wrapper

# ---------------- safe tools ----------------
SAFE_PREFIXES = (
    "ls", "pwd", "whoami", "date", "uptime", "df", "free", "hostname",
    "vcgencmd", "ip a", "ip addr", "git status", "git log", "git diff",
    "systemctl status", "systemctl --user status", "systemctl --user list-units",
    "tailscale status", "docker ps", "pm2 list", "ps aux", "ss -",
    "cat /proc/cpuinfo", "cat /proc/meminfo", "sensors", "journalctl --user -n",
)
BLOCK_TOKENS = (
    "sudo", "rm ", "rm -", "mkfs", " dd ", "dd if", ":(){",
    "shutdown", "reboot", "poweroff", "halt", "kill ", "pkill", "killall",
    "chmod -r 777", "chown -r", "/etc/shadow", "curl |", "wget |",
    "| sh", "| bash", "> /", ">> /", "mv /", "apt ", "apt-", "pip install",
    "npm install", "passwd", "useradd", "userdel",
)

def _sh(cmd, timeout=RUN_TIMEOUT):
    try:
        p = subprocess.run(cmd if isinstance(cmd, list) else shlex.split(cmd),
                           capture_output=True, text=True, timeout=timeout)
        out = (p.stdout + p.stderr).strip()
        return out[:MAX_OUT] or "(no output)"
    except subprocess.TimeoutExpired:
        return "(timed out)"
    except Exception as e:
        return "(error: %s)" % e

def tool_status():
    parts = []
    parts.append("Uptime: " + _sh("uptime -p"))
    try:
        load = Path("/proc/loadavg").read_text().split()[:3]
        parts.append("Load: " + " ".join(load))
    except Exception:
        pass
    parts.append("Memory:\n" + _sh("free -h"))
    parts.append("Disk:\n" + _sh("df -h /"))
    temp = _sh("vcgencmd measure_temp")
    if "error" in temp or "(error" in temp:
        try:
            t = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()) / 1000.0
            temp = "temp=%.1f'C" % t
        except Exception:
            temp = "temp=unknown"
    parts.append("CPU: " + temp)
    return "\n".join(parts)

def tool_search(query):
    try:
        r = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
            timeout=10,
        )
        d = r.json()
        bits = []
        if d.get("AbstractText"):
            bits.append(d["AbstractText"])
        if d.get("Answer"):
            bits.append(d["Answer"])
        for t in (d.get("RelatedTopics") or [])[:3]:
            if isinstance(t, dict) and t.get("Text"):
                bits.append("- " + t["Text"])
        if bits:
            return "Search: %s\n%s" % (query, "\n".join(bits)[:MAX_OUT])
        return "Search: %s\n(no instant answer found)" % query
    except Exception as e:
        return "Search failed: %s" % e

def run_safe_command(cmd):
    low = " " + cmd.lower().strip() + " "
    for bad in BLOCK_TOKENS:
        if bad in low:
            return "Blocked for safety: %s" % cmd
    if not cmd.lower().strip().startswith(SAFE_PREFIXES):
        return "Not in allowlist. Allowed: " + ", ".join(SAFE_PREFIXES[:8]) + " ..."
    return _sh(cmd)

def _safe_path(name):
    name = name.strip().lstrip("/")
    p = (WORKSPACE / name).resolve()
    if not str(p).startswith(str(WORKSPACE)):
        return None
    return p

def tool_read_file(name):
    p = _safe_path(name)
    if not p or not p.is_file():
        return "File not found in workspace: %s" % name
    try:
        return "%s:\n%s" % (p.name, p.read_text(errors="replace")[:8000])
    except Exception as e:
        return "Read error: %s" % e

def tool_write_file(name, content):
    p = _safe_path(name)
    if not p:
        return "Bad path."
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content[:100000])
        return "Wrote %d bytes to %s" % (len(content), p.name)
    except Exception as e:
        return "Write error: %s" % e

def tool_list_files():
    try:
        items = []
        for p in sorted(WORKSPACE.rglob("*"))[:80]:
            rel = p.relative_to(WORKSPACE)
            items.append(("/ " if p.is_dir() else "  ") + str(rel))
        return "Workspace %s:\n%s" % (WORKSPACE, "\n".join(items) or "(empty)")
    except Exception as e:
        return "List error: %s" % e

RE_STATUS = re.compile(r"\b(pi5?|system|server|cpu|memory|disk)\s+(status|health|stats)\b|\bhow('s| is) the (pi|server|system)\b", re.I)
RE_TEMP = re.compile(r"\b(pi\s+)?(temperature|temp|overheat|throttl)", re.I)
RE_SEARCH = re.compile(r"^(search|google|find|look ?up|deep ?search|research)\s+(?:for\s+|about\s+)?(.+)$", re.I | re.S)
RE_RUN = re.compile(r"^(run|execute|cmd|command)\s+(.+)$", re.I | re.S)
RE_READ = re.compile(r"^(read|open|show)\s+(?:file\s+)?([\w./-]+)$", re.I)
RE_WRITE = re.compile(r"^write\s+(?:file\s+)?([\w./-]+)\s*:\s*(.+)$", re.I | re.S)
RE_LS = re.compile(r"^(list|ls)\s*(files|workspace)?\s*$", re.I)
RE_TIME = re.compile(r"^(what'?s|what is|tell me|current)?\s*(the\s+)?(time|date|today'?s date|day)\??\s*$", re.I)

def route_intent(text):
    t = text.strip()
    m = RE_STATUS.search(t)
    if m:
        return "status", tool_status()
    if RE_TEMP.search(t):
        return "status", tool_status()
    m = RE_SEARCH.match(t)
    if m:
        return "search", tool_search(m.group(2).strip())
    m = RE_RUN.match(t)
    if m:
        return "run", run_safe_command(m.group(2).strip())
    m = RE_READ.match(t)
    if m:
        return "read", tool_read_file(m.group(2))
    m = RE_WRITE.match(t)
    if m:
        return "write", tool_write_file(m.group(1), m.group(2))
    if RE_LS.match(t):
        return "ls", tool_list_files()
    if RE_TIME.match(t):
        return "time", time.strftime("It is %I:%M %p, %A %d %B %Y.")
    return None, None

# ---------------- brain ----------------

def _chat_openai_style(base, key, model, messages):
    r = requests.post(
        base.rstrip("/") + "/chat/completions",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "temperature": 0.6, "max_tokens": 400},
        timeout=BRAIN_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

def brain_reply(user_text, tool_note=None):
    content = user_text
    if tool_note:
        content = (user_text +
                   "\n\n[Live tool output from Nova-Pi - summarize naturally, do not read raw dumps]\n" +
                   tool_note)
    with HLOCK:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + HISTORY[-HISTORY_MAX:] + [
            {"role": "user", "content": content}]
    providers = []
    if GROQ_API_KEY:
        providers.append(("groq", "https://api.groq.com/openai/v1", GROQ_API_KEY, GROQ_MODEL))
    if MOONSHOT_API_KEY:
        providers.append(("moonshot", "https://api.moonshot.ai/v1", MOONSHOT_API_KEY, MOONSHOT_MODEL))
    if OPENAI_API_KEY:
        providers.append(("openai", "https://api.openai.com/v1", OPENAI_API_KEY, OPENAI_MODEL))
    if not providers:
        return None, "none"
    for name, base, key, model in providers:
        try:
            out = _chat_openai_style(base, key, model, msgs)
            with HLOCK:
                HISTORY.append({"role": "user", "content": user_text})
                HISTORY.append({"role": "assistant", "content": out})
                del HISTORY[:-HISTORY_MAX]
            return out, name
        except Exception as e:
            log.warning("brain %s failed: %s", name, e)
            continue
    return None, "all_failed"

# ---------------- tts ----------------

def tts_make(text):
    if not HAS_TTS:
        return None
    clean = re.sub(r"[*_`#>\[\]()]", " ", text).strip()
    if not clean:
        return None
    fname = uuid.uuid4().hex + ".mp3"
    fpath = TTS_DIR / fname
    try:
        asyncio.run(edge_tts.Communicate(clean, VOICE).save(str(fpath)))
        return fname if fpath.exists() and fpath.stat().st_size > 0 else None
    except Exception as e:
        log.warning("tts failed: %s", e)
        return None

def tts_cleanup():
    now = time.time()
    for p in TTS_DIR.glob("*.mp3"):
        try:
            if now - p.stat().st_mtime > 3600:
                p.unlink()
        except Exception:
            pass

# ---------------- web UI ----------------
LOGIN_PAGE = """<!doctype html><html><head><meta name=viewport content="width=device-width,initial-scale=1">
<title>JARVIS Login</title><style>
body{background:#0a0c10;color:#e8e8ea;font-family:system-ui;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{background:#12151c;border:1px solid #232a38;border-radius:16px;padding:32px;width:320px;text-align:center}
h1{font-size:20px;letter-spacing:3px;color:#f5b942;margin:0 0 18px}
input{width:100%;padding:12px;border-radius:10px;border:1px solid #2a3140;background:#0d1016;color:#fff;box-sizing:border-box;margin-bottom:12px}
button{width:100%;padding:12px;border:0;border-radius:10px;background:#f5b942;color:#111;font-weight:700;cursor:pointer}
.err{color:#ff6b6b;font-size:13px;margin-top:10px}
</style></head><body><form class=card method=post action=/login>
<h1>E V E · J A R V I S</h1>
<input name=token type=password placeholder="Access token" autofocus>
<button>Enter</button>__ERR__
</form></body></html>"""

UI_PAGE = """<!doctype html><html><head><meta name=viewport content="width=device-width,initial-scale=1,maximum-scale=1">
<title>EVE JARVIS</title><style>
:root{--amber:#f5b942;--bg:#0a0c10;--panel:#12151c;--line:#232a38;--txt:#e8e8ea}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font-family:system-ui,-apple-system,sans-serif;height:100vh;display:flex;flex-direction:column}
header{padding:12px 16px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:10px;background:var(--panel)}
.dot{width:10px;height:10px;border-radius:50%;background:#37d67a;box-shadow:0 0 8px #37d67a}
h1{font-size:15px;letter-spacing:4px;margin:0;color:var(--amber)}
#brain{margin-left:auto;font-size:11px;color:#8a93a5}
#chat{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px}
.msg{max-width:85%;padding:10px 14px;border-radius:14px;line-height:1.45;font-size:15px;white-space:pre-wrap}
.me{align-self:flex-end;background:#1c2740;border:1px solid #2a3a5f;border-bottom-right-radius:4px}
.ai{align-self:flex-start;background:var(--panel);border:1px solid var(--line);border-bottom-left-radius:4px}
.ai b{color:var(--amber)}
#controls{padding:14px;border-top:1px solid var(--line);background:var(--panel);display:flex;gap:10px;align-items:center}
#mic{width:64px;height:64px;border-radius:50%;border:2px solid var(--amber);background:#181207;color:var(--amber);font-size:26px;cursor:pointer;flex:none;transition:.2s}
#mic.on{background:var(--amber);color:#111;animation:pulse 1.2s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(245,185,66,.5)}70%{box-shadow:0 0 0 18px rgba(245,185,66,0)}100%{box-shadow:0 0 0 0 rgba(245,185,66,0)}}
#text{flex:1;padding:12px 14px;border-radius:12px;border:1px solid #2a3140;background:#0d1016;color:#fff;font-size:15px}
#send{padding:12px 16px;border-radius:12px;border:0;background:var(--amber);color:#111;font-weight:700;cursor:pointer}
#hint{text-align:center;font-size:11px;color:#5c6575;padding:6px}
#langbar{display:flex;gap:6px;padding:8px 14px 0;background:var(--panel)}
.lang{font-size:11px;padding:4px 10px;border-radius:20px;border:1px solid var(--line);background:transparent;color:#8a93a5;cursor:pointer}
.lang.sel{border-color:var(--amber);color:var(--amber)}
</style></head><body>
<header><div class=dot></div><h1>E V E · J A R V I S</h1><span id=brain>...</span></header>
<div id=langbar>
<button class="lang sel" data-l="en-IN">EN</button>
<button class="lang" data-l="ta-IN">தமிழ்</button>
<button class=lang id=vmute>🔊 voice on</button>
<button class=lang id=wakebtn>💤 wake word</button>
</div>
<div id=chat></div>
<div id=hint>tap the mic and talk — or type below</div>
<div id=controls>
<button id=mic>🎙</button>
<input id=text placeholder="type a command... (search ..., run ls, system status)">
<button id=send>➤</button>
</div>
<script>
const chat=document.getElementById('chat'),mic=document.getElementById('mic'),
text=document.getElementById('text'),send=document.getElementById('send'),
hint=document.getElementById('hint'),wakebtn=document.getElementById('wakebtn');
let lang='en-IN',voiceOn=true,listening=false,rec=null;
let wakeMode=false,awake=false,awakeTimer=null;
const WAKE_WORDS=['hey dragon','hey nova','ok dragon','hey jarvis'];
fetch('/healthz').then(r=>r.json()).then(j=>{document.getElementById('brain').textContent='brain: '+j.brain+(j.tts?' · voice: on':' · voice: off')}).catch(()=>{});
document.querySelectorAll('.lang[data-l]').forEach(b=>b.onclick=()=>{document.querySelectorAll('.lang[data-l]').forEach(x=>x.classList.remove('sel'));b.classList.add('sel');lang=b.dataset.l});
document.getElementById('vmute').onclick=e=>{voiceOn=!voiceOn;e.target.textContent=voiceOn?'🔊 voice on':'🔇 voice off';e.target.classList.toggle('sel',voiceOn)};
function bubble(t,who){const d=document.createElement('div');d.className='msg '+who;d.textContent=t;chat.appendChild(d);chat.scrollTop=chat.scrollHeight;return d}
function play(url){if(!url||!voiceOn)return;const a=new Audio(url);a.play().catch(()=>{})}
let actx=null;
function beep(f,d){try{actx=actx||new (window.AudioContext||window.webkitAudioContext)();const o=actx.createOscillator(),g=actx.createGain();o.frequency.value=f||880;o.type='sine';o.connect(g);g.connect(actx.destination);g.gain.setValueAtTime(0.18,actx.currentTime);g.gain.exponentialRampToValueAtTime(0.001,actx.currentTime+(d||0.18));o.start();o.stop(actx.currentTime+(d||0.18));}catch(e){}}
async function ask(q){
 if(!q)return; bubble(q,'me'); const w=bubble('…','ai');
 try{
  const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:q})});
  const j=await r.json(); w.textContent=j.reply||j.error||'(no reply)'; play(j.audio);
 }catch(e){w.textContent='network error';}
}
send.onclick=()=>{const q=text.value.trim();text.value='';ask(q)};
text.addEventListener('keydown',e=>{if(e.key==='Enter')send.onclick()});
function heard(t){
 const low=t.toLowerCase();
 if(wakeMode&&!awake){
  let hit=null;
  for(const w of WAKE_WORDS){if(low.includes(w)){hit=w;break}}
  if(!hit){hint.textContent="💤 sleeping — say 'Hey Dragon'";return}
  awake=true;beep(880,0.15);setTimeout(()=>beep(1320,0.15),160);
  mic.classList.add('on');hint.textContent='🐉 yes boss? listening...';
  clearTimeout(awakeTimer);
  awakeTimer=setTimeout(()=>{awake=false;mic.classList.remove('on');hint.textContent="💤 sleeping — say 'Hey Dragon'"},9000);
  const cmd=low.split(hit)[1].trim();
  if(cmd){clearTimeout(awakeTimer);awake=false;mic.classList.remove('on');hint.textContent="💤 sleeping — say 'Hey Dragon'";ask(t.slice(low.indexOf(hit)+hit.length).trim())}
  return;
 }
 if(wakeMode&&awake){
  awake=false;mic.classList.remove('on');clearTimeout(awakeTimer);
  hint.textContent="💤 sleeping — say 'Hey Dragon'";ask(t);return;
 }
 ask(t);
}
const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
if(SR){
 rec=new SR();rec.lang=lang;rec.interimResults=false;rec.maxAlternatives=1;rec.continuous=false;
 rec.onresult=e=>{heard(e.results[0][0].transcript)};
 rec.onend=()=>{listening=false;if(!wakeMode)mic.classList.remove('on');if(wakeMode){try{rec.start();listening=true}catch(e){}}};
 rec.onerror=()=>{listening=false;if(!wakeMode)mic.classList.remove('on')};
}
wakebtn.onclick=()=>{
 if(!rec){alert('Wake word needs Chrome/Edge over HTTPS (use the tunnel URL)');return}
 wakeMode=!wakeMode;wakebtn.classList.toggle('sel',wakeMode);
 wakebtn.textContent=wakeMode?'🐉 wake: ON':'💤 wake word';
 if(wakeMode){awake=false;try{rec.lang=lang;rec.start();listening=true;mic.classList.add('on')}catch(e){}
  hint.textContent="💤 sleeping — say 'Hey Dragon'";bubble('Wake mode on. Say "Hey Dragon" anytime, boss.','ai')}
 else{awake=false;clearTimeout(awakeTimer);try{rec.stop()}catch(e){}mic.classList.remove('on');hint.textContent='tap the mic and talk — or type below'}
};
mic.onclick=()=>{
 if(!rec){alert('Speech recognition needs Chrome/Edge over HTTPS (use the tunnel URL)');return}
 if(wakeMode){if(awake){awake=false;mic.classList.remove('on');hint.textContent="💤 sleeping — say 'Hey Dragon'"}return}
 if(listening){rec.stop();return}
 rec.lang=lang;try{rec.start();listening=true;mic.classList.add('on')}catch(e){}
};
bubble('JARVIS online. Say the word, boss.','ai');
</script></body></html>"""

# ---------------- routes ----------------
@app.route("/login", methods=["POST"])
def login():
    if TOKEN and request.form.get("token", "") == TOKEN:
        session["ok"] = True
        return UI_PAGE
    page = LOGIN_PAGE.replace("__ERR__", '<div class=err>wrong token</div>')
    return page, 401

@app.route("/")
@require_auth
def index():
    return UI_PAGE

@app.route("/healthz")
def healthz():
    brain = "groq" if GROQ_API_KEY else ("moonshot" if MOONSHOT_API_KEY else ("openai" if OPENAI_API_KEY else "none"))
    return jsonify({"ok": True, "brain": brain, "tts": HAS_TTS, "voice": VOICE, "port": PORT})

@app.route("/api/chat", methods=["POST"])
@require_auth
def api_chat():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "empty"}), 400
    tool, result = route_intent(text)
    reply, provider = brain_reply(text, tool_note=result)
    if reply is None:
        if result:
            reply = result if len(result) < 600 else result[:600] + " ..."
        elif provider == "none":
            reply = "No brain key set. Add GROQ_API_KEY to the env file and restart me, boss."
        else:
            reply = "All brains are unreachable right now. Check the internet on the Pi."
    audio = tts_make(reply)
    threading.Thread(target=tts_cleanup, daemon=True).start()
    return jsonify({"reply": reply, "audio": ("/api/tts/" + audio) if audio else None,
                    "tool": tool, "brain": provider})

@app.route("/api/tts/<fname>")
@require_auth
def api_tts(fname):
    if not re.fullmatch(r"[a-f0-9]{32}\.mp3", fname):
        return "nope", 404
    p = TTS_DIR / fname
    if not p.exists():
        return "gone", 404
    return send_file(str(p), mimetype="audio/mpeg")

if __name__ == "__main__":
    log.info("port=%s token=%s tts=%s voice=%s", PORT, "set" if TOKEN else "OPEN", HAS_TTS, VOICE)
    log.info("workspace=%s", WORKSPACE)
    app.run(host="127.0.0.1", port=PORT, threaded=True)
