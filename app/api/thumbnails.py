from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import JOBS_DIR

router = APIRouter()


@router.get("/thumbnails/{job_id}/{event_index}.jpg")
def serve_thumbnail(job_id: str, event_index: int):
    thumb_path = JOBS_DIR / job_id / "thumbnails" / f"{event_index}.jpg"
    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not yet generated.")
    return FileResponse(
        str(thumb_path),
        media_type="image/jpeg",
        headers={
            "ETag": f"{job_id}-{event_index}",
            "Cache-Control": "public, max-age=86400",
        },
    )
