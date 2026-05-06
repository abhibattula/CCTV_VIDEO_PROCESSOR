import csv
import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from app.core.analytics import compute
from app.core.report_gen import generate as generate_pdf
from app.database import get_conn

router = APIRouter()


@router.get("/reports/{job_id}/analytics")
def analytics(job_id: str):
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone():
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        return compute(job_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/reports/{job_id}/pdf")
def report_pdf(job_id: str):
    """Generate PDF report — disk-backed, served via FileResponse (research Decision 9)."""
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone():
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        pdf_path = generate_pdf(job_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"report_{job_id[:8]}.pdf",
    )


@router.get("/reports/{job_id}/csv")
def report_csv(job_id: str):
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone():
        raise HTTPException(status_code=404, detail="Job not found")

    events = conn.execute(
        "SELECT * FROM events WHERE job_id=? ORDER BY event_index", (job_id,)
    ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "event_index", "start_s", "end_s", "duration_s",
        "start_clock", "end_clock", "peak_motion_score",
        "zone_label", "tag", "included",
    ])
    for ev in events:
        writer.writerow([
            ev["event_index"], ev["start_s"], ev["end_s"], ev["duration_s"],
            ev["start_clock"], ev["end_clock"], ev["peak_motion_score"],
            ev["zone_label"], ev["tag"], "yes" if ev["included"] else "no",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=events_{job_id[:8]}.csv"},
    )
