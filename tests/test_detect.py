import numpy as np
import pytest

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


def test_default_clip_length_lands_in_15_to_30_second_range():
    # burst with plenty of room on both sides -- should get the full nominal
    # lead_in + lead_out window (defaults: 5s + 15s = 20s), not the old 8s.
    pcm = np.concatenate([_silence(30), _burst(1.0), _silence(30)])
    highlights = find_highlights_in_audio(pcm, min_gap_s=5.0)
    assert len(highlights) == 1
    assert 15.0 <= highlights[0].clip_duration <= 30.0


def test_min_clip_duration_floor_pulls_from_the_side_with_room():
    # burst very close to the end of the video -- lead_out alone would clamp
    # to ~1.25s of trailing room, which used to mean a ~6s clip. The floor
    # should pull the rest from lead_in instead, landing exactly at the floor.
    pcm = np.concatenate([_silence(30), _burst(0.5), _silence(1)])
    duration_s = len(pcm) / SAMPLE_RATE
    highlights = find_highlights_in_audio(pcm, duration_s=duration_s, min_gap_s=5.0)
    assert len(highlights) == 1
    h = highlights[0]
    assert h.clip_duration == pytest.approx(15.0)
    assert h.clip_start + h.clip_duration == pytest.approx(duration_s)
