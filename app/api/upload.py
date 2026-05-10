import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from app.config import UPLOAD_DIR, CHUNK_SIZE
from app.database import get_conn

router = APIRouter()


def _safe_chunk_index(stem: str) -> Optional[int]:
    """Parse chunk index from filename stem. Returns None if malformed."""
    try:
        parts = stem.split("_")
        return int(parts[1]) if len(parts) >= 2 else None
    except (ValueError, IndexError):
        return None


@router.post("/upload/init")
async def upload_init(body: dict):
    filename = body.get("filename", "upload.mp4")
    total_size = int(body.get("total_size", 0))

    upload_id = str(uuid.uuid4())
    upload_dir = UPLOAD_DIR / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    import json as _json
    (upload_dir / "meta.json").write_text(
        _json.dumps({"filename": filename, "total_size": total_size})
    )  # IMP-7: use json.dumps, not f-string — filenames can contain quotes/backslashes

    return {"upload_id": upload_id, "chunk_size": CHUNK_SIZE}


@router.post("/upload/chunk")
async def upload_chunk(request: Request):
    """Receive one chunk using multipart form — streams to disk in 64KB buffers."""
    form = await request.form()
    upload_id = form.get("upload_id")
    chunk_index = int(form.get("chunk_index", 0))
    chunk_data = form.get("chunk_data")

    if not upload_id:
        raise HTTPException(status_code=400, detail="upload_id required")
    if chunk_data is None:
        raise HTTPException(status_code=400, detail="chunk_data required")

    upload_dir = UPLOAD_DIR / upload_id
    if not upload_dir.exists():
        raise HTTPException(status_code=404, detail="Upload session not found")

    chunk_path = upload_dir / f"chunk_{chunk_index:06d}"

    import aiofiles
    async with aiofiles.open(str(chunk_path), "wb") as f:
        if hasattr(chunk_data, "read"):
            while True:
                buf = await chunk_data.read(65536)
                if not buf:
                    break
                await f.write(buf)
        else:
            await f.write(chunk_data if isinstance(chunk_data, bytes) else chunk_data.encode())

    return {"chunk_index": chunk_index, "received": True}


@router.post("/upload/finalize")
async def upload_finalize(body: dict):
    import json

    upload_id = body.get("upload_id")
    expected_chunks = int(body.get("expected_chunks", 0))

    if not upload_id:
        raise HTTPException(status_code=400, detail="upload_id required")

    upload_dir = UPLOAD_DIR / upload_id
    if not upload_dir.exists():
        raise HTTPException(status_code=404, detail="Upload session not found")

    meta = json.loads((upload_dir / "meta.json").read_text())
    filename = meta["filename"]
    total_size = meta.get("total_size", 0)

    # Sort chunks safely — skip any file with a non-numeric index (BUG-05 fix)
    raw_chunks = list(upload_dir.glob("chunk_*"))
    chunks = []
    for c in raw_chunks:
        idx = _safe_chunk_index(c.stem)
        if idx is not None:
            chunks.append((idx, c))
    chunks.sort(key=lambda x: x[0])
    chunk_files = [c for _, c in chunks]

    if len(chunk_files) < expected_chunks:
        present = {idx for idx, _ in chunks}
        missing = list(set(range(expected_chunks)) - present)[:10]
        raise HTTPException(status_code=400, detail=f"Missing chunks: {missing}")

    if total_size:
        disk = shutil.disk_usage(str(UPLOAD_DIR))
        if disk.free < total_size * 1.1:
            raise HTTPException(status_code=400, detail="Insufficient disk space to assemble upload.")

    # BUG-04 fix: sanitise filename to prevent path traversal
    safe_name = Path(filename).name
    final_path = UPLOAD_DIR / upload_id / safe_name

    import aiofiles
    async with aiofiles.open(str(final_path), "wb") as out:
        for chunk in chunk_files:
            async with aiofiles.open(str(chunk), "rb") as src:
                while True:
                    buf = await src.read(65536)
                    if not buf:
                        break
                    await out.write(buf)

    for chunk in chunk_files:
        chunk.unlink(missing_ok=True)

    file_size = final_path.stat().st_size
    return {"source_path": str(final_path), "size": file_size}


@router.get("/upload/status/{upload_id}")
def upload_status(upload_id: str, expected_chunks: int = 0):
    upload_dir = UPLOAD_DIR / upload_id
    if not upload_dir.exists():
        raise HTTPException(status_code=404, detail="Upload session not found")

    # BUG-05 fix: safe integer parsing for chunk index
    received = []
    for c in upload_dir.glob("chunk_*"):
        idx = _safe_chunk_index(c.stem)
        if idx is not None:
            received.append(idx)
    received.sort()

    return {"received_chunks": received, "total_expected": expected_chunks}
