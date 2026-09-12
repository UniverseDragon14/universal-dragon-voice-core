from __future__ import annotations

import hmac
import io
import os
from pathlib import Path
from typing import Literal

import soundfile as sf
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from emotion import apply_output_character, detect_language, resolve_mood
from engines import EngineUnavailable, IndicF5Engine, KokoroEngine


HOST = os.environ.get("NOVA_VOICE_HOST", "127.0.0.1")
PORT = int(os.environ.get("NOVA_VOICE_PORT", "8125"))
TOKEN = os.environ.get("NOVA_VOICE_TOKEN", "").strip()
VOICE_ROOT = Path(
    os.environ.get(
        "NOVA_VOICE_ROOT",
        str(Path(__file__).resolve().parent / "voices" / "nova_female"),
    )
)
MAX_TEXT_CHARS = int(os.environ.get("NOVA_VOICE_MAX_TEXT", "1600"))

app = FastAPI(title="NOVA Voice Soul v3", version="3.0.0")
kokoro = KokoroEngine()
indicf5 = IndicF5Engine(VOICE_ROOT)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    language: Literal["auto", "en", "ta"] = "auto"
    mood: Literal[
        "auto",
        "neutral",
        "warm",
        "confident",
        "calm",
        "happy",
        "concerned",
        "firm",
        "whisper",
    ] = "auto"
    intensity: float = Field(default=0.72, ge=0.0, le=1.0)
    engine: Literal["auto", "kokoro", "indicf5"] = "auto"

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("text cannot be blank")
        return value


def _authorize(authorization: str | None) -> None:
    if not TOKEN:
        return
    expected = f"Bearer {TOKEN}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="invalid voice token")


def _select_engine(language: str, requested: str):
    if requested == "kokoro":
        if language != "en":
            raise HTTPException(status_code=400, detail="Kokoro route is English-only in Voice Soul v3")
        return kokoro
    if requested == "indicf5":
        if language != "ta":
            raise HTTPException(status_code=400, detail="IndicF5 route is reserved for Tamil in Voice Soul v3")
        return indicf5
    return indicf5 if language == "ta" else kokoro


def _wav_bytes(audio, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, audio, sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


@app.get("/healthz")
def healthz():
    return {
        "ok": True,
        "service": "nova-voice-soul-v3",
        "version": "3.0.0",
        "voice_root": str(VOICE_ROOT),
        "engines": {
            "kokoro": kokoro.status(),
            "indicf5": indicf5.status(),
        },
        "security": {
            "token_required": bool(TOKEN),
            "tts_only": True,
            "executes_actions": False,
        },
    }


@app.post("/v3/speak")
def speak(req: SpeakRequest, authorization: str | None = Header(default=None)):
    _authorize(authorization)

    language = detect_language(req.text) if req.language == "auto" else req.language
    mood = resolve_mood(req.mood, req.text)
    engine = _select_engine(language, req.engine)

    try:
        audio, sample_rate = engine.synthesize(req.text, mood, req.intensity)
    except EngineUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    audio = apply_output_character(audio, mood, req.intensity)
    wav = _wav_bytes(audio, sample_rate)

    return Response(
        content=wav,
        media_type="audio/wav",
        headers={
            "X-NOVA-Voice-Engine": engine.name,
            "X-NOVA-Voice-Mood": mood.name,
            "X-NOVA-Voice-Language": language,
            "X-NOVA-Voice-Sample-Rate": str(sample_rate),
            "Cache-Control": "no-store",
        },
    )


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
