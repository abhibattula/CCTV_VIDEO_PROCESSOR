"""
FFmpeg-based export engine.
Stream copy for H.264/HEVC originals; re-encode for other codecs or compressed outputs.
"""
import secrets
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Tuple

from app.config import FFMPEG_THREADS, JOBS_DIR, OUTPUTS_DIR, PREVIEW_DIR

STREAM_COPY_SAFE = {"h264", "hevc", "mpeg2video", "mpeg4"}


def _run_ffmpeg(cmd: list, logger: Optional[Callable] = None) -> None:
    """Run an ffmpeg command, streaming stderr to logger."""
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True)
    if logger:
        for line in proc.stderr:
            line = line.strip()
            if line:
                logger(f"[ffmpeg] {line}")
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg exited with code {proc.returncode}")


def run(
    job_id: str,
    job: dict,
    settings: dict,
    logger: Callable[[str], None],
) -> Tuple[Path, str, int]:
    """Export included events to a merged MP4. Returns (output_path, output_name, output_size)."""
    from app.database import get_conn

    conn = get_conn()
    events = conn.execute(
        "SELECT * FROM events WHERE job_id=? AND included=1 ORDER BY start_s",
        (job_id,),
    ).fetchall()

    if not events:
        raise ValueError("No events selected — include at least one event to export.")

    source_path = job["source_path"]
    source_name = Path(source_path).stem
    has_audio = bool(job.get("source_has_audio", 0))
    source_codec = (job.get("source_codec") or "").lower()
    needs_reencode = bool(job.get("needs_reencode", 0))
    output_quality = settings.get("output_quality", "original")
    recording_start = job.get("recording_start")

    # A3 fix: re-encode when needs_reencode=True OR quality != "original" (two independent triggers)
    do_reencode = needs_reencode or (output_quality != "original")

    audio_flags = ["-c:a", "copy"] if has_audio else ["-an"]  # ISSUE-11

    job_dir = JOBS_DIR / job_id
    seg_dir = job_dir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    logger(f"[EXPORT] Exporting {len(events)} events — {'re-encode' if do_reencode else 'stream copy'}")

    # --- Step 1: Extract each event as .ts intermediate ---
    seg_files = []
    for i, ev in enumerate(events):
        seg_path = seg_dir / f"seg_{i:04d}.ts"
        seg_files.append(seg_path)
        start_s = float(ev["start_s"])
        duration = float(ev["end_s"]) - start_s

        if do_reencode:
            video_flags = ["-c:v", "libx264", "-preset", "veryfast"]
            if output_quality == "compressed_720p":
                video_flags += ["-vf", "scale=-2:720", "-crf", "28"]
            elif output_quality == "small_480p":
                video_flags += ["-vf", "scale=-2:480", "-crf", "32"]
            else:
                video_flags += ["-crf", "23"]
        else:
            video_flags = ["-c:v", "copy"]

        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-fflags", "+genpts+igndts",  # ISSUE-10: NVR PTS discontinuities
            "-ss", str(start_s),
            "-i", source_path,
            "-t", str(duration),
            *video_flags,
            *audio_flags,
            "-avoid_negative_ts", "make_zero",
            "-threads", str(FFMPEG_THREADS),
            "-y",
            str(seg_path),
        ]
        logger(f"[EXPORT] Segment {i+1}/{len(events)}: {start_s:.1f}s–{start_s+duration:.1f}s")
        _run_ffmpeg(cmd, logger)

        # Update progress
        progress = 0.5 + (i + 1) / len(events) * 0.5
        conn.execute("UPDATE jobs SET progress=? WHERE id=?", (progress, job_id))
        conn.commit()

    # --- Step 2: Write concat.txt ---
    concat_path = job_dir / "concat.txt"
    with open(concat_path, "w") as f:
        for seg in seg_files:
            f.write(f"file '{seg.resolve()}'\n")

    # --- Step 3: Write ffmetadata.txt (chapter markers) ---
    meta_path = job_dir / "ffmetadata.txt"
    with open(meta_path, "w") as f:
        f.write(";FFMETADATA1\n")
        cumulative_ms = 0
        for i, ev in enumerate(events):
            dur_ms = int((float(ev["end_s"]) - float(ev["start_s"])) * 1000)
            start_clock = ev["start_clock"] or f"{float(ev['start_s']):.0f}s"
            f.write("[CHAPTER]\n")
            f.write("TIMEBASE=1/1000\n")
            f.write(f"START={cumulative_ms}\n")
            f.write(f"END={cumulative_ms + dur_ms}\n")
            f.write(f"title=Event {i+1} — {start_clock}\n")
            cumulative_ms += dur_ms

    # --- Step 4: Merge with concat demuxer ---
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_name = f"{source_name}_activity_{timestamp}.mp4"
    output_path = OUTPUTS_DIR / job_id / output_name
    output_path.parent.mkdir(parents=True, exist_ok=True)

    merge_cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(concat_path),
        "-i", str(meta_path),
        "-map_metadata", "1",
        "-c", "copy",
        "-threads", str(FFMPEG_THREADS),
        "-use_wallclock_as_timestamps", "1",
        "-movflags", "+faststart",
        "-y",
        str(output_path),
    ]
    logger(f"[EXPORT] Merging segments into {output_name}")
    _run_ffmpeg(merge_cmd, logger)

    # --- Cleanup .ts segments ---
    for seg in seg_files:
        seg.unlink(missing_ok=True)
    try:
        seg_dir.rmdir()
    except OSError:
        pass

    output_size = output_path.stat().st_size
    logger(f"[EXPORT] Done — {output_name} ({output_size / 1e6:.1f} MB)")

    return output_path, output_name, output_size


def generate_preview(
    source_path: str,
    start_s: float,
    end_s: float,
    token: str,
) -> str:
    """Extract a temp clip for in-browser preview. Returns absolute path to clip (ISSUE-04)."""
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PREVIEW_DIR / f"{token}.mp4"
    clip_start = max(0.0, start_s - 2)
    clip_dur = (end_s - start_s) + 4

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", str(clip_start),
        "-i", source_path,
        "-t", str(clip_dur),
        "-c", "copy",
        "-movflags", "faststart",
        "-y",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"Preview generation failed: {proc.stderr.decode()[:200]}")

    return str(out_path)
