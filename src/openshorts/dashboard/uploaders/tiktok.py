"""TikTok Content Posting API (Direct Post) uploader.

Needs an access token from a TikTok for Developers app with the
`video.publish` scope approved (TikTok reviews Direct Post access before
granting it — the sandbox/unaudited tier only allows posting as drafts to
your own test account). Paste the resulting access token into the
dashboard's Connections tab.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from openshorts.dashboard.uploaders.base import NotConnectedError, PostResult, StatsResult, UploadError

platform = "tiktok"

INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
QUERY_URL = "https://open.tiktokapis.com/v2/video/query/"


def is_connected(token: str) -> bool:
    return bool(token) and len(token) > 20


def upload(token: str, file_path: Path, title: str, description: str) -> PostResult:
    if not is_connected(token):
        raise NotConnectedError("No TikTok access token saved.")

    file_path = Path(file_path)
    size = file_path.stat().st_size
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}

    with httpx.Client(timeout=60.0) as client:
        init = client.post(
            INIT_URL,
            headers=headers,
            json={
                "post_info": {"title": title[:150], "privacy_level": "SELF_ONLY"},
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": size,
                    "chunk_size": size,
                    "total_chunk_count": 1,
                },
            },
        )
        body = init.json()
        if init.status_code != 200 or body.get("error", {}).get("code") not in (None, "ok"):
            raise UploadError(f"TikTok publish init failed: {init.status_code} {body}")

        data = body["data"]
        publish_id = data["publish_id"]
        upload_url = data["upload_url"]

        with file_path.open("rb") as f:
            put = client.put(
                upload_url,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes 0-{size - 1}/{size}",
                },
                content=f.read(),
            )
        if put.status_code not in (200, 201):
            raise UploadError(f"TikTok video upload failed: {put.status_code} {put.text}")

        # Publishing is asynchronous — poll briefly for a terminal status.
        for _ in range(10):
            status_resp = client.post(STATUS_URL, headers=headers, json={"publish_id": publish_id})
            status = status_resp.json().get("data", {}).get("status")
            if status == "PUBLISH_COMPLETE":
                break
            if status == "FAILED":
                raise UploadError(f"TikTok publish failed: {status_resp.json()}")
            time.sleep(2)

        return PostResult(remote_id=publish_id, remote_url="https://www.tiktok.com/")


def get_stats(token: str, remote_id: str) -> StatsResult:
    if not is_connected(token):
        raise NotConnectedError("No TikTok access token saved.")

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            QUERY_URL,
            params={"fields": "id,view_count"},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
            json={"filters": {"video_ids": [remote_id]}},
        )
    if resp.status_code != 200:
        raise UploadError(f"TikTok stats fetch failed: {resp.status_code} {resp.text}")
    videos = resp.json().get("data", {}).get("videos", [])
    if not videos:
        return StatsResult(views=0, watch_time_seconds=None)
    return StatsResult(views=int(videos[0].get("view_count", 0)), watch_time_seconds=None)
