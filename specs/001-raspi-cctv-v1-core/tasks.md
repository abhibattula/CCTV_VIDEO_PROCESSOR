---
description: "Task list for RasPi CCTV Analyst v1 Core Pipeline"
---

# Tasks: RasPi CCTV Analyst â€” v1 Core Pipeline

**Input**: Design documents from `specs/001-raspi-cctv-v1-core/`
**Prerequisites**: plan.md âœ… | spec.md âœ… | research.md âœ… | data-model.md âœ… | contracts/api-contracts.md âœ…
**Constitution**: `.specify/memory/constitution.md` v1.0.0 â€” all tasks comply with Principles Iâ€“VII
**Issues Register**: `ISSUES.md` â€” 17 pre-identified issues + 11 post-analysis remediations (speckit-analyze); all embedded in task descriptions
**Tests**: Not requested. Manual acceptance testing via `quickstart.md` after each story phase.
**Workflow**: Superpowers + SpecKit hybrid â€” `superpowers:brainstorm` completed (17 issues found);
  `superpowers:code-reviewer` MUST run after each phase completes.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no shared state)
- **[Story]**: Maps to user story (US1â€“US8)
- Every task includes the exact file path to create or modify

---

## Phase 1: Setup

**Purpose**: Project initialization. Creates the skeleton everything attaches to.
No application logic yet â€” just structure, dependencies, and a health-check endpoint.

- [x] T001 Create `requirements.txt` with pinned minor versions: fastapi==0.111.*, uvicorn[standard]==0.29.*, opencv-python-headless==4.9.*, numpy==1.26.*, psutil==5.9.*, pandas==2.2.*, reportlab==4.1.*, aiofiles==23.*, python-multipart==0.0.*
- [x] T002 [P] Create `.gitignore` covering: `*.pyc`, `__pycache__/`, `venv/`, `.env`, `cctv_analyst.db`, `data/`, `outputs/`, `ssl/`, `config.json`
- [x] T003 [P] Create directory skeleton: `app/`, `app/api/`, `app/core/`, `app/utils/`, `static/css/`, `static/js/components/`, `static/js/pages/`, `static/pages/`, `static/icons/`, `data/.gitkeep`, `outputs/.gitkeep`, `specs/`
- [x] T004 Write `app/__init__.py` (empty)
- [x] T005 Write `app/config.py`: psutil RAM detection at import time (`psutil.virtual_memory().total / 1e9`); set `RAM_MODE = "2gb" if total < 3.0 else "4gb"`; define all constants: `DETECT_WIDTH=320`, `DETECT_HEIGHT=240`, `BATCH_SIZE=30`, `FFMPEG_THREADS=2`, `THUMB_CACHE_SIZE=50`, `ENABLE_YOLO=False`, `LOG_RING_SIZE=2000`, `CHUNK_SIZE=1048576`, `RAM_GUARD_PERCENT=75`, `THERMAL_LIMIT_C=80`; define `DATA_DIR`, `JOBS_DIR`, `UPLOAD_DIR`, `PREVIEW_DIR`, `OUTPUTS_DIR` as `Path` objects
- [x] T006 [P] Write `app/utils/__init__.py` (empty)
- [x] T007 [P] Write `app/utils/ffprobe.py`: run `ffprobe -v quiet -print_format json -show_streams -show_format`; return typed dict with `duration_s: float`, `avg_frame_rate: float` (parse `avg_frame_rate` string like "25/1" â€” NOT `r_frame_rate`; ISSUE-02), `width: int`, `height: int`, `codec_name: str`, `has_audio: bool` (any stream with `codec_type == "audio"`), `needs_reencode: bool` (codec not in `{"h264","hevc","mpeg2video","mpeg4"}`; ISSUE-13), `recording_start: Optional[str]` from `probe["format"]["tags"].get("creation_time")` â€” NVR files often embed this; return `None` if absent (FR-020, A1 fix); raise `ValueError` on non-video or corrupt file (FR-003)
- [x] T008 [P] Write `app/utils/system.py`: implement `get_cpu_temp() -> Optional[float]` â€” try `vcgencmd measure_temp` first, parse `temp=54.2'C`; on `FileNotFoundError` try `/sys/class/thermal/thermal_zone0/temp` (divide by 1000); return `None` if both fail â€” NEVER crash (ISSUE-14); implement `get_disk_usage(path: str) -> dict` wrapping `shutil.disk_usage`
- [x] T009 [P] Write `app/utils/file_utils.py`: `ALLOWED_ROOTS = [Path("/media"), Path("/mnt")]`; `validate_path(path: str) -> Path` resolves with `.resolve()`, checks startswith any allowed root, raises `PermissionError` if outside â€” prevents path traversal (FR-006, ISSUE from file browser); `is_video_file(path: Path) -> bool` checks suffix in `{".mp4",".mkv",".avi",".mov",".ts",".mts",".flv"}`
- [x] T010 [P] Write `app/utils/time_utils.py`: `seconds_to_clock(s: float, recording_start: Optional[str]) -> str` â€” if `recording_start` is set, add offset to UTC and format as "HH:MM AM/PM"; else format as "HH:MM:SS"; `parse_pts_time(ffmpeg_stderr_line: str) -> Optional[float]` â€” parse `pts_time:XX.XXX` from `showinfo` filter output (ISSUE-02)
- [x] T011 Write `app/database.py`: WAL mode + NORMAL synchronous + foreign_keys ON at connect; thread-local connections via `threading.local()`; `get_conn() -> sqlite3.Connection` returning `row_factory=sqlite3.Row` connection; `init_db()` runs `CREATE TABLE IF NOT EXISTS` for all **4 tables** (jobs, events, exports, audit_log) with all columns from `data-model.md` including `source_has_audio`, `source_codec`, `needs_reencode`, `source_width`, `source_height`, `recording_start`; create all indexes including `idx_exports_job_id` (I2 fix â€” exports table tracks all re-export runs per job)
- [x] T012 Write `app/models.py`: `@dataclass` definitions for `Job`, `Event`, `AuditEntry`, `GlobalSettings`; `Job.from_row(row: sqlite3.Row)` and `Event.from_row(row)` factory classmethods; `JobStatus` string enum with 7 valid values
- [x] T013 Write `app/main.py`: FastAPI app with `lifespan` context manager; on startup: call `init_db()`, create data dirs (`DATA_DIR`, `JOBS_DIR`, `UPLOAD_DIR`, `PREVIEW_DIR`, `OUTPUTS_DIR`), store asyncio event loop reference in `log_buffer.set_loop(asyncio.get_event_loop())`, start job worker thread, start `asyncio.create_task(_preview_cleanup_loop())` (deletes files in `PREVIEW_DIR` older than 300s every 60s, A5 fix); on shutdown: signal worker to drain; mount `StaticFiles` at `/static`; serve all 8 HTML pages at clean URLs: `GET /` â†’ `pages/index.html`, `GET /jobs/new` â†’ `pages/new-job.html`, `GET /jobs` â†’ `pages/jobs.html`, `GET /jobs/{job_id}` â†’ `pages/job-detail.html`, `GET /reports` â†’ `pages/reports.html`, `GET /settings` â†’ `pages/settings.html`, `GET /system` â†’ `pages/system.html`, `GET /audit` â†’ `pages/audit.html` (A4 fix â€” all 8 explicit); include all API routers under `/api` prefix; add `GET /api/health` returning `{"status":"ok","ram_mode":RAM_MODE}`; HTTPS: if `ssl/key.pem` and `ssl/cert.pem` exist, pass to uvicorn via `ssl_keyfile`/`ssl_certfile` uvicorn config (ISSUE-01)

**Checkpoint**: `uvicorn app.main:app` starts without error. `GET /api/health` returns `{"status":"ok","ram_mode":"2gb"}`.

---

## Phase 2: Foundational â€” Core Engines

**Purpose**: All background processing engines. MUST complete before any user story begins.
No story can be independently tested until these are done.

**âš ï¸ CRITICAL**: No user story work begins until this phase is complete.

- [x] T014 Write `app/core/__init__.py` (empty)
- [x] T015 Write `app/core/log_buffer.py`: `LogBuffer` class with `_history: dict[str, deque]` (maxlen=2000) and `_subscribers: dict[str, list[asyncio.Queue]]`; `set_loop(loop)` stores the asyncio event loop; `append(job_id, line)` appends to history deque AND calls `loop.call_soon_threadsafe(q.put_nowait, line)` for every subscriber queue â€” bridges worker thread to async SSE clients (ISSUE-08); `subscribe(job_id) -> asyncio.Queue` creates queue, replays only the **last 100 lines** (`list(_history[job_id])[-100:]`) into the queue on connect â€” NOT all 2000 (FR-018; I3 fix â€” avoids dumping an hour of logs to a reconnecting client); adds queue to subscribers list; `unsubscribe(job_id, queue)` removes from list; `close(job_id)` pushes sentinel `"__DONE__"` to all subscribers; singleton `log_buffer = LogBuffer()` at module level
- [x] T016 Write `app/core/audit_logger.py`: `log(action: str, detail: str, actor: str, level: str, job_id: Optional[str])` writes to `audit_log` table with ISO 8601 UTC timestamp; uses `get_conn()` thread-local connection; all writes committed immediately; action values drawn from canonical catalogue in `data-model.md`
- [x] T017 Write `app/core/ram_guard.py`: `check(job_id: str, logger_fn)` calls `psutil.virtual_memory().available`; if available < total * (1 - RAM_GUARD_PERCENT/100): `logger_fn("[RAM GUARD] XX% used â€” throttling")` then `time.sleep(2)` (ISSUE-03: monitors system-wide available, NOT process RSS); also check `get_cpu_temp()` from `utils/system.py` â€” if > `THERMAL_LIMIT_C`: `logger_fn("[THERMAL] XXXÂ°C â€” pausing")` then `time.sleep(5)` (ISSUE-14 graceful fallback handled in get_cpu_temp)
- [x] T018 Write `app/core/job_queue.py`: `JobQueue` class with `threading.Thread(daemon=True)`; worker polls `SELECT * FROM jobs WHERE status='queued' AND (scheduled_at IS NULL OR scheduled_at <= datetime('now')) ORDER BY created_at LIMIT 1` every 2 seconds; on find: update status to `running`, dispatch to detection engine; `_cancel_event: threading.Event` checked between frame batches; on startup: `UPDATE jobs SET status='queued' WHERE status IN ('running','detecting','exporting')` (crash recovery, restores interrupted jobs, ISSUE-09 companion); `cancel(job_id)` sets `_cancel_event` and updates DB; `retry(job_id)` sets status=`queued`; singleton `job_queue = JobQueue()` started from `app/main.py` lifespan
- [x] T019 Write `app/core/detection_engine.py`: implement 8-step MOG2 pipeline:
  **Step 1** â€” FFmpeg pipe: `target_fps = source_avg_fps / (frame_skip+1)`; cmd includes `-vf "fps={target_fps:.4f},scale={W}:{H},showinfo"` `-pix_fmt rgb24 -f rawvideo`; `frame_size = W * H * 3` (ISSUE-06: frame skip in FFmpeg not Python);
  **Step 2** â€” PTS parsing: spawn stderr reader thread calling `parse_pts_time()` from `utils/time_utils.py`; map frame index to PTS timestamp (ISSUE-02);
  **Step 3** â€” Preprocess: `cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)`; CLAHE if sensitivity==high;
  **Step 4** â€” MOG2: `history={low:700,medium:500,high:200}[sensitivity]`; `varThreshold={low:32,medium:16,high:8}[sensitivity]`; `detectShadows=True`; threshold at 200 to remove shadows;
  **Step 5** â€” **Morphological filter** (ISSUE-07): `kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(5,5))`; apply `MORPH_OPEN` then `MORPH_CLOSE` â€” removes noise blobs;
  **Step 6** â€” Zone mask: pre-render polygon mask from normalised zone coordinates; `cv2.bitwise_and(fg_mask, zone_mask)`;
  **Step 7** â€” Score: `motion_ratio = cv2.countNonZero(fg_mask) / (W*H)`; thresholds `{low:0.02,medium:0.005,high:0.001}`;
  **Step 8** â€” Segment state machine + checkpoint every `BATCH_SIZE` frames: write `checkpoint.json` with `frames_processed`, `pts_time`, `last_confirmed_event_index` (ISSUE-05); flush confirmed events to `events` table; call `ram_guard.check()`; check `_cancel_event`;
  **Crash resume**: if `checkpoint.json` exists: `DELETE FROM events WHERE job_id=? AND event_index > ?`; seek FFmpeg to `checkpoint.pts_time`; run 500-frame MOG2 warmup (discard detections) before resuming (ISSUE-05, ISSUE-09);
  **Timeline.json**: write after detection completes using schema from `data-model.md`
- [x] T020 Write `app/core/export_engine.py`:
  **Segment extraction** (per included event): `ffmpeg -fflags +genpts+igndts -ss {start} -i {source} -t {dur} -c:v copy {audio_flags} -avoid_negative_ts make_zero -threads {FFMPEG_THREADS} seg_{n:04d}.ts` where `audio_flags = ["-c:a","copy"] if has_audio else ["-an"]` (ISSUE-10: NVR PTS fix; ISSUE-11: audio check);
  **Re-encode trigger** (A3 fix): re-encode when `needs_reencode=True` **OR** `settings["output_quality"] != "original"` â€” these are two independent triggers (OR, not AND); if quality is "compressed_720p": add `-vf scale=-2:720 -crf 28`; if "small_480p": add `-vf scale=-2:480 -crf 32`; use `-c:v libx264 -preset veryfast` for all re-encode paths (ISSUE-13);
  **Concat**: write `concat.txt`; write `ffmetadata.txt` (one `[CHAPTER]` per event with real clock time); `ffmpeg -f concat -safe 0 -i concat.txt -i ffmetadata.txt -map_metadata 1 -c copy -threads {FFMPEG_THREADS} {output}.mp4`;
  **Output filename**: always timestamped `{source_stem}_activity_{YYYYMMDD_HHMMSS}.mp4` â€” NEVER overwrites (FR-038, clarification Q4);
  **Cleanup**: delete `.ts` segments after successful merge;
  **On-demand preview** (ISSUE-04): `generate_preview(source, start_s, end_s, token) -> str`: `ffmpeg -ss {start-2} -i {source} -t {dur+4} -c copy -movflags faststart previews/{token}.mp4`; register token with 300s TTL; background coroutine deletes expired previews every 60s
- [x] T021 Write `app/core/thumbnail_gen.py`: post-detection sweep (NOT during detection, to avoid I/O pressure); for each event: `mid_s = start_s + duration_s/2`; `ffmpeg -ss {mid_s} -i {source} -frames:v 1 -vf scale=320:180 -q:v 5 {job_dir}/thumbnails/{event_index}.jpg`; update `events.thumbnail_path` in DB; LRU dict capped at `THUMB_CACHE_SIZE` (50 in 2GB mode) for stat-call avoidance
- [x] T022 Write `app/core/analytics.py`: `compute(job_id: str) -> dict`; load events from DB for job; pandas DataFrame; hourly activity: `groupby(floor(start_s/3600))`; duration histogram: 5 bins; `activity_percent = sum(included duration_s) / source_duration_s * 100`; peak hour; longest event; avg event; events by tag; return serialisable dict
- [x] T023 Write `app/core/report_gen.py`: ReportLab `SimpleDocTemplate` to a named temp file (NOT BytesIO â€” ISSUE from research Decision 9); cover page with job metadata + RAM mode; summary stats table; hourly activity bar chart via ReportLab `VerticalBarChart`; event log table (10 rows/page); save to `data/jobs/{job_id}/report_{timestamp}.pdf`; return file path for `FileResponse`

**Checkpoint**: All engine modules import cleanly. Detection engine processes a 30-second test video and writes `timeline.json` with correct event timestamps. Export engine produces a valid MP4 from 2 events.

---

## Phase 3: US1 â€” Submit a Video Analysis Job (Priority: P1)

**Goal**: Operator can submit a job via USB path or browser upload, see it queued, and confirm processing starts.

**Independent Test**: Submit a job for a `.mp4` file via the file browser. Verify it appears in the queue with status "Queued" within 3 seconds. Verify the codec warning appears for an MJPEG source. Verify the disk space error appears when free space is insufficient (FR-004).

### Implementation for User Story 1

- [x] T024 [P] [US1] Write `app/api/__init__.py` (empty)
- [x] T025 [US1] Write `app/api/jobs.py` â€” implement all core job endpoints:
  **POST /api/jobs**: validate `source_path` exists and is a video (call `ffprobe.py`); disk space check `shutil.disk_usage(output_dir).free >= file_size * 2.2` â†’ HTTP 400 with actionable message if insufficient (ISSUE-12, FR-004); 4K warning if `width > 1920` and `RAM_MODE=="2gb"` (ISSUE-03); codec warning if `needs_reencode==True` (ISSUE-13); store `recording_start` from ffprobe result (A1 fix); freeze `settings` as JSON blob; generate UUID4 job ID; INSERT into jobs table; enqueue via `job_queue`; return `{"job_id":"...","status":"queued","warnings":[...]}`;
  **GET /api/jobs** (list with filters);
  **GET /api/jobs/{id}** (full detail + all events + `exports` array from exports table â€” I2 fix);
  **POST /api/jobs/{id}/cancel**: if status in (`queued`,`running`,`detecting`,`exporting`) â†’ set `_cancel_event`, update `status=cancelled`, log audit; else HTTP 409 (I1 fix â€” moved from T054/Phase 7 to Phase 3 so cancel button works in MVP);
  **DELETE /api/jobs/{id}**: set `status=deleted`; if `?delete_output=true` also `os.remove(output_path)` if exists (I1 fix â€” moved from T054/Phase 7)
- [x] T026 [US1] Write `app/api/filebrowser.py` â€” `GET /api/browse?path=`: call `file_utils.validate_path(path)` (raises `PermissionError` â†’ HTTP 403 if outside whitelist); list directory entries with `name`, `is_dir`, `size`, `mtime`, `is_video`; sort dirs first then files; return `{"path","parent","entries"}`
- [x] T026b [US1] Write zone editor frame endpoint in `app/api/jobs.py` â€” **GET /api/jobs/{job_id}/zone-frame**: extract single frame at 10% into source video: `ffmpeg -ss {duration*0.1} -i {source_path} -frames:v 1 -vf scale=960:540 /tmp/zone_{job_id}.jpg`; serve via `FileResponse(..., media_type="image/jpeg")`; cache to `/tmp/zone_{job_id}.jpg` and re-serve on repeat calls without re-extracting; return HTTP 404 if job/source not found (C1 fix â€” FR-009 zone editor needs this frame to draw polygons on)
- [x] T027 [US1] Write `app/api/upload.py` â€” three endpoints: `POST /api/upload/init` creates `data/uploads/{uuid}/` dir, returns `{"upload_id","chunk_size":1048576}`; `POST /api/upload/chunk` uses **`Request.stream()`** pattern (NOT `UploadFile`) with explicit 65KB iteration: `async for chunk in request.stream(): await f.write(chunk)` â€” guaranteed no OOM on 21GB files (research Decision 8); `POST /api/upload/finalize` assembles chunks with `shutil.copyfileobj(src, dst, 65536)`, deletes part files, runs disk check, returns `{"source_path","size"}`; `GET /api/upload/status/{upload_id}` returns received chunk indices for resume (FR-005)
- [x] T028 [P] [US1] Write `static/css/base.css`: CSS custom properties for all color tokens (`--color-primary:#2563eb`, `--color-success:#16a34a`, `--color-warning:#d97706`, `--color-danger:#dc2626`, `--color-muted:#6b7280`); `--bg`, `--text`, `--bg-card`, `--border`; dark mode via `[data-theme="dark"]` â€” toggle on `<html>` element; typography tokens; spacing scale; base reset (box-sizing, margin 0)
- [x] T029 [P] [US1] Write `static/css/layout.css`: app shell with CSS Grid (`sidebar + main`); persistent sidebar 220px wide, collapsible; main area full remaining width; header bar; mobile: sidebar collapses to icons-only at <768px
- [x] T030 [P] [US1] Write `static/css/components.css`: card, badge (status colors), progress bar (animated), modal overlay, toast notification, button variants, gauge circles (conic-gradient), spinner, table, form inputs, toggle switch
- [x] T031 [US1] Write `static/js/app.js`: ES module client-side router; `ROUTES` map of URL pattern â†’ dynamic `import()` of page module; `navigate(path)` updates `history.pushState` and calls `unmount()` on outgoing page then `mount(container, params)` on incoming; sidebar nav rendered once by `nav.js` (persists across transitions); extract `:id` param from URL pattern; register service worker if `"serviceWorker" in navigator`; dark mode: read `localStorage.getItem("darkMode")`, apply `document.documentElement.setAttribute("data-theme","dark")`
- [x] T032 [P] [US1] Write `static/js/api.js`: `el(tag, text, attrs={})` DOM builder â€” uses `textContent` ONLY, never `innerHTML` (ISSUE-16); `apiFetch(path, options)` wrapper with `Content-Type: application/json`; throws `ApiError(status, detail)` on non-200; export named `api` object with methods for every endpoint group: `api.jobs.list()`, `api.jobs.create(body)`, `api.jobs.get(id)`, `api.jobs.updateEvent(jobId,eid,body)`, `api.upload.init()`, `api.upload.finalize()`, `api.browse(path)`, `api.system.stats()`, `api.settings.get()`, `api.settings.put(body)`, `api.reports.analytics(id)`, `api.audit.list(params)`
- [x] T033 [P] [US1] Write `static/js/components/nav.js`: renders persistent sidebar `<nav>` with links to all 8 pages; highlights active page via `location.pathname`; collapse toggle on mobile; on every `mount()`: call `api.system.stats()` and if `disk_warn===true` inject a `<div class="disk-warning-banner">` above `<main id="app">` â€” this is the only place this check runs, ensuring all 8 pages show the banner (C3 fix, FR-045); `mount(container)` / `unmount()` exports; exports `updateDiskWarning(stats)` so polling pages can update the banner without re-mounting nav
- [x] T034 [P] [US1] Write `static/js/components/toast.js`: `toast.success(msg)`, `toast.error(msg)`, `toast.warn(msg)`; renders top-right toast with auto-dismiss after 5 seconds; stacks multiple toasts
- [x] T035 [P] [US1] Write `static/js/components/modal.js`: `modal.open(content_element)` / `modal.close()`; closes on Escape key or overlay click; traps focus inside modal
- [x] T036 [P] [US1] Write `static/js/components/upload-widget.js`: drag-and-drop zone with visual feedback; `File.slice(start, end)` for chunked upload (lazy blob, safe for 21GB, never loads file into memory); sequential chunk loop with `await api.upload.chunk(uploadId, i, blob)`; progress bar showing bytes/s and ETA; retry failed chunks up to 3Ã— with exponential backoff; store `upload_id` in `sessionStorage`; on mount check for interrupted upload via `api.upload.status(id)` and resume from first missing chunk (FR-005)
- [x] T037 [P] [US1] Write `static/pages/new-job.html`: minimal shell with manifest link, Apple meta tags, `<link rel="stylesheet">` for base/layout/components CSS, `<nav id="sidebar"></nav>`, `<main id="app"></main>`, `<script type="module" src="/static/js/app.js"></script>`
- [x] T038 [US1] Write `static/js/pages/new-job.js`: tab widget (File Path | Upload File); File Path tab: text input + "Browse" button â†’ opens file browser modal (tree navigator, calls `api.browse(path)`); Upload tab: mounts `upload-widget.js`; Detection settings: Low/Medium/High slider (3-position), padding seconds input (0â€“30), min gap input (1â€“60), min event seconds (default 3); Output: quality radio (Original/720p/480p), format select (MP4/MKV); Zone editor button â†’ modal with canvas for drawing up to 5 polygons on a frame extracted at 10% into video (clarification Q5, FR-009); Submit â†’ `api.jobs.create(body)` â†’ on success `router.navigate("/jobs/" + id)`; show codec/disk warnings from response
- [x] T039 [P] [US1] Write `static/pages/jobs.html` (Job Queue page shell â€” same structure as new-job.html)
- [x] T040 [US1] Write `static/js/pages/job-queue.js`: table polling `api.jobs.list()` every 5 seconds; columns: Status badge, Source Name, Created, Duration, Progress bar (running only), Events, Actions (Cancel/Retry/Delete); status badges color-coded with pulse animation for running; clicking row navigates to `/jobs/{id}`; "New Analysis Job" button

**Checkpoint**: Open `https://raspberrypi.local:5000/jobs/new` in browser. Browse to a `.mp4` file. Confirm job appears in queue within 3 seconds (US1 Independent Test verified).

---

## Phase 4: US3 â€” Review and Edit the Motion Event Timeline (Priority: P1)

**Goal**: After detection, operator sees timeline strip, clicks events for thumbnails/preview, includes/excludes events.

**Independent Test**: Open a completed job at `/jobs/{id}`. Verify green event blocks on timeline canvas. Click an event â€” thumbnail and details appear. Click "Play Clip" â€” video player opens within 10 seconds (clarification Q1, FR-022). Toggle one event to Excluded â€” timeline and summary bar update immediately (FR-023).

### Implementation for User Story 3

- [x] T041 [US3] Write `app/api/jobs.py` additions â€” `PUT /api/jobs/{id}/events/{eid}` (toggle `included`, set `tag`; persist to DB; return updated event); `POST /api/jobs/{id}/events/{eid}/preview` (generate temp clip via `export_engine.generate_preview()`; return `{"preview_url":"/api/previews/{token}.mp4","expires_in_seconds":300}`; 503 if preview already generating; ISSUE-04)
- [x] T042 [US3] Write `app/api/thumbnails.py` â€” `GET /api/thumbnails/{job_id}/{event_index}.jpg`: serve via `FileResponse` with `ETag: {job_id}-{event_index}` header; return 404 if file not yet generated; add `Cache-Control: public, max-age=86400` (thumbnails are immutable)
- [x] T043 [US3] Write `static/js/components/timeline-strip.js`:
  Canvas renderer with `devicePixelRatio` scaling for HiDPI;
  **Responsive** (ISSUE-15): detect `window.matchMedia("(pointer: coarse)")` â€” touch: `canvas.height=80px`, min segment px=12; mouse: `canvas.height=48px`;
  `render(events, sourceDuration, selectedIndex)`: `fillRect` in `--color-success` for included, `--color-muted` for excluded;
  Timestamp axis: ticks every 1h (<12h source), 3h (12â€“24h), 6h (24h+); format via `utils/time_utils`;
  Touch/click handler: `x / canvas.width * sourceDuration` â†’ binary search events array â†’ dispatch custom `"event-selected"` CustomEvent;
  Touch pan (4-hour windows on mobile): swipe left/right advances `viewStart` by 4h;
  Redraw via `requestAnimationFrame` only on state change â€” no continuous animation loop;
  Exports `{ mount(canvas, events, durationS, onSelect), updateEvents(events), setSelected(index) }`
- [x] T044 [P] [US3] Write `static/js/components/event-card.js`: `build(event, jobId)` â†’ returns DOM element using `el()` builder (ISSUE-16); thumbnail `<img>` with `loading="lazy"` and `IntersectionObserver` for lazy load; clock times, duration, confidence score; `<select>` for tag (Person/Vehicle/Animal/False Positive/Review Required); Include/Exclude toggle button; "Play Clip" button â†’ calls `api.jobs.preview(jobId, eventId)` â†’ shows loading spinner â†’ opens modal with `<video src="{preview_url}" controls autoplay>`; video loads within 10 seconds (FR-022)
- [x] T045 [P] [US3] Write `static/pages/job-detail.html` (Job Detail page shell)
- [x] T046 [US3] Write `static/js/pages/job-detail.js`:
  **Header**: source name, status badge, duration, file size; SSE log panel (collapsible); progress bar + ETA when `status=detecting`;
  **Summary bar** (sticky): total duration | included activity | activity% | estimated output size | events N included / M excluded; recalculates on every toggle; estimated size formula (A2 fix): for stream copy (`output_quality=="original"`): `estimated_bytes = (total_included_s / source_duration_s) * source_file_size`; for re-encode quality options: `estimated_bytes = total_included_s * target_bitrate_bps / 8` where 720pâ‰ˆ2_000_000 bps, 480pâ‰ˆ800_000 bps; display as human-readable (MB/GB);
  **Timeline canvas**: mounts `timeline-strip.js`; on `"event-selected"` event: scroll corresponding event card into view and highlight;
  **Event card grid**: CSS Grid auto-fill; virtual scrolling when >100 events (render 30 visible, update on scroll); uses `event-card.js`;
  **Bulk actions**: "Include All", "Exclude All" buttons; "Export Selected" button â†’ calls export API (Phase 5); disabled with message "No events selected" when included count is 0 (FR-055);
  Connects SSE client for live updates (Phase 6 will add SSE panel); `api.jobs.get(id)` on mount

**Checkpoint**: Submit and complete a short (5-min) detection job. Open Job Detail page. Verify timeline canvas shows events. Click event â€” card highlights. Click "Play Clip" â€” video player opens.

---

## Phase 5: US4 â€” Export Selected Clips as a Merged Video (Priority: P1)

**Goal**: Operator exports selected events as merged MP4 with chapter markers. Sees output size, compression ratio, and download link.

**Independent Test**: On a completed job with 3+ included events, click "Export Selected Clips". Verify output MP4 plays in VLC. Verify chapter markers appear (one per event, labelled with real clock time). Verify exported in under 10 minutes for a 1-hour H.264 source. Verify FR-055: export button is disabled when 0 events included.

### Implementation for User Story 4

- [x] T047 [US4] Write `app/api/export.py` â€” `POST /api/jobs/{id}/export`: load job + events; count `WHERE included=1`; if count == 0 return HTTP 400 `"No events selected â€” include at least one event to export."` (FR-055, clarification Q3); update job status to `exporting`; run `export_engine` in worker thread; output filename = `{source_stem}_activity_{YYYYMMDD_HHMMSS}.mp4` (never overwrites, FR-038, clarification Q4); on completion: INSERT into `exports` table (`job_id`, `output_path`, `output_name`, `output_size`, `created_at`, `settings_snapshot` with included event IDs); UPDATE `jobs.output_path`, `jobs.output_name`, `jobs.output_size` to latest export (denormalised convenience); update `jobs.status=completed`; push completion log to `log_buffer` (I2 fix â€” exports table records every export run)
- [x] T047b [US4] Add output serving + exports history endpoints to `app/api/export.py` â€” `GET /api/jobs/{id}/output`: verify `jobs.output_path` exists; return `FileResponse(path, media_type="video/mp4")` â€” FastAPI's FileResponse supports HTTP range requests automatically (enables HTML5 video seeking, FR-035, C2 fix); return HTTP 404 if no export yet; HTTP 410 if path recorded but file deleted; `GET /api/jobs/{id}/exports`: query `exports` table for all rows with `job_id`, return list ordered by `created_at DESC` (I2 fix â€” History page can show all export runs)
- [x] T048 [US4] Write `app/api/reports.py` â€” `GET /api/reports/{id}/analytics` calls `analytics.compute(job_id)` returns JSON; `GET /api/reports/{id}/pdf` calls `report_gen` â†’ `FileResponse(pdf_path, media_type="application/pdf", filename="report_{job_id}.pdf")` â€” disk-backed NOT BytesIO (research Decision 9); `GET /api/reports/{id}/csv` generates CSV via `csv.writer` on `StringIO`, returns `StreamingResponse` with `text/csv`
- [x] T049 [US4] Update `static/js/pages/job-detail.js` â€” add export flow: "Export Selected Clips" button `POST`s to export API; during export: show progress bar fed by SSE `type:progress`; on completion: show confirmation card with output path, file size, compression ratio (e.g., "24h â†’ 18 min, 97% smaller"); "Download" link (`href="/api/jobs/{id}/output"`); "Preview Output" button opens HTML5 `<video src="/api/jobs/{id}/output" controls>` modal â€” range requests supported, video is seekable (C2 fix, FR-035); also show export history list from `GET /api/jobs/{id}/exports` so operator can see all previous re-export files (I2 fix); "Generate Report" button â†’ `window.open("/api/reports/{id}/pdf")`; "Export CSV" button downloads CSV

**Checkpoint**: Full pipeline verified: submit â†’ detect â†’ review (exclude 1 event) â†’ export â†’ play output in browser â†’ verify chapter markers.

---

## Phase 6: US2 â€” Monitor Live Detection Progress (Priority: P2)

**Goal**: Live log panel, progress bar, system gauges update during detection without page refresh. Works across multiple browser tabs simultaneously.

**Independent Test**: Start a detection job. Open Job Detail page in two browser tabs. Confirm log lines appear in both simultaneously within 1 second. Confirm neither tab freezes other dashboard operations (ISSUE-08 asyncio.Queue fix).

### Implementation for User Story 2

- [x] T050 [US2] Write `app/api/sse.py` â€” `GET /api/jobs/{id}/stream`: set `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`; call `log_buffer.subscribe(job_id)` â†’ get `asyncio.Queue`; replay history: drain queue of all pre-queued history lines immediately; then enter loop: `await asyncio.wait_for(q.get(), timeout=30.0)` â€” on `TimeoutError` yield keepalive `data: {"type":"keepalive"}\n\n`; on `"__DONE__"` sentinel yield `data: {"type":"done","status":"..."}\n\n` and close; clean up via `finally: log_buffer.unsubscribe(job_id, q)` (ISSUE-08: zero thread pool usage)
- [x] T051 [US2] Write `static/js/sse-client.js`: `SseClient` class wrapping `EventSource`; `connect(url, handlers)` where `handlers` is `{log, progress, system, done, keepalive}`; auto-reconnect with exponential backoff on error; `disconnect()` closes EventSource; `isConnected()` boolean
- [x] T052 [US2] Write `static/js/components/system-gauges.js`: four CSS conic-gradient circle gauges for CPU%, RAM%, Disk%, Temp; temperature sparkline on `<canvas>` (30-point rolling, `requestAnimationFrame` only on update); color-coding: temp <60Â°C=green, 60â€“75Â°C=amber, >75Â°C=red pulsing; exports `{ mount(container), update(stats) }`
- [x] T053 [US2] Update `static/js/pages/job-detail.js` â€” connect `SseClient` when job status is `detecting` or `exporting`; SSE log panel: scrollable, max 200 DOM lines (virtual window â€” remove top lines as new arrive to prevent DOM bloat); auto-scroll to bottom unless operator has scrolled up; thermal warning banner when SSE `type:system` has `temp_c > thermal_limit`; disconnect SSE on `unmount()`

**Checkpoint**: Start detection on a 5-min test video. Open two browser tabs on Job Detail. Confirm both receive log lines live. Confirm settings page remains responsive while detection runs.

---

## Phase 7: US5 â€” Browse and Reopen Historical Jobs (Priority: P2)

**Goal**: All past jobs listed with stats. Reopen timeline, change event selections, re-export without re-running detection.

**Independent Test**: Complete a job. Reopen it from History. Toggle 2 events to Excluded. Click Re-export. Verify a NEW timestamped output file is created (does not overwrite old one, clarification Q4). Verify detection was NOT re-run (job transitions directly to `exporting`).

### Implementation for User Story 5

- [x] T054 [US5] Add retry endpoint to `app/api/jobs.py` â€” `POST /api/jobs/{id}/retry`: if status == `failed` â†’ reset `status=queued` (checkpoint.json preserved on disk; worker will resume from it, ISSUE-09); log `JOB_RETRIED` to audit; return `{"status":"queued","resumed_from_checkpoint": checkpoint_exists}`. **Note**: cancel and delete handlers were moved to T025 (Phase 3) so they work in the MVP â€” only retry is added here since it depends on failed jobs existing
- [x] T055 [US5] Update `static/js/pages/job-queue.js` â€” History section: table shows all completed/failed/cancelled jobs; columns: source filename (via `el()` textContent â€” ISSUE-16), date, source duration, activity duration, activity%, output filename, status; "Reopen Timeline" button â†’ `navigate("/jobs/{id}")`; "Re-export" button â†’ POST export API; "Delete" button â†’ confirmation modal â†’ DELETE API; "Retry" button for failed jobs

**Checkpoint**: Complete 2 jobs. Verify both appear in history with correct stats. Reopen second job, change 1 exclusion, re-export. Verify two distinct output files exist with different timestamps.

---

## Phase 8: US6 â€” Install the Dashboard as a Native PWA (Priority: P2)

**Goal**: App installable on Android/iOS/desktop. Opens in standalone mode (no browser chrome). Offline shell visible when Pi unreachable.

**Independent Test**: Visit `https://raspberrypi.local:5000` on Android Chrome. Accept cert warning. Confirm install prompt appears. Install. Open from home screen. Confirm standalone mode (no address bar). Stop the Pi service. Reopen app â€” confirm "Pi not reachable" message, not browser error.

### Implementation for User Story 6

- [x] T056 [US6] Create `static/manifest.json`: `name:"RasPi CCTV Analyst"`, `short_name:"CCTV Analyst"`, `display:"standalone"`, `start_url:"/"`, `background_color:"#0f172a"`, `theme_color:"#2563eb"`, `orientation:"any"`, icons array with 192px and 512px entries (maskable purpose on 512)
- [x] T057 [US6] Create `static/icons/icon-192.png` and `static/icons/icon-512.png`: camera/shield motif SVG converted to PNG at both sizes; 512px uses `purpose: "any maskable"` with logo centred in 80% safe zone; generate using Inkscape CLI or Python `cairosvg`/`Pillow`
- [x] T058 [US6] Write `static/sw.js`: define `CACHE_NAME = "cctv-shell-v1"`; `SHELL_URLS` = all 8 HTML pages + all CSS files + `app.js`, `api.js`, `sse-client.js` + manifest + icons; `install` event: `caches.open(CACHE_NAME).then(c => c.addAll(SHELL_URLS))`; `fetch` event: if `url.pathname.startsWith("/api/")` â†’ NEVER intercept (live data must always be fresh); else â†’ `caches.match(request).then(cached => cached || fetch(request))`; `activate` event: delete old cache versions; offline fallback for non-API requests that miss cache
- [x] T059 [US6] Update all `static/pages/*.html`: add `<link rel="manifest" href="/static/manifest.json">`, `<meta name="theme-color" content="#2563eb">`, `<meta name="apple-mobile-web-app-capable" content="yes">`, `<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">`, `<meta name="apple-mobile-web-app-title" content="CCTV Analyst">`
- [x] T060 [US6] Write `install.sh`: check `uname -m` for aarch64 (warn if not); `sudo apt-get install -y ffmpeg python3-pip python3-venv`; `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`; `mkdir -p data/uploads data/jobs data/previews outputs ssl`; generate TLS cert if `ssl/cert.pem` does not exist: `openssl req -x509 -newkey rsa:4096 -nodes -days 3650 -keyout ssl/key.pem -out ssl/cert.pem -subj "/CN=raspberrypi.local" -addext "subjectAltName=DNS:raspberrypi.local,DNS:localhost,IP:127.0.0.1"` (ISSUE-01); `python -c "from app.database import init_db; init_db()"`; copy and configure `cctv-analyst.service`; `systemctl daemon-reload && systemctl enable cctv-analyst`; print `"Dashboard: https://$(hostname).local:5000"` (FR-040â€“FR-043)
- [x] T061 [US6] Write `cctv-analyst.service`: `ExecStart={INSTALL_DIR}/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 5000 --workers 1 --ssl-keyfile ssl/key.pem --ssl-certfile ssl/cert.pem`; `MemoryMax=1400M`; `CPUQuota=360%`; `Restart=on-failure`; `RestartSec=10`; `WorkingDirectory={INSTALL_DIR}`; `[Install] WantedBy=multi-user.target`

**Checkpoint**: Install on Android device. Confirm standalone mode. Stop service. Confirm offline shell (not browser error page).

---

## Phase 9: US7 â€” Monitor System Health (Priority: P3)

**Goal**: System Diagnostics page shows live CPU temp, RAM, disk, uptime with 10s updates. Disk warning banner visible on all pages.

**Independent Test**: Open System page during detection. Confirm all 4 gauges show values and update every 10 seconds without page reload. Verify disk warning banner appears site-wide when disk > 85%.

### Implementation for User Story 7

- [x] T062 [US7] Write `app/api/system.py` â€” `GET /api/system/stats`: `cpu_percent = psutil.cpu_percent(interval=None)`; `vm = psutil.virtual_memory()`; `temp_c = system.get_cpu_temp()` (None if unavailable, ISSUE-14); `disk = shutil.disk_usage(DATA_DIR)`; `uptime_s = time.time() - psutil.boot_time()`; maintain module-level `_temp_history: deque` of `(unix_ts, temp_c)` maxlen=30, populated by `_TempPoller` threading.Timer that reschedules itself every 10s; return full stats dict including `disk_warn: bool`, `ram_mode: str`
- [x] T063 [US7] Write `app/api/dashboard.py` â€” `GET /api/dashboard`: call `/api/system/stats` logic; query last 5 completed/running jobs; get active job (first `status IN ('running','detecting','exporting')`); compute `storage_warning = disk_percent > disk_warn_percent`; return combined response
- [x] T064 [P] [US7] Write `static/pages/system.html` (System Diagnostics page shell)
- [x] T065 [US7] Write `static/js/pages/system.js`: mount `system-gauges.js`; poll `api.system.stats()` every 10 seconds; update gauges and sparkline; display uptime as "Xd Xh Xm"; display app version and RAM mode badge; service status (check if API responds vs shows error)
- [x] T066 [P] [US7] Write `static/pages/index.html` (Dashboard page shell)
- [x] T067 [US7] Write `static/js/pages/dashboard.js`: 4-card system status row (CPU temp, RAM%, Disk%, CPU%); recent 5 jobs card list (clickable â†’ job detail); "New Analysis Job" CTA button; storage warning banner (conditionally rendered when `storage_warning:true`); active job widget showing live progress; poll `api.dashboard()` every 10 seconds

**Checkpoint**: Open System page during a running job. Confirm all gauges updating. Simulate high disk by checking `disk_warn` flag.

---

## Phase 10: US8 â€” Configure Global Defaults (Priority: P3)

**Goal**: Settings page persists defaults across reboots. New jobs inherit them. Analytics, reports, and audit pages complete the 8-page dashboard.

**Independent Test**: Change default sensitivity to "High" in Settings. Open New Job page â€” confirm slider defaults to High. Reboot Pi â€” confirm setting preserved. Verify "Unsaved changes" indicator appears when navigating away without saving (clarification Q3 companion).

### Implementation for User Story 8

- [x] T068 [US8] Write `app/api/settings.py` â€” `GET /api/settings`: read `config.json`, return parsed dict; create with defaults if file missing; `PUT /api/settings`: validate all fields via Pydantic model (e.g., `thermal_limit_c` must be 60â€“90, `disk_warn_percent` must be 50â€“95); write `config.json`; log `SETTINGS_CHANGED` to audit; return `{"saved":true}`; HTTP 422 on validation failure (FR-049)
- [x] T069 [US8] Write `app/api/audit.py` â€” `GET /api/audit`: supports `?level=`, `?actor=`, `?job_id=`, `?start=` (ISO date), `?end=`, `?limit=100`, `?offset=0`; builds parameterized SQL with dynamic WHERE clauses (NEVER string interpolation); returns entries + total; also add audit CSV export endpoint returning `StreamingResponse` with `text/csv`
- [x] T070 [P] [US8] Write `static/pages/settings.html` (Settings page shell)
- [x] T071 [US8] Write `static/js/pages/settings.js`: pre-populate all fields from `api.settings.get()`; dirty-state tracking (compare current vs saved JSON); "Unsaved changes" amber banner when dirty; "Save Settings" button â†’ `api.settings.put(data)` â†’ toast success; dark mode toggle: toggle `data-theme="dark"` on `<html>` AND persist to `localStorage` AND include in settings PUT body; MOG2 history advanced field (hidden by default, "Show advanced" link)
- [x] T072 [P] [US8] Write `static/pages/reports.html` (Reports page shell)
- [x] T073 [US8] Write `static/js/pages/reports.js`: job selector dropdown (completed jobs only); on select â†’ `api.reports.analytics(id)` â†’ render hourly bar chart (pure SVG, 24 bars labelled 00:00â€“23:00); duration histogram (5 SVG bars); summary stats table; "Export PDF" â†’ `window.open("/api/reports/{id}/pdf")`; "Export CSV" â†’ `window.location.href = "/api/reports/{id}/csv"`
- [x] T074 [P] [US8] Write `static/pages/audit.html` (Audit Log page shell)
- [x] T075 [US8] Write `static/js/pages/audit.js`: filter bar: Level dropdown, Actor dropdown, Job ID input, date range pickers; "Apply" fetches `api.audit.list(params)`; virtualized table: render 50 visible rows, replace on scroll (prevent DOM pressure for 10k+ entries); all audit entry text via `el()` textContent (ISSUE-16); "Export CSV" button; timestamp display in local time

**Checkpoint**: All 8 dashboard pages load correctly. Settings persist after `systemctl restart cctv-analyst`. Audit log shows entries from all previous test actions.

---

## Phase 11: Polish & Packaging

**Purpose**: Finalise deployment artifacts, run end-to-end validation, verify all success criteria.

- [x] T076 Write `Dockerfile`: `FROM arm64v8/python:3.11-slim`; `RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*`; `WORKDIR /app`; `COPY requirements.txt .`; `RUN pip install --no-cache-dir -r requirements.txt`; `COPY . .`; `RUN mkdir -p data/uploads data/jobs data/previews outputs ssl`; `EXPOSE 5000`; `CMD ["python","-m","uvicorn","app.main:app","--host","0.0.0.0","--port","5000","--workers","1"]`
- [x] T077 Write `docker-compose.yml`: service `cctv-analyst`; `build:.`; `ports:["5000:5000"]`; `volumes:[./data:/app/data, ./outputs:/app/outputs, ./ssl:/app/ssl, ./cctv_analyst.db:/app/cctv_analyst.db, ./config.json:/app/config.json, /media:/media:ro]`; `restart:unless-stopped`; `mem_limit:1400m`; `cpus:3.6`
- [x] T078 [P] Write `README.md`: hardware requirements; one-command install; first-run steps; how to access at `https://raspberrypi.local:5000`; hardware requirements table; supported formats; performance benchmarks; FAQ for cert warning, thermal throttling, disk space
- [x] T079 Run end-to-end validation per `specs/001-raspi-cctv-v1-core/quickstart.md`: submit 30-min H.264 test video â†’ detect â†’ review (exclude 2 events) â†’ export â†’ play in browser â†’ verify chapter markers â†’ trigger crash (restart service mid-detection) â†’ confirm resume within 1-2s â†’ verify SC-001 through SC-010 checklist
- [x] T080 [P] Verify SC-007 memory ceiling: `watch -n 5 "systemctl status cctv-analyst | grep Memory"` during 24h detection job; confirm `MemoryCurrent` stays â‰¤ 1400MB throughout

**Checkpoint**: Full end-to-end golden path passes. All 10 Success Criteria verified.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies â€” start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 â€” **BLOCKS all user story phases**
- **Phase 3 (US1)**: Depends on Phase 2 â€” first independently testable story
- **Phase 4 (US3)**: Depends on Phase 2 + Phase 3 (needs working job submission to test timeline)
- **Phase 5 (US4)**: Depends on Phase 4 (export button lives on Job Detail page)
- **Phase 6 (US2)**: Depends on Phase 2 + Phase 4 (SSE log panel extends Job Detail page)
- **Phase 7 (US5)**: Depends on Phase 3 + Phase 5 (needs completed jobs to reopen)
- **Phase 8 (US6)**: Depends on Phase 1 (HTTPS) + Phase 3 (needs pages to cache)
- **Phase 9 (US7)**: Depends on Phase 1 (system.py util) â€” can start early
- **Phase 10 (US8)**: Depends on Phase 3 (settings API used by new job form defaults)
- **Phase 11 (Polish)**: Depends on all phases complete

### User Story Dependencies

- **US1 (P1)**: First story â€” no story dependencies
- **US3 (P1)**: Can start after Phase 2; needs a completed job from US1 for independent test
- **US4 (P1)**: Depends on US3 (export is part of Job Detail page)
- **US2 (P2)**: Depends on Phase 2 (SSE engine); partially extends US3's Job Detail page
- **US5 (P2)**: Depends on US1 + US4 (needs completed exports to re-export)
- **US6 (P2)**: Independent of other stories (only needs the pages to exist)
- **US7 (P3)**: Almost independent â€” only needs Phase 1 utilities
- **US8 (P3)**: Depends on US1 (settings feed into new job form)

### Critical Path

`Phase 1 â†’ Phase 2 â†’ Phase 3 (US1) â†’ Phase 4 (US3) â†’ Phase 5 (US4)` â€” the P1 MVP path.

### Parallel Opportunities Within Each Phase

**Phase 1**: T002, T003, T006â€“T010 all `[P]` â€” run in parallel after T001
**Phase 2**: T014â€“T015 parallel; T016â€“T017 parallel; T018â€“T023 can run in parallel once T015 (log_buffer) done
**Phase 3 (US1)**: T024, T028â€“T030, T032â€“T034, T037, T039 all `[P]` â€” run in parallel

---

## Implementation Strategy

### MVP (P1 Stories Only â€” Phases 1â€“5)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational â€” **critical blocker**
3. Complete Phase 3: US1 â†’ Test: submit job, see it queued
4. Complete Phase 4: US3 â†’ Test: review timeline, preview clip
5. Complete Phase 5: US4 â†’ Test: export, verify merged MP4 with chapters
6. **STOP AND VALIDATE**: Full pipeline working end-to-end

### Incremental Delivery (Add P2 then P3)

1. Foundation + P1 stories â†’ Working core pipeline (MVP)
2. Add Phase 6 (US2 â€” live progress) â†’ Real-time monitoring working
3. Add Phase 7 (US5 â€” history) â†’ Re-export without re-detection working
4. Add Phase 8 (US6 â€” PWA) â†’ Installable on phone/laptop
5. Add Phases 9â€“10 (US7+US8 â€” system + settings) â†’ Full dashboard complete
6. Phase 11 (Packaging) â†’ Production-ready

### Error Prevention (User's Requirement: "no errors or malfunctions")

Tasks include explicit ISSUE references ensuring every known error source is addressed:
- ISSUE-01 (HTTPS): T060, T061
- ISSUE-02 (timestamp drift): T019 (detection_engine), T007 (ffprobe avg_frame_rate)
- ISSUE-03 (FFmpeg RAM): T017 (ram_guard system-wide), T025 (4K warning)
- ISSUE-04 (clip preview): T020 (export_engine.generate_preview), T041, T046
- ISSUE-05 (MOG2 resume): T019 (warmup pass + checkpoint)
- ISSUE-06 (frame skip): T019 (fps filter in FFmpeg)
- ISSUE-07 (morphological filter): T019 (MORPH_OPEN + MORPH_CLOSE)
- ISSUE-08 (SSE thread pool): T015 (log_buffer asyncio.Queue), T050 (sse.py)
- ISSUE-09 (event dedup): T018 (job_queue DELETE before resume), T019
- ISSUE-10 (NVR PTS): T020 (export_engine -fflags +genpts+igndts)
- ISSUE-11 (audio check): T020 (audio_flags conditional)
- ISSUE-12 (disk check): T025 (jobs.py POST validation)
- ISSUE-13 (codec warning): T007 (ffprobe needs_reencode), T025 (warning response)
- ISSUE-14 (vcgencmd): T008 (system.py graceful fallback)
- ISSUE-15 (mobile canvas): T043 (timeline-strip.js pointer:coarse)
- ISSUE-16 (XSS via innerHTML): T032 (api.js el() builder), T044 (event-card), T055, T075
- ISSUE-17 (MOG2 slow objects): T019 (configurable history, documented in settings)

**Post-analysis fixes applied (speckit-analyze remediation):**
- C1 (zone frame endpoint): T026b added â€” `GET /api/jobs/{id}/zone-frame`
- C2 (output serving endpoint): T047b added â€” `GET /api/jobs/{id}/output` + `GET /api/jobs/{id}/exports`
- C3 (disk warning all pages): T033 (nav.js) updated â€” disk warning in persistent nav
- I1 (cancel/delete ordering): T025 updated â€” cancel/delete moved to Phase 3 (MVP); T054 updated â€” retry only
- I2 (re-export orphan files): T011 (exports table), T047 (INSERT into exports), T047b (exports history endpoint)
- I3 (replay 100 lines): T015 updated â€” subscribe() replays last 100 not all 2000
- A1 (recording_start): T007 updated â€” ffprobe extracts creation_time tag
- A2 (estimated size formula): T046 updated â€” formula specified for stream copy and re-encode modes
- A3 (re-encode trigger): T020 updated â€” OR condition (needs_reencode OR quality != original)
- A4 (explicit URLs): T013 updated â€” all 8 URLâ†’HTML mappings listed explicitly
- A5 (preview cleanup): T013 updated â€” cleanup coroutine registered in lifespan startup

---

## Notes

- All `[P]` tasks write to different files â€” no shared state, safe to run in parallel
- Each user story phase ends with an explicit **Checkpoint** â€” stop and test before proceeding
- `superpowers:code-reviewer` MUST run after each phase Checkpoint passes
- Commit after each phase with message: `feat(phase-N): [description] â€” closes US#`
- Never use `innerHTML` with API data anywhere in `static/js/` â€” enforced by `el()` builder
- PDF reports served via `FileResponse` (disk-backed) â€” NOT `StreamingResponse(BytesIO)` (buffers full PDF in RAM)
- Upload endpoint uses `Request.stream()` â€” NOT `UploadFile` (may buffer full file)
- Timeline canvas uses `requestAnimationFrame` only on state changes â€” no continuous animation loop

