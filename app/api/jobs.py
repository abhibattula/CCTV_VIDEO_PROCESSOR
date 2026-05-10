import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import JOBS_DIR
from app.database import get_conn
from app.models import Job, Event, JobStatus
from app.utils import ffprobe as ffprobe_util
from app.utils.file_utils import is_video_file

router = APIRouter()


def _job_to_dict(row) -> dict:
    d = dict(row)
    try:
        d["settings"] = json.loads(d["settings"]) if d["settings"] else {}
    except Exception:
        d["settings"] = {}
    d["source_has_audio"] = bool(d.get("source_has_audio", 0))
    d["needs_reencode"] = bool(d.get("needs_reencode", 0))
    d["progress"] = float(d.get("progress") or 0.0)
    return d


# ─── POST /api/jobs ────────────────────────────────────────────────────────────

@router.post("/jobs", status_code=201)
def create_job(body: dict):
    source_path = body.get("source_path", "")
    settings = body.get("settings", {})
    scheduled_at = body.get("scheduled_at")
    recording_start_override = body.get("recording_start")

    p = Path(source_path)
    if not p.exists():
        raise HTTPException(status_code=422, detail="Source file does not exist.")
    if not is_video_file(p):
        raise HTTPException(status_code=422, detail="File is not a valid video or uses an unsupported container.")

    try:
        meta = ffprobe_util.probe(source_path)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Disk space check: need ~2.2× source size (ISSUE-12)
    output_dir = settings.get("output_dir", str(Path.home() / "cctv_output"))
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    file_size = p.stat().st_size
    disk = shutil.disk_usage(output_dir)
    needed = file_size * 2.2
    if disk.free < needed:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient disk space. Need ~{needed/1e9:.1f}GB, "
                   f"only {disk.free/1e9:.1f}GB available on {output_dir}.",
        )

    warnings = []

    # 4K warning on 2GB Pi (ISSUE-03)
    from app.config import RAM_MODE
    if meta["width"] > 1920 and RAM_MODE == "2gb":
        warnings.append({
            "code": "SOURCE_4K_ON_2GB",
            "message": "4K source detected. Processing may be RAM-constrained on 2GB Pi.",
        })

    # Codec re-encode warning (ISSUE-13)
    if meta["needs_reencode"]:
        codec = meta["codec_name"].upper()
        warnings.append({
            "code": "CODEC_REENCODE_REQUIRED",
            "message": f"Source uses {codec} codec. Export will require re-encoding (~2 hours).",
        })

    recording_start = recording_start_override or meta.get("recording_start")
    job_id = str(uuid.uuid4())

    # Default settings
    defaults = {
        "sensitivity": "medium",
        "padding_s": 3,
        "min_gap_s": 5,
        "min_event_s": 3,
        "output_quality": "original",
        "output_format": "mp4",
        "output_dir": output_dir,
        "frame_skip": 1,
        "hw_decode": False,
        "zones": [],
    }
    defaults.update(settings)

    conn = get_conn()
    conn.execute(
        """INSERT INTO jobs
           (id, status, source_path, source_name, duration_s, source_fps,
            source_width, source_height, source_codec, source_has_audio,
            needs_reencode, file_size, settings, created_at, scheduled_at, recording_start)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            job_id, JobStatus.QUEUED,
            source_path, p.name,
            meta["duration_s"], meta["avg_frame_rate"],
            meta["width"], meta["height"],
            meta["codec_name"],
            1 if meta["has_audio"] else 0,
            1 if meta["needs_reencode"] else 0,
            file_size,
            json.dumps(defaults),
            datetime.now(timezone.utc).isoformat(),
            scheduled_at,
            recording_start,
        ),
    )
    conn.commit()

    from app.core.job_queue import job_queue
    from app.core.audit_logger import log as audit_log
    audit_log("JOB_SUBMITTED", f"{p.name} ({file_size/1e9:.1f} GB, {meta['duration_s']:.0f}s)",
              actor="user", job_id=job_id)

    return {"job_id": job_id, "status": "queued", "warnings": warnings}


# ─── GET /api/jobs ─────────────────────────────────────────────────────────────

@router.get("/jobs")
def list_jobs(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    conn = get_conn()
    where = "WHERE status != 'deleted'"
    params: list = []
    if status:
        where += " AND status=?"
        params.append(status)

    total = conn.execute(f"SELECT COUNT(*) FROM jobs {where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()

    return {
        "jobs": [_job_to_dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ─── GET /api/jobs/{job_id} ───────────────────────────────────────────────────

@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    events = conn.execute(
        "SELECT * FROM events WHERE job_id=? ORDER BY event_index", (job_id,)
    ).fetchall()

    exports = conn.execute(
        "SELECT * FROM exports WHERE job_id=? ORDER BY created_at DESC", (job_id,)
    ).fetchall()

    event_dicts = [Event.from_row(e).to_dict() for e in events]
    included = [e for e in event_dicts if e["included"]]
    total_activity_s = sum(
        float(e["end_s"]) - float(e["start_s"]) for e in events if e["included"]
    )
    source_dur = float(row["duration_s"] or 1)
    activity_pct = round(total_activity_s / source_dur * 100, 2) if source_dur else 0.0

    # Estimated output size
    source_size = int(row["file_size"] or 0)
    settings = json.loads(row["settings"]) if row["settings"] else {}
    if settings.get("output_quality", "original") == "original":
        est_size = int((total_activity_s / source_dur) * source_size) if source_dur else 0
    else:
        bitrate = 2_000_000 if settings.get("output_quality") == "compressed_720p" else 800_000
        est_size = int(total_activity_s * bitrate / 8)

    return {
        "job": _job_to_dict(row),
        "events": event_dicts,
        "event_count": len(event_dicts),
        "included_count": len(included),
        "total_activity_s": round(total_activity_s, 2),
        "activity_percent": activity_pct,
        "estimated_output_size": est_size,
        "exports": [dict(e) for e in exports],
    }


# ─── PUT /api/jobs/{job_id}/events/{event_id} ─────────────────────────────────

VALID_TAGS = {"Person", "Vehicle", "Animal", "False Positive", "Review Required", None}

@router.put("/jobs/{job_id}/events/{event_id}")
def update_event(job_id: str, event_id: int, body: dict):
    conn = get_conn()
    ev = conn.execute("SELECT * FROM events WHERE id=? AND job_id=?", (event_id, job_id)).fetchone()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")

    updates = {}
    if "included" in body:
        updates["included"] = 1 if body["included"] else 0
    if "tag" in body:
        tag = body["tag"]
        if tag not in VALID_TAGS:
            raise HTTPException(status_code=422, detail=f"Invalid tag. Must be one of: {VALID_TAGS}")
        updates["tag"] = tag

    if updates:
        set_clause = ", ".join(f"{k}=?" for k in updates)
        conn.execute(
            f"UPDATE events SET {set_clause} WHERE id=?",
            list(updates.values()) + [event_id],
        )
        conn.commit()

    updated = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    return {"id": updated["id"], "included": bool(updated["included"]), "tag": updated["tag"]}


# ─── POST /api/jobs/{job_id}/cancel ──────────────────────────────────────────

@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    conn = get_conn()
    row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    if row["status"] not in JobStatus.CANCELLABLE:
        raise HTTPException(status_code=409, detail=f"Job is not cancellable in state: {row['status']}")

    from app.core.job_queue import job_queue
    from app.core.audit_logger import log as audit_log
    job_queue.cancel(job_id)
    audit_log("JOB_CANCELLED", actor="user", job_id=job_id)
    return {"status": "cancelled"}


# ─── DELETE /api/jobs/{job_id} ────────────────────────────────────────────────

@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, delete_output: bool = Query(False)):
    conn = get_conn()
    row = conn.execute("SELECT output_path FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    output_deleted = False
    if delete_output and row["output_path"]:
        try:
            Path(row["output_path"]).unlink(missing_ok=True)
            output_deleted = True
        except OSError:
            pass

    conn.execute("UPDATE jobs SET status='deleted' WHERE id=?", (job_id,))
    conn.commit()

    from app.core.audit_logger import log as audit_log
    audit_log("JOB_DELETED", actor="user", job_id=job_id)
    return {"deleted": True, "output_deleted": output_deleted}


# ─── POST /api/jobs/{job_id}/retry ───────────────────────────────────────────

@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str):
    conn = get_conn()
    row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    if row["status"] != JobStatus.FAILED:
        raise HTTPException(status_code=409, detail=f"Job cannot be retried from state: {row['status']}")

    from app.core.job_queue import job_queue
    from app.core.audit_logger import log as audit_log
    has_checkpoint = job_queue.retry(job_id)
    audit_log("JOB_RETRIED", actor="user", job_id=job_id)
    return {"status": "queued", "resumed_from_checkpoint": has_checkpoint}


# ─── GET /api/jobs/{job_id}/zone-frame (C1 fix — FR-009) ─────────────────────

@router.get("/jobs/{job_id}/zone-frame")
def zone_frame(job_id: str, width: int = Query(960), height: int = Query(540)):
    import subprocess as sp
    conn = get_conn()
    row = conn.execute("SELECT source_path, duration_s FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    source_path = row["source_path"]
    if not Path(source_path).exists():
        raise HTTPException(status_code=404, detail="Source file no longer accessible")

    # IMP-5: store in job dir (not /tmp) so it is cleaned up with the job
    # and does not accumulate across many jobs on the Pi's limited storage.
    from app.config import JOBS_DIR
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    out_path = job_dir / "zone_frame.jpg"

    if not out_path.exists():
        duration = float(row["duration_s"] or 0)
        seek_s = duration * 0.10

        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-ss", str(seek_s),
            "-i", source_path,
            "-frames:v", "1",
            "-vf", f"scale={width}:{height}",
            "-y", str(out_path),
        ]
        result = sp.run(cmd, capture_output=True, timeout=15)
        if result.returncode != 0:
            raise HTTPException(status_code=503, detail="Frame extraction in progress. Retry in 2 seconds.")

    return FileResponse(str(out_path), media_type="image/jpeg")
