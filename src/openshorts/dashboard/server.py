"""FastAPI app for the OpenShorts dashboard."""

from __future__ import annotations

import json
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from openshorts.dashboard import db, pipeline
from openshorts.dashboard.categorize import ALL_CATEGORIES, CATEGORY_LABELS
from openshorts.dashboard.metadata import build_description, build_title
from openshorts.dashboard.uploaders import REGISTRY as UPLOADERS
from openshorts.dashboard.uploaders import tiktok as tiktok_uploader
from openshorts.dashboard.uploaders.base import NotConnectedError, TokenExpiredError, UploadError

STATIC_DIR = Path(__file__).parent / "static"

# OAuth CSRF state tokens, in-memory: this is a single-process local
# dashboard, so there's no need for persistence, just a short-lived check
# that the callback matches a /start we actually issued.
_oauth_states: dict[str, float] = {}
_OAUTH_STATE_TTL = 600  # seconds


def _persist_token(platform: str, token: str, meta: dict | None = None) -> None:
    conn = db.connect()
    try:
        if meta is not None:
            conn.execute(
                "UPDATE connections SET access_token = ?, meta_json = ?, updated_at = ? WHERE platform = ?",
                (token, json.dumps(meta), time.time(), platform),
            )
        else:
            conn.execute(
                "UPDATE connections SET access_token = ?, updated_at = ? WHERE platform = ?",
                (token, time.time(), platform),
            )
        conn.commit()
    finally:
        conn.close()


def _call_with_refresh(platform: str, connection: dict, call):
    """Run `call(access_token)`; on a TokenExpiredError, refresh once (if the
    uploader supports it) and retry. `connection` is mutated in place so a
    caller looping over multiple calls for the same platform reuses the
    refreshed token instead of refreshing again on every iteration.

    `refresh_access_token` returns {"access_token": ..., **meta_updates} --
    some platforms (TikTok) rotate the refresh token on every use, so any
    extra keys beyond access_token get merged back into the saved meta,
    not just the token, or the *next* refresh would use a dead refresh_token.
    """
    try:
        return call(connection["access_token"])
    except TokenExpiredError:
        refresher = getattr(UPLOADERS[platform], "refresh_access_token", None)
        if not refresher:
            raise
        meta = json.loads(connection["meta_json"] or "{}")
        result = refresher(meta)
        new_token = result["access_token"]
        meta_updates = {k: v for k, v in result.items() if k != "access_token"}
        if meta_updates:
            meta.update(meta_updates)
            _persist_token(platform, new_token, meta)
            connection["meta_json"] = json.dumps(meta)
        else:
            _persist_token(platform, new_token)
        connection["access_token"] = new_token
        return call(new_token)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="OpenShorts Dashboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/terms")
def terms() -> FileResponse:
    return FileResponse(STATIC_DIR / "terms.html")


@app.get("/privacy")
def privacy() -> FileResponse:
    return FileResponse(STATIC_DIR / "privacy.html")


@app.get("/oauth/tiktok/callback/tiktokP07l0xDqtVcLCcQUjLmTpqSzUEyo80n4.txt")
def tiktok_domain_verification() -> PlainTextResponse:
    # TikTok's "URL properties" ownership check for the redirect URI, required
    # before submitting the app for Direct Post review. Static/one-time -- the
    # exact filename and token are whatever TikTok's dashboard generated.
    return PlainTextResponse("tiktok-developers-site-verification=P07l0xDqtVcLCcQUjLmTpqSzUEyo80n4")


# ---------------------------------------------------------------- sources --

class SourceIn(BaseModel):
    url_or_path: str
    title: Optional[str] = None
    threshold: float = 2.5
    min_gap_s: float = 15.0


@app.post("/api/sources")
def create_source(body: SourceIn, background_tasks: BackgroundTasks) -> dict:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO sources (url_or_path, title, status, created_at) VALUES (?, ?, 'queued', ?)",
            (body.url_or_path, body.title, time.time()),
        )
        conn.commit()
        source_id = cur.lastrowid
    finally:
        conn.close()

    background_tasks.add_task(
        pipeline.ingest_source, source_id, body.url_or_path,
        threshold=body.threshold, min_gap_s=body.min_gap_s,
    )
    return {"id": source_id, "status": "queued"}


@app.get("/api/sources")
def list_sources() -> list[dict]:
    conn = db.connect()
    try:
        rows = conn.execute("SELECT * FROM sources ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ------------------------------------------------------------------ clips --

class CategoryIn(BaseModel):
    category: str


@app.get("/api/clips")
def list_clips(category: Optional[str] = None) -> list[dict]:
    conn = db.connect()
    try:
        query = "SELECT * FROM clips"
        params: tuple = ()
        if category:
            query += " WHERE category = ?"
            params = (category,)
        query += " ORDER BY created_at DESC"
        clips = [dict(r) for r in conn.execute(query, params).fetchall()]

        for clip in clips:
            posts = conn.execute(
                "SELECT platform, remote_url, posted_at FROM posts WHERE clip_id = ? ORDER BY posted_at",
                (clip["id"],),
            ).fetchall()
            clip["posts"] = [dict(p) for p in posts]
            clip["category_label"] = CATEGORY_LABELS.get(clip["category"], clip["category"])
        return clips
    finally:
        conn.close()


@app.get("/api/clips/{clip_id}/file")
def get_clip_file(clip_id: int) -> FileResponse:
    conn = db.connect()
    try:
        row = conn.execute("SELECT file_path FROM clips WHERE id = ?", (clip_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(404, "Clip not found")
    path = Path(row["file_path"])
    if not path.exists():
        raise HTTPException(404, "Clip file missing on disk")
    return FileResponse(path, media_type="video/mp4")


@app.patch("/api/clips/{clip_id}")
def update_clip_category(clip_id: int, body: CategoryIn) -> dict:
    if body.category not in ALL_CATEGORIES:
        raise HTTPException(400, f"Unknown category. Must be one of {list(ALL_CATEGORIES)}")
    conn = db.connect()
    try:
        conn.execute("UPDATE clips SET category = ? WHERE id = ?", (body.category, clip_id))
        conn.commit()
    finally:
        conn.close()
    return {"id": clip_id, "category": body.category}


# ------------------------------------------------------------- connections --

class ConnectionIn(BaseModel):
    access_token: str
    meta: Optional[dict] = None


@app.get("/api/connections")
def list_connections() -> list[dict]:
    # meta_json holds secrets (refresh_token, client_secret, Instagram's own
    # access config) -- never return it verbatim, even though this endpoint
    # normally only serves localhost, since this dashboard may also be
    # reachable through a public tunnel (e.g. for Instagram's public_base_url).
    conn = db.connect()
    try:
        rows = conn.execute("SELECT * FROM connections").fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        token = d.pop("access_token", None) or ""
        d["token_preview"] = f"...{token[-4:]}" if token else None
        meta = json.loads(d.pop("meta_json", None) or "{}")
        d["has_meta"] = bool(meta)
        out.append(d)
    return out


@app.post("/api/connections/{platform}")
def save_connection(platform: str, body: ConnectionIn) -> dict:
    if platform not in UPLOADERS:
        raise HTTPException(404, f"Unknown platform '{platform}'")
    uploader = UPLOADERS[platform]
    connected = uploader.is_connected(body.access_token)
    conn = db.connect()
    try:
        conn.execute(
            """INSERT INTO connections (platform, access_token, meta_json, connected, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(platform) DO UPDATE SET
                 access_token = excluded.access_token,
                 meta_json = excluded.meta_json,
                 connected = excluded.connected,
                 updated_at = excluded.updated_at""",
            (platform, body.access_token, json.dumps(body.meta or {}), int(connected), time.time()),
        )
        conn.commit()
    finally:
        conn.close()
    return {"platform": platform, "connected": connected}


@app.delete("/api/connections/{platform}")
def clear_connection(platform: str) -> dict:
    conn = db.connect()
    try:
        conn.execute(
            "UPDATE connections SET access_token = NULL, connected = 0, updated_at = ? WHERE platform = ?",
            (time.time(), platform),
        )
        conn.commit()
    finally:
        conn.close()
    return {"platform": platform, "connected": False}


# ------------------------------------------------------------- tiktok oauth --
# TikTok requires an HTTPS redirect URI (no localhost, unlike Google), so
# this goes through real server routes behind a public tunnel rather than a
# throwaway local server. See scripts/get_youtube_token.py's docstring and
# README for the Google-vs-TikTok redirect difference.

def _cleanup_oauth_states() -> None:
    cutoff = time.time() - _OAUTH_STATE_TTL
    for s in [s for s, ts in _oauth_states.items() if ts < cutoff]:
        del _oauth_states[s]


@app.get("/oauth/tiktok/start")
def tiktok_oauth_start():
    config = tiktok_uploader.load_app_config()
    if not config:
        raise HTTPException(
            400,
            f"No TikTok app config saved at {tiktok_uploader.APP_CONFIG_FILE}. "
            f"Needs client_key, client_secret, redirect_uri from your TikTok Developer app.",
        )
    _cleanup_oauth_states()
    state = secrets.token_urlsafe(16)
    _oauth_states[state] = time.time()
    url = tiktok_uploader.build_authorize_url(config["client_key"], config["redirect_uri"], state)
    return RedirectResponse(url)


@app.get("/oauth/tiktok/callback")
def tiktok_oauth_callback(
    code: Optional[str] = None, state: Optional[str] = None,
    error: Optional[str] = None, error_description: Optional[str] = None,
):
    if error:
        return HTMLResponse(f"<h1>TikTok authorization failed</h1><p>{error}: {error_description}</p>", status_code=400)
    if not state or state not in _oauth_states:
        raise HTTPException(400, "Invalid or expired OAuth state -- start over from the Connections tab.")
    del _oauth_states[state]
    if not code:
        raise HTTPException(400, "TikTok didn't return an authorization code.")

    config = tiktok_uploader.load_app_config()
    if not config:
        raise HTTPException(400, f"No TikTok app config saved at {tiktok_uploader.APP_CONFIG_FILE}.")

    token_data = tiktok_uploader.exchange_code(
        config["client_key"], config["client_secret"], code, config["redirect_uri"],
    )
    meta = {
        "refresh_token": token_data.get("refresh_token"),
        "client_key": config["client_key"],
        "client_secret": config["client_secret"],
        "open_id": token_data.get("open_id"),
    }
    conn = db.connect()
    try:
        conn.execute(
            """INSERT INTO connections (platform, access_token, meta_json, connected, updated_at)
               VALUES ('tiktok', ?, ?, 1, ?)
               ON CONFLICT(platform) DO UPDATE SET
                 access_token = excluded.access_token, meta_json = excluded.meta_json,
                 connected = excluded.connected, updated_at = excluded.updated_at""",
            (token_data["access_token"], json.dumps(meta), time.time()),
        )
        conn.commit()
    finally:
        conn.close()

    return HTMLResponse(
        "<h1>TikTok connected</h1><p>You can close this tab and go back to the OpenShorts dashboard.</p>"
    )


# -------------------------------------------------------------------- post --

class PostIn(BaseModel):
    platform: str
    title: Optional[str] = None
    description: Optional[str] = None


@app.post("/api/clips/{clip_id}/post")
def post_clip(clip_id: int, body: PostIn) -> dict:
    if body.platform not in UPLOADERS:
        raise HTTPException(404, f"Unknown platform '{body.platform}'")

    conn = db.connect()
    try:
        clip_row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
        if not clip_row:
            raise HTTPException(404, "Clip not found")
        existing_post = conn.execute(
            "SELECT * FROM posts WHERE clip_id = ? AND platform = ?", (clip_id, body.platform)
        ).fetchone()
        connection_row = conn.execute(
            "SELECT * FROM connections WHERE platform = ?", (body.platform,)
        ).fetchone()
    finally:
        conn.close()

    if existing_post:
        # Enforced server-side, not just a disabled button -- a clip never goes
        # out twice to the same platform, no matter how the request got sent.
        raise HTTPException(
            409,
            f"This clip was already posted to {body.platform} "
            f"({existing_post['remote_url'] or existing_post['remote_id']}).",
        )

    if not connection_row or not connection_row["connected"]:
        raise HTTPException(
            400,
            f"{body.platform} isn't connected yet. Add an access token in the Connections tab first.",
        )

    clip = dict(clip_row)
    title = body.title or build_title(clip)
    description = body.description if body.description is not None else build_description(clip, body.platform)

    connection = dict(connection_row)
    uploader = UPLOADERS[body.platform]
    extra = json.loads(connection["meta_json"] or "{}")
    try:
        result = _call_with_refresh(
            body.platform,
            connection,
            lambda token: uploader.upload(
                token, Path(clip["file_path"]), title, description, clip_id=clip["id"], **extra
            ),
        )
    except NotConnectedError as exc:
        raise HTTPException(400, str(exc)) from exc
    except UploadError as exc:
        raise HTTPException(502, str(exc)) from exc

    conn = db.connect()
    try:
        conn.execute(
            """INSERT INTO posts (clip_id, platform, remote_id, remote_url, status, posted_at)
               VALUES (?, ?, ?, ?, 'posted', ?)""",
            (clip_id, body.platform, result.remote_id, result.remote_url, time.time()),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "platform": body.platform, "remote_id": result.remote_id, "remote_url": result.remote_url,
        "title": title,
    }


# ------------------------------------------------------------------- stats --

@app.get("/api/stats")
def get_stats() -> dict:
    conn = db.connect()
    try:
        posts = conn.execute(
            """SELECT p.id, p.clip_id, p.platform, p.remote_id, p.remote_url, c.category
               FROM posts p JOIN clips c ON c.id = p.clip_id"""
        ).fetchall()

        total_views = 0
        total_watch_time = 0.0
        by_platform: dict[str, dict] = {}
        best = None  # (views, post_row)

        for post in posts:
            latest = conn.execute(
                "SELECT * FROM stats WHERE post_id = ? ORDER BY fetched_at DESC LIMIT 1",
                (post["id"],),
            ).fetchone()
            views = latest["views"] if latest else 0
            watch_time = (latest["watch_time_seconds"] or 0) if latest else 0

            total_views += views
            total_watch_time += watch_time

            bucket = by_platform.setdefault(post["platform"], {"views": 0, "watch_time_seconds": 0, "posts": 0})
            bucket["views"] += views
            bucket["watch_time_seconds"] += watch_time
            bucket["posts"] += 1

            if best is None or views > best[0]:
                best = (views, dict(post))

        return {
            "total_views": total_views,
            "total_watch_time_seconds": total_watch_time,
            "by_platform": by_platform,
            "best_performing": best[1] if best else None,
            "has_connections": any(
                dict(r)["connected"] for r in conn.execute("SELECT connected FROM connections").fetchall()
            ),
        }
    finally:
        conn.close()


@app.post("/api/stats/refresh")
def refresh_stats() -> dict:
    conn = db.connect()
    try:
        connections = {r["platform"]: dict(r) for r in conn.execute("SELECT * FROM connections").fetchall()}
        posts = conn.execute("SELECT * FROM posts").fetchall()

        refreshed, failed = 0, 0
        for post in posts:
            connection = connections.get(post["platform"])
            if not connection or not connection["connected"]:
                continue
            uploader = UPLOADERS[post["platform"]]
            try:
                stats = _call_with_refresh(
                    post["platform"], connection,
                    lambda token: uploader.get_stats(token, post["remote_id"]),
                )
            except (NotConnectedError, UploadError):
                failed += 1
                continue
            conn.execute(
                """INSERT INTO stats (post_id, views, watch_time_seconds, fetched_at)
                   VALUES (?, ?, ?, ?)""",
                (post["id"], stats.views, stats.watch_time_seconds, time.time()),
            )
            refreshed += 1
        conn.commit()
        return {"refreshed": refreshed, "failed": failed}
    finally:
        conn.close()
