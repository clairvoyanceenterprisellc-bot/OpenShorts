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

## Dashboard

A local web dashboard sits on top of the CLI: drop in a stream/video link, watch it get split into categorized clips, and (once connected) post them straight to YouTube/TikTok/Instagram.

```bash
openshorts dashboard
# -> http://127.0.0.1:8788
```

Four tabs:

- **Add Video** — paste a stream/VOD URL (downloaded via `yt-dlp`) or a local file path. Runs the same detect → cut pipeline as the CLI in the background and shows live progress (queued → downloading → detecting → clipping → done).
- **Clips** — every clip generated, filterable by category (**Best Moments**, **Funny Clips**, **Tips & Tricks**, **Unsorted**), playable inline, re-taggable with a dropdown, and postable to any connected platform.
- **Connections** — add an access token per platform (YouTube, TikTok, Instagram) to enable posting/stats for it. Not connected by default — see below.
- **Stats** — total views, watch time, and best-performing clip, pulled live from each platform's API once connected.

**Auto-categorization is honest about its limits.** Loudness alone can flag an *intense* moment, so the top-scoring highlights in a session get auto-tagged "Best Moments." "Funny Clips" and "Tips & Tricks" are manual-tag categories for now — telling those apart needs to know what's actually being *said*, which is a speech-to-text pass (e.g. faster-whisper) away and is the natural next addition.

**Connecting YouTube/TikTok/Instagram is real, but needs your own API credentials** — there's no shared/shortcut auth:

| Platform | What you need | Where |
|---|---|---|
| YouTube | OAuth2 access token, scope `youtube.upload` | Google Cloud Console → create an OAuth client → run the consent flow |
| TikTok | Access token from a Content Posting API app | [developers.tiktok.com](https://developers.tiktok.com) (TikTok reviews Direct Post access before granting it) |
| Instagram | Access token + IG Business account id + a **public URL** your clips are hosted at | Meta for Developers → Instagram Graph API, `instagram_content_publish` permission. Instagram ingests video by URL, not upload — a localhost dashboard can't serve that itself, so you'll need somewhere (S3, R2, your own server) to host clips publicly first. |

Paste the token (and, for Instagram, the extra fields) into the Connections tab. Until a platform has a valid token, posting to it stays disabled in the Clips tab rather than silently pretending to work.

Data (SQLite db, downloaded sources, cut clips) lives in `~/.openshorts/`, not in the repo.

## Status

Early scaffold, built ahead of GTA 6's release so the pipeline is ready on day one. Audio-spike detection and the dashboard both work today on any gameplay video; game-specific detectors and real OAuth token refresh are the natural next steps.

## License

MIT — see [LICENSE](LICENSE).
