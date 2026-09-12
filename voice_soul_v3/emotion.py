from __future__ import annotations

from dataclasses import dataclass
import re

import numpy as np


@dataclass(frozen=True)
class MoodProfile:
    name: str
    speed: float
    gain: float


MOODS: dict[str, MoodProfile] = {
    "neutral": MoodProfile("neutral", 1.00, 1.00),
    "warm": MoodProfile("warm", 0.96, 1.00),
    "confident": MoodProfile("confident", 0.98, 1.04),
    "calm": MoodProfile("calm", 0.92, 0.96),
    "happy": MoodProfile("happy", 1.05, 1.03),
    "concerned": MoodProfile("concerned", 0.93, 0.98),
    "firm": MoodProfile("firm", 0.95, 1.06),
    "whisper": MoodProfile("whisper", 0.88, 0.76),
}

_TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")


def detect_language(text: str) -> str:
    """Return 'ta' when Tamil script is present, otherwise 'en'."""
    if _TAMIL_RE.search(text):
        return "ta"
    return "en"


def infer_mood(text: str) -> str:
    """Small deterministic planner; the LLM may explicitly override this later."""
    low = text.lower().strip()

    if any(k in low for k in ("careful", "warning", "attention", "important", "கவனம்", "எச்சரிக்கை")):
        return "firm"
    if any(k in low for k in ("sorry", "problem", "failed", "error", "worried", "மன்னிக்க", "பிரச்சனை")):
        return "concerned"
    if any(k in low for k in ("great", "nice", "excellent", "done", "success", "super", "அருமை", "முடிந்தது")):
        return "happy"
    if any(k in low for k in ("quiet", "softly", "whisper", "மெதுவாக")):
        return "whisper"
    if any(k in low for k in ("relax", "calm", "steady", "அமைதி")):
        return "calm"
    if any(k in low for k in ("ready", "confirmed", "verified", "online", "நிச்சயம்", "தயார்")):
        return "confident"
    if any(k in low for k in ("welcome", "hello", "hi ", "thank", "வணக்கம்", "நன்றி")):
        return "warm"
    return "neutral"


def resolve_mood(requested: str, text: str) -> MoodProfile:
    name = infer_mood(text) if requested == "auto" else requested
    return MOODS.get(name, MOODS["neutral"])


def apply_output_character(audio: np.ndarray, profile: MoodProfile, intensity: float) -> np.ndarray:
    """Apply conservative level shaping without destroying speech naturalness."""
    x = np.asarray(audio, dtype=np.float32).reshape(-1)
    if x.size == 0:
        return x

    amount = max(0.0, min(1.0, float(intensity)))
    gain = 1.0 + (profile.gain - 1.0) * amount
    x = x * gain

    peak = float(np.max(np.abs(x)))
    if peak > 0.985:
        x = x * (0.985 / peak)
    return x.astype(np.float32, copy=False)
