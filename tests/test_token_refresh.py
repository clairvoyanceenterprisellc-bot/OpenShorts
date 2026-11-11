"""Tests the auto-refresh path: an expired token should get silently refreshed
and the call retried, with the new token persisted back to the connection --
no re-auth, no user-visible error.
"""

import json
import time
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openshorts.dashboard import db, server
from openshorts.dashboard.server import app
from openshorts.dashboard.uploaders.base import PostResult, StatsResult, TokenExpiredError


def _make_fake_uploader(refresh_meta_seen: list):
    """A fake platform module: first call with the stale token raises
    TokenExpiredError, refresh_access_token mints a new one, and the retried
    call with the new token succeeds."""

    def upload(token, file_path, title, description, **_ignored):
        if token == "stale-token":
            raise TokenExpiredError("401")
        assert token == "fresh-token"
        return PostResult(remote_id="vid123", remote_url="https://youtu.be/vid123")

    def get_stats(token, remote_id):
        if token == "stale-token":
            raise TokenExpiredError("401")
        assert token == "fresh-token"
        return StatsResult(views=42, watch_time_seconds=100.0)

    def refresh_access_token(meta):
        refresh_meta_seen.append(meta)
        return "fresh-token"

    def is_connected(token):
        return bool(token)

    return types.SimpleNamespace(
        upload=upload, get_stats=get_stats, refresh_access_token=refresh_access_token,
        is_connected=is_connected, platform="youtube",
    )


def _seed_connection(db_path, meta: dict) -> None:
    conn = db.connect(db_path)
    try:
        conn.execute(
            """INSERT INTO connections (platform, access_token, meta_json, connected, updated_at)
               VALUES ('youtube', 'stale-token', ?, 1, ?)
               ON CONFLICT(platform) DO UPDATE SET
                 access_token = excluded.access_token, meta_json = excluded.meta_json,
                 connected = excluded.connected, updated_at = excluded.updated_at""",
            (json.dumps(meta), time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_clip_and_post(db_path, tmp_path) -> int:
    conn = db.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO sources (id, url_or_path, status, created_at) VALUES (1, 'x.mp4', 'done', ?)",
            (time.time(),),
        )
        clip_file = tmp_path / "clip.mp4"
        clip_file.write_bytes(b"fake")
        cur = conn.execute(
            """INSERT INTO clips (source_id, file_path, category, peak_time, score, created_at)
               VALUES (1, ?, 'best_moments', 5.0, 3.0, ?)""",
            (str(clip_file), time.time()),
        )
        clip_id = cur.lastrowid
        conn.commit()
        return clip_id
    finally:
        conn.close()


@pytest.fixture
def fake_youtube(monkeypatch):
    seen_meta = []
    fake = _make_fake_uploader(seen_meta)
    monkeypatch.setitem(server.UPLOADERS, "youtube", fake)
    return seen_meta


def test_post_clip_refreshes_expired_token_and_retries(isolated_dashboard, tmp_path, fake_youtube):
    meta = {"refresh_token": "rt", "client_id": "cid", "client_secret": "csec"}
    _seed_connection(isolated_dashboard, meta)
    clip_id = _seed_clip_and_post(isolated_dashboard, tmp_path)

    client = TestClient(app)
    resp = client.post(f"/api/clips/{clip_id}/post", json={"platform": "youtube"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["remote_id"] == "vid123"
    assert fake_youtube == [meta]  # refresh_access_token was called exactly once, with the saved meta

    conn = db.connect(isolated_dashboard)
    row = conn.execute("SELECT access_token FROM connections WHERE platform='youtube'").fetchone()
    conn.close()
    assert row["access_token"] == "fresh-token"  # persisted back for next time


def test_stats_refresh_refreshes_expired_token_and_retries(isolated_dashboard, tmp_path, fake_youtube):
    meta = {"refresh_token": "rt", "client_id": "cid", "client_secret": "csec"}
    _seed_connection(isolated_dashboard, meta)
    clip_id = _seed_clip_and_post(isolated_dashboard, tmp_path)

    conn = db.connect(isolated_dashboard)
    conn.execute(
        """INSERT INTO posts (clip_id, platform, remote_id, remote_url, status, posted_at)
           VALUES (?, 'youtube', 'vid123', 'https://youtu.be/vid123', 'posted', ?)""",
        (clip_id, time.time()),
    )
    conn.commit()
    conn.close()

    client = TestClient(app)
    resp = client.post("/api/stats/refresh")

    assert resp.status_code == 200
    assert resp.json() == {"refreshed": 1, "failed": 0}

    stats = client.get("/api/stats").json()
    assert stats["total_views"] == 42
    assert stats["total_watch_time_seconds"] == 100.0


def test_upload_with_no_refresh_support_surfaces_as_upload_error(isolated_dashboard, tmp_path, monkeypatch):
    def upload(token, file_path, title, description, **_ignored):
        raise TokenExpiredError("401, and this module has no refresh_access_token")

    fake_no_refresh = types.SimpleNamespace(upload=upload, is_connected=lambda t: bool(t), platform="youtube")
    monkeypatch.setitem(server.UPLOADERS, "youtube", fake_no_refresh)

    _seed_connection(isolated_dashboard, meta={})
    clip_id = _seed_clip_and_post(isolated_dashboard, tmp_path)

    client = TestClient(app)
    resp = client.post(f"/api/clips/{clip_id}/post", json={"platform": "youtube"})
    assert resp.status_code == 502  # bubbles up as a normal failure instead of crashing
