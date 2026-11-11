"""End-to-end test against a real, synthetically generated video file.

Skipped automatically if ffmpeg isn't on PATH.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from openshorts.detect import detect_highlights
from openshorts.ffmpeg_utils import cut_clip, probe_duration

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)


@pytest.fixture
def synthetic_video(tmp_path: Path) -> Path:
    """A 20s video: color bars with a quiet tone, except a loud burst at t=10-11s."""
    out = tmp_path / "session.mp4"
    # Quiet base tone for the whole 20s, with a loud tone mixed in only during [10, 11).
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=20:r=10",
            "-f", "lavfi", "-i",
            "sine=frequency=220:duration=20,volume=0.05",
            "-f", "lavfi", "-i",
            "sine=frequency=880:duration=1,volume=12,adelay=10000|10000",
            "-filter_complex", "[1:a][2:a]amix=inputs=2:duration=first:dropout_transition=0[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
            "-t", "20",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    return out


@requires_ffmpeg
def test_detects_highlight_in_synthetic_video(synthetic_video: Path):
    highlights = detect_highlights(synthetic_video, min_gap_s=5.0)
    assert len(highlights) == 1
    assert 9.0 <= highlights[0].time <= 12.0


def _probe_dimensions(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    stream = json.loads(result.stdout)["streams"][0]
    return stream["width"], stream["height"]


@requires_ffmpeg
def test_cut_clip_produces_a_playable_file(synthetic_video: Path, tmp_path: Path):
    out_path = tmp_path / "clip.mp4"
    cut_clip(synthetic_video, out_path, start=9.0, duration=3.0)
    assert out_path.exists()
    assert out_path.stat().st_size > 0


@requires_ffmpeg
def test_cut_clip_defaults_to_vertical_shorts_format(synthetic_video: Path, tmp_path: Path):
    """The source is a 320x240 landscape test video -- by default, output
    should come out as a proper vertical 1080x1920 Short, not a cut-down
    landscape video."""
    out_path = tmp_path / "clip.mp4"
    cut_clip(synthetic_video, out_path, start=9.0, duration=3.0)
    width, height = _probe_dimensions(out_path)
    assert (width, height) == (1080, 1920)


@requires_ffmpeg
def test_cut_clip_vertical_false_keeps_original_framing(synthetic_video: Path, tmp_path: Path):
    out_path = tmp_path / "clip.mp4"
    cut_clip(synthetic_video, out_path, start=9.0, duration=3.0, vertical=False)
    width, height = _probe_dimensions(out_path)
    assert (width, height) == (320, 240)


@requires_ffmpeg
def test_cut_clip_caps_duration_at_max_duration(synthetic_video: Path, tmp_path: Path):
    out_path = tmp_path / "clip.mp4"
    cut_clip(synthetic_video, out_path, start=0.0, duration=20.0, max_duration=5.0)
    assert probe_duration(out_path) == pytest.approx(5.0, abs=0.5)
