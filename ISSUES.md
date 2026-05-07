# Pre-Implementation Issues Register
## RasPi CCTV Analyst — Discovered Before Coding Began

These issues were identified through deep spec review and hardware analysis before any code was written.
Each entry documents: the problem, why it matters, and the exact fix applied in the implementation.

---

## Severity Legend
- 🔴 **Blocker** — Feature completely broken or data corrupted without fix
- 🟠 **High** — Significant accuracy/reliability failure under real-world conditions
- 🟡 **Medium** — Bad UX or security gap; degraded but functional

---

## 🔴 ISSUE-01 — PWA Will Not Install Over HTTP

**Status:** Fixed in Phase 7 (PWA) and Phase 10 (install.sh)

**Problem:**
Service workers — the technology that enables PWA installation — only register on `https://` origins,
`localhost`, and `127.0.0.1`. The spec targets `http://raspberrypi.local:5000`.
Chrome, Firefox, and Android **silently refuse** to register the service worker at this origin.
The "Add to Home Screen" install prompt never appears. The PWA feature the user chose is completely non-functional over plain HTTP.

**Evidence:** Chrome Secure Contexts spec; MDN Service Worker API requirements.

**Fix:**
`install.sh` auto-generates a self-signed TLS certificate at installation time:
```bash
openssl req -x509 -newkey rsa:4096 -nodes -days 3650 \
  -keyout ssl/key.pem -out ssl/cert.pem \
  -subj "/CN=raspberrypi.local" \
  -addext "subjectAltName=DNS:raspberrypi.local,DNS:localhost,IP:127.0.0.1"
```
Uvicorn starts with `--ssl-keyfile ssl/key.pem --ssl-certfile ssl/cert.pem`.
The app runs at `https://raspberrypi.local:5000`. On first visit, the user accepts the
browser's self-signed cert warning once. After that, the PWA installs cleanly on any device.

Advanced users may substitute `mkcert` for a locally-trusted cert (zero browser warning).

**Files affected:** `install.sh`, `cctv-analyst.service`, `docker-compose.yml`, `app/main.py`

---

## 🔴 ISSUE-02 — Timestamp Drift on Long Recordings

**Status:** Fixed in Phase 3 (Detection Engine)

**Problem:**
The plan calculated event timestamps as `frame_count / nominal_fps` using `r_frame_rate` from ffprobe
(the header value). Many CCTV cameras output at 23.976fps, 29.97fps, or variable rates but their
container headers report `r_frame_rate` as 24 or 30.

Drift over 24 hours example:
- True FPS: 29.97 | Header FPS: 30.00
- Drift rate: `(30 - 29.97) / 30 = 0.001` seconds per second
- Over 24h: `0.001 × 86400 = 86.4 seconds` of accumulated error

At the end of a 24-hour recording, events would be timestamped ~1.5 minutes late.
Exported clips would be cut at the wrong times — the "motion event" would actually contain
post-event footage rather than the event itself.

**Fix:**
Use FFmpeg's `showinfo` filter to extract precise PTS (Presentation TimeStamp) per frame.
PTS values are derived from the container's actual encoded timestamps, not from frame counting:
```python
"-vf", f"fps={target_fps:.3f},scale={W}:{H},showinfo"
```
Parse PTS from FFmpeg stderr:
```
[Parsed_showinfo] n:   0 pts: 1234567 pts_time:41.152
```
The `pts_time` value is used as the frame's authoritative timestamp.
This is accurate to the millisecond regardless of FPS header values, and handles
variable-framerate (VFR) footage from NVR systems correctly.

**Files affected:** `app/core/detection_engine.py`, `app/utils/ffprobe.py`

---

## 🔴 ISSUE-03 — FFmpeg Subprocess RAM Not Counted in Memory Budget

**Status:** Fixed in Phase 1 (config.py) and Phase 2 (job validation)

**Problem:**
The original memory budget (~197MB) only accounted for the Python process.
FFmpeg is a **separate OS process** with its own decode buffers not visible to `psutil`
RSS readings of the Python process.

FFmpeg internal memory for video decode (approximate, from libavcodec reference frames):
- 720p H.264: ~30MB
- 1080p H.264: ~80-120MB
- 1080p H.265: ~80-150MB
- 4K H.264: ~200-350MB
- 4K H.265: ~300-500MB

Revised worst-case for Pi 5 2GB:
```
OS + drivers:          ~500MB
Python + FastAPI:       ~197MB
FFmpeg (1080p H.264):  ~100MB
─────────────────────────────
Total:                 ~797MB   ✅ safe (1.2GB headroom)

FFmpeg (4K H.265):     ~400MB
─────────────────────────────
Total:                ~1100MB   ⚠️ only 900MB headroom
```

**Fix:**
1. `app/utils/ffprobe.py` extracts source `width` and `height` at job creation.
2. `app/api/jobs.py` at job creation: if `width > 1920` and RAM mode is `2gb`, return a
   non-blocking warning in the API response:
   ```json
   { "warning": "4K source detected. Processing on 2GB Pi may be slow and RAM-constrained. Consider downscaling the source to 1080p first." }
   ```
3. `ram_guard.py` monitors **system-wide** free memory (`psutil.virtual_memory().available`),
   not just the Python process RSS. This catches FFmpeg's subprocess memory consumption.
4. RAM guard threshold lowered to trigger at 75% system memory used (not 80%) to leave
   more headroom for the FFmpeg subprocess.

**Files affected:** `app/config.py`, `app/core/ram_guard.py`, `app/api/jobs.py`, `app/utils/ffprobe.py`

---

## 🔴 ISSUE-04 — Clip Preview Cannot Use Raw HTTP Range Requests

**Status:** Fixed in Phase 5 (API endpoints) and Phase 6 (frontend)

**Problem:**
The original plan served clip previews via HTTP range requests on the raw source file.
This **does not work**. A browser `<video>` element cannot decode an H.264 stream starting
from an arbitrary byte offset — it needs a proper MP4 container starting from a keyframe
with correct PTS timestamps. Sending a raw byte range from the middle of a 21GB MP4
produces garbled video or nothing at all.

HTTP range requests work for *serving* a complete video file that is already properly
containerized. They do not work for *slicing* a portion of a source video on the fly.

**Fix:**
On-demand temp clip extraction endpoint:
```
POST /api/jobs/{id}/events/{eid}/preview
→ { "preview_url": "/api/previews/{token}.mp4", "expires_in": 300 }
```
Backend extracts a properly-containerized clip:
```bash
ffmpeg -ss {start_s - 2} -i source.mp4 -t {duration + 4} \
       -c copy -movflags faststart /tmp/previews/{token}.mp4
```
`-movflags faststart` places the MP4 moov atom at the front so the browser can play
without downloading the full clip. `-ss` before `-i` ensures fast seek to a keyframe.
The clip is a properly-formed MP4 file ready for HTML5 video streaming with range-request support.
Temp clips are auto-deleted after 5 minutes by a background cleanup coroutine.

**Files affected:** `app/api/jobs.py` (new preview endpoint), `app/core/export_engine.py`,
`static/js/pages/job-detail.js`

---

## 🟠 ISSUE-05 — MOG2 Background Model Lost After Crash Resume

**Status:** Fixed in Phase 3 (Detection Engine)

**Problem:**
MOG2's background model is an in-memory Gaussian mixture model. It cannot be serialized
or saved to disk in standard OpenCV. After a crash and resume from `checkpoint.json`,
a fresh MOG2 instance is created with zero background knowledge.

For the first ~500 frames after resuming (~17-20 seconds of footage at 25fps), MOG2
classifies **every pixel as foreground** because it has not yet learned the scene.
This floods the timeline with false-positive motion events during the warmup window.

**Fix:**
After seeking to the checkpoint frame, run a **500-frame silent warmup pass** where
MOG2 processes frames normally but detected events are discarded:
```python
WARMUP_FRAMES = config.MOG2_HISTORY  # 500
for _ in range(WARMUP_FRAMES):
    raw = proc.stdout.read(frame_size)
    if not raw or len(raw) < frame_size:
        break
    frame = np.frombuffer(raw, np.uint8).reshape((H, W, 3))
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    mog2.apply(gray)  # updates model; result discarded
log_buffer.append(job_id, "[RESUME] Background model warmed up. Resuming detection.")
```
After warmup, normal event detection resumes. This costs ~1 second of wall-clock time
(Python can process 500 small grayscale frames very quickly) but ensures clean detection.

**Files affected:** `app/core/detection_engine.py`

---

## 🟠 ISSUE-06 — Frame Skip Performed in Python Instead of FFmpeg

**Status:** Fixed in Phase 3 (Detection Engine)

**Problem:**
The original plan piped ALL frames from FFmpeg into Python, then skipped alternate frames
in the Python loop. This is wasteful:

- 24h at 25fps = 2,160,000 frames
- Each frame at 320×240 RGB = 230KB
- Total pipe data = **~470GB** piped from FFmpeg to Python
- Python reads and immediately discards every other frame (50% of pipe data)

The pipe is the bottleneck: the Pi's USB 3.0 bus and Python's `stdout.read()` loop are
doing twice as much work as necessary.

**Fix:**
Apply frame skip inside FFmpeg using the `fps` filter before scaling:
```python
target_fps = source_fps / (frame_skip + 1)  # frame_skip=1 → halve fps
"-vf", f"fps={target_fps:.4f},scale={W}:{H},showinfo"
```
FFmpeg applies the fps filter before the scale filter. At `fps=12.5` (half of 25fps):
- FFmpeg decodes only the frames it needs to output (skips B-frame decoding for dropped frames)
- Pipe carries only ~235GB instead of ~470GB
- Python loop processes ~1,080,000 frames instead of ~2,160,000
- **~2× speedup** with zero accuracy loss for the detection task

**Files affected:** `app/core/detection_engine.py`

---

## 🟠 ISSUE-07 — No Morphological Filtering on MOG2 Mask

**Status:** Fixed in Phase 3 (Detection Engine)

**Problem:**
MOG2's foreground mask contains isolated noise pixels: single-pixel hits from JPEG/H.264
compression artifacts, IR camera grain, subtle lighting changes, and lens dust.
Counting these with `cv2.countNonZero` inflates the motion score at medium/high sensitivity,
causing false positive events on every windy tree, passing cloud shadow, or flickering light.

**Fix:**
Apply two morphological passes between the threshold and the score step:
```python
kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
# OPEN: erode then dilate — removes small isolated blobs (noise)
fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
# CLOSE: dilate then erode — fills small holes in real motion regions
fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)
```
The 5×5 elliptical kernel removes blobs smaller than ~5 pixels diameter (noise)
while preserving blobs larger than that (actual foreground objects).
CPU cost: ~2% increase per frame — negligible.

This is standard practice in all production CCTV motion detection pipelines.

**Files affected:** `app/core/detection_engine.py`

---

## 🟠 ISSUE-08 — SSE Exhausts FastAPI Thread Pool

**Status:** Fixed in Phase 2 (log_buffer.py) and Phase 5 (SSE endpoint)

**Problem:**
`log_buffer.subscribe()` as a blocking sync iterator requires `asyncio.run_in_executor()`
in the FastAPI SSE endpoint, holding one thread from FastAPI's thread pool for the entire
job duration (up to 2+ hours).

FastAPI's default executor thread pool on Pi = `min(32, cpu_count × 5)` = min(32, 20) = 20.
With 4-5 browser tabs watching the same job (SSE connection per tab), 4-5 threads are held.
For a 2-hour job, these threads are unavailable for all other synchronous FastAPI operations
(settings changes, event toggles, job cancels). The UI becomes unresponsive.

**Fix:**
Replace the blocking sync iterator with an `asyncio.Queue`-based fan-out.
Each SSE client gets its own `asyncio.Queue`. The LogBuffer's `append()` method
(called from the background worker thread) uses `loop.call_soon_threadsafe()` to push
to all subscriber queues without blocking:

```python
# log_buffer.py
class LogBuffer:
    def __init__(self):
        self._history: dict[str, deque] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._loop: asyncio.AbstractEventLoop = None

    def set_loop(self, loop): self._loop = loop

    def append(self, job_id: str, line: str):
        self._history.setdefault(job_id, deque(maxlen=2000)).append(line)
        for q in self._subscribers.get(job_id, []):
            self._loop.call_soon_threadsafe(q.put_nowait, line)

    def subscribe(self, job_id: str) -> asyncio.Queue:
        q = asyncio.Queue()
        self._subscribers.setdefault(job_id, []).append(q)
        # Replay history
        for line in self._history.get(job_id, []):
            q.put_nowait(line)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue):
        subs = self._subscribers.get(job_id, [])
        if q in subs: subs.remove(q)
```

SSE endpoint (fully async, zero thread pool usage):
```python
async def event_stream(job_id: str):
    q = log_buffer.subscribe(job_id)
    try:
        while True:
            line = await asyncio.wait_for(q.get(), timeout=30.0)
            if line == "__DONE__": break
            yield f"data: {json.dumps({'type':'log','line':line})}\n\n"
    except asyncio.TimeoutError:
        yield "data: {\"type\":\"keepalive\"}\n\n"  # prevents proxy timeout
    finally:
        log_buffer.unsubscribe(job_id, q)
```

**Files affected:** `app/core/log_buffer.py`, `app/api/sse.py`

---

## 🟠 ISSUE-09 — Event Deduplication Missing on Crash Resume

**Status:** Fixed in Phase 2 (job_queue.py) and Phase 3 (detection_engine.py)

**Problem:**
After crash-resuming from a checkpoint, the detection engine continues from frame N.
The `events` table already contains events 0 through `last_event_index`.
The resumed detection re-detects events in the checkpoint window overlap (the last
incomplete batch of up to 30 frames). This inserts duplicate events with the same
timestamps, corrupting the timeline.

**Fix:**
Before resuming detection, trim the events table to the checkpoint's confirmed state:
```python
# In detection_engine.py, after loading checkpoint.json:
with get_conn() as conn:
    conn.execute(
        "DELETE FROM events WHERE job_id = ? AND event_index > ?",
        (job_id, checkpoint["last_confirmed_event_index"])
    )
    conn.commit()
```
`last_confirmed_event_index` is the index of the last fully-closed event at checkpoint time.
Any open/partial event at checkpoint time is discarded and will be re-detected cleanly.

**Files affected:** `app/core/detection_engine.py`, `app/core/job_queue.py`

---

## 🟠 ISSUE-10 — NVR Stream Restart PTS Discontinuities Break Export

**Status:** Fixed in Phase 4 (Export Engine)

**Problem:**
Many NVR systems (Hikvision, Dahua, Uniview) restart their H.264 streams hourly or at
midnight, resetting PTS (Presentation TimeStamp) to zero mid-file. The resulting file
appears to be one continuous recording but contains internal PTS discontinuities.

The concat demuxer produces garbled output when PTS values jump backwards. Symptoms:
- Audio/video desync in the output
- VLC shows wrong duration
- Some players refuse to play the file past the discontinuity point

**Fix:**
Add `-fflags +genpts+igndts` to ALL FFmpeg segment extraction commands:
```bash
ffmpeg -fflags +genpts+igndts -ss {start} -i {source} -t {duration} \
       -c copy -avoid_negative_ts make_zero {segment}.ts
```
- `+genpts`: Forces FFmpeg to generate new, monotonically-increasing PTS values
- `+igndts`: Ignores DTS values from the source (which may be wrong or negative)
- `-avoid_negative_ts make_zero`: Shifts the segment to start at PTS=0

This is safe for all input files (harmless when PTS is already correct) and fixes
all NVR stream-restart discontinuity cases.

Also add `-use_wallclock_as_timestamps 1` to the concat merge step as an additional guard.

**Files affected:** `app/core/export_engine.py`

---

## 🟠 ISSUE-11 — No Audio Stream Detection Before Export

**Status:** Fixed in Phase 1 (ffprobe.py) and Phase 4 (export_engine.py)

**Problem:**
CCTV cameras almost universally have no audio track. The original export FFmpeg command
included `-c:a copy`. When run against an audio-less source:
- FFmpeg logs: `Stream specifier ':a' in filtergraph... matches no streams`
- Output MP4 has a broken/empty audio track header
- Some players refuse to play the file or show "0:00" for audio duration

**Fix:**
`ffprobe.py` detects audio presence:
```python
has_audio = any(s["codec_type"] == "audio" for s in probe["streams"])
```
`export_engine.py` conditionally includes audio flags:
```python
audio_flags = ["-c:a", "copy"] if job.source_has_audio else ["-an"]
```
`-an` explicitly tells FFmpeg to strip audio entirely from the output — clean, no warnings.

**Files affected:** `app/utils/ffprobe.py`, `app/core/export_engine.py`, `app/database.py`
(add `source_has_audio` column to `jobs` table)

---

## 🟠 ISSUE-12 — No Disk Space Pre-Check Before Starting Detection

**Status:** Fixed in Phase 2 (job validation in jobs.py)

**Problem:**
A user submits a 24-hour 1080p job (source = 21GB). The system starts detection,
runs for 2 hours on Pi, then hits disk-full during FFmpeg segment extraction.
The job fails with a cryptic `ffmpeg: No space left on device` error.
The user has wasted 2 hours of Pi processing time.

The detection work is preserved in checkpoint.json and the events table, but
the failure is confusing and could have been caught at submission time.

**Fix:**
At job creation (`POST /api/jobs`), calculate estimated disk requirement:
```python
source_size = os.path.getsize(source_path)
# Segments: worst case = 100% activity = full source size
# Output: same as segments (stream copy, same bitrate)
# Thumbnails: ~200 events × 30KB = 6MB (negligible)
# Safety buffer: 20%
required_bytes = int(source_size * 2.2)
free_bytes = shutil.disk_usage(output_dir).free
if free_bytes < required_bytes:
    raise HTTPException(
        status_code=400,
        detail=f"Insufficient disk space. Need ~{required_bytes//1e9:.1f}GB, "
               f"only {free_bytes//1e9:.1f}GB available. Free up space or choose "
               f"a different output location."
    )
```
This is a hard block — the job is rejected before queuing. The user gets an immediate,
actionable error message.

**Files affected:** `app/api/jobs.py`

---

## 🟡 ISSUE-13 — No Codec Compatibility Warning for Re-encode Penalty

**Status:** Fixed in Phase 1 (ffprobe.py) and Phase 2 (job creation)

**Problem:**
VP9, AV1, MJPEG, and ProRes sources cannot be stream-copied into MPEG-TS intermediate
files. The export engine falls back to libx264 re-encoding, which adds 30-120+ minutes
to the job on Pi. The user is not warned — they expect the job to finish quickly based
on "Original Quality" being selected, then wait unexpectedly.

**Fix:**
At job creation, `ffprobe.py` checks codec against a stream-copy-safe whitelist:
```python
STREAM_COPY_SAFE = {"h264", "hevc", "mpeg2video", "mpeg4"}
codec = probe["streams"][0]["codec_name"]
needs_reencode = codec not in STREAM_COPY_SAFE
```
API response includes:
```json
{
  "job_id": "...",
  "warnings": [
    {
      "code": "CODEC_REENCODE_REQUIRED",
      "message": "Source uses MJPEG codec. Export will require re-encoding to H.264 (~2 hours on this hardware). Stream copy is not available for this format."
    }
  ]
}
```
The frontend displays this as an amber warning banner on the Job Detail page and
the New Job confirmation step.

**Files affected:** `app/utils/ffprobe.py`, `app/api/jobs.py`, `app/models.py`

---

## 🟡 ISSUE-14 — `vcgencmd` Crashes Outside Raspberry Pi OS

**Status:** Fixed in Phase 1 (utils/system.py)

**Problem:**
`vcgencmd measure_temp` is only available on Raspberry Pi OS. It raises `FileNotFoundError`
on Docker (x86_64 Linux), macOS, Windows, or Ubuntu. The system temperature polling
background thread crashes and logs an error every 10 seconds on non-Pi environments.
This breaks the System Diagnostics page and pollutes logs during development.

**Fix:**
All `vcgencmd` calls are wrapped in a graceful fallback:
```python
def get_cpu_temp() -> Optional[float]:
    """Returns CPU temperature in Celsius, or None if not on Raspberry Pi OS."""
    try:
        result = subprocess.run(
            ["vcgencmd", "measure_temp"],
            capture_output=True, text=True, timeout=2
        )
        # Output format: "temp=54.2'C"
        return float(result.stdout.split("=")[1].split("'")[0])
    except (FileNotFoundError, ValueError, IndexError, subprocess.TimeoutExpired):
        # Try /sys/class/thermal (works on most Linux including Pi)
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                return int(f.read().strip()) / 1000.0
        except (FileNotFoundError, ValueError):
            return None  # Not available (Windows, macOS)
```
The fallback tries `/sys/class/thermal/thermal_zone0/temp` which works on all Linux
(including Pi, Ubuntu, Docker on Linux). If both fail, `None` is returned.
The frontend shows `"N/A"` in the temperature gauge when `None` is received — no crash,
no error log spam, clean degradation.

**Files affected:** `app/utils/system.py` (new file extracted from system.py), `app/api/system.py`

---

## 🟡 ISSUE-15 — Canvas Timeline Too Small for Touch/Mobile

**Status:** Fixed in Phase 6 (frontend, timeline-strip.js)

**Problem:**
The user chose PWA (installable on phone). The timeline canvas at 40px height with
hundreds of event segments is effectively untouchable on a phone screen. Apple HIG
requires minimum 44×44pt touch targets; Material Design requires 48×48dp.
A 40px canvas with events that might be 3-5px wide on a 24-hour timeline cannot
be interacted with meaningfully on mobile.

**Fix:**
Responsive layout via `window.matchMedia('(pointer: coarse)')` (touch device detection):

**Desktop (pointer: fine — mouse):**
- Canvas height: 48px
- Event segment minimum width: 4px (clamped so very short events are still visible)
- Click to select

**Touch (pointer: coarse — finger):**
- Canvas height: 80px
- Event segment minimum width: 12px (wider tap targets)
- Tap to select; long-press to show context menu (tag/exclude)
- Below the canvas: scrollable event list (full-width cards, 80px tall each)
- Timeline shows only 4-hour windows at a time with swipe navigation (prevents
  events being too small to tap on a 24-hour timeline at phone width)

**Files affected:** `static/js/components/timeline-strip.js`, `static/css/components.css`,
`static/js/pages/job-detail.js`

---

## 🟡 ISSUE-16 — XSS via Source Filename in DOM

**Status:** Fixed as a coding standard enforced across all frontend files

**Problem:**
Source filenames, tags, zone names, and audit log entries come from user-supplied data
(file paths, upload names, settings inputs). If the frontend inserts these values using
`element.innerHTML = value`, an attacker (or even an accidentally-named file like
`<img src=x onerror=alert(1)>.mp4`) would execute JavaScript in the browser.

Affected pages if `innerHTML` were used: Job Queue table, Job Detail header, History table,
Audit Log rows, Reports job selector.

**Fix:**
**Hard rule:** Never use `innerHTML`, `outerHTML`, or `insertAdjacentHTML` with any value
that originates from the API or database. Always use:

```javascript
// ✅ CORRECT — safe, no XSS possible
element.textContent = filename;

// ✅ CORRECT — building elements safely
const td = document.createElement('td');
td.textContent = job.source_name;
row.appendChild(td);

// ❌ NEVER — XSS vulnerability
element.innerHTML = `<td>${job.source_name}</td>`;
```

A `safeHtml(template, values)` utility function is provided in `static/js/api.js`
that builds DOM nodes from templates using `textContent` assignment, preventing
accidental `innerHTML` use in templates:
```javascript
function el(tag, text, attrs = {}) {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v));
    return e;
}
```
All frontend code uses `el()` for dynamic content — zero `innerHTML` with user data.

**Files affected:** All `static/js/pages/*.js`, `static/js/components/*.js`

---

## 🟡 ISSUE-17 — Slow-Moving Objects Disappear From MOG2 Background Model

**Status:** Documented as known limitation; partially mitigated in Phase 3

**Problem:**
MOG2's `history=500` means the background model adapts to slowly-changing scenes
within ~17 seconds (at 25fps). A person standing motionless for >20 seconds gradually
becomes "background" and MOG2 stops detecting them as foreground. This is a fundamental
limitation of background-subtraction algorithms — not a bug, but a real accuracy gap
for the use case (someone standing at a door, a parked car slowly rolling forward).

This cannot be fully solved without object detection (YOLOv8n — deferred to v1.5).

**Mitigation:**
1. `history` is exposed as a configurable Advanced Setting (range: 100–2000, default: 500).
   Users who need to detect slow-moving subjects can lower it to 150 (5 seconds).
   Trade-off: lower history = more false positives from slow lighting changes.

2. A UI note is shown next to the sensitivity slider:
   `"Note: objects stationary for >20s may not be detected. Lower MOG2 history in Advanced
   Settings for slow-moving subjects."`

3. High sensitivity mode uses `history=200` automatically (the user accepted more false
   positives by choosing High, so the trade-off is appropriate).

**Files affected:** `app/config.py`, `app/core/detection_engine.py`, `static/js/pages/new-job.js`

---

## Summary Table

| ID | Severity | Issue | Fix Phase |
|---|---|---|---|
| ISSUE-01 | 🔴 Blocker | PWA requires HTTPS — HTTP breaks service worker | Phase 7 + install.sh |
| ISSUE-02 | 🔴 Blocker | Timestamp drift from nominal vs actual FPS | Phase 3 |
| ISSUE-03 | 🔴 Blocker | FFmpeg subprocess RAM not counted in memory budget | Phase 1 + 2 |
| ISSUE-04 | 🔴 Blocker | Clip preview range-request approach doesn't work | Phase 5 |
| ISSUE-05 | 🟠 High | MOG2 has no background after crash resume (false positive flood) | Phase 3 |
| ISSUE-06 | 🟠 High | Frame skip in Python wastes 2× pipe bandwidth | Phase 3 |
| ISSUE-07 | 🟠 High | No morphological noise filter on MOG2 mask | Phase 3 |
| ISSUE-08 | 🟠 High | SSE blocks thread pool for entire job duration | Phase 2 + 5 |
| ISSUE-09 | 🟠 High | Duplicate events inserted on crash resume | Phase 2 + 3 |
| ISSUE-10 | 🟠 High | NVR PTS discontinuities corrupt export | Phase 4 |
| ISSUE-11 | 🟠 High | No audio check — FFmpeg errors on silent CCTV | Phase 1 + 4 |
| ISSUE-12 | 🟠 High | No disk space check — job fails after hours of work | Phase 2 |
| ISSUE-13 | 🟡 Medium | No codec warning for silent re-encode penalty | Phase 1 + 2 |
| ISSUE-14 | 🟡 Medium | `vcgencmd` crashes outside Raspberry Pi OS | Phase 1 |
| ISSUE-15 | 🟡 Medium | Canvas timeline untouchable on mobile/tablet | Phase 6 |
| ISSUE-16 | 🟡 Medium | XSS possible via filename in DOM via innerHTML | All frontend phases |
| ISSUE-17 | 🟡 Medium | Slow subjects disappear from MOG2 (known limitation) | Phase 3 (partial) |

---

*Document generated: 2026-05-05. All issues resolved in implementation before first commit of application code.*

---

## Post-Deployment Bug Register (2026-05-07)

Discovered during first real Pi deployment. All fixed in commit `fix: resolve post-deployment bugs`.

---

### BUG-01 — Systemd service fails on paths with spaces 🔴 Blocker

**Symptom on Pi:**
```
Unable to locate executable '/home/abhi/Desktop/PI': No such file or directory
```
**Root cause:** `install.sh` writes the systemd unit file using an unquoted shell variable `${INSTALL_DIR}`. When the installation path contains spaces (e.g. `PI PROJECTS/Video Processor/...`), systemd splits the value at the first space and tries to execute the truncated path as a binary.

**Exact broken lines in generated service file:**
```ini
WorkingDirectory=/home/abhi/Desktop/PI PROJECTS/...     ← truncated by systemd
ExecStart=/home/abhi/Desktop/PI PROJECTS/.../python ...  ← tries to exec "/home/abhi/Desktop/PI"
```

**Fix applied — `install.sh`:** Quote `${INSTALL_DIR}` in the heredoc so double quotes are literal characters written into the service file. Also collapsed multi-line `ExecStart` continuation (backslash line-continuation is unreliable in systemd unit files). Added `PYTHONUNBUFFERED=1` for clean log output.
```ini
WorkingDirectory="${INSTALL_DIR}"
ExecStart="${INSTALL_DIR}/venv/bin/python" -m uvicorn app.main:app --host 0.0.0.0 --port 5000 ...
```

**Fix applied — `cctv-analyst.service`:** Updated static template with quoted paths and single-line `ExecStart`.

**Files:** `install.sh`, `cctv-analyst.service`

---

### BUG-02 — Settings endpoint crashes with Pydantic v2 🔴 Blocker

**Symptom:** `PUT /api/settings` raises `AttributeError: 'SettingsModel' object has no attribute 'dict'` or `PydanticUserError` on startup due to deprecated `@validator` decorator.

**Root cause:** FastAPI 0.111 ships with Pydantic v2. The settings model used Pydantic v1 patterns:
- `@validator(field)` decorator → removed in v2, replaced by `@field_validator`
- `body.dict()` method → removed in v2, replaced by `body.model_dump()`

**Fix applied — `app/api/settings.py`:**
- `from pydantic import BaseModel, validator` → `from pydantic import BaseModel, field_validator`
- All `@validator("field")` → `@field_validator("field")` with added `@classmethod` decorator
- `body.dict()` → `body.model_dump(exclude_none=True)`

**Files:** `app/api/settings.py`

---

### BUG-03 — FFmpeg exit code 1 accepted as success 🟠 High

**Symptom:** Export produces empty or corrupt output with no error reported.

**Root cause:** `_run_ffmpeg()` checked `if proc.returncode not in (0, 1)` — treating exit code 1 as success. FFmpeg only returns 0 on success; any non-zero code is a failure.

**Fix applied — `app/core/export_engine.py`:**
```diff
- if proc.returncode not in (0, 1):
+ if proc.returncode != 0:
```

**Files:** `app/core/export_engine.py`

---

### BUG-04 — Path traversal vulnerability in upload finalize 🟠 Security

**Symptom:** A malicious `filename` like `../../etc/passwd` in the upload init request could cause the assembled file to be written outside `UPLOAD_DIR`.

**Root cause:** `final_path = UPLOAD_DIR / upload_id / filename` — `filename` was used verbatim without sanitisation.

**Fix applied — `app/api/upload.py`:**
```diff
- final_path = UPLOAD_DIR / upload_id / filename
+ safe_name = Path(filename).name   # strips any directory components
+ final_path = UPLOAD_DIR / upload_id / safe_name
```

**Files:** `app/api/upload.py`

---

### BUG-05 — Upload endpoints crash on malformed chunk filenames 🟠 High

**Symptom:** `upload_finalize` or `GET /upload/status/{id}` raises `ValueError: invalid literal for int()` if any file in the upload directory has a non-numeric chunk suffix.

**Root cause:** `int(x.stem.split("_")[1])` called without exception handling. Any unexpected file in the directory (e.g., `meta.json` or OS temp files) causes a crash.

**Fix applied — `app/api/upload.py`:** Added `_safe_chunk_index()` helper that catches `ValueError`/`IndexError` and returns `None`. All chunk collection loops now use this helper and skip unparseable entries.

**Files:** `app/api/upload.py`

---

### BUG-06 — Dead code double-calculates total_activity_s 🟡 Minor

**Symptom:** Wasted CPU on every `GET /api/jobs/{id}` call; confusing duplicate logic.

**Root cause:** `total_activity_s` was calculated twice — first with a broken dict-access pattern (lines 182–185), then immediately overridden by the correct calculation (lines 187–189). The first block was unreachable dead code.

**Fix applied — `app/api/jobs.py`:** Removed the first (incorrect) calculation block. Kept only the correct version.

**Files:** `app/api/jobs.py`

---

### Post-Deployment Bug Summary

| Bug | Severity | File(s) | Status |
|---|---|---|---|
| BUG-01: systemd spaces in path | 🔴 Blocker | `install.sh`, `cctv-analyst.service` | ✅ Fixed |
| BUG-02: Pydantic v2 incompatibility | 🔴 Blocker | `app/api/settings.py` | ✅ Fixed |
| BUG-03: FFmpeg exit code wrong | 🟠 High | `app/core/export_engine.py` | ✅ Fixed |
| BUG-04: Upload path traversal | 🟠 Security | `app/api/upload.py` | ✅ Fixed |
| BUG-05: Upload crash on bad chunk name | 🟠 High | `app/api/upload.py` | ✅ Fixed |
| BUG-06: Dead code double calculation | 🟡 Minor | `app/api/jobs.py` | ✅ Fixed |

*All 6 bugs fixed in commit on 2026-05-07.*
