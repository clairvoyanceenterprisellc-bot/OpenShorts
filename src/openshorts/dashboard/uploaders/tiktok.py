"""TikTok Content Posting API (Direct Post) uploader.

Needs an access token from a TikTok for Developers app with the
`video.publish` scope, obtained via the real OAuth flow (build_authorize_url
+ exchange_code below) -- unlike Google, TikTok requires an HTTPS redirect
URI, so this goes through server.py's /oauth/tiktok/start and
/oauth/tiktok/callback routes rather than a local throwaway server.

Posts use `privacy_level: SELF_ONLY` — confirmed by testing against the real
API, not an assumption: an unaudited app's /publish/video/init/ call is hard
*rejected* (403 `unaudited_client_can_only_post_to_private_accounts`) for
anything else, even PUBLIC_TO_EVERYONE against an account that's itself set
to private. Once your app passes TikTok's audit for Direct Post, change this
to PUBLIC_TO_EVERYONE to actually post publicly -- until then, every post
here is visible only to the posting account, and that's a TikTok-side
restriction this code can't override.

Access tokens are short-lived (2 hours); refresh_access_token trades the
saved refresh_token (180-day lifetime, rotates on every use) for a new one,
wired into the same TokenExpiredError-triggered auto-refresh as youtube.py.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from openshorts.dashboard import db
from openshorts.dashboard.uploaders.base import (
    NotConnectedError,
    PostResult,
    StatsResult,
    TokenExpiredError,
    UploadError,
)

platform = "tiktok"

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
QUERY_URL = "https://open.tiktokapis.com/v2/video/query/"

SCOPES = "user.info.basic,video.publish"

# App-level credentials (client_key/client_secret/redirect_uri) for the
# TikTok Developer app itself -- distinct from a user's access token, so
# this lives in its own file rather than the connections table's meta_json.
# {"client_key": "...", "client_secret": "...", "redirect_uri": "https://.../oauth/tiktok/callback"}
APP_CONFIG_FILE = db.APP_DIR / "tiktok_app.json"


def load_app_config() -> dict | None:
    if not APP_CONFIG_FILE.exists():
        return None
    return json.loads(APP_CONFIG_FILE.read_text())


def is_connected(token: str) -> bool:
    return bool(token) and len(token) > 20


def build_authorize_url(client_key: str, redirect_uri: str, state: str) -> str:
    import urllib.parse

    params = {
        "client_key": client_key,
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(client_key: str, client_secret: str, code: str, redirect_uri: str) -> dict:
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key": client_key,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
    body = resp.json()
    if resp.status_code != 200 or "access_token" not in body:
        raise UploadError(f"TikTok token exchange failed: {resp.status_code} {body}")
    return body


def refresh_access_token(meta: dict) -> dict:
    """Returns {"access_token": ..., "refresh_token": ...}.

    TikTok rotates the refresh token on every use -- the old one stops
    working the moment a new one is issued. Returning it alongside the
    access token (rather than just a bare string) lets server.py persist
    both, so the *next* refresh doesn't fail with a stale refresh_token.
    """
    missing = [k for k in ("refresh_token", "client_key", "client_secret") if not meta.get(k)]
    if missing:
        raise UploadError(f"Can't refresh TikTok token (missing {', '.join(missing)}) — reconnect via TikTok OAuth.")
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key": meta["client_key"],
                "client_secret": meta["client_secret"],
                "grant_type": "refresh_token",
                "refresh_token": meta["refresh_token"],
            },
        )
    body = resp.json()
    if resp.status_code != 200 or "access_token" not in body:
        raise UploadError(f"TikTok token refresh failed: {resp.status_code} {body}")
    return {"access_token": body["access_token"], "refresh_token": body.get("refresh_token", meta["refresh_token"])}


def upload(token: str, file_path: Path, title: str, description: str, **_ignored) -> PostResult:
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
                # TikTok's "title" field is the full caption shown with the video, same role
                # as description on other platforms -- hashtags/mentions need no special
                # syntax, just space/newline separation (which build_description already
                # produces). Real limit is 2200 UTF-16 code units, not the 150 this used to
                # assume. `title` alone (the bare clip title with no hashtags) is unused here.
                "post_info": {"title": description[:2200], "privacy_level": "SELF_ONLY"},
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": size,
                    "chunk_size": size,
                    "total_chunk_count": 1,
                },
            },
        )
        body = init.json()
        if init.status_code == 401:
            raise TokenExpiredError(f"TikTok publish init failed: {init.status_code} {body}")
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
        if put.status_code == 401:
            raise TokenExpiredError(f"TikTok video upload failed: {put.status_code} {put.text}")
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
    if resp.status_code == 401:
        raise TokenExpiredError(f"TikTok stats fetch failed: {resp.status_code} {resp.text}")
    if resp.status_code != 200:
        raise UploadError(f"TikTok stats fetch failed: {resp.status_code} {resp.text}")
    videos = resp.json().get("data", {}).get("videos", [])
    if not videos:
        return StatsResult(views=0, watch_time_seconds=None)
    return StatsResult(views=int(videos[0].get("view_count", 0)), watch_time_seconds=None)
