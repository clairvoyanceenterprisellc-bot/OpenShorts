"""Common interface every platform uploader implements.

Each uploader does real HTTP calls against the platform's official API —
there's no simulated/fake-success mode. Until a valid access token is saved
for a platform (Connections tab), `is_connected` stays False and the
dashboard disables posting to it rather than pretending the call worked.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class NotConnectedError(RuntimeError):
    """Raised when an upload/stats call is attempted without a usable token."""


class UploadError(RuntimeError):
    """Raised when the platform's API rejects the request."""


class TokenExpiredError(UploadError):
    """Raised specifically for a 401 — the dashboard catches this one to try a refresh.

    An uploader module that wants auto-refresh support raises this (rather than
    a plain UploadError) on an auth failure, and exposes a module-level
    `refresh_access_token(meta: dict) -> str`. Modules without that function
    just never raise this, and expired tokens surface as a normal UploadError.
    """


@dataclass
class PostResult:
    remote_id: str
    remote_url: str


@dataclass
class StatsResult:
    views: int
    watch_time_seconds: float | None  # None when the platform/scope doesn't expose it


class Uploader(Protocol):
    platform: str

    def is_connected(self, token: str) -> bool: ...

    def upload(self, token: str, file_path: Path, title: str, description: str) -> PostResult: ...

    def get_stats(self, token: str, remote_id: str) -> StatsResult: ...
