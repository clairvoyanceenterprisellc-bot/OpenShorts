"""Turns a dropped stream/video link (or local file) into categorized clips."""

from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlparse

from openshorts.dashboard import db
from openshorts.dashboard.categorize import assign_categories
from openshorts.detect import detect_highlights
from openshorts.ffmpeg_utils import cut_clip

DATA_DIR = db.APP_DIR
DOWNLOADS_DIR = DATA_DIR / "downloads"
CLIPS_DIR = DATA_DIR / "clips"


def _is_url(value: str) -> bool:
    return urlparse(value).scheme in ("http", "https")


def _set_status(conn, source_id: int, status: str, error: str | None = None) -> None:
    conn.execute(
        "UPDATE sources SET status = ?, error = ? WHERE id = ?",
        (status, error, source_id),
    )
    conn.commit()


def _download(url: str, source_id: int) -> Path:
    import yt_dlp  # imported lazily: only needed when a URL is dropped in

    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out_template = str(DOWNLOADS_DIR / f"source_{source_id}.%(ext)s")
    opts = {
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "outtmpl": out_template,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info))
        if not path.exists():
            # merge_output_format can change the extension after download
            mp4_path = path.with_suffix(".mp4")
            if mp4_path.exists():
                path = mp4_path
        return path


def ingest_source(source_id: int, url_or_path: str, db_path: Path | None = None) -> None:
    """Run the full pipeline for one source: download -> detect -> cut -> categorize.

    Meant to run as a background task; all state transitions are written to
    the `sources`/`clips` tables so the UI can poll for progress.
    """
    conn = db.connect(db_path)
    try:
        if _is_url(url_or_path):
            _set_status(conn, source_id, "downloading")
            video_path = _download(url_or_path, source_id)
        else:
            video_path = Path(url_or_path)
            if not video_path.exists():
                raise FileNotFoundError(f"No such file: {video_path}")

        _set_status(conn, source_id, "detecting")
        highlights = detect_highlights(video_path)

        if not highlights:
            _set_status(conn, source_id, "done")
            return

        categories = assign_categories([h.score for h in highlights])

        _set_status(conn, source_id, "clipping")
        for i, (highlight, category) in enumerate(zip(highlights, categories), start=1):
            category_dir = CLIPS_DIR / category
            clip_path = category_dir / f"source_{source_id}_clip{i:02d}.mp4"
            cut_clip(video_path, clip_path, highlight.clip_start, highlight.clip_duration)
            conn.execute(
                """INSERT INTO clips (source_id, file_path, category, peak_time, score, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (source_id, str(clip_path), category, highlight.time, highlight.score, time.time()),
            )
            conn.commit()

        _set_status(conn, source_id, "done")
    except Exception as exc:  # pipeline runs in a background task — surface the error, don't crash it
        _set_status(conn, source_id, "error", error=str(exc))
    finally:
        conn.close()
