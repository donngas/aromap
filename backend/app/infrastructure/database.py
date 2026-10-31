"""Small SQLite registry; never holds user projects or image bytes."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS uploads (
                    id TEXT PRIMARY KEY,
                    relative_path TEXT NOT NULL,
                    width_px INTEGER NOT NULL,
                    height_px INTEGER NOT NULL,
                    media_type TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK (kind IN ('recognition', 'simulation')),
                    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'succeeded', 'failed')),
                    image_id TEXT REFERENCES uploads(id),
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    result_path TEXT,
                    error_code TEXT,
                    error_message TEXT
                );
                CREATE INDEX IF NOT EXISTS jobs_image_state ON jobs(image_id, state);
                CREATE INDEX IF NOT EXISTS jobs_expiry ON jobs(expires_at);
                CREATE INDEX IF NOT EXISTS uploads_expiry ON uploads(expires_at);
            """)
