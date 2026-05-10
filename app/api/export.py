import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.database import get_conn
from app.models import JobStatus

router = APIRouter()


@router.post("/jobs/{job_id}/export")
def trigger_export(job_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    # Count included events (FR-055 — disable export when 0 events)
    count = conn.execute(
        "SELECT COUNT(*) FROM events WHERE job_id=? AND included=1", (job_id,)
    ).fetchone()[0]
    if count == 0:
        raise HTTPException(
            status_code=400,
            detail="No events selected — include at least one event to export.",
        )

    if row["status"] == JobStatus.EXPORTING:
        raise HTTPException(status_code=409, detail="Export already in progress.")

    # Run export in background thread (non-blocking response).
    # run_export reads settings internally from DB — no need to pass them here.
    def _run():
        from app.core.job_queue import job_queue
        job_queue.run_export(job_id)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    # Derive likely output name for immediate response
    import json
    from datetime import datetime, timezone
    source_stem = Path(row["source_path"]).stem
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_name = f"{source_stem}_activity_{timestamp}.mp4"

    return {"status": "exporting", "output_name": output_name}


@router.get("/jobs/{job_id}/output")
def serve_output(job_id: str):
    """Serve exported video with HTTP range request support (C2 fix, FR-035)."""
    conn = get_conn()
    row = conn.execute("SELECT output_path FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    if not row["output_path"]:
        raise HTTPException(status_code=404, detail="No export completed yet.")

    output_path = Path(row["output_path"])
    if not output_path.exists():
        raise HTTPException(status_code=410, detail="Output file was deleted from disk.")

    return FileResponse(
        str(output_path),
        media_type="video/mp4",
        headers={"Accept-Ranges": "bytes"},
    )


@router.get("/jobs/{job_id}/exports")
def list_exports(job_id: str):
    """List all export runs for a job (I2 fix — multiple exports per re-export)."""
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone():
        raise HTTPException(status_code=404, detail="Job not found")

    rows = conn.execute(
        "SELECT * FROM exports WHERE job_id=? ORDER BY created_at DESC", (job_id,)
    ).fetchall()

    exports = []
    for r in rows:
        import json
        snapshot = {}
        try:
            snapshot = json.loads(r["settings_snapshot"] or "{}")
        except Exception:
            pass
        exports.append({
            "id": r["id"],
            "output_name": r["output_name"],
            "output_size": r["output_size"],
            "created_at": r["created_at"],
            "included_events": len(snapshot.get("included_event_ids", [])),
        })

    return {"exports": exports}
