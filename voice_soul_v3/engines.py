from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np
import torch

from emotion import MoodProfile


class EngineUnavailable(RuntimeError):
    pass


class KokoroEngine:
    name = "kokoro"
    sample_rate = 24000

    def __init__(self) -> None:
        self.voice = os.environ.get("NOVA_KOKORO_VOICE", "af_heart")
        self._pipeline = None
        self._lock = threading.Lock()
        self._load_error: str | None = None

    def _load(self):
        if self._pipeline is not None:
            return self._pipeline
        with self._lock:
            if self._pipeline is not None:
                return self._pipeline
            if self._load_error:
                raise EngineUnavailable(self._load_error)
            try:
                from kokoro import KPipeline
                self._pipeline = KPipeline(lang_code="a")
            except Exception as exc:
                self._load_error = f"Kokoro load failed: {exc}"
                raise EngineUnavailable(self._load_error) from exc
        return self._pipeline

    def status(self) -> dict:
        return {
            "engine": self.name,
            "loaded": self._pipeline is not None,
            "voice": self.voice,
            "error": self._load_error,
        }

    def synthesize(self, text: str, mood: MoodProfile, intensity: float) -> tuple[np.ndarray, int]:
        pipeline = self._load()
        speed = 1.0 + (mood.speed - 1.0) * max(0.0, min(1.0, intensity))
        chunks: list[np.ndarray] = []
        try:
            generator = pipeline(text, voice=self.voice, speed=speed)
            for _graphemes, _phonemes, audio in generator:
                arr = np.asarray(audio, dtype=np.float32).reshape(-1)
                if arr.size:
                    chunks.append(arr)
        except Exception as exc:
            raise EngineUnavailable(f"Kokoro synthesis failed: {exc}") from exc
        if not chunks:
            raise EngineUnavailable("Kokoro returned no audio")
        return np.concatenate(chunks), self.sample_rate


class IndicF5Engine:
    name = "indicf5"
    sample_rate = 24000

    def __init__(self, voice_root: str | Path) -> None:
        self.voice_root = Path(voice_root)
        self.model_id = os.environ.get("NOVA_INDICF5_MODEL", "ai4bharat/IndicF5")
        self.enabled = os.environ.get("NOVA_ENABLE_INDICF5", "1").lower() not in {"0", "false", "no"}
        self._model = None
        self._lock = threading.Lock()
        self._load_error: str | None = None

    def _load(self):
        if not self.enabled:
            raise EngineUnavailable("IndicF5 disabled by NOVA_ENABLE_INDICF5")
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            if self._load_error:
                raise EngineUnavailable(self._load_error)
            try:
                from transformers import AutoModel
                model = AutoModel.from_pretrained(self.model_id, trust_remote_code=True)
                if torch.cuda.is_available() and hasattr(model, "to"):
                    model = model.to("cuda")
                if hasattr(model, "eval"):
                    model.eval()
                self._model = model
            except Exception as exc:
                self._load_error = f"IndicF5 load failed: {exc}"
                raise EngineUnavailable(self._load_error) from exc
        return self._model

    def _reference(self, mood: MoodProfile) -> tuple[Path, str]:
        mood_audio = self.voice_root / f"{mood.name}.wav"
        mood_text = self.voice_root / f"{mood.name}.txt"
        if not mood_audio.is_file() or not mood_text.is_file():
            mood_audio = self.voice_root / "neutral.wav"
            mood_text = self.voice_root / "neutral.txt"
        if not mood_audio.is_file() or not mood_text.is_file():
            raise EngineUnavailable(
                f"NOVA voice reference missing. Expected {self.voice_root}/neutral.wav and neutral.txt"
            )
        transcript = mood_text.read_text(encoding="utf-8").strip()
        if not transcript:
            raise EngineUnavailable(f"Empty reference transcript: {mood_text}")
        return mood_audio, transcript

    def status(self) -> dict:
        return {
            "engine": self.name,
            "enabled": self.enabled,
            "loaded": self._model is not None,
            "model": self.model_id,
            "voice_root": str(self.voice_root),
            "cuda": torch.cuda.is_available(),
            "error": self._load_error,
        }

    def synthesize(self, text: str, mood: MoodProfile, intensity: float) -> tuple[np.ndarray, int]:
        del intensity  # mood is expressed by the selected consented reference recording
        model = self._load()
        ref_audio, ref_text = self._reference(mood)
        try:
            with torch.inference_mode():
                audio = model(text, ref_audio_path=str(ref_audio), ref_text=ref_text)
        except Exception as exc:
            raise EngineUnavailable(f"IndicF5 synthesis failed: {exc}") from exc
        arr = np.asarray(audio)
        if arr.dtype == np.int16:
            arr = arr.astype(np.float32) / 32768.0
        else:
            arr = arr.astype(np.float32)
        arr = arr.reshape(-1)
        if not arr.size:
            raise EngineUnavailable("IndicF5 returned no audio")
        return arr, self.sample_rate
