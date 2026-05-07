"""
8-step MOG2 detection pipeline.
Runs entirely in a worker thread — no asyncio, no thread pool usage.

FIX-A: loglevel changed to 'warning' so codec/filter errors are visible.
FIX-B: showinfo filter removed; PTS estimated from frame count (simpler, no race condition).
        FFmpeg stderr is collected and logged to the job log buffer for diagnostics.
        If FFmpeg produces 0 frames, a RuntimeError is raised so the job is marked FAILED
        (not silently COMPLETED with 0 events).
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
    FFMPEG_THREADS,
    JOBS_DIR,
)
from app.database import get_conn
from app.utils.time_utils import seconds_to_clock

FRAME_SIZE = W * H * 3  # RGB24 bytes per frame

SENSITIVITY_HISTORY = {"low": 700, "medium": 500, "high": 200}
SENSITIVITY_THRESHOLD = {"low": 32, "medium": 16, "high": 8}
MOTION_THRESHOLD = {"low": 0.02, "medium": 0.005, "high": 0.001}

WARMUP_FRAMES = 500  # MOG2 warmup after crash resume (ISSUE-05)


def _build_ffmpeg_cmd(
    source_path: str,
    target_fps: float,
    ss: Optional[float] = None,
    hw_decode: bool = False,
) -> list:
    """Build FFmpeg pipe command. Frame skip via fps filter (ISSUE-06).
    FIX-A: loglevel=warning so codec/format errors reach stderr for diagnostics.
    FIX-B: showinfo removed — PTS estimated from frame count instead.
    """
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning"]
    if hw_decode:
        cmd += ["-hwaccel", "auto"]
    if ss is not None:
        cmd += ["-ss", str(ss)]
    cmd += [
        "-i", source_path,
        "-vf", f"fps={target_fps:.6f},scale={W}:{H}",
        "-pix_fmt", "rgb24",
        "-f", "rawvideo",
        "-",
    ]
    return cmd


def _build_zone_mask(zones: list) -> Optional[np.ndarray]:
    """Pre-render polygon mask from normalised coordinates."""
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
    from app.config import JOBS_DIR
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
    """Main detection pipeline entry point."""
    from app.core.ram_guard import check as ram_check

    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "thumbnails").mkdir(exist_ok=True)

    sensitivity = settings.get("sensitivity", "medium")
    frame_skip = int(settings.get("frame_skip", 1))
    padding_s = float(settings.get("padding_s", 3))
    min_gap_s = float(settings.get("min_gap_s", 5))
    min_event_s = float(settings.get("min_event_s", 3))
    zones = settings.get("zones", [])
    hw_decode = bool(settings.get("hw_decode", False))
    recording_start = job.get("recording_start")

    source_path = job["source_path"]
    source_fps = float(job.get("source_fps") or 25.0)
    source_duration_s = float(job.get("duration_s") or 0.0)

    target_fps = source_fps / max(1, frame_skip + 1)  # ISSUE-06
    if target_fps <= 0:
        target_fps = 12.5  # safe fallback
    total_frames_est = int(source_duration_s * target_fps)

    # --- Crash resume ---
    checkpoint = _read_checkpoint(job_dir)
    resume_pts: Optional[float] = None
    last_confirmed_index = -1
    frames_done = 0

    if checkpoint:
        resume_pts = checkpoint.get("pts_time", 0.0)
        last_confirmed_index = checkpoint.get("last_confirmed_event_index", -1)
        frames_done = checkpoint.get("frames_processed", 0)

        # Delete events past checkpoint to prevent duplicates (ISSUE-09)
        conn = get_conn()
        conn.execute(
            "DELETE FROM events WHERE job_id=? AND event_index > ?",
            (job_id, last_confirmed_index),
        )
        conn.commit()
        logger(f"[RESUME] Resuming from checkpoint at {resume_pts:.1f}s (frame {frames_done})")
    else:
        logger(f"[START] Detection started — source: {job['source_name']}")

    logger(
        f"[DETECTION] FFmpeg starting — {target_fps:.1f} fps, {W}×{H} px, "
        f"sensitivity={sensitivity}, source_fps={source_fps:.1f}"
    )

    # --- Step 1: Start FFmpeg pipe ---
    cmd = _build_ffmpeg_cmd(source_path, target_fps, ss=resume_pts, hw_decode=hw_decode)

    # FIX-B: stderr collected in a list so we can log it to the job on failure
    stderr_lines: list = []
    stderr_lock = threading.Lock()

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )

    def _stderr_reader():
        for line in proc.stderr:
            decoded = line.decode("utf-8", errors="replace").rstrip()
            if decoded:
                with stderr_lock:
                    stderr_lines.append(decoded)
                # Log FFmpeg warnings/errors directly to the job log panel
                logger(f"[ffmpeg] {decoded}")

    stderr_thread = threading.Thread(target=_stderr_reader, daemon=True)
    stderr_thread.start()

    # --- MOG2 initialisation ---
    history = SENSITIVITY_HISTORY[sensitivity]
    var_threshold = SENSITIVITY_THRESHOLD[sensitivity]
    mog2 = cv2.createBackgroundSubtractorMOG2(
        history=history, varThreshold=var_threshold, detectShadows=True
    )
    motion_ratio_threshold = MOTION_THRESHOLD[sensitivity]

    # CLAHE for high sensitivity
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    # --- Zone mask ---
    zone_mask = _build_zone_mask(zones)

    # --- Morphological kernel (ISSUE-07) ---
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    # Warmup pass after crash resume (ISSUE-05)
    if resume_pts is not None:
        logger(f"[RESUME] Warming up MOG2 background model ({WARMUP_FRAMES} frames)...")
        for _ in range(WARMUP_FRAMES):
            raw = proc.stdout.read(FRAME_SIZE)
            if len(raw) < FRAME_SIZE:
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(H, W, 3)
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            mog2.apply(gray)
        logger("[RESUME] Warmup complete — resuming detection")

    # --- Segment state machine ---
    in_event = False
    event_start: float = 0.0
    event_start_clock: str = ""
    silence_start: float = 0.0
    peak_score: float = 0.0
    confirmed_events: list = []
    event_index = last_confirmed_index + 1

    conn = get_conn()
    frame_idx = 0
    # FIX-B: PTS estimated from frame count — no showinfo race condition
    current_pts = resume_pts or 0.0
    first_frame_logged = False

    try:
        while True:
            raw = proc.stdout.read(FRAME_SIZE)
            if len(raw) < FRAME_SIZE:
                break

            if cancel_event.is_set():
                break

            # FIX-B: simple frame-count-based PTS (no showinfo, no race condition)
            current_pts = (resume_pts or 0.0) + frame_idx / target_fps

            # Log first frame receipt so we know FFmpeg is producing output
            if not first_frame_logged:
                logger("[DETECTION] First frame received — FFmpeg pipeline is working")
                first_frame_logged = True

            frame = np.frombuffer(raw, dtype=np.uint8).reshape(H, W, 3)

            # Step 3: Preprocess
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            if sensitivity == "high":
                gray = clahe.apply(gray)

            # Step 4: MOG2
            fg_mask = mog2.apply(gray)
            _, fg_mask = cv2.threshold(fg_mask, 200, 255, cv2.THRESH_BINARY)

            # Step 5: Morphological filter (ISSUE-07)
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)

            # Step 6: Zone mask
            if zone_mask is not None:
                fg_mask = cv2.bitwise_and(fg_mask, zone_mask)

            # Step 7: Score
            motion_ratio = cv2.countNonZero(fg_mask) / (W * H)
            is_motion = motion_ratio >= motion_ratio_threshold

            # Step 8: Segment state machine
            if not in_event and is_motion:
                in_event = True
                event_start = max(0.0, current_pts - padding_s)
                event_start_clock = seconds_to_clock(event_start, recording_start)
                peak_score = motion_ratio
                silence_start = 0.0
            elif in_event:
                if is_motion:
                    peak_score = max(peak_score, motion_ratio)
                    silence_start = 0.0
                else:
                    if silence_start == 0.0:
                        silence_start = current_pts
                    silence_duration = current_pts - silence_start
                    if silence_duration >= min_gap_s:
                        # Close event
                        event_end = silence_start + padding_s
                        duration = event_end - event_start
                        if duration >= min_event_s:
                            confirmed_events.append({
                                "event_index": event_index,
                                "start_s": round(event_start, 3),
                                "end_s": round(event_end, 3),
                                "start_clock": event_start_clock,
                                "end_clock": seconds_to_clock(event_end, recording_start),
                                "peak_motion_score": round(peak_score, 4),
                                "zone_label": zones[0]["label"] if zones else None,
                            })
                            event_index += 1
                        in_event = False
                        silence_start = 0.0
                        peak_score = 0.0

            frame_idx += 1
            frames_done += 1

            # Checkpoint every BATCH_SIZE frames
            if frame_idx % BATCH_SIZE == 0:
                _flush_events(conn, job_id, confirmed_events, recording_start)
                flushed_count = len(confirmed_events)
                last_idx = (
                    confirmed_events[-1]["event_index"] if confirmed_events
                    else last_confirmed_index
                )
                confirmed_events.clear()

                _write_checkpoint(job_dir, {
                    "job_id": job_id,
                    "frames_processed": frames_done,
                    "pts_time": current_pts,
                    "last_confirmed_event_index": last_idx,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

                progress = min(frames_done / max(total_frames_est, 1), 0.99)
                conn.execute("UPDATE jobs SET progress=? WHERE id=?", (progress, job_id))
                conn.commit()

                elapsed = int(current_pts)
                total_events_so_far = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE job_id=?", (job_id,)
                ).fetchone()[0]
                logger(
                    f"[{elapsed//3600:02d}:{(elapsed%3600)//60:02d}:{elapsed%60:02d}] "
                    f"Frame {frames_done}/{total_frames_est} — "
                    f"{total_events_so_far} events so far"
                )

                ram_check(job_id, logger)

                if cancel_event.is_set():
                    break

        # FIX-A: Raise if FFmpeg produced no frames at all — turns silent failure into FAILED job
        if frames_done == 0 and not cancel_event.is_set():
            stderr_thread.join(timeout=3)
            with stderr_lock:
                err_text = "\n".join(stderr_lines[-10:]) if stderr_lines else "(no stderr output)"
            raise RuntimeError(
                f"FFmpeg produced 0 frames from the source video. "
                f"The file may be corrupted, use an unsupported codec, or the path is wrong.\n"
                f"FFmpeg output:\n{err_text}"
            )

        # --- Close any open event at end of video ---
        if in_event and not cancel_event.is_set():
            event_end = current_pts + padding_s
            duration = event_end - event_start
            if duration >= min_event_s:
                confirmed_events.append({
                    "event_index": event_index,
                    "start_s": round(event_start, 3),
                    "end_s": round(event_end, 3),
                    "start_clock": event_start_clock,
                    "end_clock": seconds_to_clock(event_end, recording_start),
                    "peak_motion_score": round(peak_score, 4),
                    "zone_label": zones[0]["label"] if zones else None,
                })

        # Final flush
        _flush_events(conn, job_id, confirmed_events, recording_start)
        conn.execute("UPDATE jobs SET progress=1.0 WHERE id=?", (job_id,))
        conn.commit()

        # Write timeline.json
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
                "[HINT] No motion detected. If the video has movement, try resubmitting "
                "with High sensitivity. Check the log above for any FFmpeg warnings."
            )

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        stderr_thread.join(timeout=2)


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
