import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.log_buffer import log_buffer
from app.database import get_conn
from app.models import JobStatus

router = APIRouter()


@router.get("/jobs/{job_id}/stream")
async def job_stream(job_id: str):
    conn = get_conn()
    row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()

    async def event_generator():
        # If job already completed, replay history then send done
        if row and row["status"] in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            q = log_buffer.subscribe(job_id)
            try:
                while not q.empty():
                    line = q.get_nowait()
                    if line == "__DONE__":
                        break
                    yield f"data: {json.dumps({'type': 'log', 'line': line})}\n\n"
            except asyncio.QueueEmpty:
                pass
            finally:
                log_buffer.unsubscribe(job_id, q)
            yield f"data: {json.dumps({'type': 'done', 'status': row['status']})}\n\n"
            return

        q = log_buffer.subscribe(job_id)
        try:
            while True:
                try:
                    line = await asyncio.wait_for(q.get(), timeout=30.0)
                    if line == "__DONE__":
                        current = get_conn().execute(
                            "SELECT status FROM jobs WHERE id=?", (job_id,)
                        ).fetchone()
                        status = current["status"] if current else "unknown"
                        yield f"data: {json.dumps({'type': 'done', 'status': status})}\n\n"
                        break
                    yield f"data: {json.dumps({'type': 'log', 'line': line})}\n\n"
                except asyncio.TimeoutError:
                    yield 'data: {"type":"keepalive"}\n\n'
        finally:
            log_buffer.unsubscribe(job_id, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/jobs/{job_id}/events/{event_id}/preview")
async def generate_preview(job_id: str, event_id: int):
    import secrets
    from app.database import get_conn
    conn = get_conn()

    ev = conn.execute("SELECT * FROM events WHERE id=? AND job_id=?", (event_id, job_id)).fetchone()
    if not ev:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Event not found")

    job = conn.execute("SELECT source_path FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Job not found")

    token = secrets.token_urlsafe(16)

    # Run synchronously in thread pool (short FFmpeg extract)
    import asyncio
    loop = asyncio.get_event_loop()
    from app.core.export_engine import generate_preview as gen_preview

    try:
        await loop.run_in_executor(
            None,
            gen_preview,
            job["source_path"],
            float(ev["start_s"]),
            float(ev["end_s"]),
            token,
        )
    except RuntimeError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail=str(e))

    return {
        "preview_url": f"/api/previews/{token}.mp4",
        "expires_in_seconds": 300,
    }


@router.get("/previews/{token}.mp4")
async def serve_preview(token: str):
    from app.config import PREVIEW_DIR
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    preview_path = PREVIEW_DIR / f"{token}.mp4"
    if not preview_path.exists():
        raise HTTPException(status_code=404, detail="Preview expired or not found.")
    return FileResponse(str(preview_path), media_type="video/mp4")
