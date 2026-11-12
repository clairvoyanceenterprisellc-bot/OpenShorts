"""YouTube Data API v3 uploader.

Needs an OAuth2 access token with the `youtube.upload` scope — get one by
running `scripts/get_youtube_token.py` (create an OAuth client in Google
Cloud Console first; see the README). That script requests offline access,
so the connection also gets a refresh_token/client_id/client_secret saved
alongside the access token (in the connection's `meta`). Access tokens
expire in ~1 hour; when the API responds 401, `upload`/`get_stats` raise
`TokenExpiredError` and the dashboard (server.py) transparently refreshes via
`refresh_access_token` below and retries — no re-auth needed as long as the
refresh_token stays valid. A connection saved without that meta (e.g. a
token pasted by hand) just can't auto-refresh and needs a fresh paste.

Watch-time isn't available from this call: that needs the separate YouTube
Analytics API with a token scoped for the channel owner. `get_stats` returns
`watch_time_seconds=None` until that's wired up.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from openshorts.dashboard.uploaders.base import (
    NotConnectedError,
    PostResult,
    StatsResult,
    TokenExpiredError,
    UploadError,
)

platform = "youtube"

UPLOAD_INIT_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
TOKEN_URI = "https://oauth2.googleapis.com/token"


def is_connected(token: str) -> bool:
    return bool(token) and len(token) > 20


def refresh_access_token(meta: dict) -> dict:
    """Mint a fresh access token from the refresh_token saved alongside it.
    Returns {"access_token": ...} -- Google's refresh tokens don't rotate on
    use (unlike TikTok's), so there's no updated refresh_token to pass back.

    Requires `refresh_token`, `client_id`, `client_secret` in `meta` — exactly
    what scripts/get_youtube_token.py saves when it requests offline access.
    """
    missing = [k for k in ("refresh_token", "client_id", "client_secret") if not meta.get(k)]
    if missing:
        raise UploadError(
            f"Can't refresh YouTube token (missing {', '.join(missing)} from the saved connection) — "
            f"reconnect with scripts/get_youtube_token.py."
        )
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            meta.get("token_uri", TOKEN_URI),
            data={
                "grant_type": "refresh_token",
                "refresh_token": meta["refresh_token"],
                "client_id": meta["client_id"],
                "client_secret": meta["client_secret"],
            },
        )
    if resp.status_code != 200:
        raise UploadError(f"YouTube token refresh failed: {resp.status_code} {resp.text}")
    return {"access_token": resp.json()["access_token"]}


def upload(token: str, file_path: Path, title: str, description: str, **_ignored) -> PostResult:
    if not is_connected(token):
        raise NotConnectedError("No YouTube access token saved.")

    file_path = Path(file_path)
    size = file_path.stat().st_size
    metadata = {
        "snippet": {"title": title[:100], "description": description[:5000], "categoryId": "20"},
        "status": {"privacyStatus": "public"},
    }

    with httpx.Client(timeout=60.0) as client:
        init = client.post(
            UPLOAD_INIT_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(size),
            },
            json=metadata,
        )
        if init.status_code == 401:
            raise TokenExpiredError(f"YouTube upload init failed: {init.status_code} {init.text}")
        if init.status_code != 200 or "location" not in init.headers:
            raise UploadError(f"YouTube upload init failed: {init.status_code} {init.text}")
        upload_url = init.headers["location"]

        with file_path.open("rb") as f:
            put = client.put(
                upload_url,
                headers={"Content-Type": "video/mp4", "Content-Length": str(size)},
                content=f.read(),
            )
        if put.status_code == 401:
            raise TokenExpiredError(f"YouTube upload failed: {put.status_code} {put.text}")
        if put.status_code not in (200, 201):
            raise UploadError(f"YouTube upload failed: {put.status_code} {put.text}")

        video_id = put.json()["id"]
        return PostResult(remote_id=video_id, remote_url=f"https://youtu.be/{video_id}")


def get_stats(token: str, remote_id: str) -> StatsResult:
    if not is_connected(token):
        raise NotConnectedError("No YouTube access token saved.")

    with httpx.Client(timeout=30.0) as client:
        resp = client.get(
            VIDEOS_URL,
            params={"part": "statistics", "id": remote_id},
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code == 401:
        raise TokenExpiredError(f"YouTube stats fetch failed: {resp.status_code} {resp.text}")
    if resp.status_code != 200:
        raise UploadError(f"YouTube stats fetch failed: {resp.status_code} {resp.text}")
    items = resp.json().get("items", [])
    if not items:
        return StatsResult(views=0, watch_time_seconds=None)
    views = int(items[0]["statistics"].get("viewCount", 0))
    return StatsResult(views=views, watch_time_seconds=None)
