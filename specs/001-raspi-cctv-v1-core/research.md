# Phase 0 Research: RasPi CCTV Analyst — v1 Core Pipeline

**Branch**: `001-raspi-cctv-v1-core` | **Date**: 2026-05-05
**Status**: Complete — all NEEDS CLARIFICATION resolved

---

## Decision 1: FFmpeg MPEG-TS Intermediates → Concat Demuxer → MP4

**Decision**: Stream copy into `.ts` (MPEG-TS) segments, merge via `ffmpeg -f concat`, output MP4.

**Rationale**:
- MPEG-TS is a byte-stream format tolerant of mid-stream concatenation. MP4 requires a complete
  `moov` atom; segment extraction at arbitrary seek points produces broken MP4s without re-encoding.
- MKV segments can fail concat demuxer when timebase or codec metadata differs between segments.
- MPEG-TS with `-fflags +genpts+igndts -avoid_negative_ts make_zero` survives NVR PTS resets
  (Hikvision/Dahua stream restarts at midnight) — the single most common CCTV file pathology.
- TS demuxing has lower RAM overhead than MP4 moov parsing on 2GB Pi.

**Alternatives considered**:
- Direct MP4 segments: broken moov at arbitrary seek points → rejected
- MKV segments: timebase sensitivity → rejected
- Re-encode to normalise: defeats the purpose of stream copy speed → rejected

---

## Decision 2: OpenCV MOG2 via FFmpeg Rawvideo Pipe (Not cv2.VideoCapture)

**Decision**: `subprocess.Popen(["ffmpeg", ..., "-f", "rawvideo", "-"])` pipes RGB24 frames to Python.
`cv2.VideoCapture` with file path is not used.

**Rationale**:
- `cv2.VideoCapture` internal state (buffer position, decode context) is not serialisable.
  On crash or cancel, the exact frame position cannot be recovered externally.
- FFmpeg pipe: spawn new process with `-ss {checkpoint_pts_time}` to seek to any exact timestamp.
  Python loop is stateless — only the checkpoint file and SQLite events table carry state.
- Allows clean cancellation: set `_cancel_event`, drain the pipe, `proc.terminate()`. No internal
  OpenCV state to corrupt.
- Frame skip via FFmpeg `fps` filter (not Python loop): halves pipe bandwidth AND allows FFmpeg
  to skip non-reference frame decoding, improving speed ~20-30% (ISSUE-06).
- `showinfo` filter on the same `-vf` chain provides accurate `pts_time` per frame with zero
  additional overhead (ISSUE-02 timestamp drift fix).

**Alternatives considered**:
- `cv2.VideoCapture`: cannot checkpoint, cannot cleanly cancel → rejected
- `ffmpeg-python` wrapper: adds abstraction layer with marginal benefit; subprocess directly
  is simpler and more controllable → not used

---

## Decision 3: SQLite WAL Mode + Thread-Local Connections

**Decision**: Single `cctv_analyst.db`, WAL journal mode, `threading.local()` connections.

**Rationale**:
- WAL mode: readers (FastAPI API threads) never block writers (detection worker thread).
  Without WAL, each `INSERT` from the worker stalls API reads by ~100ms on USB SSD.
  With WAL, 2-5× faster API responsiveness under detection workload.
- Thread-local: each thread calls `get_conn()` → returns its own `sqlite3.Connection`.
  No pool overhead, no deadlocks, correct for 2-thread workload (API + worker).
- `PRAGMA synchronous=NORMAL` + WAL: safe on power loss (WAL checkpoints are atomic),
  2× faster writes than `FULL` synchronous mode.
- Pool alternatives (SQLAlchemy, aiosqlite): add ~30MB RAM + indirection → rejected for
  a 2-thread embedded app.

**Alternatives considered**:
- PostgreSQL: zero justification for external DB on single-user embedded Pi → rejected
- SQLAlchemy ORM: adds 30MB RAM, generates inefficient SQL for known schema → rejected
- aiosqlite: async wrapper around SQLite, but detection runs in sync worker thread → mismatch

---

## Decision 4: uvicorn Single Worker (--workers 1)

**Decision**: `uvicorn app.main:app --workers 1` (default). Multiprocessing disabled.

**Rationale**:
- 4-worker scenario: 4 × ~197MB Python RSS = 788MB, plus FFmpeg ~100MB, OS ~500MB = 1388MB →
  dangerously close to 1400MB systemd ceiling, OOM risk during detection.
- The workload is I/O-bound (FFmpeg pipe reads, DB writes, file I/O), not CPU-bound.
  FastAPI's async handles thousands of concurrent HTTP connections on 1 worker with no throughput loss.
- Detection runs in a `threading.Thread` (not a uvicorn worker), so scaling workers does not
  add detection capacity.
- Multiple workers would each spawn detection threads, creating SQLite write-lock races.

**Alternatives considered**:
- `--workers 4`: OOM risk + SQLite race conditions → rejected
- Celery/RQ for background processing: overkill for single-job-at-a-time embedded workload → rejected

---

## Decision 5: opencv-python-headless (Not opencv-python)

**Decision**: `opencv-python-headless==4.9.*` in requirements.txt.

**Rationale**:
- `opencv-python` pulls Qt, GTK, X11 stubs (~220MB installed). None of these are available or
  useful on Raspberry Pi OS Lite (no display server).
- `opencv-python-headless` produces the identical `cv2` module, same API surface, zero GUI deps.
- ~10MB RAM savings at import time (no Qt stubs loaded into process).
- `opencv-python` requires `libsm6 libxext6 libxrender-dev` — may not be installed on Pi OS Lite,
  causing `ImportError` at runtime. `headless` has zero external non-standard deps.

---

## Decision 6: HTTPS Self-Signed Certificate for PWA

**Decision**: `install.sh` generates a 4096-bit RSA self-signed cert with SAN for `raspberrypi.local`.
uvicorn starts with `--ssl-keyfile ssl/key.pem --ssl-certfile ssl/cert.pem`.

**Rationale**:
- Service worker registration is blocked on non-HTTPS, non-localhost origins (Chrome, Firefox,
  Safari, Android WebView — all enforce this).
- `raspberrypi.local` is an mDNS `.local` address. Some browsers treat `.local` as potentially
  localhost-equivalent, but this behaviour is inconsistent across browser versions — it cannot
  be relied upon.
- Self-signed cert with SAN (`DNS:raspberrypi.local,DNS:localhost,IP:127.0.0.1`): after the
  operator accepts the certificate warning once on each device, the browser stores the
  exception and service worker registration succeeds on subsequent visits.
- `mkcert` is an advanced alternative for zero browser warning (locally trusted cert). Documented
  in install.sh as an optional upgrade path.

**Alternatives considered**:
- Plain HTTP: service worker silently fails to register → PWA install broken → rejected
- Let's Encrypt: requires public DNS and ACME challenge — impossible for LAN-only → rejected
- mkcert: excellent UX but requires extra tool installation; self-signed is zero-dependency → default

---

## Decision 7: asyncio.Queue Fan-Out for SSE

**Decision**: `log_buffer.py` uses `asyncio.Queue` per subscriber. SSE endpoint does `await queue.get()`.

**Rationale**:
- Blocking iterator in `run_in_executor`: holds a thread pool thread for the entire job duration
  (up to 2 hours). FastAPI's thread pool (min(32, cpu_count×5) ≈ 20 on Pi) could be exhausted
  by 4-5 concurrent SSE clients, stalling all sync operations (settings saves, cancels).
- `asyncio.Queue`: fully async, zero thread pool usage. The worker thread calls
  `loop.call_soon_threadsafe(queue.put_nowait, line)` — bridges sync worker thread to async
  event loop without blocking.
- Keepalive: send `{"type":"keepalive"}` every 30s via `asyncio.wait_for(queue.get(), timeout=30)`.
  Prevents proxy timeouts (Nginx default 60s, HAProxy default varies). Add `X-Accel-Buffering: no`
  header for Nginx reverse proxy scenarios.

---

## Decision 8: Request.stream() for Chunked Upload (Not UploadFile)

**Decision**: `app/api/upload.py` uses `async for chunk in request.stream()` with explicit 65KB buffer.

**Rationale**:
- FastAPI's `UploadFile` may buffer the entire part in memory depending on python-multipart
  version and content-length headers. For a 21GB upload, this is catastrophic OOM.
- `Request.stream()` is a raw async generator yielding bytes from the network socket directly.
  Combined with `aiofiles.open(path, "wb")` and explicit `await f.write(chunk)`, the maximum
  in-memory footprint is exactly one network read buffer (~65KB).
- Browser: `File.slice(start, end)` creates a `Blob` reference (lazy — OS filesystem handle,
  not a memory copy). When `fetch()` sends the blob, the browser reads 64KB at a time from
  disk into the network buffer. Safe for 21GB files.

---

## Decision 9: FileResponse for PDF Reports (Not StreamingResponse(BytesIO))

**Decision**: `report_gen.py` saves PDF to a named temp file; `reports.py` returns `FileResponse(path)`.

**Rationale**:
- `StreamingResponse(BytesIO(pdf_bytes))`: buffers the entire PDF in RAM before the first byte
  is sent to the client. A 50-thumbnail PDF is ~15-40MB — unnecessary RAM pressure.
- `FileResponse`: FastAPI sends the file in chunks from disk using `starlette.responses.FileResponse`
  which internally uses `anyio.open_file()` with chunked reads. True streaming from disk.
- `ReportLab 4.1+` ships pure-Python aarch64 wheels — no C compilation on Pi.
- RAM during generation with ~200 event thumbnails: ~80-120MB (within budget, acceptable).
- Temp file is deleted by a background cleanup coroutine after `FileResponse` completes.

---

## Resolved: No NEEDS CLARIFICATION Items

All Technical Context fields in `plan.md` are fully specified. No technology choices remain open.
The spec clarification session resolved 5 additional ambiguities (see `spec.md` § Clarifications).

**Recommendation**: Proceed to Phase 1 (data-model.md, contracts, quickstart.md).
