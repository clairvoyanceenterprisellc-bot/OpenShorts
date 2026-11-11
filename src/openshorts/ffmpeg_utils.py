"""Thin wrappers around the ffmpeg/ffprobe binaries."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16_000

# Every major short-form platform (YouTube Shorts, TikTok, Instagram Reels)
# expects vertical 9:16 video; this is the standard resolution for it.
SHORTS_WIDTH = 1080
SHORTS_HEIGHT = 1920
# 60s is the tightest common denominator across platforms that is still
# reliably classified as a "Short" (YouTube's Shorts shelf historically
# required <=60s; it now tolerates up to 3min, but 60s stays the safe default).
SHORTS_MAX_DURATION = 60.0


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


def cut_clip(
    video_path: Path,
    out_path: Path,
    start: float,
    duration: float,
    vertical: bool = True,
    max_duration: float = SHORTS_MAX_DURATION,
) -> None:
    """Cut a clip [start, start+duration) from video_path into out_path.

    By default reframes to a 1080x1920 vertical canvas — scales the source to
    fit the width and fills the rest of the frame with a blurred, cropped
    copy of itself, rather than cropping away the sides of the gameplay —
    and caps the clip at `max_duration` seconds, so what comes out is always
    short-format, not a cut-down long-form video with the wrong aspect ratio.
    Pass `vertical=False` to keep the source's original framing instead.
    """
    require_ffmpeg()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    duration = min(duration, max_duration)

    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{start:.3f}",
        "-i", str(video_path),
        "-t", f"{duration:.3f}",
    ]
    if vertical:
        cmd += [
            "-filter_complex",
            f"[0:v]scale={SHORTS_WIDTH}:{SHORTS_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={SHORTS_WIDTH}:{SHORTS_HEIGHT},boxblur=20:5[bg];"
            f"[0:v]scale={SHORTS_WIDTH}:-2[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[v]",
            "-map", "[v]", "-map", "0:a?",
        ]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(out_path)]

    subprocess.run(cmd, check=True)
