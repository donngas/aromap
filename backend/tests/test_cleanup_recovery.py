"""Crash recovery for the filesystem/SQLite publication boundary."""

import os
import time

from app.config import Settings
from app.infrastructure.database import Database
from app.infrastructure.jobs import Jobs
from app.infrastructure.storage import LocalStorage


def test_cleanup_recovers_missing_files_and_prunes_only_old_orphans(tmp_path):
    storage = LocalStorage(tmp_path)
    database = Database(tmp_path / "registry.sqlite3")
    database.initialize()
    now = time.time()
    with database.connect() as db:
        db.execute("INSERT INTO uploads VALUES (?, ?, ?, ?, ?, ?, ?)",
                   ("missing", "uploads/missing/image.png", 1, 1, "image/png", now - 100, now - 50))
        db.execute("INSERT INTO jobs (id,kind,state,created_at,updated_at,expires_at) "
                   "VALUES ('active','recognition','running',?,?,?)", (now, now, now - 50))
    paths = ["uploads/orphan/image.png", "results/orphan.json", "results/.interrupted.tmp",
             "results/active.json", "uploads/fresh/image.png"]
    for relative in paths:
        path = storage.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"artifact")
        if "fresh" not in relative:
            os.utime(path, (now - 100, now - 100))
    jobs = Jobs(Settings(data_dir=tmp_path, retention_seconds=10), database, storage)
    jobs.cleanup()
    jobs.cleanup()
    assert not any(storage.path(path).exists() for path in paths[:3])
    assert all(storage.path(path).exists() for path in paths[3:])
    with database.connect() as db:
        assert db.execute("SELECT count(*) FROM uploads").fetchone()[0] == 0
        assert db.execute("SELECT state FROM jobs").fetchone()[0] == "running"
