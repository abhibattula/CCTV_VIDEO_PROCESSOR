import sqlite3
import threading
from typing import Optional

_local = threading.local()


def get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        from app.config import DATA_DIR
        db_path = DATA_DIR.parent / "cctv_analyst.db"
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id               TEXT PRIMARY KEY,
            status           TEXT NOT NULL DEFAULT 'queued',
            source_path      TEXT NOT NULL,
            source_name      TEXT NOT NULL,
            duration_s       REAL,
            source_fps       REAL,
            source_width     INTEGER,
            source_height    INTEGER,
            source_codec     TEXT,
            source_has_audio INTEGER DEFAULT 0,
            needs_reencode   INTEGER DEFAULT 0,
            file_size        INTEGER,
            settings         TEXT NOT NULL,
            created_at       TEXT NOT NULL,
            scheduled_at     TEXT,
            started_at       TEXT,
            finished_at      TEXT,
            error_msg        TEXT,
            phase            TEXT,
            progress         REAL DEFAULT 0,
            output_path      TEXT,
            output_name      TEXT,
            output_size      INTEGER,
            recording_start  TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_status     ON jobs(status);
        CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);

        CREATE TABLE IF NOT EXISTS events (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id            TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            event_index       INTEGER NOT NULL,
            start_s           REAL NOT NULL,
            end_s             REAL NOT NULL,
            duration_s        REAL GENERATED ALWAYS AS (end_s - start_s) STORED,
            start_clock       TEXT,
            end_clock         TEXT,
            peak_motion_score REAL,
            zone_label        TEXT,
            tag               TEXT,
            included          INTEGER NOT NULL DEFAULT 1,
            thumbnail_path    TEXT,
            created_at        TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_events_job_id       ON events(job_id);
        CREATE INDEX IF NOT EXISTS idx_events_job_included ON events(job_id, included);

        CREATE TABLE IF NOT EXISTS exports (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id            TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            output_path       TEXT NOT NULL,
            output_name       TEXT NOT NULL,
            output_size       INTEGER,
            created_at        TEXT NOT NULL,
            settings_snapshot TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_exports_job_id ON exports(job_id);

        CREATE TABLE IF NOT EXISTS audit_log (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            ts      TEXT NOT NULL,
            level   TEXT NOT NULL,
            actor   TEXT NOT NULL,
            action  TEXT NOT NULL,
            detail  TEXT,
            job_id  TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_audit_ts     ON audit_log(ts DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_job_id ON audit_log(job_id);
        CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
    """)
    conn.commit()
