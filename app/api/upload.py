import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from app.config import UPLOAD_DIR, CHUNK_SIZE
from app.database import get_conn

router = APIRouter()


@router.post("/upload/init")
async def upload_init(body: dict):
    filename = body.get("filename", "upload.mp4")
    total_size = int(body.get("total_size", 0))

    upload_id = str(uuid.uuid4())
    upload_dir = UPLOAD_DIR / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Store metadata
    (upload_dir / "meta.json").write_text(
        f'{{"filename":"{filename}","total_size":{total_size}}}'
    )

    return {"upload_id": upload_id, "chunk_size": CHUNK_SIZE}


@router.post("/upload/chunk")
async def upload_chunk(request: Request):
    """Receive one chunk using Request.stream() — never buffers full file (research Decision 8)."""
    import json

    # Parse multipart manually via python-multipart
    from starlette.datastructures import UploadFile
    form = await request.form()
    upload_id = form.get("upload_id")
    chunk_index = int(form.get("chunk_index", 0))
    chunk_data = form.get("chunk_data")

    if not upload_id:
        raise HTTPException(status_code=400, detail="upload_id required")

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
    upload_id = body.get("upload_id")
    expected_chunks = int(body.get("expected_chunks", 0))

    if not upload_id:
        raise HTTPException(status_code=400, detail="upload_id required")

    upload_dir = UPLOAD_DIR / upload_id
    if not upload_dir.exists():
        raise HTTPException(status_code=404, detail="Upload session not found")

    # Read stored metadata
    import json
    meta = json.loads((upload_dir / "meta.json").read_text())
    filename = meta["filename"]
    total_size = meta.get("total_size", 0)

    # Verify all chunks present
    chunks = sorted(upload_dir.glob("chunk_*"), key=lambda x: int(x.stem.split("_")[1]))
    if len(chunks) < expected_chunks:
        missing = set(range(expected_chunks)) - {int(c.stem.split("_")[1]) for c in chunks}
        raise HTTPException(status_code=400, detail=f"Missing chunks: {list(missing)[:10]}")

    # Disk space check before assembly
    if total_size:
        disk = shutil.disk_usage(str(UPLOAD_DIR))
        if disk.free < total_size * 1.1:
            raise HTTPException(status_code=400, detail="Insufficient disk space to assemble upload.")

    # Assemble
    final_path = UPLOAD_DIR / upload_id / filename
    import aiofiles
    async with aiofiles.open(str(final_path), "wb") as out:
        for chunk in chunks:
            async with aiofiles.open(str(chunk), "rb") as src:
                while True:
                    buf = await src.read(65536)
                    if not buf:
                        break
                    await out.write(buf)

    # Delete chunk files
    for chunk in chunks:
        chunk.unlink(missing_ok=True)

    file_size = final_path.stat().st_size
    return {"source_path": str(final_path), "size": file_size}


@router.get("/upload/status/{upload_id}")
def upload_status(upload_id: str, expected_chunks: int = 0):
    upload_dir = UPLOAD_DIR / upload_id
    if not upload_dir.exists():
        raise HTTPException(status_code=404, detail="Upload session not found")

    chunks = sorted(upload_dir.glob("chunk_*"), key=lambda x: int(x.stem.split("_")[1]))
    received = [int(c.stem.split("_")[1]) for c in chunks]
    return {"received_chunks": received, "total_expected": expected_chunks}
