"""Thin wrappers around the ffmpeg/ffprobe binaries."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16_000


class FfmpegNotFoundError(RuntimeError):
    pass


def require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise FfmpegNotFoundError(
            "ffmpeg/ffprobe not found on PATH. Install ffmpeg: https://ffmpeg.org/download.html"
        )


def probe_duration(video_path: Path) -> float:
    """Return the duration of a media file in seconds."""
    require_ffmpeg()
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def extract_mono_pcm(video_path: Path, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Decode a video's audio track to mono 16-bit PCM, returned as float32 in [-1, 1]."""
    require_ffmpeg()
    proc = subprocess.run(
        [
            "ffmpeg",
            "-v", "error",
            "-i", str(video_path),
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ac", "1",
            "-ar", str(sample_rate),
            "-",
        ],
        capture_output=True,
        check=True,
    )
    pcm = np.frombuffer(proc.stdout, dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def cut_clip(video_path: Path, out_path: Path, start: float, duration: float) -> None:
    """Cut a clip [start, start+duration) from video_path into out_path, re-encoding for accuracy."""
    require_ffmpeg()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v", "error",
            "-ss", f"{start:.3f}",
            "-i", str(video_path),
            "-t", f"{duration:.3f}",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-c:a", "aac",
            str(out_path),
        ],
        check=True,
    )
