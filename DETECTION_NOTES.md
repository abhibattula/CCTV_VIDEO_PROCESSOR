# Detection Engine — Root Cause Notes

> Developer reference. Documents every detection bug found during deployment,
> its root cause, the evidence chain, and the exact fix applied.
> Branch: `002-detection-pts-fix`

---

## The Detection Pipeline (Brief)

```
FFmpeg pipe → stdout (RGB24 frames) → MOG2 → morphological filter →
motion ratio → segment state machine → events DB
```

FFmpeg stderr → background thread → log_buffer → SSE → browser log panel

---

## Bug Register

---

### BUG-DET-01 — FFmpeg produces 10–29 frames then exits (CRITICAL)

**Symptom**: Log shows `[DIAG frame 10]` then immediately `[DONE] Detection complete — 1 motion events found`. No checkpoint lines. Preview clip shows static empty scene. Real motion events never processed.

**Evidence**:
- Checkpoints fire every 30 frames. No checkpoint → `frame_idx < 30` at exit.
- `[DIAG frame 10]` fires at `frame_idx == 9` → confirmed at least 10 frames.
- Therefore: 10 ≤ frames_done ≤ 29. A 60+ second video should produce 3600+ frames.
- The 1 "event" is a spurious end-of-video close: `in_event=True` from MOG2 init noise, `event_end = ~0.3 + 2 = 2.3s`, `duration = 2.3s ≥ min_event_s=2` → kept.

**Root Cause**: `-ignore_editlist 1` was in the FFmpeg command.

Android/iPhone phone videos contain an MP4 edit list that says:
> "Skip the first N frames. These are encoder pre-roll (warmup). The video starts at timestamp T."

For the test video: edit list at timestamp `11710`, timescale `60000` → `11710/60000 = 0.195 seconds` of encoder warmup.

When FFmpeg is told to **ignore** the edit list (`-ignore_editlist 1`), it starts decoding from absolute byte 0 — including those encoder warmup frames. These frames have **broken or absent reference frames**. They were produced before the H.264 encoder had enough data to create clean inter-prediction. They are not intended for display.

FFmpeg attempts to decode them, produces 10–29 corrupt/partial output frames, then hits an unrecoverable decoder state and exits. The Python read loop gets EOF. Detection ends after 0.5 seconds of video content.

**What was the intent?** `-ignore_editlist 1` was added to prevent an earlier bug where the `fps` filter stalled because the edit list made the first frame's PTS = 0.195s instead of 0.000s. The fix was `+genpts`. Both were added, but `-ignore_editlist 1` made things worse.

**The correct relationship**:
- `-fflags +genpts` regenerates PTS from 0 **after** the edit list skip → fps filter gets frames at PTS=0,1/fps,2/fps,... → works correctly ✓
- `-ignore_editlist 1` forces decoding **before** the edit list skip → broken pre-roll frames → early exit ✗
- These two flags conflict. `+genpts` alone is the correct fix. `-ignore_editlist` must be absent.

**Fix**: Removed `-ignore_editlist 1` from `_build_ffmpeg_cmd()` in `detection_engine.py`. The flag remains in `generate_preview()` in `export_engine.py` where it is harmless (fast seek past pre-roll, not sequential decoding).

**Commit**: `002-detection-pts-fix` branch

---

### BUG-DET-02 — Spurious event at T=0 from MOG2 initialisation

**Symptom**: 1 event detected at the very beginning of the video (T=0 to ~2.5s), preview shows empty static scene.

**Root Cause**: MOG2 initialises with high-variance Gaussian distributions for all pixels. During the first 30 frames, the classifier has no background model and produces noisy foreground output. At `sensitivity=high`, the threshold is 0.0005 × 320 × 240 = 38 pixels. MOG2 init noise easily exceeds this, triggering `is_motion=True` from frame 0. If the video has little actual motion in the first 3 seconds (e.g., user placed camera and waited), the event stays open until the end-of-video close block:

```python
if in_event and not cancel_event.is_set():
    event_end = current_pts + padding_s    # ~0.3 + 2 = 2.3s
    duration = event_end - event_start     # 2.3 - 0 = 2.3s ≥ min_event_s=2 → KEPT
```

**Fix**: Added 30-frame initial warmup for fresh detection (not crash resume). MOG2 processes 30 frames silently to build a basic background model before event detection begins. 30 frames = 0.5s at 60fps, 1.2s at 25fps — short enough not to miss early motion.

```python
INITIAL_WARMUP = 30
if resume_pts is None:
    for _ in range(INITIAL_WARMUP):
        raw = proc.stdout.read(FRAME_SIZE)
        ...
        mog2.apply(gray)
        frame_idx += 1  # so PTS remains accurate from first detected event
```

---

### BUG-DET-03 — detectShadows=True silently discarded all motion pixels

**Symptom**: 0 events detected regardless of sensitivity. No error, no failure. Fixed in commit `95e0a3c`.

**Root Cause**: MOG2 with `detectShadows=True` marks shadow pixels as `127` and confirmed foreground as `255`. The code then applied `cv2.threshold(fg_mask, 200, 255, THRESH_BINARY)` which converts `127→0`, silently removing all shadow-classified pixels. In surveillance footage with overhead lighting or directional light, most moving object pixels are classified as `127` (shadow). Result: 0 foreground pixels → 0 events.

**Fix**: `detectShadows=False`. All motion pixels are now `255`, nothing silently discarded. Morphological filter handles noise reduction instead.

---

### BUG-DET-04 — fps filter stall on phone videos (edit list + timestamp mismatch)

**Symptom**: Only 1–9 frames produced by FFmpeg (before DIAG fires), job completes with 0 events but no FAILED status.

**Root Cause**: The `fps=target_fps` filter in FFmpeg maps source frames to output timestamps using: output frame N → source frame nearest to N/fps. The edit list made the first source frame's PTS = 0.195s. The fps filter expected a frame at PTS = 0.000s. No frame existed at 0.000s, so the filter couldn't produce output frame 0. It produced 1–9 frames from what frames it could, then stalled.

**Fix**: `-fflags +genpts`. This regenerates all PTS from 0 starting at the first frame output (which is the first frame AFTER the edit list skip). The fps filter now receives frames starting at PTS=0,1/fps,2/fps,...— perfect alignment.

**Additionally**: For `frame_skip=0` (process every frame), the `fps` filter is unnecessary. Removed it for that case. Only used when `frame_skip > 0`.

---

### BUG-DET-05 — Morphological OPEN 5×5 erased legitimate motion

**Symptom**: 0 events detected even when motion was confirmed by eye.

**Root Cause**: The 5×5 elliptical kernel in `cv2.MORPH_OPEN` erodes 2 pixels from every edge of a foreground region. At 320×240 detection resolution, a person at medium distance might be only 15–20px wide. After OPEN, they'd be 11–16px wide — still above noise level. But at long distance or through a window, a 5px-wide silhouette becomes 1px after erosion and then disappears in dilation.

**Fix**: Changed kernel from `(5,5)` to `(3,3)`. Only erodes 1px from each edge. More small legitimate regions survive.

---

### BUG-DET-06 — High sensitivity merges separate events (background noise bridges gap)

**Symptom**: User expected 2 events, got 1. The event spans the entire active period including a long quiet gap.

**Root Cause**: With `sensitivity=high`, `MOTION_THRESHOLD["high"] = 0.0005` (38 pixels). H.264 compression artifacts and camera noise can produce 40–80 pixels of "foreground" in an otherwise static scene. This keeps `is_motion=True` during the quiet gap between real events, so `silence_start` is never set for long enough to trigger event close (`min_gap_s=2`).

**Not a code bug** — this is expected MOG2 behaviour at very high sensitivity. The solution is:
- Use `sensitivity=medium` (threshold=154 pixels) for better event separation when events have long quiet gaps
- Use `sensitivity=high` only when detecting subtle/distant motion and false positive rate is acceptable

---

## FFmpeg Flag Reference for This Project

| Flag | Where used | Effect | When to use |
|---|---|---|---|
| `-fflags +igndts` | Detection, Export | Ignore DTS, trust PTS | Always — NVR recordings often have broken DTS |
| `-fflags +genpts` | Detection, Export | Regenerate PTS from 0 | Always — fixes edit list offset for fps filter |
| `-fflags +discardcorrupt` | Export only | Skip corrupt frames silently | Optional — for damaged recordings |
| `-ignore_editlist 1` | Export only (fast seek) | Skip edit list when seeking | Only for fast seek (-ss before -i); harmful for sequential decode from 0 |
| `-avoid_negative_ts make_zero` | Export, Preview | Clamp negative PTS after seek | Always when using -ss with stream copy |
| `-movflags faststart` | Export, Preview | MOOV atom first for streaming | Always for browser-played MP4 |

**Rule**: Never add `-ignore_editlist 1` to the detection command. It is safe in export/preview (fast seek skips past pre-roll) but harmful in detection (sequential decode from frame 0 hits pre-roll frames).

---

## Phone Video Quirks Reference

| Metadata | Meaning | Impact |
|---|---|---|
| `com.android.video.temporal_layers_count` | Android temporal layer count marker | No decoding impact; just metadata |
| Edit list at offset ~0.195s | Encoder pre-roll skip instruction | Honoured by default; do NOT ignore in detection |
| `avg_frame_rate: 59.6` | Average frames per second | Source for `target_fps` calculation; accurate for CFR phone videos |
| `r_frame_rate: 60000/1001` | Container-declared rate | Often slightly different from avg; avg is more reliable for timing |

---

## What Format Should Users Record In?

**Best**: H.264 MP4 (`.mp4`) — stream copy, fast export, browser-playable preview. Most phones default to this.

**Good**: H.265/HEVC MP4, H.264 MKV, H.264 TS — all stream-copy safe.

**Slow export**: MJPEG `.avi` — requires re-encode; 1–2 hours per hour of footage.

**Unsupported for stream copy**: VP9, AV1 — requires re-encode.

No format change is required for the test video. H.264 MP4 from Android is correct.

---

*Last updated: 2026-05-10 — branch `002-detection-pts-fix`*
