import numpy as np

from openshorts.detect import find_highlights_in_audio

SAMPLE_RATE = 16_000


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)


def _burst(seconds: float, amplitude: float = 0.9) -> np.ndarray:
    n = int(seconds * SAMPLE_RATE)
    return (amplitude * np.sin(2 * np.pi * 220 * np.arange(n) / SAMPLE_RATE)).astype(np.float32)


def test_no_highlights_in_silence():
    pcm = _silence(10)
    assert find_highlights_in_audio(pcm) == []


def test_finds_a_single_burst():
    pcm = np.concatenate([_silence(10), _burst(1.0), _silence(10)])
    highlights = find_highlights_in_audio(pcm, min_gap_s=5.0)
    assert len(highlights) == 1
    # the burst starts at t=10s and runs 1s, peak window should land in there
    assert 9.5 <= highlights[0].time <= 11.5


def test_merges_nearby_bursts_into_one_highlight():
    pcm = np.concatenate([_silence(5), _burst(0.5), _silence(1), _burst(0.5), _silence(5)])
    highlights = find_highlights_in_audio(pcm, min_gap_s=15.0)
    assert len(highlights) == 1


def test_separate_bursts_beyond_min_gap_stay_distinct():
    pcm = np.concatenate([_silence(5), _burst(0.5), _silence(20), _burst(0.5), _silence(5)])
    highlights = find_highlights_in_audio(pcm, min_gap_s=5.0)
    assert len(highlights) == 2


def test_clip_window_respects_lead_in_and_out_and_duration_bounds():
    pcm = np.concatenate([_silence(2), _burst(0.5), _silence(2)])
    duration_s = len(pcm) / SAMPLE_RATE
    highlights = find_highlights_in_audio(
        pcm, lead_in_s=10.0, lead_out_s=10.0, duration_s=duration_s
    )
    assert len(highlights) == 1
    h = highlights[0]
    assert h.clip_start == 0.0
    assert h.clip_start + h.clip_duration == duration_s
