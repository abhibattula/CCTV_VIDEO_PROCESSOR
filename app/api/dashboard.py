from fastapi import APIRouter

from app.database import get_conn

router = APIRouter()


@router.get("/dashboard")
def dashboard():
    from app.api.system import system_stats
    system = system_stats()

    conn = get_conn()

    # Last 5 jobs (non-deleted)
    recent_rows = conn.execute(
        "SELECT id, status, source_name, created_at, finished_at, progress, output_name "
        "FROM jobs WHERE status != 'deleted' ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    recent_jobs = [dict(r) for r in recent_rows]

    # Active job (currently processing)
    active_row = conn.execute(
        "SELECT id, status, progress, source_name FROM jobs "
        "WHERE status IN ('running','detecting','exporting') LIMIT 1"
    ).fetchone()
    active_job = dict(active_row) if active_row else None

    return {
        "system": system,
        "recent_jobs": recent_jobs,
        "storage_warning": system.get("disk_warn", False),
        "active_job": active_job,
    }
