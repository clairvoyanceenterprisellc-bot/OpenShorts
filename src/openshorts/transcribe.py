"""Short, audio-derived captions for a clip, via local speech-to-text.

Uses faster-whisper (CTranslate2) so this runs fully offline/local, no API
key -- consistent with the rest of this project. The model downloads once
(cached by huggingface_hub) on first real use.

This is deliberately best-effort: a clip might have no speech at all (just
gameplay sound, music, silence), the model might not be installed yet, or
transcription might fail for some other reason. In every one of those cases
`transcribe_clip` returns None rather than raising, so callers always have a
sane fallback (e.g. the category-based GTA6 title templates).
"""

from __future__ import annotations

import re
from pathlib import Path

# English-only + small: clips are short (15-30s) and this needs to run inline
# in the clip-cutting pipeline without becoming the slow part of it.
MODEL_SIZE = "base.en"
MAX_CAPTION_CHARS = 70

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def _shorten(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        # cut at the last whole word that still fits, rather than mid-word
        text = text[:max_chars].rsplit(" ", 1)[0] or text[:max_chars]
    # a clip's audio often starts mid-sentence -- capitalize for use as a title
    return text[:1].upper() + text[1:] if text else text


def transcribe_clip(file_path: Path, max_chars: int = MAX_CAPTION_CHARS) -> str | None:
    """Return a short caption transcribed from the clip's own audio, or None
    if there's no usable speech in it (or transcription isn't available)."""
    try:
        model = _get_model()
        segments, _info = model.transcribe(
            str(file_path), beam_size=1, vad_filter=True, condition_on_previous_text=False,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
    except Exception:
        return None

    if not text:
        return None
    return _shorten(text, max_chars)
