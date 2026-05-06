"""
Post-detection thumbnail generation.
Runs after detection completes — NOT during detection (avoids I/O pressure on Pi).
"""
import subprocess
from pathlib import Path
from typing import Callable

from app.config import JOBS_DIR, THUMB_CACHE_SIZE
from app.database import get_conn


def run(job_id: str, source_path: str, logger: Callable[[str], None]) -> None:
    """Generate 320x180 JPEG thumbnails for all events in this job."""
    conn = get_conn()
    events = conn.execute(
        "SELECT id, event_index, start_s, end_s FROM events WHERE job_id=? ORDER BY event_index",
        (job_id,),
    ).fetchall()

    if not events:
        return

    job_dir = JOBS_DIR / job_id
    thumb_dir = job_dir / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)

    logger(f"[THUMBNAILS] Generating {len(events)} thumbnails...")

    for ev in events:
        idx = ev["event_index"]
        mid_s = (float(ev["start_s"]) + float(ev["end_s"])) / 2
        out_path = thumb_dir / f"{idx}.jpg"

        if out_path.exists():
            continue  # already generated (e.g., resume after crash)

        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-ss", str(mid_s),
            "-i", source_path,
            "-frames:v", "1",
            "-vf", "scale=320:180",
            "-q:v", "5",
            "-y",
            str(out_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=15)
        if proc.returncode == 0:
            rel_path = f"data/jobs/{job_id}/thumbnails/{idx}.jpg"
            conn.execute(
                "UPDATE events SET thumbnail_path=? WHERE id=?",
                (rel_path, ev["id"]),
            )

    conn.commit()
    logger(f"[THUMBNAILS] Done")
