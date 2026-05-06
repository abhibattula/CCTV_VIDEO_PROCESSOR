import csv
import io
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.database import get_conn

router = APIRouter()


@router.get("/audit")
def list_audit(
    level: Optional[str] = Query(None),
    actor: Optional[str] = Query(None),
    job_id: Optional[str] = Query(None),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    conn = get_conn()
    conditions = []
    params: list = []

    if level:
        conditions.append("level=?")
        params.append(level)
    if actor:
        conditions.append("actor=?")
        params.append(actor)
    if job_id:
        conditions.append("job_id=?")
        params.append(job_id)
    if start:
        conditions.append("ts >= ?")
        params.append(start)
    if end:
        conditions.append("ts <= ?")
        params.append(end + "T23:59:59")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    total = conn.execute(f"SELECT COUNT(*) FROM audit_log {where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM audit_log {where} ORDER BY ts DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()

    return {"entries": [dict(r) for r in rows], "total": total}


@router.get("/audit/export.csv")
def export_audit_csv(
    level: Optional[str] = Query(None),
    actor: Optional[str] = Query(None),
    job_id: Optional[str] = Query(None),
):
    conn = get_conn()
    conditions = []
    params: list = []
    if level:
        conditions.append("level=?")
        params.append(level)
    if actor:
        conditions.append("actor=?")
        params.append(actor)
    if job_id:
        conditions.append("job_id=?")
        params.append(job_id)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM audit_log {where} ORDER BY ts DESC", params
    ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "ts", "level", "actor", "action", "detail", "job_id"])
    for row in rows:
        writer.writerow([row["id"], row["ts"], row["level"], row["actor"],
                         row["action"], row["detail"], row["job_id"]])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
    )
