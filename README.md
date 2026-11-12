# OpenShorts

Auto-detect highlight moments in long gameplay recordings and cut them into short clips, ready for YouTube Shorts / TikTok / Reels.

Built to be ready for GTA 6: point it at a recording session, get back a folder of candidate clips sorted by "excitement" score.

## How it works

1. **Extract audio** from the source video with `ffmpeg`.
2. **Score loudness over time** using a rolling RMS window — sudden spikes (explosions, gunfire, shouting, chat reactions) usually mean something happened.
3. **Find peaks** above a threshold, merge nearby ones, and pad each with a configurable amount of lead-in/lead-out (defaults: 5s before, 15s after — a 20s clip, with a 15s floor that extends short edge-clamped clips so nothing ends up tiny near the start/end of a video).
4. **Cut clips** from the source video at those timestamps with `ffmpeg`, reframed to a 1080x1920 vertical canvas and capped at 60 seconds — actual short-format output, not a trimmed-down landscape long-form video. The source footage isn't cropped to get there: it's scaled to fit the vertical frame's width with a blurred, cropped copy of itself filling the rest, so nothing on the sides of the gameplay gets cut off.

This is a simple, model-free MVP. It doesn't know what GTA 6 looks like yet — it just finds "loud moments." That's deliberately the first slice: it works on any gameplay footage today, and more detectors (kill-feed OCR, scene-cut detection, chat/Twitch reaction mining) can be added later behind the same `Highlight` interface.

## Requirements

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/) and `ffprobe` on your `PATH`
- For the dashboard's "drop a YouTube link" feature: [Node.js](https://nodejs.org) 22+ on your `PATH` (yt-dlp needs a JS runtime to solve YouTube's signature challenge — see the Dashboard section below) and, on Windows, cookies exported to a file (Chrome's live cookie database can't be read directly)
- Speech-to-text captions (below) run locally via `faster-whisper` — no API key, but it downloads a ~150MB model the first time it actually transcribes a clip, so that first run needs internet once

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

# Tune sensitivity or clip length (defaults: 5s lead-in, 15s lead-out, 15s minimum)
openshorts clip session.mp4 --out clips/ --threshold 2.5 --min-gap 20 --lead-in 5 --lead-out 25

# Keep the source's original landscape framing instead of reframing vertical, or change the length cap
openshorts clip session.mp4 --out clips/ --no-vertical
openshorts clip session.mp4 --out clips/ --max-duration 30
```

## Dashboard

A local web dashboard sits on top of the CLI: drop in a stream/video link, watch it get split into categorized clips, and (once connected) post them straight to YouTube/TikTok/Instagram.

```bash
openshorts dashboard
# -> http://127.0.0.1:8788
```

Four tabs:

- **Add Video** — paste a stream/VOD URL (downloaded via `yt-dlp`) or a local file path. Runs the same detect → cut pipeline as the CLI in the background and shows live progress (queued → downloading → detecting → clipping → done). Clips always come out vertical (1080x1920), land in the 15-30s range (nominal 20s, never below a 15s floor), and are capped at 60 seconds — ready to post as-is. The dashboard doesn't have a `--no-vertical` equivalent, since every clip from here is meant to go straight to a platform that expects Shorts/Reels format. A **Sensitivity** slider on the form maps to `--threshold` — lower it for quieter/more consistent audio (real commentary-heavy footage often needs ~1.5-2.0 instead of the 2.5 default); a completed source that found nothing shows "Done — 0 clips found" rather than looking indistinguishable from a working one.

  **Two separate things have to work for a YouTube URL to download, and both bit us in testing:**

  1. **Auth.** YouTube increasingly bot-checks anonymous downloads ("Sign in to confirm you're not a bot"). Reading cookies live from a running Chrome (`cookiesfrombrowser`) doesn't work on Windows at all — not just a file-lock issue, modern Chrome's "App-Bound Encryption" blocks yt-dlp's decryption outright (closing Chrome first doesn't help). The fix: export your youtube.com cookies with a browser extension (e.g. "Get cookies.txt LOCALLY", Netscape format) and save the file to `~/.openshorts/youtube_cookies.txt` — the dashboard uses it automatically once it's there, no live browser access needed.
  2. **Format extraction.** YouTube requires solving a JS signature challenge to get real video/audio formats back — without it, yt-dlp silently gets only storyboard thumbnails and fails with a confusing "Requested format is not available" error. This needs a JS runtime on `PATH` (Node.js 22+ works; install the `yt-dlp-ejs` package, already a dependency here) — see [yt-dlp's EJS wiki](https://github.com/yt-dlp/yt-dlp/wiki/EJS) for background. Only Deno is tried by default; the dashboard explicitly enables Node instead since that's more commonly already installed.
- **Clips** — every clip generated, filterable by category (**Best Moments**, **Funny Clips**, **Tips & Tricks**, **Unsorted**), playable inline, re-taggable with a dropdown, and postable to any connected platform. Each clip's own audio is transcribed locally (`faster-whisper`, right after it's cut) into a short caption shown on its card — real content, not a template, so it's inherently unique per clip; a clip with no usable speech (pure gameplay sound, silence) just shows "No speech detected" rather than a fabricated one. Posting uses that caption as the title when there is one (`GTA 6 — <caption>`), falling back to a GTA 6-themed category template when there isn't, plus a description loaded with popular GTA 6 hashtags (`#GTA6 #GrandTheftAuto6 #GTA6Clips` etc., with a platform-specific tag added: `#Shorts` / `#fyp #foryou` / `#Reels`) — pass your own `title`/`description` in the request to override. YouTube posts are made **public** (`privacyStatus: public`). TikTok posts use `privacy_level: SELF_ONLY` — confirmed against the real API: an unaudited app's publish call is hard-rejected (403 `unaudited_client_can_only_post_to_private_accounts`) for any broader value, even against an account that's itself set to private. Once your TikTok app passes their Direct Post audit, change that to `PUBLIC_TO_EVERYONE` in `tiktok.py` to actually post publicly. A clip can only be posted to a given platform **once** — enforced server-side (a repeat attempt gets a 409 with a link to the existing post), not just a disabled button.
- **Connections** — add an access token per platform (YouTube, TikTok, Instagram) to enable posting/stats for it. Not connected by default — see below.
- **Stats** — total views, watch time, and best-performing clip, pulled live from each platform's API once connected.

**Auto-categorization is honest about its limits.** Loudness alone can flag an *intense* moment, so the top-scoring highlights in a session get auto-tagged "Best Moments." "Funny Clips" and "Tips & Tricks" are manual-tag categories for now — telling those apart needs to know what's actually being *said*, which is a speech-to-text pass (e.g. faster-whisper) away and is the natural next addition.

**Connecting YouTube/TikTok/Instagram is real, but needs your own API credentials** — there's no shared/shortcut auth:

| Platform | What you need | Where |
|---|---|---|
| YouTube | OAuth2 access token, scope `youtube.upload` | Google Cloud Console → create an OAuth client → `python scripts/get_youtube_token.py --client-secret path/to/client_secret.json` (see below) |
| TikTok | Access token from a Content Posting API app | [developers.tiktok.com](https://developers.tiktok.com) (TikTok reviews Direct Post access before granting it — until your app passes that audit, TikTok silently posts everything as a private draft regardless of what's requested) |
| Instagram | Access token + IG Business account id + a **public URL** your clips are hosted at | Meta for Developers → Instagram Graph API, `instagram_content_publish` permission. Instagram ingests video by URL, not upload — a localhost dashboard can't serve that itself, so you'll need somewhere (S3, R2, your own server) to host clips publicly first. |

For TikTok/Instagram, paste the token (and, for Instagram, the extra fields) straight into the Connections tab. Until a platform has a valid token, posting to it stays disabled in the Clips tab rather than silently pretending to work.

**YouTube has a helper script and auto-refresh**, since access tokens pasted by hand expire in ~1 hour:

```bash
pip install -e ".[youtube-auth]"
python scripts/get_youtube_token.py --client-secret path/to/client_secret.json
```

This runs Google's real OAuth consent flow (a browser tab opens for you to sign in) and posts the resulting token straight to the running dashboard — the token itself is never printed. It requests offline access, so a `refresh_token` gets saved alongside the access token; when the dashboard hits a 401 from YouTube's API, it transparently refreshes and retries, so once this is connected it should keep working without you re-running anything. If your Google Cloud project's OAuth consent screen is still in "Testing" mode (likely, unless you've gone through Google's verification review — `youtube.upload` is a sensitive scope), add your own Google account under **OAuth consent screen → Test users** first, or you'll hit an "Access blocked" error.

Data (SQLite db, downloaded sources, cut clips) lives in `~/.openshorts/`, not in the repo.

## Status

Early scaffold, built ahead of GTA 6's release so the pipeline is ready on day one. Audio-spike detection and the dashboard both work today on any gameplay video, and YouTube posting auto-refreshes its own token; game-specific detectors and the same refresh treatment for TikTok/Instagram are the natural next steps.

## License

MIT — see [LICENSE](LICENSE).
