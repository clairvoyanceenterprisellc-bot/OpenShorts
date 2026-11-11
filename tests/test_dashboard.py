"""End-to-end test of the dashboard API against a real synthetic video.

Uses temp dirs for the db/data so it never touches a real ~/.openshorts.
"""

import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openshorts.dashboard import db, pipeline
from openshorts.dashboard.server import app

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH"
)


@pytest.fixture
def isolated_dashboard(tmp_path, monkeypatch):
    db_path = tmp_path / "dashboard.db"
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "DOWNLOADS_DIR", tmp_path / "downloads")
    monkeypatch.setattr(pipeline, "CLIPS_DIR", tmp_path / "clips")
    db.init_db(db_path)
    return db_path


@pytest.fixture
def synthetic_video(tmp_path: Path) -> Path:
    out = tmp_path / "session.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=16:r=10",
            "-f", "lavfi", "-i", "sine=frequency=220:duration=16,volume=0.05",
            "-f", "lavfi", "-i", "sine=frequency=880:duration=1,volume=12,adelay=8000|8000",
            "-filter_complex", "[1:a][2:a]amix=inputs=2:duration=first:dropout_transition=0[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
            "-t", "16",
            str(out),
        ],
        check=True, capture_output=True,
    )
    return out


@requires_ffmpeg
def test_full_pipeline_via_api(isolated_dashboard, synthetic_video):
    client = TestClient(app)

    resp = client.post("/api/sources", json={"url_or_path": str(synthetic_video)})
    assert resp.status_code == 200
    source_id = resp.json()["id"]

    # TestClient runs BackgroundTasks synchronously before returning the response,
    # but ours is scheduled on the response itself -- poll briefly for "done".
    for _ in range(30):
        sources = client.get("/api/sources").json()
        status = next(s["status"] for s in sources if s["id"] == source_id)
        if status in ("done", "error"):
            break
        time.sleep(1)
    assert status == "done", sources

    clips = client.get("/api/clips").json()
    assert len(clips) == 1
    clip = clips[0]
    assert clip["category"] == "best_moments"  # the only highlight in the session
    assert clip["posts"] == []

    # clip file is actually servable
    file_resp = client.get(f"/api/clips/{clip['id']}/file")
    assert file_resp.status_code == 200
    assert file_resp.headers["content-type"] == "video/mp4"

    # recategorize
    patch_resp = client.patch(f"/api/clips/{clip['id']}", json={"category": "funny"})
    assert patch_resp.status_code == 200
    assert client.get("/api/clips?category=funny").json()[0]["id"] == clip["id"]

    # connections start out disconnected
    connections = client.get("/api/connections").json()
    assert all(c["connected"] == 0 for c in connections)

    # posting to an unconnected platform is rejected, not silently faked
    post_resp = client.post(f"/api/clips/{clip['id']}/post", json={"platform": "youtube"})
    assert post_resp.status_code == 400

    # saving an obviously-too-short token does not mark the platform connected
    save_resp = client.post("/api/connections/youtube", json={"access_token": "short"})
    assert save_resp.json()["connected"] is False

    # stats are honest about having nothing to show yet
    stats = client.get("/api/stats").json()
    assert stats["total_views"] == 0
    assert stats["has_connections"] is False
