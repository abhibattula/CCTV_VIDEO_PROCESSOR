# Detection Engine — Root Cause Notes

> Developer reference. Documents every detection bug found during deployment,
> its root cause, the evidence chain, and the exact fix applied.
> Updated: 2026-05-10 | Branch: `002-detection-pts-fix`

---

## The Detection Pipeline (Brief)

```
FFmpeg subprocess (stdout) → FRAME_SIZE bytes/frame → MOG2 → morphological filter
→ motion_ratio → segment state machine → events DB → log_buffer → SSE → browser
```

FFmpeg subprocess stderr → background thread → filter lines → job log panel

---

## Bug Register

---

### BUG-DET-01 — FFmpeg produces 10–29 frames then exits early

**Symptom**: `[DIAG frame N]` fires, then immediately `[DONE] 1 motion events found`.
No checkpoint lines (checkpoints fire every 30 frames → fewer than 30 frames processed).
Preview clip shows empty static scene. Real motion events never processed.

**Evidence**: DIAG at `frame_idx == INITIAL_WARMUP + 9`. No checkpoint →
`frame_idx < 30 + INITIAL_WARMUP` at exit. A 115-second 60fps video has 6864 frames.

**Root Cause 1 (original)**: `-ignore_editlist 1` forces FFmpeg to decode encoder
pre-roll frames (0–0.195s before the edit list position). These frames have
broken/absent reference frames — H.264 encoder warmup, not intended for display.
FFmpeg produces 10–29 corrupt output frames then hits unrecoverable decoder state.

**Root Cause 2 (in `002` branch)**: `-ignore_editlist 1` was supposed to be
removed, but a secondary effect was that `frame_idx` was being referenced before
assignment (CRIT-1 below), crashing with `UnboundLocalError` on every fresh job.

**Correct fix**: DO NOT use `-ignore_editlist 1` in detection. Use `-fflags +igndts+genpts`:
- FFmpeg honours the edit list (skips pre-roll)
- `+genpts` regenerates PTS from 0 after the edit list skip
- fps filter (when used for frame_skip>0) receives frames at PTS=0,1/fps,2/fps ✓

**Commit**: `4812ee5`, `822f820`

---

### BUG-DET-02 — `UnboundLocalError: frame_idx referenced before assignment` (CRIT-1 + CRIT-2)

**Symptom**: Every fresh (non-resume) detection job immediately fails with
`UnboundLocalError`. Resume jobs unaffected.

**Root Cause**: The 30-frame initial warmup loop (added to prevent spurious T=0 events)
did `frame_idx += 1` but `frame_idx = 0` was defined 25 lines later in the state machine
section. Python raises `UnboundLocalError` on the first warmup iteration.

**Secondary bug (CRIT-2)**: Even if CRIT-1 was fixed by moving the initialisation,
the state machine section had a second `frame_idx = 0` reset that would silently
discard the warmup count — making `current_pts` wrong for the first 0.5–1.2 seconds
of detected events.

**Fix**: 
1. Moved `frame_idx = 0` to immediately before the warmup block.
2. Removed the stale `frame_idx = 0` in the state machine section.
3. Warmup block increments `frame_idx` to `INITIAL_WARMUP` so `current_pts = frame_idx / target_fps` starts at the correct time offset (not T=0).

**Commit**: `002-detection-pts-fix`

---

### BUG-DET-03 — DIAG condition never fires after warmup (IMP-1)

**Symptom**: After CRIT-1/CRIT-2 fix, `frame_idx` starts at `INITIAL_WARMUP=30`.
The DIAG check was `frame_idx == 9` — never true when frame_idx starts at 30.

**Fix**: Changed condition to `frame_idx == INITIAL_WARMUP + 9` (10th frame of
real detection, post-warmup). Log label updated to `[DIAG frame 40]`.

**Commit**: `002-detection-pts-fix`

---

### BUG-DET-04 — `detectShadows=True` silently discarded all motion

**Symptom**: 0 events always. No error. Fixed in `95e0a3c`.

**Root Cause**: MOG2 with `detectShadows=True` marks shadow pixels as `127` and
confirmed foreground as `255`. The code applied `cv2.threshold(fg_mask, 200, 255,
THRESH_BINARY)` which converts `127→0` — silently removing shadow-classified
pixels. In surveillance footage most moving object pixels are classified as `127`.

**Fix**: `detectShadows=False`. All motion pixels are `255`, nothing discarded.
Morphological filter handles noise reduction instead.

---

### BUG-DET-05 — fps filter stall on phone videos (edit list + PTS mismatch)

**Symptom**: Only 1–9 frames produced. `[DIAG frame N]` never fires.

**Root Cause**: `fps=target_fps` filter maps output timestamps to source frames by PTS.
The edit list made first source frame PTS = 0.195s. The filter expected a frame at
PTS = 0.000s. Mismatch → filter stalled after a few frames.

**Fix**: `-fflags +igndts+genpts`. `+genpts` regenerates PTS from 0 starting at
the first frame output (first valid frame after edit list skip). fps filter then
receives frames at PTS=0,1/fps,2/fps — correct alignment.

For `frame_skip=0` (process every frame): fps filter is unnecessary; removed.
For `frame_skip>0`: fps filter remains and works correctly with `+genpts`.

**Commit**: `4812ee5`

---

### BUG-DET-06 — Spurious T=0 event from MOG2 initialisation

**Symptom**: 1 event found at T=0–2.5s with empty-scene preview.

**Root Cause**: MOG2 starts with high-variance Gaussians. During the first ~30 frames
the classifier is noisy, producing 30–200 foreground pixels exceeding the
high-sensitivity threshold (38 px). End-of-video close block converts this noise
into an event: `event_end = ~0.3 + 2 = 2.3s`, `duration >= min_event_s=2` → kept.

**Fix**: 30-frame initial warmup for fresh detection. MOG2 processes frames silently
to build a background model before event detection begins.

**Commit**: `002-detection-pts-fix`

---

### BUG-DET-07 — Morphological OPEN 5×5 erased legitimate motion

**Symptom**: 0 events even when motion confirmed by eye. Fixed in `0e329c8`.

**Root Cause**: 5×5 elliptical kernel erodes 2px from every edge. At 320×240,
distant subjects (5px wide) are erased entirely.

**Fix**: Changed kernel from `(5,5)` to `(3,3)`. Only erodes 1px per edge.

---

### BUG-DET-08 — High sensitivity merges separate events

**Symptom**: User expected 2 events, got 1 spanning entire active period.

**Root Cause**: `threshold=0.0005` (38 pixels). H.264 compression artifacts produce
40–80 pixels of "foreground" in a static scene, keeping `is_motion=True` during
quiet gaps and preventing event closure.

**Not a code bug** — expected MOG2 behaviour at very high sensitivity.
Use `sensitivity=medium` (threshold=154 px) for better event separation.

---

## System Bug Register (non-detection)

---

### BUG-SYS-01 — `_restore_interrupted_jobs` re-runs detection on interrupted exports (CRIT-4)

**File**: `app/core/job_queue.py`

**Root Cause**: On service restart, any job in `exporting` state was reset to `queued`.
The queue worker then re-ran full detection, even though detection completed and all
events were in the DB. For a 24h video this meant 1–2h of unnecessary re-detection.

**Fix**: Split restore logic:
- `detecting/running` → `queued` (correct: re-run detection with checkpoint resume)
- `exporting` → `completed` (correct: detection done, user can re-trigger export manually)

---

### BUG-SYS-02 — Export daemon thread crashes silently (CRIT-3, documented limitation)

**File**: `app/api/export.py`

**Root Cause**: Export runs in a daemon thread. If the thread is killed by OOM/signal
(not a Python exception), the job stays in `exporting` state. `_restore_interrupted_jobs`
now resets it to `completed` on next startup (BUG-SYS-01 fix).

**Limitation**: If the service never restarts after OOM kill, the job shows `exporting`
indefinitely. The 4-second polling fallback in the UI (`_pollInterval`) will not
resolve this — it only polls until `completed` or `failed`.

**Acceptable**: On 2GB Pi, OOM during stream-copy export is very unlikely.
Re-encode exports could trigger it for long MJPEG files.

---

### BUG-SYS-03 — `frame_idx` UnboundLocalError (see BUG-DET-02)

### BUG-SYS-04 — `asyncio.get_event_loop()` deprecated in Python 3.10+

**File**: `app/main.py`

**Fix**: Changed to `asyncio.get_running_loop()`. The lifespan context is an
async function so a running loop is always available.

---

### BUG-SYS-05 — f-string JSON in `upload_init` breaks on filenames with quotes

**File**: `app/api/upload.py`

**Root Cause**: `f'{{"filename":"{filename}",...}}'` — a filename containing `"` or `\`
produces malformed JSON, causing `upload_finalize` to crash with `json.JSONDecodeError`.

**Fix**: `json.dumps({"filename": filename, "total_size": total_size})`.

---

### BUG-SYS-06 — Zone frame stored in `/tmp` — accumulates across jobs

**File**: `app/api/jobs.py`

**Root Cause**: Zone editor frame cached in `/tmp/zone_{job_id}.jpg`. Never cleaned up.
On a 2GB Pi with limited storage, repeated zone frame requests fill `/tmp`.

**Fix**: Store in `JOBS_DIR / job_id / "zone_frame.jpg"`. Cleaned up with the job.

---

### BUG-SYS-07 — Export polling interval leaks on page navigation (IMP-8)

**File**: `static/js/pages/job-detail.js`

**Root Cause**: `setInterval(...)` started on export, but `unmount()` didn't clear it.
After navigation, interval continued polling `/api/jobs/{id}` every 4 seconds.

**Fix**: Hoisted `_pollInterval` to module scope. `unmount()` now calls
`clearInterval(_pollInterval)`.

---

### BUG-SYS-08 — `cctv-analyst.service` committed with real user's path

**File**: `cctv-analyst.service`

**Root Cause**: Template file contained `User=abhi` and hardcoded path. Misleading
for any other installation. `install.sh` generates the correct file dynamically.

**Fix**: Replaced with clearly-marked template using placeholder tokens.

---

## FFmpeg Flag Reference

| Flag | Where | Effect | Rule |
|---|---|---|---|
| `-fflags +igndts` | Detection, Export | Ignore DTS, trust PTS | Always — NVR recordings have broken DTS |
| `-fflags +genpts` | Detection, Export | Regenerate PTS from 0 | Always — fixes edit list PTS offset for fps filter |
| `-ignore_editlist 1` | Export preview only | Skip edit list when seeking | ONLY for fast seek (`-ss` before `-i`). NEVER in detection (sequential decode of pre-roll crashes) |
| `-avoid_negative_ts make_zero` | Export, Preview | Clamp negative PTS after seek | Always with `-ss` + stream copy |
| `-movflags faststart` | Export, Preview | MOOV atom first | Always for browser-played MP4 |
| `detectShadows=False` | Detection MOG2 | All motion = 255 | Always — True was silently discarding shadow pixels |

---

## Sensitivity Calibration Guide

| Sensitivity | MOG2 history | varThreshold | Motion threshold | Min px (320×240) | Use case |
|---|---|---|---|---|---|
| low | 700 frames | 32 | 0.01 | 768 | Busy scenes, reduce false positives |
| medium | 500 frames | 16 | 0.002 | 154 | Standard CCTV, recommended default |
| high | 200 frames | 8 | 0.0005 | 38 | Distant/subtle motion, nighttime |

High sensitivity can merge separate events if background noise keeps `is_motion=True`
during quiet gaps. Use medium for reliable event separation.

---

## Video Format Reference

| Format | Export | Speed | Notes |
|---|---|---|---|
| H.264 MP4 | Stream copy | ⚡ Fast | Recommended. Android/iPhone default. |
| H.265/HEVC MP4 | Stream copy | ⚡ Fast | |
| MJPEG AVI | Re-encode | 🐢 Slow | 1–2h per 24h footage |
| VP9/AV1 | Re-encode | 🐢 Slow | Convert to H.264 first |

Phone videos (Android/iPhone): H.264 MP4 with edit list. The edit list is normal —
do NOT add `-ignore_editlist 1` to the detection pipeline. `+genpts` handles it correctly.

---

*Updated: 2026-05-10 — branch `002-detection-pts-fix`*
