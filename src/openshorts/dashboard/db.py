"""SQLite storage for the dashboard.

One connection is opened per call — sqlite3 connections aren't safe to share
across threads, and FastAPI's BackgroundTasks run in a thread pool.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

APP_DIR = Path.home() / ".openshorts"
DEFAULT_DB_PATH = APP_DIR / "dashboard.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url_or_path TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    error TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    file_path TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'unsorted',
    peak_time REAL NOT NULL,
    score REAL NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS connections (
    platform TEXT PRIMARY KEY,
    access_token TEXT,
    meta_json TEXT,
    connected INTEGER NOT NULL DEFAULT 0,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_id INTEGER NOT NULL REFERENCES clips(id),
    platform TEXT NOT NULL,
    remote_id TEXT,
    remote_url TEXT,
    status TEXT NOT NULL DEFAULT 'posted',
    error TEXT,
    posted_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL REFERENCES posts(id),
    views INTEGER NOT NULL DEFAULT 0,
    watch_time_seconds REAL,
    fetched_at REAL NOT NULL
);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    # Resolved against the module global at call time (not frozen as a default
    # argument) so tests can redirect storage by patching DEFAULT_DB_PATH.
    db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        for platform in ("youtube", "tiktok", "instagram"):
            conn.execute(
                "INSERT OR IGNORE INTO connections (platform, connected, updated_at) VALUES (?, 0, ?)",
                (platform, time.time()),
            )
        conn.commit()
    finally:
        conn.close()
