# Implementation Plan: RasPi CCTV Analyst — v1 Core Pipeline

**Branch**: `001-raspi-cctv-v1-core` | **Date**: 2026-05-05 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/001-raspi-cctv-v1-core/spec.md`
**Full implementation plan**: `.claude/plans/functional-prancing-sunrise.md`
**Issues register**: `ISSUES.md` (17 pre-identified issues, all resolved)

## Summary

Build the complete RasPi CCTV Analyst v1 core pipeline: a self-hosted PWA that processes
pre-recorded CCTV footage on a Raspberry Pi 5 (2GB RAM), detects motion events via OpenCV
MOG2, presents a visual timeline for review, and exports only the relevant clips as a merged
MP4 with chapter markers. All processing is local; no data leaves the device.

The system comprises a FastAPI backend (single-worker uvicorn), a background worker thread
for the detection/export pipeline, a SQLite WAL database for job state, and a Vanilla JS
multi-page PWA frontend served over HTTPS.

## Technical Context

**Language/Version**: Python 3.11 (backend), HTML5 + Vanilla JS ES Modules (frontend — no Node.js)
**Primary Dependencies**: FastAPI 0.111, uvicorn 0.29, opencv-python-headless 4.9, FFmpeg 5.x,
  numpy 1.26, pandas 2.2, ReportLab 4.1, psutil 5.9, aiofiles 23.x, python-multipart 0.0.x
**Storage**: SQLite 3.x (WAL mode, thread-local connections, no ORM); JSON flat files
  (timeline.json, checkpoint.json, config.json)
**Testing**: Manual integration testing against Pi 5 2GB hardware for performance SCs;
  pytest for unit-testable utility functions
**Target Platform**: Raspberry Pi 5 (aarch64), Raspberry Pi OS Lite 64-bit;
  Docker on Linux (amd64/aarch64) as alternative deployment
**Project Type**: Self-hosted web service (PWA) + background video processing pipeline
**Performance Goals**: 24h 1080p detection ≤2.5h; export ≤10min; page load ≤2s; timeline canvas redraw ≤5ms
**Constraints**: systemd MemoryMax=1400M; 2 FFmpeg threads; 320×240 detection resolution; no npm/build step;
  uvicorn --workers 1 only (multiprocessing wastes 300MB headroom with zero detection speed gain)
**Scale/Scope**: Single operator, one active job at a time, source files up to 24 hours, 200+ events per job

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **I. Privacy-First**: No external transmission. All processing local. Dashboard served LAN-only.
- [x] **II. Hardware-Adaptive**: psutil RAM detection at startup; 2GB constants (320×240, batch=30, threads=2);
  systemd MemoryMax=1400M; system-wide RAM guard at 75% available.
- [x] **III. Accuracy**: Morphological OPEN+CLOSE filter (ISSUE-07); PTS timestamps via `showinfo`
  filter (ISSUE-02); 500-frame MOG2 warmup after crash resume (ISSUE-05).
- [x] **IV. Resilience**: Checkpoint every 30 frames (ISSUE-05); job queue restores crashed jobs to
  `queued` on startup; event dedup DELETE before resume (ISSUE-09).
- [x] **V. PWA/No Framework**: Vanilla JS ES Modules; no npm; `el()` builder with `textContent` only
  (ISSUE-16); service worker caches shell only; HTTPS via self-signed cert (ISSUE-01).
- [x] **VI. Transparency**: timeline.json, checkpoint.json, config.json all human-readable; SQLite
  audit_log table; FileResponse for PDFs (disk-backed, not BytesIO).
- [x] **VII. Hybrid Workflow**: `superpowers:brainstorm` completed pre-implementation (17 issues found);
  ISSUES.md documents all fixes; constitution v1.0.0 ratified; speckit clarify completed (5 Qs).

*No Constitution Check violations. Complexity Tracking table not required.*

## Project Structure

### Documentation (this feature)

```text
specs/001-raspi-cctv-v1-core/
├── plan.md              ← This file
├── research.md          ← Phase 0 output
├── data-model.md        ← Phase 1 output
├── quickstart.md        ← Phase 1 output
├── contracts/
│   └── api-contracts.md ← Phase 1 output
├── checklists/
│   └── requirements.md  ← Spec quality checklist (updated)
└── tasks.md             ← Phase 2 output (/speckit-tasks — not yet created)
```

### Source Code (repository root)

```text
(repo root)/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI factory, lifespan, router mounts, HTTPS
│   ├── config.py                  # psutil RAM detection at import; all 2GB/4GB constants
│   ├── database.py                # SQLite WAL, thread-local connections, migrations
│   ├── models.py                  # Dataclasses: Job, Event, AuditEntry, Settings
│   ├── api/
│   │   ├── __init__.py
│   │   ├── dashboard.py           # GET /api/dashboard
│   │   ├── jobs.py                # CRUD /api/jobs, preview endpoint
│   │   ├── export.py              # POST /api/jobs/{id}/export
│   │   ├── filebrowser.py         # GET /api/browse (path-whitelisted)
│   │   ├── upload.py              # POST /api/upload/* (Request.stream() pattern)
│   │   ├── thumbnails.py          # GET /api/thumbnails/{job_id}/{event_id}.jpg
│   │   ├── reports.py             # GET /api/reports/{job_id}/pdf|csv (FileResponse)
│   │   ├── settings.py            # GET/PUT /api/settings
│   │   ├── system.py              # GET /api/system/stats
│   │   ├── audit.py               # GET /api/audit
│   │   └── sse.py                 # GET /api/jobs/{id}/stream (asyncio.Queue fan-out)
│   ├── core/
│   │   ├── __init__.py
│   │   ├── job_queue.py           # SQLite state machine + daemon worker thread
│   │   ├── detection_engine.py    # 8-step MOG2 pipeline (including morphological filter)
│   │   ├── export_engine.py       # FFmpeg TS segments + concat demuxer + chapters
│   │   ├── thumbnail_gen.py       # ffmpeg mid-event frame → 320×180 JPEG
│   │   ├── analytics.py           # pandas groupby over events table
│   │   ├── report_gen.py          # ReportLab PDF → temp file → FileResponse
│   │   ├── ram_guard.py           # System-wide psutil.virtual_memory().available
│   │   ├── log_buffer.py          # asyncio.Queue fan-out (not blocking iterator)
│   │   └── audit_logger.py        # Append-only SQLite audit_log writer
│   └── utils/
│       ├── __init__.py
│       ├── ffprobe.py             # duration, codec, avg_frame_rate, has_audio, needs_reencode
│       ├── file_utils.py          # Path whitelist validation, USB mount detection
│       ├── time_utils.py          # HH:MM:SS ↔ seconds, pts_time parsing
│       └── system.py              # get_cpu_temp() with vcgencmd + /sys fallback
│
├── static/
│   ├── manifest.json              # PWA manifest (standalone, dark theme)
│   ├── sw.js                      # Service worker (shell-only cache, never API)
│   ├── icons/
│   │   ├── icon-192.png
│   │   └── icon-512.png           # maskable
│   ├── css/
│   │   ├── base.css               # CSS custom properties, dark/light theme tokens
│   │   ├── layout.css             # App shell, persistent sidebar nav
│   │   └── components.css         # Cards, badges, modals, gauges, canvas timeline
│   ├── js/
│   │   ├── app.js                 # Client-side router (ES module dynamic imports)
│   │   ├── api.js                 # fetch() wrappers + el() DOM builder (XSS safe)
│   │   ├── sse-client.js          # EventSource wrapper with keepalive + reconnect
│   │   └── components/
│   │       ├── nav.js             # Sidebar (persists across page transitions)
│   │       ├── toast.js           # Toast notifications
│   │       ├── modal.js           # Generic modal helper
│   │       ├── timeline-strip.js  # Canvas renderer (responsive: mouse 48px, touch 80px)
│   │       ├── event-card.js      # Event card DOM builder (textContent only)
│   │       └── upload-widget.js   # Drag-drop + chunked upload (File.slice, sequential)
│   └── pages/
│       ├── index.html             # Dashboard
│       ├── new-job.html           # New Job
│       ├── jobs.html              # Job Queue
│       ├── job-detail.html        # Job Detail + Timeline Review
│       ├── reports.html           # Analytics & Reports
│       ├── settings.html          # Settings
│       ├── system.html            # System Diagnostics
│       └── audit.html             # Audit Log
│
├── data/
│   ├── uploads/                   # Chunked upload staging (1MB parts)
│   ├── jobs/
│   │   └── {job_id}/
│   │       ├── timeline.json
│   │       ├── checkpoint.json
│   │       ├── concat.txt
│   │       ├── ffmetadata.txt
│   │       ├── clips/             # .ts segments (deleted after merge)
│   │       └── thumbnails/        # {event_id}.jpg
│   └── previews/                  # Temp clip previews (auto-deleted after 5min)
│
├── outputs/                       # Final merged MP4s (one per export run, timestamped)
├── ssl/                           # Auto-generated by install.sh (self-signed TLS)
│   ├── key.pem
│   └── cert.pem
├── cctv_analyst.db                # SQLite (WAL mode, created at first run)
├── config.json                    # User settings (created from defaults at first run)
│
├── requirements.txt
├── install.sh                     # One-command guided Pi installer + SSL cert generation
├── cctv-analyst.service           # systemd unit (MemoryMax=1400M, CPUQuota=360%)
├── docker-compose.yml             # /media:/media:ro, MemoryMax 1400MB
├── Dockerfile                     # FROM arm64v8/python:3.11-slim
└── ISSUES.md                      # Pre-implementation issues register (17 issues)
```

**Structure Decision**: Single-project web service. Backend (`app/`) and frontend (`static/`) coexist
in the repo root. FastAPI serves both the REST API and the static PWA files from a single uvicorn
process. No separate frontend build step or Node.js toolchain required.

## Implementation Phases

### Phase 1 — Project Scaffold & Backend Foundation
**Files**: `requirements.txt`, `app/main.py`, `app/config.py`, `app/database.py`,
`app/models.py`, `app/utils/*.py`, `data/.gitkeep`, `.gitignore`, `ssl/` (install.sh)

Key decisions locked in by research:
- `opencv-python-headless` (not `opencv-python`): ~10MB RAM savings, no GUI deps on Pi OS Lite
- `uvicorn --workers 1`: multiprocessing wastes 300MB with zero detection speed gain
- `app/utils/system.py`: `get_cpu_temp()` tries vcgencmd → /sys/class/thermal → None (never crashes)
- `app/utils/ffprobe.py`: returns `avg_frame_rate` (not `r_frame_rate`), `has_audio`, `needs_reencode`

### Phase 2 — Job Queue & Database Layer
**Files**: `app/database.py` (schema), `app/core/job_queue.py`, `app/core/log_buffer.py`,
`app/core/audit_logger.py`

Key: `log_buffer.py` uses `asyncio.Queue` fan-out (not blocking iterator) so SSE never holds
thread pool threads. `job_queue.py` deletes events past `last_confirmed_event_index` before
resuming crashed jobs (ISSUE-09).

### Phase 3 — Detection Engine
**Files**: `app/core/detection_engine.py`, `app/core/ram_guard.py`

8-step pipeline:
1. Acquire via FFmpeg pipe with `fps={target},scale={W}:{H},showinfo` filter
2. Parse PTS from stderr (not frame_count/fps — ISSUE-02)
3. Preprocess: BGR→Gray, optional CLAHE for High sensitivity
4. MOG2 diff (history: low=700, medium=500, high=200)
5. **Morphological OPEN+CLOSE** with 5×5 elliptical kernel (ISSUE-07)
6. Zone mask bitwise-AND
7. Score: `countNonZero / total_pixels` (thresholds: low=0.02, medium=0.005, high=0.001)
8. Segment state machine + checkpoint every 30 frames

Crash resume: DELETE events past checkpoint, then 500-frame MOG2 warmup (ISSUE-05).
RAM guard: monitors `psutil.virtual_memory().available` system-wide (ISSUE-03).

### Phase 4 — Export Engine + Thumbnails
**Files**: `app/core/export_engine.py`, `app/core/thumbnail_gen.py`

Export pipeline:
1. Extract segments: `ffmpeg -fflags +genpts+igndts -ss {s} -i {src} -t {d} -c:v copy {audio} -avoid_negative_ts make_zero seg.ts`
2. Merge: `ffmpeg -f concat -safe 0 -i concat.txt -i ffmetadata.txt -map_metadata 1 -c copy output.mp4`
3. Chapter markers in ffmetadata.txt (one per event, real clock time)
4. Audio flags: `-c:a copy` if has_audio, else `-an` (ISSUE-11)
5. Re-encode fallback: `-c:v libx264 -preset veryfast -crf 28` when needs_reencode=True (ISSUE-13)
6. On-demand preview: extract ±2s temp clip via `ffmpeg -movflags faststart` → auto-delete after 5min (ISSUE-04)

Thumbnails: Post-detection sweep. `ffmpeg -ss {mid_s} -frames:v 1 -vf scale=320:180 -q:v 5`.

### Phase 5 — REST API Endpoints
**Files**: All `app/api/*.py`

Critical patterns:
- SSE (`sse.py`): `asyncio.Queue` fan-out; 30s `wait_for` timeout → send keepalive; replay history on connect
- Upload (`upload.py`): `Request.stream()` pattern with 65KB buffer (not `UploadFile`) — guaranteed no OOM
- Reports (`reports.py`): Generate PDF to named temp file → serve via `FileResponse` (not `StreamingResponse(BytesIO)`)
- File browser (`filebrowser.py`): `Path.resolve()` against `/media`, `/mnt`, `INPUT_DIR` whitelist (ISSUE)
- Disk check (`jobs.py`): `shutil.disk_usage(output_dir).free >= source_size * 2.2` at job creation (ISSUE-12)
- 4K warning (`jobs.py`): `width > 1920` + `RAM_MODE == "2gb"` → `warnings` field in response (ISSUE-03)

### Phase 6 — Frontend (All 8 Pages)
**Files**: All `static/` files

Router: `app.js` ES module dynamic imports; `mount(container, params)` / `unmount()` per page.
XSS: All API data via `el(tag, text)` using `textContent` — zero `innerHTML` with user data (ISSUE-16).
Timeline canvas: `pointer: coarse` → 80px height, 12px min segment width, 4h pan windows (ISSUE-15).
Clip preview: `POST /api/jobs/{id}/events/{eid}/preview` → loading spinner → `<video>` (ISSUE-04).
Lazy thumbnails: `IntersectionObserver` — never eager-load 200+ JPEGs at once.

### Phase 7 — PWA (Manifest + Service Worker + SSL)
**Files**: `static/manifest.json`, `static/sw.js`, `static/icons/`, `install.sh`

HTTPS is mandatory for service worker registration on `raspberrypi.local` (non-localhost origin).
`install.sh` generates `ssl/key.pem` + `ssl/cert.pem` via openssl with SAN for `raspberrypi.local`.
Service worker: shell-only cache (`SHELL_URLS`); API paths (`/api/`) never intercepted.
mDNS `.local` handling varies by browser — self-signed cert + user acceptance is the reliable path.

### Phase 8 — File Browser + Chunked Upload
**Files**: `app/api/filebrowser.py`, `app/api/upload.py`, `static/js/components/upload-widget.js`

Upload protocol: init → chunks (1MB) → finalize.
Server: `Request.stream()` with `while buf := await request.stream.__anext__(): f.write(buf)`.
Client: `File.slice(start, end)` creates Blob reference (lazy, safe for 21GB); sequential chunks.
Resume: `sessionStorage` stores `upload_id`; `GET /api/upload/status/{id}` returns received chunks.

### Phase 9 — Analytics + PDF Reports
**Files**: `app/core/analytics.py`, `app/core/report_gen.py`, `app/api/reports.py`

ReportLab 4.1+ ships pure-Python aarch64 wheels — no compilation on Pi.
RAM during generation with ~200 thumbnails: ~80-120MB (safe within budget).
Pattern: `canvas.save(tmp_file_path)` → `FileResponse(tmp_file_path, media_type="application/pdf")`.
Do NOT use `StreamingResponse(BytesIO)` — it buffers the full PDF in RAM before sending.
Analytics: pandas groupby on events table; returns JSON consumed by frontend charts.

### Phase 10 — Packaging
**Files**: `install.sh`, `cctv-analyst.service`, `Dockerfile`, `docker-compose.yml`

systemd: `MemoryMax=1400M`, `CPUQuota=360%`, `Restart=on-failure`, `RestartSec=10`.
Docker: `FROM arm64v8/python:3.11-slim`; `/media:/media:ro`; `mem_limit: 1400m`.
install.sh: apt → venv → pip → ssl cert → DB init → systemd enable → print URL.
