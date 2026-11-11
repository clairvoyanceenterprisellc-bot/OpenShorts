"""YouTube Data API v3 uploader.

Needs an OAuth2 access token with the `youtube.upload` scope (create an OAuth
client in Google Cloud Console, run the consent flow, paste the resulting
access token into the dashboard's Connections tab). Token refresh isn't
handled here — access tokens expire in ~1 hour, so you'll need to repaste a
fresh one until a refresh-token flow is added.

Watch-time isn't available from this call: that needs the separate YouTube
Analytics API with an `youtube.readonly`-scoped token tied to the channel
owner. `get_stats` returns `watch_time_seconds=None` until that's wired up.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from openshorts.dashboard.uploaders.base import NotConnectedError, PostResult, StatsResult, UploadError

platform = "youtube"

UPLOAD_INIT_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


def is_connected(token: str) -> bool:
    return bool(token) and len(token) > 20


def upload(token: str, file_path: Path, title: str, description: str) -> PostResult:
    if not is_connected(token):
        raise NotConnectedError("No YouTube access token saved.")

    file_path = Path(file_path)
    size = file_path.stat().st_size
    metadata = {
        "snippet": {"title": title[:100], "description": description[:5000], "categoryId": "20"},
        "status": {"privacyStatus": "private"},
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
        if init.status_code != 200 or "location" not in init.headers:
            raise UploadError(f"YouTube upload init failed: {init.status_code} {init.text}")
        upload_url = init.headers["location"]

        with file_path.open("rb") as f:
            put = client.put(
                upload_url,
                headers={"Content-Type": "video/mp4", "Content-Length": str(size)},
                content=f.read(),
            )
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
    if resp.status_code != 200:
        raise UploadError(f"YouTube stats fetch failed: {resp.status_code} {resp.text}")
    items = resp.json().get("items", [])
    if not items:
        return StatsResult(views=0, watch_time_seconds=None)
    views = int(items[0]["statistics"].get("viewCount", 0))
    return StatsResult(views=views, watch_time_seconds=None)
