import shutil
import subprocess
from pathlib import Path

import pytest

from openshorts.transcribe import _shorten, transcribe_clip

requires_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")


def test_shorten_leaves_short_text_unchanged():
    assert _shorten("hello there", 70) == "Hello there"


def test_shorten_truncates_at_word_boundary_not_mid_word():
    text = "the quick brown fox jumps over the lazy dog and keeps running"
    short = _shorten(text, 20)
    assert len(short) <= 20
    # every word in the result is a real whole word from the source, not a cut-off fragment
    assert all(word in text.split() for word in short.lower().split())


def test_shorten_capitalizes_first_letter():
    assert _shorten("gta 6 is wild", 70)[0] == "G"


def test_shorten_empty_text_stays_empty():
    assert _shorten("   ", 70) == ""


@requires_ffmpeg
def test_transcribe_clip_returns_none_for_non_speech_audio(tmp_path):
    """A clip with only a synthesized tone (no speech) should come back None,
    not raise -- and not hallucinate text out of nothing."""
    pytest.importorskip("faster_whisper")
    out = tmp_path / "tone.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "color=c=black:s=320x240:d=3:r=5",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
            "-t", "3",
            str(out),
        ],
        check=True, capture_output=True,
    )
    assert transcribe_clip(out) is None
