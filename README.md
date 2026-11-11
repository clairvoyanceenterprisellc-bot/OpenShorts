# OpenShorts

Auto-detect highlight moments in long gameplay recordings and cut them into short clips, ready for YouTube Shorts / TikTok / Reels.

Built to be ready for GTA 6: point it at a recording session, get back a folder of candidate clips sorted by "excitement" score.

## How it works

1. **Extract audio** from the source video with `ffmpeg`.
2. **Score loudness over time** using a rolling RMS window — sudden spikes (explosions, gunfire, shouting, chat reactions) usually mean something happened.
3. **Find peaks** above a threshold, merge nearby ones, and pad each with a configurable amount of lead-in/lead-out.
4. **Cut clips** from the source video at those timestamps with `ffmpeg` (stream copy when possible, falling back to re-encode).

This is a simple, model-free MVP. It doesn't know what GTA 6 looks like yet — it just finds "loud moments." That's deliberately the first slice: it works on any gameplay footage today, and more detectors (kill-feed OCR, scene-cut detection, chat/Twitch reaction mining) can be added later behind the same `Highlight` interface.

## Requirements

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/) and `ffprobe` on your `PATH`

## Install

```bash
pip install -e .
```

## Usage

```bash
# Find highlights and print them (no cutting)
openshorts scan session.mp4

# Find highlights and cut clips into ./clips
openshorts clip session.mp4 --out clips/

# Tune sensitivity
openshorts clip session.mp4 --out clips/ --threshold 2.5 --min-gap 20 --lead-in 3 --lead-out 5
```

## Status

Early scaffold, built ahead of GTA 6's release so the pipeline is ready on day one. Audio-spike detection works today on any video; the architecture is set up for additional detectors later.

## License

MIT — see [LICENSE](LICENSE).
