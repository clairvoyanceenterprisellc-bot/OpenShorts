"""Highlight detection.

MVP strategy: loudness-spike detection. Explosions, gunfire, shouting and chat
reactions all tend to show up as a sudden jump in audio RMS energy relative to
the recent baseline. We score the audio in short windows, z-score each window
against the whole session, and treat any window that clears `threshold`
standard deviations as a highlight.

This intentionally has no game-specific knowledge. More detectors (kill-feed
OCR, scene-cut detection, Twitch chat velocity, etc.) can be added later —
each just needs to produce a list of `Highlight`s that get merged with these.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from openshorts.ffmpeg_utils import SAMPLE_RATE, extract_mono_pcm, probe_duration


@dataclass(frozen=True)
class Highlight:
    """A detected highlight moment and the clip window around it."""

    time: float          # seconds into the video where the spike occurs
    score: float         # how many std devs above baseline loudness
    clip_start: float    # seconds into the video where the clip should start
    clip_duration: float # length of the clip in seconds


def _rolling_rms(pcm: np.ndarray, window_samples: int) -> np.ndarray:
    """RMS energy per non-overlapping window."""
    n_windows = len(pcm) // window_samples
    if n_windows == 0:
        return np.array([])
    trimmed = pcm[: n_windows * window_samples]
    windows = trimmed.reshape(n_windows, window_samples)
    return np.sqrt(np.mean(np.square(windows), axis=1))


def find_highlights_in_audio(
    pcm: np.ndarray,
    sample_rate: int = SAMPLE_RATE,
    window_s: float = 0.5,
    threshold: float = 2.5,
    min_gap_s: float = 15.0,
    lead_in_s: float = 5.0,
    lead_out_s: float = 15.0,
    duration_s: float | None = None,
    min_clip_duration_s: float = 15.0,
) -> list[Highlight]:
    """Find loudness-spike highlights in a mono PCM signal."""
    window_samples = max(1, int(window_s * sample_rate))
    rms = _rolling_rms(pcm, window_samples)
    if rms.size == 0:
        return []

    std = rms.std()
    if std == 0:
        return []
    z = (rms - rms.mean()) / std

    candidate_idxs = np.flatnonzero(z > threshold)
    if candidate_idxs.size == 0:
        return []

    total_duration = duration_s if duration_s is not None else len(pcm) / sample_rate

    # Merge candidates within min_gap_s of each other, keeping the loudest.
    merged: list[tuple[int, float]] = []
    min_gap_windows = max(1, int(min_gap_s / window_s))
    for idx in candidate_idxs:
        score = float(z[idx])
        if merged and idx - merged[-1][0] <= min_gap_windows:
            if score > merged[-1][1]:
                merged[-1] = (idx, score)
        else:
            merged.append((idx, score))

    highlights = []
    for idx, score in merged:
        peak_time = (idx + 0.5) * window_s
        clip_start = max(0.0, peak_time - lead_in_s)
        clip_end = min(total_duration, peak_time + lead_out_s)

        if clip_end - clip_start < min_clip_duration_s:
            # Near the start/end of the video, lead_in/lead_out can get
            # clamped short -- pull the shortfall from whichever side has
            # room left, so clips don't end up far shorter than intended.
            clip_end = min(total_duration, clip_start + min_clip_duration_s)
            clip_start = max(0.0, clip_end - min_clip_duration_s)

        clip_duration = clip_end - clip_start
        if clip_duration <= 0:
            continue
        highlights.append(
            Highlight(
                time=peak_time,
                score=score,
                clip_start=clip_start,
                clip_duration=clip_duration,
            )
        )
    return highlights


def detect_highlights(
    video_path: Path,
    window_s: float = 0.5,
    threshold: float = 2.5,
    min_gap_s: float = 15.0,
    lead_in_s: float = 5.0,
    lead_out_s: float = 15.0,
    min_clip_duration_s: float = 15.0,
) -> list[Highlight]:
    """Detect highlights directly from a video file on disk."""
    video_path = Path(video_path)
    pcm = extract_mono_pcm(video_path)
    duration = probe_duration(video_path)
    return find_highlights_in_audio(
        pcm,
        sample_rate=SAMPLE_RATE,
        window_s=window_s,
        threshold=threshold,
        min_gap_s=min_gap_s,
        lead_in_s=lead_in_s,
        lead_out_s=lead_out_s,
        duration_s=duration,
        min_clip_duration_s=min_clip_duration_s,
    )
