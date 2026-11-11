"""Instagram Graph API uploader (Reels, via a connected Facebook Page/IG Business account).

Real constraint worth knowing up front: Instagram's media-publishing endpoint
takes a `video_url` it fetches server-side — it does not accept raw file
bytes from your machine. That means your clip needs to be reachable at a
public HTTPS URL before Instagram can ingest it, which a localhost dashboard
can't provide on its own. Set `public_base_url` in the Instagram connection
(Connections tab) to wherever the dashboard itself is publicly reachable from
(e.g. a Cloudflare Tunnel pointed at it) — `upload()` raises `UploadError`
with this explanation if it's missing, rather than silently failing. The
video URL handed to Instagram is that base URL plus this dashboard's own
`/api/clips/{id}/file` route (by clip id, not filename) — so `public_base_url`
needs to point at the dashboard, not at a separate file host.

Needs an access token for an Instagram Business/Creator account linked to a
Facebook Page, with `instagram_content_publish` permission.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from openshorts.dashboard.uploaders.base import NotConnectedError, PostResult, StatsResult, UploadError

platform = "instagram"

GRAPH_BASE = "https://graph.facebook.com/v19.0"


def is_connected(token: str) -> bool:
    return bool(token) and len(token) > 20


def upload(
    token: str,
    file_path: Path,
    title: str,
    description: str,
    clip_id: int | None = None,
    ig_user_id: str | None = None,
    public_base_url: str | None = None,
    **_ignored,
) -> PostResult:
    if not is_connected(token):
        raise NotConnectedError("No Instagram access token saved.")
    if not ig_user_id:
        raise UploadError("No Instagram Business account id configured (set it in Connections).")
    if not public_base_url:
        raise UploadError(
            "Instagram needs clips at a public URL, not a local file. Set 'public_base_url' on the "
            "Instagram connection to wherever this dashboard is publicly reachable from (e.g. a "
            "Cloudflare Tunnel pointed at it)."
        )
    if clip_id is None:
        raise UploadError("Instagram upload needs the clip's id to build its public URL.")

    video_url = f"{public_base_url.rstrip('/')}/api/clips/{clip_id}/file"

    with httpx.Client(timeout=60.0) as client:
        create = client.post(
            f"{GRAPH_BASE}/{ig_user_id}/media",
            data={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": description[:2200] or title,
                "access_token": token,
            },
        )
        create_body = create.json()
        if create.status_code != 200 or "id" not in create_body:
            raise UploadError(f"Instagram media create failed: {create.status_code} {create_body}")
        creation_id = create_body["id"]

        for _ in range(30):
            status = client.get(
                f"{GRAPH_BASE}/{creation_id}",
                params={"fields": "status_code", "access_token": token},
            )
            status_code = status.json().get("status_code")
            if status_code == "FINISHED":
                break
            if status_code == "ERROR":
                raise UploadError(f"Instagram media processing failed: {status.json()}")
            time.sleep(3)

        publish = client.post(
            f"{GRAPH_BASE}/{ig_user_id}/media_publish",
            data={"creation_id": creation_id, "access_token": token},
        )
        publish_body = publish.json()
        if publish.status_code != 200 or "id" not in publish_body:
            raise UploadError(f"Instagram publish failed: {publish.status_code} {publish_body}")

        media_id = publish_body["id"]
        return PostResult(remote_id=media_id, remote_url=f"https://www.instagram.com/reel/{media_id}/")


def get_stats(token: str, remote_id: str) -> StatsResult:
    if not is_connected(token):
        raise NotConnectedError("No Instagram access token saved.")

    with httpx.Client(timeout=30.0) as client:
        resp = client.get(
            f"{GRAPH_BASE}/{remote_id}/insights",
            params={"metric": "plays,reach", "access_token": token},
        )
    if resp.status_code != 200:
        raise UploadError(f"Instagram stats fetch failed: {resp.status_code} {resp.text}")
    values = {item["name"]: item["values"][0]["value"] for item in resp.json().get("data", [])}
    return StatsResult(views=int(values.get("plays", 0)), watch_time_seconds=None)
