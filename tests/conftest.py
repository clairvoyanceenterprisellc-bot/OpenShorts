import pytest

from openshorts.dashboard import db, pipeline


@pytest.fixture
def isolated_dashboard(tmp_path, monkeypatch):
    """Redirect the dashboard's db/downloads/clips storage into a temp dir
    for the duration of one test, so tests never touch a real ~/.openshorts."""
    db_path = tmp_path / "dashboard.db"
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "DOWNLOADS_DIR", tmp_path / "downloads")
    monkeypatch.setattr(pipeline, "CLIPS_DIR", tmp_path / "clips")
    db.init_db(db_path)
    return db_path
