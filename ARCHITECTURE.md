# Architecture & Developer Notes — RasPi CCTV Analyst

> **Audience**: This document is for developers working on the codebase, or anyone curious about how the system is built and why each decision was made. No jargon is used without explanation — a technically interested non-developer should be able to follow along.

---

## What the System Does (Plain English)

Imagine you have a 24-hour security camera recording. Most of it is empty — a quiet street, a parked car, nothing happening. You only care about the 18 minutes where something actually moved.

This system watches the recording so you do not have to. It finds every moment something moved (a person, a car, even a cat), shows you those moments on a visual timeline, lets you throw away the ones you don't care about, and stitches the rest into a short highlight video.

Everything runs on a Raspberry Pi plugged into your home network. No internet is needed. No video ever leaves your home.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Your Phone / Laptop (Browser or Installed PWA App)            │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │Dashboard │  │ New Job  │  │ Timeline │  │  Export  │  ...  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
│       │              │              │              │             │
│       └──────────────┴──────────────┴──────────────┘            │
│                            HTTPS / SSE                          │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  Raspberry Pi 5 (LAN)   │
                    │                          │
                    │  FastAPI Web Server      │
                    │  (uvicorn, 1 worker)     │
                    │         │                │
                    │  SQLite Database (WAL)   │
                    │         │                │
                    │  Background Worker Thread│
                    │  ├─ Detection Engine     │
                    │  ├─ Export Engine        │
                    │  └─ Thumbnail Generator  │
                    │                          │
                    │  USB Drive (your videos) │
                    └──────────────────────────┘
```

---

## Component-by-Component Breakdown

### 1. The Web Server — `app/main.py`

**What it is**: A FastAPI application running under uvicorn (a lightweight Python web server). It handles all incoming HTTP requests from your browser.

**Why single worker?** The Raspberry Pi 5 2GB has limited RAM. Running multiple worker processes would waste ~300MB on duplicated Python interpreter overhead with zero speed benefit (detection is CPU/IO-bound, not web-request-bound). One worker handles everything.

**Why FastAPI?** It generates an automatic OpenAPI spec (`/docs`), handles type validation with Pydantic, and has native async/await support which is essential for the real-time SSE log streaming without blocking.

**Key pattern — lifespan context manager**: On startup the server: creates data directories, initialises the database, starts the background worker thread, and registers the async preview cleanup loop. On shutdown it signals the worker to stop cleanly.

**Route registration order matters**: All `/api/*` routes are registered **before** `StaticFiles` is mounted. If you mount static files first, FastAPI's static file handler would shadow your API routes.

---

### 2. The Database — `app/database.py`

**What it is**: SQLite — a single-file database that lives at `cctv_analyst.db` in the project root.

**Why SQLite?** The system has one user, one active job at a time, and no concurrent writes from multiple processes. SQLite is simpler, more reliable (no server process to crash), and fast enough. PostgreSQL or MySQL would add complexity with zero benefit here.

**WAL mode**: SQLite normally locks the entire file for writes. WAL (Write-Ahead Logging) mode allows one writer and multiple concurrent readers simultaneously — essential because the background worker thread writes progress updates while the web server reads job status for API responses.

**Thread-local connections**: Each Python thread gets its own database connection (`threading.local()`). SQLite connections are not safe to share across threads. The web server's async threads and the background worker thread each use their own connection.

**Four tables:**

| Table | Purpose |
|---|---|
| `jobs` | One row per submitted video job. Tracks status, settings, timestamps, output path. |
| `events` | One row per detected motion event. Contains start/end times, tags, include/exclude flag. |
| `exports` | One row per export run. Tracks every time "Export Selected Clips" was clicked, not just the latest. |
| `audit_log` | Append-only log of all user and system actions (job submitted, exported, settings changed, etc.). |

**Why an `exports` table?** The user can re-export after changing their event selections. Each re-export creates a new timestamped output file. Without the `exports` table, older export files would be orphaned in the file system with no record in the database.

---

### 3. The Job Queue — `app/core/job_queue.py`

**What it is**: A single Python daemon thread that runs in the background as long as the server is running. It continuously checks the database for queued jobs and processes them one at a time.

**Why a thread and not asyncio?** Video processing (OpenCV, FFmpeg, NumPy) uses blocking system calls. Python's asyncio cannot run blocking code without freezing the entire server. The background thread runs blocking code while the async web server continues handling HTTP requests without interruption.

**State machine**: Jobs move through these states in order:
```
queued → running → detecting → exporting → completed
queued → cancelled
running/detecting/exporting → failed
failed → queued   (retry — resumes from checkpoint)
completed → queued (re-export — skips detection, reruns export only)
```

**Crash recovery**: When the server restarts after a crash, the job queue checks for any jobs stuck in `running`, `detecting`, or `exporting` state (these were interrupted by the crash) and resets them to `queued` so they get picked up again automatically.

**Cancel mechanism**: A `threading.Event` is checked between every frame batch during detection. When the user clicks Cancel, the event is set and the detection loop exits cleanly at the next batch boundary — no force-kill needed.

---

### 4. The Detection Engine — `app/core/detection_engine.py`

**The most important file in the codebase.** This is where the actual motion detection happens.

#### How It Works (Step by Step)

**Step 1 — Feed frames via FFmpeg pipe**

Instead of using OpenCV's built-in video reader (`cv2.VideoCapture`), we run FFmpeg as a subprocess and pipe raw image frames into Python. This is more complex but solves three problems:
- **Frame skip** happens in FFmpeg with a `fps` filter — this halves the pipe bandwidth compared to doing it in Python after reading every frame.
- **Crash recovery** — we can seek to any timestamp and resume from there.
- **Accurate timestamps** — FFmpeg's `showinfo` filter prints the exact PTS (Presentation TimeStamp) of every frame to stderr, which we parse in a separate thread. This is more accurate than computing timestamps from frame count and FPS.

The FFmpeg command looks like:
```bash
ffmpeg -i input.mp4 -vf "fps=12.5,scale=320:240,showinfo" -pix_fmt rgb24 -f rawvideo -
```
This outputs raw RGB bytes at 320×240 resolution at ~12.5fps (half of a 25fps source).

**Step 2 — Background subtraction (MOG2)**

MOG2 (Mixture of Gaussians 2) is an OpenCV algorithm that builds a model of what the "background" looks like and highlights anything that deviates from it. It learns the background over time — so a static parked car eventually becomes background, and a moving car stands out.

Sensitivity settings control how easily the algorithm triggers:
- **Low**: Only obvious large movements. Few false positives.
- **Medium**: Balanced. Catches people walking, cars driving.
- **High**: Catches subtle movements. More false positives (leaves, light changes).

**Step 3 — Noise reduction (morphological filter)**

Raw motion masks have speckle noise — tiny isolated pixels that trigger due to image compression artifacts, IR camera grain, or rain. We apply two OpenCV operations:
- **MORPH_OPEN** (erode then dilate): Removes isolated small blobs.
- **MORPH_CLOSE** (dilate then erode): Fills small holes inside real motion regions.

This is the fix for false positives from cheap cameras with noisy sensors.

**Step 4 — Zone filtering**

If the user has drawn detection zones on the zone editor canvas, we pre-render those polygons into a mask image. Only motion within the zones counts — motion outside is ignored. This lets you, for example, only care about the front door and ignore a busy road in the background.

**Step 5 — Event segmentation**

The algorithm maintains a simple state machine:
- When motion ratio exceeds the threshold → enter an event, record start time.
- When motion drops below threshold for `min_gap_s` seconds → close the event, record end time.
- Apply `padding_s` seconds before and after each event (so clips don't start/end abruptly).
- Discard events shorter than `min_event_s` seconds.

**Step 6 — Checkpoint every 30 frames**

Every 30 frames (~2.4 seconds of source video at medium skip), the engine:
1. Writes `checkpoint.json` with the current timestamp and last confirmed event.
2. Flushes confirmed events to the database.
3. Updates job progress percentage.
4. Checks RAM usage and CPU temperature (throttles if limits exceeded).
5. Checks if the user pressed Cancel.

This means if the Pi crashes or loses power, at most 30 frames of work are lost.

**Crash resume**:
1. On restart, the job queue moves the interrupted job back to `queued`.
2. When the worker picks it up, `checkpoint.json` is found.
3. Events past the checkpoint are deleted from the database (duplicate prevention).
4. FFmpeg seeks directly to the checkpoint timestamp.
5. 500 frames are processed in "warmup" mode (no events recorded) to rebuild the MOG2 background model.
6. Detection resumes normally.

---

### 5. The Export Engine — `app/core/export_engine.py`

**What it does**: Takes a list of included events and produces a single merged MP4 with chapter markers.

**The process:**
1. For each included event, extract that time range from the source file as a `.ts` (MPEG Transport Stream) segment.
2. Write a `concat.txt` file listing all segment files.
3. Write a `ffmetadata.txt` file with chapter markers (one per event, labelled with the real clock time).
4. Run FFmpeg's concat demuxer to merge all segments into a single output MP4.
5. Clean up the `.ts` segment files.

**Stream copy vs. re-encode**: For H.264/HEVC sources, FFmpeg can copy the video data directly without decoding and re-encoding it (`-c:v copy`). This is extremely fast (the Pi can "copy" a 21GB file in minutes) and lossless. For MJPEG or other codecs, FFmpeg must decode and re-encode using libx264 (`-preset veryfast`) which takes much longer.

**Why `.ts` segments?** MPEG Transport Stream handles the timestamp discontinuity between segments cleanly. MP4 segments would have timestamp issues at join points.

**NVR timestamp fix**: Some NVR (Network Video Recorder) systems produce recordings with broken or discontinuous timestamps. The flag `-fflags +genpts+igndts` instructs FFmpeg to regenerate timestamps from scratch, fixing these issues.

**Chapter markers**: The output MP4 contains chapter metadata. In any chapter-aware player (VLC, QuickTime, most smart TVs), you can jump directly to "Event 3 — 10:34 PM" without scrubbing.

---

### 6. Real-Time Log Streaming — SSE — `app/core/log_buffer.py` + `app/api/sse.py`

**The problem**: The detection engine runs in a background thread. The web client wants to see live log lines as detection progresses. Bridging a background thread to async HTTP is tricky.

**The solution — asyncio.Queue fan-out**:

```
Background thread → log_buffer.append(job_id, line)
                              │
                    call_soon_threadsafe()
                              │
                    asyncio.Queue (one per connected client)
                              │
                    SSE endpoint → await queue.get() → send to browser
```

`call_soon_threadsafe()` is the key — it is the only thread-safe way to put items into an asyncio queue from a non-async thread. Multiple browser tabs can subscribe simultaneously; each gets its own queue.

**Keepalive**: If no log line arrives for 30 seconds, the SSE endpoint sends a keepalive message so the browser doesn't time out the connection.

**History replay**: When a client connects (or reconnects after a network blip), the last 100 log lines are immediately replayed into the new queue before live updates begin. This gives context without flooding the client with hours of old logs.

---

### 7. The Frontend — Vanilla JavaScript, No Framework

**Why no React/Vue/Angular?** The system runs on a Pi. No `npm install`, no build step, no 50MB `node_modules` folder. The frontend is plain HTML + CSS + JavaScript ES modules — load the page, it works.

**Client-side router**: `app.js` maps URL patterns to JavaScript page modules. When you navigate to `/jobs/123`, the router dynamically imports `pages/job-detail.js`, calls its `mount(container, params)` function, and renders the page into the `<main id="app">` element. The sidebar stays mounted across all page transitions.

**XSS prevention**: All user-controlled data (filenames, job names, log lines) is inserted into the DOM using `element.textContent`, never `element.innerHTML`. The `el(tag, text, attrs)` helper function enforces this pattern across all 19 JavaScript files. A filename like `<script>alert(1)</script>` will appear as literal text, not execute.

**Canvas timeline**: The motion event timeline is drawn on an HTML5 `<canvas>` element using `fillRect()` for each event. This is GPU-accelerated and redraws in under 1ms even with 200+ events. The timeline adapts to touch screens (80px height, larger hit targets, swipe-to-pan) vs. mouse screens (48px height, precise click detection).

---

### 8. PWA — Progressive Web App

**What makes it a PWA?**
1. A `manifest.json` file describing the app (name, icon, colors, display mode).
2. A service worker (`sw.js`) that caches the app shell files.
3. Served over HTTPS.

**What the service worker does**:
- On install: caches all HTML pages, CSS files, JavaScript files, and icons.
- On every request: if the URL starts with `/api/`, bypass the cache entirely (live data must always be fresh). Otherwise, serve from cache if available.
- When offline: serves the cached shell with a "Pi not reachable" message instead of a browser error page.

**Why HTTPS?** Browser security policy requires HTTPS for service workers (and therefore PWAs). On `localhost` it is exempt, but on any LAN hostname (`raspberrypi.local`) HTTPS is mandatory. The installer generates a self-signed certificate with a 10-year validity and adds the proper Subject Alternative Names (SAN) so modern browsers accept it without a hostname mismatch error.

---

## Data Flow: Full Job Lifecycle

```
User clicks "Start Analysis"
        │
        ▼
POST /api/jobs
  ├─ ffprobe validates source file
  ├─ Disk space check (2.2× source size required)
  ├─ codec/resolution warnings generated
  ├─ Job row inserted into jobs table (status=queued)
  └─ Returns job_id + warnings

Background worker (every 2s poll)
  ├─ Finds queued job
  ├─ Updates status=detecting
  ├─ Runs detection_engine.run()
  │   ├─ FFmpeg pipe → frame batches
  │   ├─ MOG2 → motion scores
  │   ├─ Morphological filter → clean mask
  │   ├─ Zone mask applied
  │   ├─ Segment state machine → events
  │   ├─ Checkpoint every 30 frames
  │   └─ timeline.json written on completion
  ├─ Runs thumbnail_gen.run() (post-detection)
  └─ Updates status=completed

User reviews timeline
  ├─ GET /api/jobs/{id} → events list
  ├─ PUT /api/jobs/{id}/events/{eid} → toggle include/exclude
  └─ POST /api/jobs/{id}/events/{eid}/preview → temp clip for playback

User clicks "Export Selected Clips"
  │
  ▼
POST /api/jobs/{id}/export
  ├─ Count included events (0 → HTTP 400)
  ├─ Runs export_engine.run() in thread
  │   ├─ Extract .ts segments per event
  │   ├─ Write concat.txt + ffmetadata.txt
  │   ├─ FFmpeg concat merge → output.mp4
  │   └─ Cleanup .ts files
  ├─ INSERT into exports table
  └─ UPDATE jobs.output_path (denormalised convenience)
```

---

## File Layout Reference

```
app/
├── main.py               Entry point — FastAPI app, lifespan, route registration
├── config.py             Hardware detection — RAM mode, all Pi-safe constants
├── database.py           SQLite WAL, thread-local connections, schema init
├── models.py             Job / Event / AuditEntry dataclasses + from_row() factories
├── api/
│   ├── jobs.py           POST/GET/DELETE/PUT jobs + zone-frame endpoint
│   ├── export.py         POST export, GET output (range requests), GET exports history
│   ├── sse.py            GET stream (SSE), POST preview
│   ├── filebrowser.py    GET /api/browse (path whitelist enforced)
│   ├── upload.py         POST init/chunk/finalize, GET status
│   ├── thumbnails.py     GET /api/thumbnails/{job_id}/{idx}.jpg
│   ├── system.py         GET /api/system/stats (CPU, RAM, temp, disk)
│   ├── dashboard.py      GET /api/dashboard (combined system + recent jobs)
│   ├── settings.py       GET/PUT /api/settings (Pydantic validated)
│   ├── audit.py          GET /api/audit (filtered log), GET audit CSV
│   └── reports.py        GET analytics JSON, GET PDF (FileResponse), GET CSV
└── core/
    ├── detection_engine.py   8-step MOG2 pipeline — the main algorithm
    ├── export_engine.py      FFmpeg concat + chapter injection
    ├── thumbnail_gen.py      Post-detection JPEG thumbnail generation
    ├── job_queue.py          Background worker thread + state machine
    ├── log_buffer.py         asyncio.Queue fan-out for SSE (ISSUE-08 fix)
    ├── audit_logger.py       Append-only audit_log writer
    ├── ram_guard.py          psutil RAM + temperature monitor/throttle
    ├── analytics.py          pandas aggregations over events
    └── report_gen.py         ReportLab PDF generation (disk-backed, not BytesIO)
```

---

## Key Design Decisions & Why

| Decision | Why |
|---|---|
| FFmpeg pipe instead of `cv2.VideoCapture` | Checkpointable, cancellable, accurate PTS timestamps from showinfo filter |
| Single uvicorn worker | No multiprocessing overhead on 2GB Pi — saves ~300MB |
| SQLite WAL mode | Concurrent reads during background writes without full-file locking |
| Thread-local DB connections | SQLite connections are not thread-safe — each thread gets its own |
| asyncio.Queue for SSE | Only way to safely push from worker thread → async SSE without blocking thread pool |
| `call_soon_threadsafe()` | Correct way to interact with the asyncio event loop from a non-async thread |
| `FileResponse` for PDFs | ReportLab writes to disk file; FileResponse streams from disk — never buffers in RAM |
| `Request.stream()` for uploads | Avoids loading entire 21GB upload into memory before writing to disk |
| Morphological filter | Removes noise from IR cameras and CCTV compression artifacts |
| 320×240 detection resolution | Full resolution (1920×1080) per frame = 6MB; at 320×240 it's 230KB. 26× less RAM per frame |
| `.ts` intermediate segments | Handles timestamp discontinuities between clips correctly during concat |
| `-fflags +genpts+igndts` | Fixes broken timestamps from NVR recordings |
| 500-frame MOG2 warmup after resume | MOG2 needs time to re-learn background after seeking. Without warmup, every frame looks like motion. |
| `textContent` never `innerHTML` | XSS prevention — user filenames rendered as text, never interpreted as HTML |

---

## Known Limitations

| Limitation | Detail | Planned Fix |
|---|---|---|
| **One job at a time** | Only one video can be analysed simultaneously | Multi-queue in v2 |
| **No object classification** | All motion is detected equally — person, car, bird all look the same | YOLOv8n in v1.5 (disabled on 2GB due to RAM) |
| **No live camera support** | System processes pre-recorded files only, not RTSP streams | RTSP snapshot in v1.5 |
| **No push notifications** | Completed jobs visible in dashboard only | Telegram/email in v2 |
| **MJPEG export is slow** | Re-encoding required; 24h MJPEG export ~2 hours | Inherent FFmpeg limitation |
| **RAM detection is fixed at startup** | Changing RAM after install requires restart | By design |
| **4K sources on 2GB Pi** | Detection works but is RAM-constrained; may thermal-throttle | Use 4GB Pi for 4K |
| **No user authentication** | Designed for LAN use; your router is the security boundary | Auth planned for v3 (multi-user) |
| **Windows-only formatting caveat** | `%-I` strftime format (POSIX) replaced with `.lstrip("0")` for cross-platform | Fixed in codebase |

---

## Pre-Implementation Issues Log

Before a single line of application code was written, a brainstorming pass identified 17 potential problems. All were addressed in the implementation:

| Issue | Problem | Fix |
|---|---|---|
| ISSUE-01 | PWA service workers require HTTPS on non-localhost | Self-signed cert generated by install.sh with SAN for `raspberrypi.local` |
| ISSUE-02 | Timestamp drift from frame counting instead of PTS | `showinfo` filter + stderr parser extracts exact PTS per frame |
| ISSUE-03 | RAM budget too tight on 2GB for full-res detection | 320×240 detection resolution; system-wide psutil guard at 75% |
| ISSUE-04 | Clip preview broken if served directly from source | Temp file extracted per preview, served as proper MP4 with faststart |
| ISSUE-05 | MOG2 produces false events immediately after seek | 500-frame warmup pass after crash resume |
| ISSUE-06 | Frame skip done in Python wastes pipe bandwidth | Frame skip via `fps` filter in FFmpeg command |
| ISSUE-07 | IR camera noise causes false positives | Morphological OPEN + CLOSE filter on motion mask |
| ISSUE-08 | SSE using `run_in_executor` blocks thread pool | asyncio.Queue per subscriber, `call_soon_threadsafe` bridge |
| ISSUE-09 | Resume after crash creates duplicate events | DELETE events past checkpoint before resuming detection |
| ISSUE-10 | NVR recordings have broken PTS timestamps | `-fflags +genpts+igndts` flag on all FFmpeg export commands |
| ISSUE-11 | Audio streams silently dropped during export | `has_audio` flag from ffprobe; conditional `-c:a copy` or `-an` |
| ISSUE-12 | Jobs fail mid-detection due to insufficient disk | Disk space check at submission: need 2.2× source size free |
| ISSUE-13 | MJPEG sources fail stream copy silently | `needs_reencode` flag from ffprobe; codec warning in API response |
| ISSUE-14 | `vcgencmd` not available on non-Pi hosts | Graceful fallback to sysfs thermal zone, then `None` |
| ISSUE-15 | Timeline events too small to tap on mobile | 80px canvas on touch devices, 12px minimum event width, swipe-to-pan |
| ISSUE-16 | Filenames with `<script>` tags could execute JS | All DOM insertion uses `textContent` via `el()` builder, never `innerHTML` |
| ISSUE-17 | Slow-moving objects missed by MOG2 at high history | History tuned per sensitivity (200/500/700 frames); CLAHE preprocessing on High |

---

## Post-Deployment Bug Register

These bugs were found during real Pi deployment and fixed in branches `001` and `002`.
See `DETECTION_NOTES.md` for the full detection-specific register.

| Bug | Severity | Root Cause | Fix |
|---|---|---|---|
| systemd path-with-spaces | Critical | `${INSTALL_DIR}` unquoted in generated unit file | Quoted `ExecStart` path in `install.sh` heredoc |
| Pydantic v2 incompatibility | Critical | `@validator` / `.dict()` are Pydantic v1 APIs; FastAPI 0.111 ships v2 | `@field_validator` + `.model_dump()` |
| `-ignore_editlist 1` in detection | Critical | Forces decoding of H.264 encoder pre-roll frames → decoder crash after 10–29 frames | Removed; `+genpts` alone is sufficient |
| `frame_idx` UnboundLocalError | Critical | Warmup block referenced `frame_idx` 25 lines before its definition | Moved `frame_idx = 0` to before warmup block |
| `frame_idx` reset after warmup | Critical | Second `frame_idx = 0` discarded warmup count → wrong PTS | Removed the stale reset |
| `detectShadows=True` + threshold 200 | Critical | Shadow pixels (127) erased by `threshold(200)` → 0 foreground pixels | `detectShadows=False` |
| FFmpeg fps filter stall | Critical | Edit list PTS offset (0.195s) misaligns fps filter expected timestamps | `-fflags +genpts` regenerates PTS from 0 |
| Preview blank video | Major | `generate_preview` missing `+genpts` → clip PTS not from 0 → browser decoder fails | Added `+igndts+genpts`, `avoid_negative_ts` |
| Export SSE disconnect | Major | SSE not reconnected after export starts → log panel blank | Reconnect SSE + 4s polling fallback |
| `_restore_interrupted_jobs` re-detects | Major | Exported jobs reset to queued → re-ran 2h detection unnecessarily | Exporting → completed; Detecting → queued |
| f-string JSON in upload_init | Major | Filenames with `"` produce malformed JSON → upload_finalize crashes | `json.dumps()` instead of f-string |
| Zone frame in `/tmp` | Minor | Never cleaned up → fills disk on low-storage Pi | Moved to `JOBS_DIR/{job_id}/zone_frame.jpg` |
| Export polling leak on unmount | Minor | `setInterval` not cleared on navigation → background network calls | Hoisted to module scope; `unmount()` clears it |
| `asyncio.get_event_loop()` deprecated | Minor | Python 3.10+ deprecation warning in journal | Changed to `get_running_loop()` |
| Dead `settings` variable in export | Cosmetic | JSON parsed but never used | Removed |

---

## Running Tests

There is no automated test suite in v1. Testing follows the manual acceptance criteria in `specs/001-raspi-cctv-v1-core/quickstart.md`.

For module-level sanity checks:
```bash
python -c "from app.main import app; from app.database import init_db; init_db(); print('OK')"
```

For live endpoint testing:
```bash
uvicorn app.main:app --port 5000 &
curl http://localhost:5000/api/health
curl http://localhost:5000/api/jobs
curl http://localhost:5000/api/system/stats
```

---

## Deployment Checklist

- [ ] `bash install.sh` completed on target Pi
- [ ] `ssl/cert.pem` and `ssl/key.pem` generated
- [ ] `systemctl is-active cctv-analyst` returns `active`
- [ ] `https://raspberrypi.local:5000/api/health` returns `{"status":"ok","ram_mode":"2gb"}`
- [ ] Dashboard loads on phone browser and install prompt appears
- [ ] Submit a test job with a short video (< 5 minutes); verify it detects and completes
- [ ] Export the test job; verify output MP4 plays in browser
- [ ] Check System page: temperature and RAM gauges show live values
- [ ] Restart service mid-detection (`sudo systemctl restart cctv-analyst`); verify job resumes
