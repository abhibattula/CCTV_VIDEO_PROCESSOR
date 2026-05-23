"""
8-step MOG2 detection pipeline.
Runs entirely in a worker thread — no asyncio, no thread pool usage.

Frame source: cv2.VideoCapture with automatic normalization fallback.

--- Why VideoCapture instead of the original FFmpeg pipe ---
The FFmpeg CLI applies strict edit-list and index logic. For Android phone
recordings with a broken MP4 index (edit list pointing to an unindexed
keyframe), every flag combination — -ignore_editlist, +ignidx, +discardcorrupt
— resolved one failure mode and revealed another. FFmpeg CLI consistently
produced only 30–38 frames from a 115-second 6864-frame video.

OpenCV's VideoCapture uses av_read_frame internally with a lenient error-
recovery loop that continues past the points where FFmpeg CLI gives up.
On x86/Windows, VideoCapture reads all 6864 frames from the same file.

--- Why normalization is also needed ---
The pip wheel for opencv-python-headless on aarch64 (Raspberry Pi) may link
against the OS's system libavcodec rather than bundling its own. If the OS
libav has the same 30-frame limitation as FFmpeg CLI, VideoCapture on Pi
would also fail. To cover this case, the engine probes VideoCapture with 60
frames at startup. If fewer than 80 % succeed, it re-encodes the source to a
clean H.264 MP4 using a VideoCapture-reads → FFmpeg-writes pipeline:

  VideoCapture  ──raw BGR24 frames──►  FFmpeg stdin  ──libx264──►  normalized.mp4

This sidesteps the libav INPUT problem (VideoCapture handles it) while
producing a perfectly-formed OUTPUT that any VideoCapture can read.

--- Crash resume ---
The normalized.mp4 (if created) is stored in JOBS_DIR/{job_id}/ and reused on
crash-resume. PTS from VideoCapture on the normalized file are valid because
FFmpeg regenerates them from frame index when writing.
"""
import json
import subprocess
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

# ── MOG2 parameters ───────────────────────────────────────────────────────────
SENSITIVITY_HISTORY = {"low": 700, "medium": 500, "high": 200}
SENSITIVITY_VAR_THR  = {"low": 32,  "medium": 16,  "high": 8}

# Motion ratio thresholds (fraction of W×H pixels that must be foreground).
# 320×240 = 76,800 px; medium threshold = 154 px minimum.
MOTION_THRESHOLD = {"low": 0.01, "medium": 0.002, "high": 0.0005}

# Warmup frames: stabilise MOG2 before event detection begins.
INITIAL_WARMUP = 30    # Fresh start: ~0.5 s at 60 fps
WARMUP_FRAMES  = 500   # Crash resume: re-establish model after seek

# Frame-reading probe before committing to a full detection pass.
PROBE_FRAMES = 60      # How many frames to test-read
PROBE_OK_MIN  = 48     # Minimum successes (80 %) before triggering normalization

# Log a progress line at most once every N seconds of video time.
LOG_INTERVAL_S = 10.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_zone_mask(zones: list) -> Optional[np.ndarray]:
    """Pre-render polygon mask from normalised [0–1] coordinates."""
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


# ── Video opening with normalization fallback ─────────────────────────────────

def _normalize_via_vc(
    source_path: str,
    normalized_path: str,
    source_fps: float,
    source_w: int,
    source_h: int,
    logger: Callable,
) -> bool:
    """
    Read frames from source_path via VideoCapture and write them into a clean
    H.264 MP4 via FFmpeg stdin. Bypasses the libav INPUT path that causes early
    EOF on malformed phone videos, while producing a well-formed OUTPUT.

    Returns True if the output was written successfully with > 100 frames.
    """
    logger(
        f"[NORMALIZE] VideoCapture → FFmpeg pipe re-encode "
        f"(source: {Path(source_path).name}, {source_w}×{source_h} @ {source_fps:.2f}fps)…"
    )

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-y",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", f"{source_w}x{source_h}",
        "-r", str(source_fps),
        "-i", "-",                          # Read raw frames from stdin
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-an",                              # Drop audio (not needed for detection)
        normalized_path,
    ]

    cap = cv2.VideoCapture(source_path)
    if not cap.isOpened():
        logger("[NORMALIZE] Cannot open source with VideoCapture — aborting normalization")
        return False

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        cap.release()
        logger("[NORMALIZE] ffmpeg not found in PATH — cannot normalize")
        return False

    frame_count = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            try:
                proc.stdin.write(frame.tobytes())
            except BrokenPipeError:
                logger("[NORMALIZE] FFmpeg stdin pipe broken — aborting")
                break
            frame_count += 1
            if frame_count % 600 == 0:
                logger(f"[NORMALIZE] Extracting frames… {frame_count} so far")
    finally:
        cap.release()
        try:
            proc.stdin.close()
        except OSError:
            pass
        _, stderr_bytes = proc.communicate(timeout=60)
        rc = proc.returncode

    if rc != 0:
        stderr_snippet = stderr_bytes.decode("utf-8", errors="replace")[-600:]
        logger(f"[NORMALIZE] FFmpeg exited {rc}: {stderr_snippet}")
        return False

    if frame_count < 100:
        logger(f"[NORMALIZE] Only {frame_count} frames extracted — source may be too short or unreadable")
        return False

    try:
        size_mb = Path(normalized_path).stat().st_size / 1_048_576
    except OSError:
        size_mb = 0.0

    logger(
        f"[NORMALIZE] Complete — {frame_count} frames written, "
        f"{size_mb:.1f} MB → {Path(normalized_path).name}"
    )
    return True


def _open_video(
    source_path: str,
    job_dir: Path,
    fallback_fps: float,
    logger: Callable,
) -> tuple:
    """
    Open a VideoCapture for detection, probing first and normalizing if needed.

    1. Open VideoCapture on source_path.
    2. Read PROBE_FRAMES frames. If < PROBE_OK_MIN succeed, the source is
       malformed on this platform → normalize using _normalize_via_vc.
    3. Re-open VideoCapture (on source or on normalized file) from frame 0.
    4. Return (cap, total_frames, actual_fps).
    """
    normalized_path = str(job_dir / "normalized.mp4")

    # Check if a cached normalization from a previous run exists
    norm_file = job_dir / "normalized.mp4"
    if norm_file.exists() and norm_file.stat().st_size > 10_000:
        logger(f"[NORMALIZE] Cached normalized video found — using it")
        cap = cv2.VideoCapture(str(norm_file))
        if cap.isOpened():
            tf = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
            fps = cap.get(cv2.CAP_PROP_FPS) or fallback_fps
            return cap, tf, fps
        cap.release()

    # Open original
    cap = cv2.VideoCapture(source_path)
    if not cap.isOpened():
        raise RuntimeError(
            f"VideoCapture cannot open: {source_path}. "
            f"File may be corrupt or use an unsupported codec."
        )

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    actual_fps   = cap.get(cv2.CAP_PROP_FPS) or fallback_fps
    src_w        = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h        = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Probe only if video is long enough
    if total_frames > PROBE_FRAMES * 2:
        probe_ok = 0
        for _ in range(PROBE_FRAMES):
            ret, _ = cap.read()
            if ret:
                probe_ok += 1
            else:
                break
        cap.release()

        if probe_ok < PROBE_OK_MIN:
            logger(
                f"[PROBE] VideoCapture read {probe_ok}/{PROBE_FRAMES} probe frames "
                f"({probe_ok * 100 // PROBE_FRAMES}% success) — "
                f"video is malformed on this platform. Normalizing…"
            )
            ok = _normalize_via_vc(
                source_path, normalized_path, actual_fps, src_w, src_h, logger
            )
            if ok and norm_file.exists():
                cap = cv2.VideoCapture(normalized_path)
                if cap.isOpened():
                    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or total_frames
                    actual_fps   = cap.get(cv2.CAP_PROP_FPS) or actual_fps
                    logger(
                        f"[NORMALIZE] Normalized video ready — "
                        f"{total_frames} frames, {actual_fps:.2f}fps"
                    )
                    return cap, total_frames, actual_fps
                cap.release()
                logger("[NORMALIZE] Cannot open normalized file — falling back to original")

            # Fallback: reopen original and hope for the best
            cap = cv2.VideoCapture(source_path)
            if not cap.isOpened():
                raise RuntimeError(f"Cannot reopen original: {source_path}")
        else:
            # Probe succeeded — reopen from frame 0 for actual processing
            logger(
                f"[PROBE] {probe_ok}/{PROBE_FRAMES} frames read OK "
                f"— VideoCapture is healthy"
            )
            cap = cv2.VideoCapture(source_path)
            if not cap.isOpened():
                raise RuntimeError(f"Cannot reopen: {source_path}")
    # (else: short video — skip probe, use cap as-is)

    return cap, total_frames, actual_fps


# ── Main detection entry point ─────────────────────────────────────────────────

def run(
    job_id: str,
    job: dict,
    settings: dict,
    cancel_event: threading.Event,
    logger: Callable[[str], None],
) -> None:
    """Main detection pipeline entry point."""
    from app.core.ram_guard import check as ram_check

    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "thumbnails").mkdir(exist_ok=True)

    sensitivity     = settings.get("sensitivity", "medium")
    frame_skip      = int(settings.get("frame_skip", 0))
    padding_s       = float(settings.get("padding_s", 2))
    min_gap_s       = float(settings.get("min_gap_s", 2))
    min_event_s     = float(settings.get("min_event_s", 2))
    zones           = settings.get("zones", [])
    recording_start = job.get("recording_start")

    source_path       = job["source_path"]
    source_fps        = float(job.get("source_fps") or 25.0)
    source_duration_s = float(job.get("duration_s") or 0.0)

    # ── Crash-resume setup ────────────────────────────────────────────────────
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

    # ── Open video with normalization fallback ────────────────────────────────
    cap, total_frames, actual_fps = _open_video(
        source_path, job_dir, source_fps, logger
    )

    logger(
        f"[DETECTION] VideoCapture ready — {total_frames} frames, "
        f"{actual_fps:.2f}fps, {W}×{H}px detection grid, "
        f"sensitivity={sensitivity}"
    )

    # Seek to crash-resume position (after normalization check so correct file is open)
    if resume_pts is not None:
        cap.set(cv2.CAP_PROP_POS_MSEC, resume_pts * 1000)
        logger(f"[RESUME] Seeked to {resume_pts:.1f}s")

    # ── MOG2 initialisation ───────────────────────────────────────────────────
    history       = SENSITIVITY_HISTORY[sensitivity]
    var_threshold = SENSITIVITY_VAR_THR[sensitivity]
    mog2 = cv2.createBackgroundSubtractorMOG2(
        history=history, varThreshold=var_threshold, detectShadows=False
    )
    motion_ratio_threshold = MOTION_THRESHOLD[sensitivity]
    clahe  = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    zone_mask = _build_zone_mask(zones)

    # frame_idx MUST be defined before the warmup block (warmup increments it)
    frame_idx = 0

    # ── Initial warmup (fresh start only) ─────────────────────────────────────
    if resume_pts is None:
        logger(
            f"[DETECTION] MOG2 warmup ({INITIAL_WARMUP} frames) — "
            f"stabilising background model before event detection…"
        )
        for _ in range(INITIAL_WARMUP):
            ret, frame = cap.read()
            if not ret:
                break
            small = cv2.resize(frame, (W, H))
            gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            mog2.apply(gray)
            frame_idx += 1
        logger(
            f"[DETECTION] Warmup complete ({frame_idx} frames) — "
            f"event detection starting from here"
        )

    # ── Crash-resume warmup ───────────────────────────────────────────────────
    if resume_pts is not None:
        logger(f"[RESUME] MOG2 warmup ({WARMUP_FRAMES} frames) after seek…")
        for _ in range(WARMUP_FRAMES):
            ret, frame = cap.read()
            if not ret:
                break
            small = cv2.resize(frame, (W, H))
            gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            mog2.apply(gray)
            # frame_idx intentionally NOT incremented — PTS anchored by resume_pts
        logger("[RESUME] Warmup complete — resuming event detection")

    # ── Segment state machine ─────────────────────────────────────────────────
    in_event          = False
    event_start       = 0.0
    event_start_clock = ""
    silence_start     = 0.0
    peak_score        = 0.0
    confirmed_events: list = []
    event_index       = last_confirmed_index + 1

    conn           = get_conn()
    current_pts    = resume_pts or 0.0
    first_frame_ok = False          # Guard for first-frame diagnostic
    batch_max_ratio = 0.0
    last_log_pts    = -LOG_INTERVAL_S   # Ensure first log fires immediately
    diag_processed  = 0                 # Count of frames through the full pipeline

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if cancel_event.is_set():
                break

            # Accurate timestamp: position AFTER the frame that was just read
            current_pts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0

            # Frame skip: discard (frame_skip) of every (frame_skip+1) frames
            if frame_skip > 0 and frame_idx % (frame_skip + 1) != 0:
                frame_idx += 1
                continue

            # ── First-frame diagnostic ─────────────────────────────────────
            if not first_frame_ok:
                mean_brightness = int(frame.mean())
                logger(
                    f"[DETECTION] First frame received at T={current_pts:.2f}s — "
                    f"VideoCapture pipeline is working. "
                    f"Brightness: {mean_brightness}/255 "
                    f"{'(WARNING: very dark — black frame?)' if mean_brightness < 5 else '(OK)'}"
                )
                first_frame_ok = True

            # ── Preprocess ────────────────────────────────────────────────
            small = cv2.resize(frame, (W, H))
            gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)  # VideoCapture = BGR
            if sensitivity == "high":
                gray = clahe.apply(gray)

            # ── MOG2 ─────────────────────────────────────────────────────
            fg_mask      = mog2.apply(gray)
            raw_fg_count = cv2.countNonZero(fg_mask)

            # ── Morphological filter ──────────────────────────────────────
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN,  kernel)
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)

            diag_processed += 1

            # ── 10th-frame diagnostic ─────────────────────────────────────
            if diag_processed == 10:
                after_morph = cv2.countNonZero(fg_mask)
                needed      = int(motion_ratio_threshold * W * H)
                logger(
                    f"[DIAG] 10th processed frame (T={current_pts:.2f}s) — "
                    f"MOG2 raw={raw_fg_count}px → after_morph={after_morph}px "
                    f"(need >={needed}px for {sensitivity} sensitivity)"
                )

            # ── Zone mask ─────────────────────────────────────────────────
            if zone_mask is not None:
                fg_mask = cv2.bitwise_and(fg_mask, zone_mask)

            # ── Score ──────────────────────────────────────────────────────
            motion_ratio = cv2.countNonZero(fg_mask) / (W * H)
            is_motion    = motion_ratio >= motion_ratio_threshold
            if motion_ratio > batch_max_ratio:
                batch_max_ratio = motion_ratio

            # ── Segment state machine ──────────────────────────────────────
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

            frame_idx   += 1
            frames_done += 1

            # ── Checkpoint every BATCH_SIZE processed frames ────────────────
            if frame_idx % BATCH_SIZE == 0:
                _flush_events(conn, job_id, confirmed_events, recording_start)
                last_idx = (
                    confirmed_events[-1]["event_index"] if confirmed_events
                    else last_confirmed_index
                )
                confirmed_events.clear()

                _write_checkpoint(job_dir, {
                    "job_id":                     job_id,
                    "frames_processed":           frames_done,
                    "pts_time":                   current_pts,
                    "last_confirmed_event_index": last_idx,
                    "timestamp":                  datetime.now(timezone.utc).isoformat(),
                })

                progress = min(frame_idx / max(total_frames, 1), 0.99)
                conn.execute("UPDATE jobs SET progress=? WHERE id=?", (progress, job_id))
                conn.commit()

                # Log only once per LOG_INTERVAL_S seconds of video time
                if current_pts - last_log_pts >= LOG_INTERVAL_S:
                    last_log_pts = current_pts
                    elapsed      = int(current_pts)
                    total_ev_db  = conn.execute(
                        "SELECT COUNT(*) FROM events WHERE job_id=?", (job_id,)
                    ).fetchone()[0]
                    logger(
                        f"[{elapsed//3600:02d}:{(elapsed%3600)//60:02d}:{elapsed%60:02d}] "
                        f"Frame {frames_done}/{total_frames} — "
                        f"max_motion={batch_max_ratio:.4f} "
                        f"(threshold={motion_ratio_threshold:.4f}) — "
                        f"{total_ev_db} events so far"
                    )
                    batch_max_ratio = 0.0

                ram_check(job_id, logger)

                if cancel_event.is_set():
                    break

        # ── Zero-frames guard ──────────────────────────────────────────────────
        if frames_done == 0 and not cancel_event.is_set():
            raise RuntimeError(
                f"VideoCapture produced 0 frames from: {source_path}. "
                f"The file may be corrupt, truncated, or use an unsupported codec. "
                f"Try re-encoding to H.264 MP4 with HandBrake and re-uploading."
            )

        # ── Low frame-count warning ────────────────────────────────────────────
        if total_frames > 200 and not cancel_event.is_set():
            coverage_pct = frames_done * 100 // max(total_frames, 1)
            if coverage_pct < 50:
                logger(
                    f"[WARN] Only {frames_done}/{total_frames} frames processed "
                    f"({coverage_pct}%). The video may be partially unreadable. "
                    f"Events in the unread portion will be missed."
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
        logger(
            f"[DONE] Detection complete — {total_found} motion event(s) found "
            f"from {frames_done} frames"
        )
        if total_found == 0:
            logger(
                "[HINT] No motion detected. "
                "Check the [DIAG] line: if after_morph >= needed, try Medium sensitivity. "
                "If [DIAG] is missing entirely, no frames were processed — check [PROBE]."
            )

    finally:
        cap.release()


def _flush_events(conn, job_id: str, events: list, recording_start: Optional[str]) -> None:
    """Insert confirmed events into DB (INSERT OR IGNORE guards against duplicate resume)."""
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
