# Data Model: RasPi CCTV Analyst — v1 Core Pipeline

**Branch**: `001-raspi-cctv-v1-core` | **Date**: 2026-05-05

---

## SQLite Schema (cctv_analyst.db)

All tables created idempotently via `CREATE TABLE IF NOT EXISTS`. WAL mode enabled at connection init.

### Table: jobs

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id               TEXT PRIMARY KEY,          -- UUID4
    status           TEXT NOT NULL DEFAULT 'queued',
    -- Valid statuses: queued | running | detecting | exporting | completed | failed | cancelled
    source_path      TEXT NOT NULL,             -- Absolute path to source video on Pi filesystem
    source_name      TEXT NOT NULL,             -- Filename only (for display)
    duration_s       REAL,                      -- Source duration in seconds (from ffprobe)
    source_fps       REAL,                      -- avg_frame_rate from ffprobe (not r_frame_rate)
    source_width     INTEGER,                   -- Source resolution width
    source_height    INTEGER,                   -- Source resolution height
    source_codec     TEXT,                      -- e.g., "h264", "hevc", "mjpeg"
    source_has_audio INTEGER DEFAULT 0,         -- Boolean: 1 if audio stream present
    needs_reencode   INTEGER DEFAULT 0,         -- Boolean: 1 if codec not in STREAM_COPY_SAFE
    file_size        INTEGER,                   -- Source file size in bytes
    settings         TEXT NOT NULL,             -- JSON blob (frozen at submission, immutable)
    created_at       TEXT NOT NULL,             -- ISO 8601
    scheduled_at     TEXT,                      -- NULL = run immediately; ISO 8601 = scheduled
    started_at       TEXT,
    finished_at      TEXT,
    error_msg        TEXT,
    phase            TEXT,                      -- 'detection' | 'export' | NULL
    progress         REAL DEFAULT 0,            -- 0.0–1.0 (current phase progress)
    output_path      TEXT,                      -- Absolute path to merged output MP4
    output_name      TEXT,                      -- Filename only (timestamped per re-export)
    output_size      INTEGER,                   -- Output file size in bytes
    recording_start  TEXT                       -- ISO 8601: from file metadata or user-supplied
);

CREATE INDEX IF NOT EXISTS idx_jobs_status     ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);
```

**settings JSON blob** (frozen at submission):
```json
{
  "sensitivity": "medium",
  "padding_s": 3,
  "min_gap_s": 5,
  "min_event_s": 3,
  "output_quality": "original",
  "output_format": "mp4",
  "output_dir": "/media/usb/output",
  "frame_skip": 1,
  "hw_decode": false,
  "zones": [
    { "label": "Zone 1", "points": [[0.1, 0.2], [0.9, 0.2], [0.9, 0.8], [0.1, 0.8]] }
  ]
}
```

**State transitions** (enforced in `job_queue.py`):
```
queued → running → detecting → exporting → completed
queued → cancelled
running | detecting | exporting → failed
failed → queued  (retry — resumes from checkpoint if exists)
completed → queued  (re-export — only export phase re-runs)
```

---

### Table: events

```sql
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    event_index     INTEGER NOT NULL,           -- 0-based sequential within job
    start_s         REAL NOT NULL,              -- Seconds from start of source (PTS-derived)
    end_s           REAL NOT NULL,              -- Seconds from start of source (PTS-derived)
    duration_s      REAL GENERATED ALWAYS AS (end_s - start_s) STORED,
    start_clock     TEXT,                       -- HH:MM:SS AM/PM (from recording_start + start_s)
    end_clock       TEXT,
    peak_motion_score REAL,                     -- Max motion ratio seen during event (0.0–1.0)
    zone_label      TEXT,                       -- NULL if no zones configured
    tag             TEXT,                       -- NULL | Person | Vehicle | Animal | False Positive | Review Required
    included        INTEGER NOT NULL DEFAULT 1, -- 1=included in export, 0=excluded
    thumbnail_path  TEXT,                       -- Relative path: data/jobs/{id}/thumbnails/{index}.jpg
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_job_id       ON events(job_id);
CREATE INDEX IF NOT EXISTS idx_events_job_included ON events(job_id, included);
```

**Constraint**: `event_index` is unique per `job_id`. Enforced in application layer.
**Checkpoint invariant**: events with `event_index > checkpoint.last_confirmed_event_index`
  are deleted before crash resume, preventing duplicates.

---

### Table: exports

Tracks every export run per job. Resolves the data integrity issue where re-exporting would
orphan the previous output file with no DB record (I2 fix, FR-038).

```sql
CREATE TABLE IF NOT EXISTS exports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    output_path TEXT NOT NULL,              -- Absolute path to merged output file
    output_name TEXT NOT NULL,              -- Filename only (timestamped, e.g., footage_activity_20260505_143022.mp4)
    output_size INTEGER,                    -- File size in bytes (set after completion)
    created_at  TEXT NOT NULL,             -- ISO 8601
    settings_snapshot TEXT                 -- JSON: which events were included at export time
);

CREATE INDEX IF NOT EXISTS idx_exports_job_id ON exports(job_id);
```

The `jobs` table retains `output_path`/`output_name`/`output_size` as **convenience denormalised
fields** pointing to the most recent export. `GET /api/jobs/{id}` returns both the latest export
(from `jobs` columns) and the full export history (from the `exports` table).

---

### Table: audit_log

```sql
CREATE TABLE IF NOT EXISTS audit_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,              -- ISO 8601 (UTC, microsecond precision)
    level   TEXT NOT NULL,             -- INFO | WARN | ERROR
    actor   TEXT NOT NULL,             -- 'user' | 'system'
    action  TEXT NOT NULL,             -- e.g., JOB_SUBMITTED | JOB_COMPLETED | EXPORT_DONE
    detail  TEXT,                      -- Human-readable description
    job_id  TEXT                       -- NULL for non-job actions
);

CREATE INDEX IF NOT EXISTS idx_audit_ts     ON audit_log(ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_job_id ON audit_log(job_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
```

**Action catalogue** (canonical values, logged consistently):
```
JOB_SUBMITTED | JOB_CANCELLED | JOB_RETRIED | JOB_COMPLETED | JOB_FAILED | JOB_DELETED
DETECTION_STARTED | DETECTION_RESUMED | DETECTION_PAUSED_THERMAL | DETECTION_DONE
EXPORT_STARTED | EXPORT_DONE | EXPORT_FAILED
PREVIEW_GENERATED
SETTINGS_CHANGED
UPLOAD_STARTED | UPLOAD_COMPLETED | UPLOAD_FAILED
```

---

## Flat Files

### timeline.json (per job, written by detection engine)

Path: `data/jobs/{job_id}/timeline.json`

```json
{
  "job_id": "string (UUID4)",
  "source_file": "string (absolute path)",
  "source_duration_s": 86400,
  "source_fps": 25.0,
  "source_resolution": [1920, 1080],
  "recording_start_utc": "2026-01-15T22:00:00Z",
  "ram_mode": "2gb",
  "processed_at": "2026-05-05T14:30:00",
  "total_activity_s": 1842,
  "activity_percent": 2.1,
  "events": [
    {
      "id": 1,
      "event_index": 0,
      "start_s": 192.4,
      "end_s": 227.1,
      "duration_s": 34.7,
      "start_clock": "10:03 PM",
      "end_clock": "10:03 PM",
      "peak_motion_score": 0.087,
      "zone_label": "Front Door",
      "tag": null,
      "included": true,
      "thumbnail_path": "data/jobs/abc123/thumbnails/0.jpg"
    }
  ]
}
```

### checkpoint.json (per job, written every 30 frames)

Path: `data/jobs/{job_id}/checkpoint.json`

```json
{
  "job_id": "string",
  "frames_processed": 9000,
  "pts_time": 360.0,
  "last_confirmed_event_index": 12,
  "timestamp": "2026-05-05T14:15:00"
}
```

`pts_time` is used for `-ss` seek on resume (not `frames_processed / fps` — avoids drift).
`last_confirmed_event_index` is used for the DELETE-before-resume dedup guard.

### config.json (global settings, created from defaults at first run)

Path: `config.json` (repo root)

```json
{
  "default_output_dir": "~/cctv_output",
  "default_sensitivity": "medium",
  "default_padding_s": 3,
  "default_min_gap_s": 5,
  "default_min_event_s": 3,
  "default_output_quality": "original",
  "default_frame_skip": 1,
  "hw_decode": false,
  "thermal_limit_c": 80,
  "disk_warn_percent": 85,
  "dark_mode": "system",
  "mog2_history": null,
  "allowed_browse_roots": ["/media", "/mnt"]
}
```

`mog2_history: null` means auto-derive from sensitivity. Set to integer to override.

---

## Key Entities (Application Layer)

### Job (app/models.py)

```python
@dataclass
class Job:
    id: str                    # UUID4
    status: str
    source_path: str
    source_name: str
    duration_s: Optional[float]
    source_fps: Optional[float]
    source_width: Optional[int]
    source_height: Optional[int]
    source_codec: Optional[str]
    source_has_audio: bool
    needs_reencode: bool
    file_size: Optional[int]
    settings: dict             # Frozen at submission
    created_at: str
    scheduled_at: Optional[str]
    started_at: Optional[str]
    finished_at: Optional[str]
    error_msg: Optional[str]
    phase: Optional[str]
    progress: float            # 0.0–1.0
    output_path: Optional[str]
    output_name: Optional[str]
    output_size: Optional[int]
    recording_start: Optional[str]
```

### Event (app/models.py)

```python
@dataclass
class Event:
    id: int                    # DB autoincrement
    job_id: str
    event_index: int           # 0-based
    start_s: float             # PTS-derived seconds
    end_s: float
    duration_s: float          # Generated column
    start_clock: Optional[str] # HH:MM AM/PM
    end_clock: Optional[str]
    peak_motion_score: Optional[float]
    zone_label: Optional[str]
    tag: Optional[str]
    included: bool
    thumbnail_path: Optional[str]
    created_at: str
```

### AuditEntry (app/models.py)

```python
@dataclass
class AuditEntry:
    id: int
    ts: str                    # ISO 8601 UTC
    level: str                 # INFO | WARN | ERROR
    actor: str                 # user | system
    action: str                # from action catalogue
    detail: Optional[str]
    job_id: Optional[str]
```

---

## Validation Rules

| Entity | Field | Rule |
|---|---|---|
| Job | `status` | MUST be one of the 7 valid status values |
| Job | `settings.sensitivity` | MUST be `low` \| `medium` \| `high` |
| Job | `settings.padding_s` | MUST be integer, 0–30 |
| Job | `settings.min_gap_s` | MUST be integer, 1–60 |
| Job | `settings.zones` | MUST have ≤5 polygons; each point normalised 0.0–1.0 |
| Event | `included` | Toggle only; never deleted, only flagged |
| Event | `tag` | MUST be one of: `Person`, `Vehicle`, `Animal`, `False Positive`, `Review Required`, or `NULL` |
| Config | `thermal_limit_c` | MUST be integer, 60–90 |
| Config | `disk_warn_percent` | MUST be integer, 50–95 |
