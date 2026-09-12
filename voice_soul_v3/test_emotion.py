import numpy as np

from emotion import apply_output_character, detect_language, infer_mood, resolve_mood


def test_language_detection():
    assert detect_language("Hello Aslam") == "en"
    assert detect_language("வணக்கம் Aslam") == "ta"


def test_mood_detection():
    assert infer_mood("NOVA is ready and verified") == "confident"
    assert infer_mood("Warning, this needs attention") == "firm"
    assert infer_mood("Great, the task is done") == "happy"


def test_output_character_never_clips():
    x = np.array([0.99, -0.99, 0.2], dtype=np.float32)
    y = apply_output_character(x, resolve_mood("firm", "test"), 1.0)
    assert float(np.max(np.abs(y))) <= 0.9851
