"""
8-step MOG2 detection pipeline.
Runs entirely in a worker thread — no asyncio, no thread pool usage.

Frame source: cv2.VideoCapture (replaces the previous FFmpeg-pipe approach).

Why VideoCapture instead of FFmpeg pipe:
  The FFmpeg CLI applies strict edit-list and index logic that caused early EOF
  on Android/iPhone phone videos with broken MP4 indexes (edit list at timestamp
  11710 with no matching index entry). Every flag combination — -ignore_editlist,
  +ignidx, +discardcorrupt — resolved one failure mode but revealed another.
  OpenCV's VideoCapture uses av_read_frame with lenient error policies and reads
  all frames from this video successfully (confirmed: 6864 frames / 115 s).
  VideoCapture also provides accurate per-frame timestamps via CAP_PROP_POS_MSEC,
  simplifying the PTS tracking that previously required a showinfo stderr thread.
"""
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from app.config import (
    DETECT_WIDTH as W,
    DETECT_HEIGHT as H,
    BATCH_SIZE,
    JOBS_DIR,
)
from app.database import get_conn
from app.utils.time_utils import seconds_to_clock

# MOG2 background model parameters
SENSITIVITY_HISTORY = {"low": 700, "medium": 500, "high": 200}
SENSITIVITY_VAR_THR  = {"low": 32,  "medium": 16,  "high": 8}

# Motion ratio thresholds (fraction of 320×240 pixels that must be foreground)
MOTION_THRESHOLD     = {"low": 0.01, "medium": 0.002, "high": 0.0005}

# Frames to stabilise MOG2 background model before event detection begins.
# Fresh start: 30 frames (~0.5 s at 60 fps) — prevents spurious T=0 events
#   from MOG2 initialisation noise.
# Crash-resume: 500 frames to re-establish model after a mid-video seek.
INITIAL_WARMUP = 30
WARMUP_FRAMES  = 500


def _build_zone_mask(zones: list) -> Optional[np.ndarray]:
    """Pre-render polygon mask from normalised [0-1] coordinates."""
    if not zones:
        return None
    mask = np.zeros((H, W), dtype=np.uint8)
    for zone in zones:
        pts = np.array(
            [[int(x * W), int(y * H)] for x, y in zone.get("points", [])],
            dtype=np.int32,
        )
        cv2.fillPoly(mask, [pts], 255)
    return mask


def _read_checkpoint(job_dir: Path) -> Optional[dict]:
    cp = job_dir / "checkpoint.json"
    if cp.exists():
        try:
            return json.loads(cp.read_text())
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _write_checkpoint(job_dir: Path, data: dict) -> None:
    tmp = job_dir / "checkpoint.json.tmp"
    tmp.write_text(json.dumps(data))
    tmp.replace(job_dir / "checkpoint.json")


def _write_timeline(job_id: str, job: dict, events: list, source_duration_s: float) -> None:
    job_dir = JOBS_DIR / job_id
    total_activity = sum(e["end_s"] - e["start_s"] for e in events if e.get("included", 1))
    activity_pct = (total_activity / source_duration_s * 100) if source_duration_s else 0.0
    timeline = {
        "job_id": job_id,
        "source_file": job["source_path"],
        "source_duration_s": source_duration_s,
        "source_fps": job.get("source_fps"),
        "source_resolution": [job.get("source_width"), job.get("source_height")],
        "recording_start_utc": job.get("recording_start"),
        "ram_mode": "2gb",
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "total_activity_s": total_activity,
        "activity_percent": round(activity_pct, 2),
        "events": events,
    }
    (job_dir / "timeline.json").write_text(json.dumps(timeline, indent=2))


def run(
    job_id: str,
    job: dict,
    settings: dict,
    cancel_event: threading.Event,
    logger: Callable[[str], None],
) -> None:
    """Main detection pipeline entry point (VideoCapture-based)."""
    from app.core.ram_guard import check as ram_check

    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "thumbnails").mkdir(exist_ok=True)

    sensitivity    = settings.get("sensitivity", "medium")
    frame_skip     = int(settings.get("frame_skip", 0))
    padding_s      = float(settings.get("padding_s", 2))
    min_gap_s      = float(settings.get("min_gap_s", 2))
    min_event_s    = float(settings.get("min_event_s", 2))
    zones          = settings.get("zones", [])
    recording_start = job.get("recording_start")

    source_path     = job["source_path"]
    source_fps      = float(job.get("source_fps") or 25.0)
    source_duration_s = float(job.get("duration_s") or 0.0)

    # ── Crash-resume setup ───────────────────────────────────────────────────
    checkpoint = _read_checkpoint(job_dir)
    resume_pts: Optional[float] = None
    last_confirmed_index = -1
    frames_done = 0

    if checkpoint:
        resume_pts           = checkpoint.get("pts_time", 0.0)
        last_confirmed_index = checkpoint.get("last_confirmed_event_index", -1)
        frames_done          = checkpoint.get("frames_processed", 0)
        conn = get_conn()
        conn.execute(
            "DELETE FROM events WHERE job_id=? AND event_index > ?",
            (job_id, last_confirmed_index),
        )
        conn.commit()
        logger(f"[RESUME] Resuming from checkpoint at {resume_pts:.1f}s (frame {frames_done})")
    else:
        logger(f"[START] Detection started — source: {job['source_name']}")

    # ── Open video with VideoCapture ─────────────────────────────────────────
    # VideoCapture uses FFmpeg's av_read_frame internally with lenient error
    # handling. It reads all frames from phone videos that the FFmpeg CLI fails
    # on (broken MP4 index, edit list issues, temporal layers, pre-roll frames).
    cap = cv2.VideoCapture(str(source_path))
    if not cap.isOpened():
        raise RuntimeError(
            f"VideoCapture cannot open: {source_path}. "
            f"File may be corrupt or use an unsupported codec."
        )

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    actual_fps   = cap.get(cv2.CAP_PROP_FPS) or source_fps

    logger(
        f"[DETECTION] VideoCapture opened — {total_frames} frames, "
        f"{actual_fps:.2f}fps, {W}×{H}px detection, sensitivity={sensitivity}"
    )

    # Seek to crash-resume position
    if resume_pts is not None:
        cap.set(cv2.CAP_PROP_POS_MSEC, resume_pts * 1000)
        logger(f"[RESUME] Seeked to {resume_pts:.1f}s")

    # ── MOG2 initialisation ──────────────────────────────────────────────────
    history      = SENSITIVITY_HISTORY[sensitivity]
    var_threshold = SENSITIVITY_VAR_THR[sensitivity]
    mog2 = cv2.createBackgroundSubtractorMOG2(
        history=history, varThreshold=var_threshold, detectShadows=False
    )
    motion_ratio_threshold = MOTION_THRESHOLD[sensitivity]
    clahe  = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    # Zone mask
    zone_mask = _build_zone_mask(zones)

    # frame_idx must be defined BEFORE the warmup block (warmup increments it)
    frame_idx = 0

    # ── Initial warmup (fresh start only) ───────────────────────────────────
    # Skip the first INITIAL_WARMUP frames for event detection but feed them to
    # MOG2 to build a stable background model. Without warmup, MOG2 init noise
    # produces spurious events at T=0.
    # Crash-resume has its own longer warmup (500 frames) below.
    if resume_pts is None:
        logger(f"[DETECTION] MOG2 warmup ({INITIAL_WARMUP} frames) — stabilising background model")
        for _ in range(INITIAL_WARMUP):
            ret, frame = cap.read()
            if not ret:
                break
            small = cv2.resize(frame, (W, H))
            gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            mog2.apply(gray)
            frame_idx += 1
        logger("[DETECTION] Warmup complete — event detection starting")

    # ── Crash-resume warmup (re-establish background model after seek) ───────
    # 500 frames needed because the scene at the seek point may look completely
    # different from the background learned before the crash.
    if resume_pts is not None:
        logger(f"[RESUME] Warming up MOG2 background model ({WARMUP_FRAMES} frames)...")
        for _ in range(WARMUP_FRAMES):
            ret, frame = cap.read()
            if not ret:
                break
            small = cv2.resize(frame, (W, H))
            gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            mog2.apply(gray)
            # frame_idx intentionally NOT incremented here — PTS anchored by
            # resume_pts, not frame count relative to seek position.
        logger("[RESUME] Warmup complete — resuming detection")

    # ── Segment state machine ────────────────────────────────────────────────
    in_event        = False
    event_start     = 0.0
    event_start_clock = ""
    silence_start   = 0.0
    peak_score      = 0.0
    confirmed_events: list = []
    event_index     = last_confirmed_index + 1

    conn = get_conn()
    # frame_idx continues from INITIAL_WARMUP (not reset — keeps PTS accurate)
    current_pts      = resume_pts or 0.0
    first_frame_logged = False
    batch_max_ratio  = 0.0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if cancel_event.is_set():
                break

            # Accurate timestamp from VideoCapture (milliseconds → seconds)
            current_pts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0

            # Frame skip in Python: discard every (frame_skip) out of (frame_skip+1)
            if frame_skip > 0 and frame_idx % (frame_skip + 1) != 0:
                frame_idx += 1
                continue

            # First-frame diagnostic: mean brightness reveals black-frame issues
            if not first_frame_logged:
                mean_brightness = int(frame.mean())
                logger(
                    f"[DETECTION] First frame received — FFmpeg pipeline is working. "
                    f"Frame brightness: {mean_brightness}/255 "
                    f"{'(WARNING: very dark — check video)' if mean_brightness < 5 else '(OK)'}"
                )
                first_frame_logged = True

            # Resize to detection resolution
            small = cv2.resize(frame, (W, H))

            # Step 3: Preprocess (OpenCV delivers BGR; convert to gray)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            if sensitivity == "high":
                gray = clahe.apply(gray)

            # Step 4: MOG2 (detectShadows=False → all motion pixels are 255)
            fg_mask     = mog2.apply(gray)
            raw_fg_count = cv2.countNonZero(fg_mask)

            # Step 5: Morphological filter (3×3 OPEN removes noise, CLOSE fills gaps)
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN,  kernel)
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)

            # Diagnostic at 10th real detection frame (post-warmup)
            if frame_idx == INITIAL_WARMUP + 9:
                after_morph = cv2.countNonZero(fg_mask)
                needed      = int(motion_ratio_threshold * W * H)
                logger(
                    f"[DIAG frame {INITIAL_WARMUP + 10}] MOG2 raw={raw_fg_count}px "
                    f"→ after_morph={after_morph}px "
                    f"(need >={needed}px for a detection at {sensitivity} sensitivity)"
                )

            # Step 6: Zone mask
            if zone_mask is not None:
                fg_mask = cv2.bitwise_and(fg_mask, zone_mask)

            # Step 7: Score
            motion_ratio = cv2.countNonZero(fg_mask) / (W * H)
            is_motion    = motion_ratio >= motion_ratio_threshold
            if motion_ratio > batch_max_ratio:
                batch_max_ratio = motion_ratio

            # Step 8: Segment state machine
            if not in_event and is_motion:
                in_event          = True
                event_start       = max(0.0, current_pts - padding_s)
                event_start_clock = seconds_to_clock(event_start, recording_start)
                peak_score        = motion_ratio
                silence_start     = 0.0
            elif in_event:
                if is_motion:
                    peak_score    = max(peak_score, motion_ratio)
                    silence_start = 0.0
                else:
                    if silence_start == 0.0:
                        silence_start = current_pts
                    if current_pts - silence_start >= min_gap_s:
                        event_end = silence_start + padding_s
                        duration  = event_end - event_start
                        if duration >= min_event_s:
                            confirmed_events.append({
                                "event_index":       event_index,
                                "start_s":           round(event_start, 3),
                                "end_s":             round(event_end, 3),
                                "start_clock":       event_start_clock,
                                "end_clock":         seconds_to_clock(event_end, recording_start),
                                "peak_motion_score": round(peak_score, 4),
                                "zone_label":        zones[0]["label"] if zones else None,
                            })
                            event_index += 1
                        in_event      = False
                        silence_start = 0.0
                        peak_score    = 0.0

            frame_idx  += 1
            frames_done += 1

            # Checkpoint every BATCH_SIZE processed frames
            if frame_idx % BATCH_SIZE == 0:
                _flush_events(conn, job_id, confirmed_events, recording_start)
                last_idx = (
                    confirmed_events[-1]["event_index"] if confirmed_events
                    else last_confirmed_index
                )
                confirmed_events.clear()

                _write_checkpoint(job_dir, {
                    "job_id":                    job_id,
                    "frames_processed":          frames_done,
                    "pts_time":                  current_pts,
                    "last_confirmed_event_index": last_idx,
                    "timestamp":                 datetime.now(timezone.utc).isoformat(),
                })

                progress = min(frame_idx / max(total_frames, 1), 0.99)
                conn.execute("UPDATE jobs SET progress=? WHERE id=?", (progress, job_id))
                conn.commit()

                elapsed = int(current_pts)
                total_events_so_far = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE job_id=?", (job_id,)
                ).fetchone()[0]
                logger(
                    f"[{elapsed//3600:02d}:{(elapsed%3600)//60:02d}:{elapsed%60:02d}] "
                    f"Frame {frames_done}/{total_frames} — "
                    f"max_motion={batch_max_ratio:.4f} (threshold={motion_ratio_threshold:.4f}) — "
                    f"{total_events_so_far} events so far"
                )
                batch_max_ratio = 0.0

                ram_check(job_id, logger)

                if cancel_event.is_set():
                    break

        # ── Zero-frames guard ─────────────────────────────────────────────────
        if frames_done == 0 and not cancel_event.is_set():
            raise RuntimeError(
                f"VideoCapture produced 0 frames from: {source_path}. "
                f"File may be corrupt or the codec is unsupported. "
                f"Try re-encoding to H.264 MP4 with HandBrake."
            )

        # ── Close any open event at end of video ──────────────────────────────
        if in_event and not cancel_event.is_set():
            event_end = current_pts + padding_s
            if event_end - event_start >= min_event_s:
                confirmed_events.append({
                    "event_index":       event_index,
                    "start_s":           round(event_start, 3),
                    "end_s":             round(event_end, 3),
                    "start_clock":       event_start_clock,
                    "end_clock":         seconds_to_clock(event_end, recording_start),
                    "peak_motion_score": round(peak_score, 4),
                    "zone_label":        zones[0]["label"] if zones else None,
                })

        # ── Final flush ───────────────────────────────────────────────────────
        _flush_events(conn, job_id, confirmed_events, recording_start)
        conn.execute("UPDATE jobs SET progress=1.0 WHERE id=?", (job_id,))
        conn.commit()

        all_events = [
            dict(r) for r in conn.execute(
                "SELECT * FROM events WHERE job_id=? ORDER BY event_index", (job_id,)
            )
        ]
        _write_timeline(job_id, job, all_events, source_duration_s)

        total_found = conn.execute(
            "SELECT COUNT(*) FROM events WHERE job_id=?", (job_id,)
        ).fetchone()[0]
        logger(f"[DONE] Detection complete — {total_found} motion events found")
        if total_found == 0:
            logger(
                "[HINT] No motion detected. Check the [DIAG] line above: "
                "if after_morph >= needed, try Medium sensitivity for fewer false positives. "
                "If [DIAG] is missing, the video produced too few frames — check the video plays in VLC."
            )

    finally:
        cap.release()


def _flush_events(conn, job_id: str, events: list, recording_start: Optional[str]) -> None:
    """Insert confirmed events into DB."""
    ts = datetime.now(timezone.utc).isoformat()
    for ev in events:
        conn.execute(
            """INSERT OR IGNORE INTO events
               (job_id, event_index, start_s, end_s, start_clock, end_clock,
                peak_motion_score, zone_label, included, created_at)
               VALUES (?,?,?,?,?,?,?,?,1,?)""",
            (
                job_id,
                ev["event_index"],
                ev["start_s"],
                ev["end_s"],
                ev.get("start_clock"),
                ev.get("end_clock"),
                ev.get("peak_motion_score"),
                ev.get("zone_label"),
                ts,
            ),
        )
    conn.commit()
