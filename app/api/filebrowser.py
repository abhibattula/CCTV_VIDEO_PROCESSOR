from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.utils.file_utils import ALLOWED_ROOTS, is_video_file, validate_path

router = APIRouter()


@router.get("/browse")
def browse(path: str = Query("/media")):
    try:
        resolved = validate_path(path)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Path not allowed.")

    if not resolved.exists():
        raise HTTPException(status_code=404, detail="Path does not exist.")
    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory.")

    parent = str(resolved.parent) if resolved != resolved.parent else str(resolved)

    entries = []
    try:
        for item in sorted(resolved.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            try:
                stat = item.stat()
                entries.append({
                    "name": item.name,
                    "is_dir": item.is_dir(),
                    "size": stat.st_size if not item.is_dir() else 0,
                    "mtime": int(stat.st_mtime),
                    "is_video": is_video_file(item) if not item.is_dir() else False,
                })
            except (PermissionError, OSError):
                continue
    except PermissionError:
        raise HTTPException(status_code=403, detail="Cannot read directory.")

    return {"path": str(resolved), "parent": parent, "entries": entries}
