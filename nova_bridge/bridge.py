from __future__ import annotations

import asyncio
import hmac
import os
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

import requests
import uvicorn

try:
    import edge_tts
except Exception:
    edge_tts = None
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

HOST = os.environ.get("NOVA_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("NOVA_BRIDGE_PORT", "8130"))

ALLOWED_ORIGINS = [
    x.strip()
    for x in os.environ.get(
        "NOVA_ALLOWED_ORIGINS",
        "https://voice.universaldragon.com,https://project28268.websitepublisher.ai",
    ).split(",")
    if x.strip()
]
REQUIRE_CF_ACCESS = os.environ.get("NOVA_REQUIRE_CF_ACCESS", "1").lower() not in {
    "0", "false", "no"
}
BRIDGE_TOKEN = os.environ.get("NOVA_BRIDGE_TOKEN", "").strip()

VOICE_URL = os.environ.get("NOVA_VOICE_URL", "http://127.0.0.1:8125").rstrip("/")
VOICE_TOKEN = (os.environ.get("NOVA_VOICE_TOKEN") or os.environ.get("DRAGON_VOICE_TOKEN", "")).strip()
VOICE_TIMEOUT = float(os.environ.get("NOVA_VOICE_TIMEOUT", "90"))
EDGE_TTS_ENABLED = os.environ.get("NOVA_EDGE_TTS_ENABLED", "1").lower() not in {"0", "false", "no"}
EDGE_TAMIL_VOICE = os.environ.get("NOVA_EDGE_TAMIL_VOICE", "ta-IN-PallaviNeural")
EDGE_ENGLISH_VOICE = os.environ.get("NOVA_EDGE_ENGLISH_VOICE", "en-IN-NeerjaExpressiveNeural")
EDGE_RATE = os.environ.get("NOVA_EDGE_RATE", "+4%")
V2_VOICE_URL = os.environ.get("NOVA_V2_VOICE_URL", "http://127.0.0.1:8124").rstrip("/")
V2_VOICE_TOKEN = (os.environ.get("NOVA_V2_VOICE_TOKEN") or os.environ.get("DRAGON_VOICE_TOKEN", "")).strip()
V2_VOICE_PROFILE = os.environ.get("NOVA_V2_VOICE_PROFILE", "nova_warm").strip() or "nova_warm"

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
MOONSHOT_API_KEY = os.environ.get("MOONSHOT_API_KEY", "").strip()
MOONSHOT_MODEL = os.environ.get("MOONSHOT_MODEL", "kimi-k2-0905-preview")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
BRAIN_TIMEOUT = float(os.environ.get("NOVA_BRAIN_TIMEOUT", "45"))

MAX_TEXT = int(os.environ.get("NOVA_BRIDGE_MAX_TEXT", "2000"))
MAX_HISTORY_MESSAGES = int(os.environ.get("NOVA_BRIDGE_HISTORY", "12"))
RATE_LIMIT_PER_MINUTE = int(os.environ.get("NOVA_BRIDGE_RATE", "30"))
AUDIO_TTL_SECONDS = int(os.environ.get("NOVA_AUDIO_TTL", "300"))
AUDIO_DIR = Path(os.environ.get("NOVA_AUDIO_DIR", str(Path(__file__).resolve().parent / "runtime_audio")))
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_PROMPT = """You are NOVA, the calm intelligent voice of Universal Dragon.
Reply for spoken conversation, normally 1 to 3 short sentences.
Use natural Tamil or Tanglish when the user uses Tamil; otherwise use clear English.
Your style is warm, youthful-adult, confident, concise and natural.
Do not use markdown, bullet lists or emojis in spoken replies.
Do not claim that a real-world action, shell command, GPIO action, message, file write,
or account change happened. This bridge is conversation-only.
If an action would be needed, explain that approval/execution must happen through the
trusted NOVA action layer and that the result must be verified separately."""

app = FastAPI(title="NOVA Secure Conversation Bridge", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-NOVA-Session"],
)

_history: dict[str, deque[dict[str, str]]] = defaultdict(
    lambda: deque(maxlen=MAX_HISTORY_MESSAGES)
)
_history_lock = threading.Lock()
_rate: dict[str, deque[float]] = defaultdict(deque)
_rate_lock = threading.Lock()


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    session_id: str | None = Field(default=None, max_length=80)
    language: str = Field(default="auto", max_length=16)
    mood: str = Field(default="auto", max_length=24)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("text cannot be blank")
        return value

    @field_validator("session_id")
    @classmethod
    def clean_session(cls, value: str | None) -> str | None:
        if not value:
            return None
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", value):
            raise ValueError("invalid session_id")
        return value



def _origin_ok(origin: str | None) -> bool:
    if not origin:
        return False
    return origin.rstrip("/") in {x.rstrip("/") for x in ALLOWED_ORIGINS}


def _bearer_ok(authorization: str | None) -> bool:
    if not BRIDGE_TOKEN:
        return False
    expected = f"Bearer {BRIDGE_TOKEN}"
    return bool(authorization and hmac.compare_digest(authorization, expected))


def _authorize_request(request: Request, authorization: str | None) -> str:
    origin = request.headers.get("origin")
    if origin and not _origin_ok(origin):
        raise HTTPException(status_code=403, detail="origin not allowed")

    cf_user = (request.headers.get("cf-access-authenticated-user-email") or "").strip()
    if REQUIRE_CF_ACCESS:
        if not cf_user and not _bearer_ok(authorization):
            raise HTTPException(status_code=401, detail="Cloudflare Access required")
    elif not origin and not _bearer_ok(authorization):
        # Local browser requests have Origin. Non-browser clients need a token.
        raise HTTPException(status_code=401, detail="authorization required")

    return cf_user or request.client.host if request.client else "local"


def _rate_limit(identity: str) -> None:
    now = time.time()
    cutoff = now - 60.0
    with _rate_lock:
        q = _rate[identity]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= RATE_LIMIT_PER_MINUTE:
            raise HTTPException(status_code=429, detail="rate limit exceeded")
        q.append(now)


def _providers():
    out = []
    if GROQ_API_KEY:
        out.append(("groq", "https://api.groq.com/openai/v1", GROQ_API_KEY, GROQ_MODEL))
    if MOONSHOT_API_KEY:
        out.append(("moonshot", "https://api.moonshot.ai/v1", MOONSHOT_API_KEY, MOONSHOT_MODEL))
    if OPENAI_API_KEY:
        out.append(("openai", "https://api.openai.com/v1", OPENAI_API_KEY, OPENAI_MODEL))
    return out


def _chat_provider(base: str, key: str, model: str, messages: list[dict[str, str]]) -> str:
    r = requests.post(
        base.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": messages,
            "temperature": 0.65,
            "max_tokens": 350,
        },
        timeout=BRAIN_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _brain_reply(session_id: str, text: str) -> tuple[str, str]:
    providers = _providers()
    if not providers:
        raise HTTPException(status_code=503, detail="no NOVA brain provider configured")

    with _history_lock:
        history = list(_history[session_id])
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history + [
        {"role": "user", "content": text}
    ]

    last_error = "unavailable"
    for name, base, key, model in providers:
        try:
            reply = _chat_provider(base, key, model, messages)
            with _history_lock:
                _history[session_id].append({"role": "user", "content": text})
                _history[session_id].append({"role": "assistant", "content": reply})
            return reply, name
        except Exception as exc:
            last_error = f"{name}: {exc.__class__.__name__}"
    raise HTTPException(status_code=503, detail=f"NOVA brain unavailable ({last_error})")


def _cleanup_audio() -> None:
    cutoff = time.time() - AUDIO_TTL_SECONDS
    for pattern in ("*.wav", "*.mp3"):
        for p in AUDIO_DIR.glob(pattern):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
            except OSError:
                pass


def _has_tamil(text: str) -> bool:
    return bool(re.search(r"[\u0B80-\u0BFF]", text))


def _voice_v3(reply: str, language: str, mood: str) -> tuple[str | None, dict[str, str]]:
    headers = {"Content-Type": "application/json"}
    if VOICE_TOKEN:
        headers["Authorization"] = f"Bearer {VOICE_TOKEN}"
    try:
        r = requests.post(
            VOICE_URL + "/v3/speak",
            headers=headers,
            json={
                "text": reply[:1600],
                "language": language if language in {"auto", "en", "ta"} else "auto",
                "mood": mood if mood in {
                    "auto", "neutral", "warm", "confident", "calm", "happy",
                    "concerned", "firm", "whisper"
                } else "auto",
                "intensity": 0.72,
                "engine": "auto",
            },
            timeout=VOICE_TIMEOUT,
        )
        if r.status_code != 200 or r.content[:4] != b"RIFF":
            return None, {"status": f"http_{r.status_code}"}
        name = uuid.uuid4().hex + ".wav"
        (AUDIO_DIR / name).write_bytes(r.content)
        return f"/v1/audio/{name}", {
            "status": "ok",
            "engine": r.headers.get("X-NOVA-Voice-Engine", "unknown"),
            "mood": r.headers.get("X-NOVA-Voice-Mood", "unknown"),
            "language": r.headers.get("X-NOVA-Voice-Language", "unknown"),
        }
    except Exception as exc:
        return None, {"status": f"unavailable:{exc.__class__.__name__}"}


async def _edge_save(text: str, voice: str, out: Path) -> None:
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=EDGE_RATE)
    await communicate.save(str(out))


def _voice_edge(reply: str) -> tuple[str | None, dict[str, str]]:
    if not EDGE_TTS_ENABLED or edge_tts is None:
        return None, {"status": "disabled" if not EDGE_TTS_ENABLED else "unavailable"}
    tamil = _has_tamil(reply)
    voice = EDGE_TAMIL_VOICE if tamil else EDGE_ENGLISH_VOICE
    name = uuid.uuid4().hex + ".mp3"
    path = AUDIO_DIR / name
    try:
        asyncio.run(_edge_save(reply[:1600], voice, path))
        if not path.is_file() or path.stat().st_size < 256:
            raise RuntimeError("empty edge audio")
        return f"/v1/audio/{name}", {
            "status": "ok",
            "engine": "edge-tts",
            "voice": voice,
            "language": "ta" if tamil else "en-IN",
        }
    except Exception as exc:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None, {"status": f"unavailable:{exc.__class__.__name__}"}


def _voice_v2(reply: str) -> tuple[str | None, dict[str, str]]:
    if _has_tamil(reply):
        return None, {"status": "unsupported_tamil_script"}
    headers = {"Content-Type": "application/json"}
    if V2_VOICE_TOKEN:
        headers["Authorization"] = f"Bearer {V2_VOICE_TOKEN}"
    try:
        r = requests.post(
            V2_VOICE_URL + "/v2/speak",
            headers=headers,
            json={
                "text": reply[:1200],
                "profile": V2_VOICE_PROFILE,
                "mood": "warm",
                "context": "chat",
                "engine": "auto",
                "intensity": 0.65,
            },
            timeout=VOICE_TIMEOUT,
        )
        if r.status_code != 200 or r.content[:4] != b"RIFF":
            return None, {"status": f"http_{r.status_code}"}
        name = uuid.uuid4().hex + ".wav"
        (AUDIO_DIR / name).write_bytes(r.content)
        return f"/v1/audio/{name}", {
            "status": "ok",
            "engine": r.headers.get("X-Dragon-Voice-Engine", "voice-soul-v2"),
            "profile": r.headers.get("X-Dragon-Voice-Profile", V2_VOICE_PROFILE),
            "language": "en",
        }
    except Exception as exc:
        return None, {"status": f"unavailable:{exc.__class__.__name__}"}


def _voice(reply: str, language: str, mood: str) -> tuple[str | None, dict[str, str]]:
    url, meta = _voice_v3(reply, language, mood)
    if url:
        return url, meta
    v3_status = meta.get("status", "unavailable")

    url, meta = _voice_edge(reply)
    if url:
        meta["preferred_v3"] = v3_status
        return url, meta
    edge_status = meta.get("status", "unavailable")

    url, meta = _voice_v2(reply)
    if url:
        meta["preferred_v3"] = v3_status
        meta["edge_fallback"] = edge_status
        return url, meta

    return None, {
        "status": "unavailable",
        "v3": v3_status,
        "edge": edge_status,
        "v2": meta.get("status", "unavailable"),
    }


@app.get("/healthz")
def healthz():
    return {
        "ok": True,
        "service": "nova-secure-conversation-bridge",
        "version": "1.0.0",
        "conversation_only": True,
        "executes_actions": False,
        "cloudflare_access_required": REQUIRE_CF_ACCESS,
        "allowed_origins": ALLOWED_ORIGINS,
        "brain_configured": bool(_providers()),
        "voice_url": VOICE_URL,
        "edge_tts_enabled": EDGE_TTS_ENABLED,
        "edge_tts_available": edge_tts is not None,
        "edge_tamil_voice": EDGE_TAMIL_VOICE,
        "edge_english_voice": EDGE_ENGLISH_VOICE,
        "local_v2_url": V2_VOICE_URL,
    }


@app.post("/v1/chat")
def chat(req: ChatRequest, request: Request, authorization: str | None = Header(default=None)):
    identity = _authorize_request(request, authorization)
    _rate_limit(identity)
    session_id = req.session_id or uuid.uuid4().hex
    reply, provider = _brain_reply(session_id, req.text)
    audio_url, voice_meta = _voice(reply, req.language, req.mood)
    threading.Thread(target=_cleanup_audio, daemon=True).start()
    return {
        "ok": True,
        "session_id": session_id,
        "reply": reply,
        "brain": provider,
        "audio_url": audio_url,
        "voice": voice_meta,
        "executed_action": False,
    }


@app.get("/v1/audio/{fname}")
def audio(fname: str, request: Request, authorization: str | None = Header(default=None)):
    identity = _authorize_request(request, authorization)
    _rate_limit(identity)
    if not re.fullmatch(r"[a-f0-9]{32}\.(wav|mp3)", fname):
        raise HTTPException(status_code=404, detail="not found")
    path = AUDIO_DIR / fname
    if not path.is_file():
        raise HTTPException(status_code=404, detail="expired")
    media_type = "audio/wav" if fname.endswith(".wav") else "audio/mpeg"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-store"})


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
