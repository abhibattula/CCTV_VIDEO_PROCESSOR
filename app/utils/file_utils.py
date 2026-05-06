from pathlib import Path

ALLOWED_ROOTS = [Path("/media"), Path("/mnt")]

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".ts", ".mts", ".flv"}


def validate_path(path: str) -> Path:
    """Resolve path and ensure it's under an allowed root. Raises PermissionError if not."""
    resolved = Path(path).resolve()
    for root in ALLOWED_ROOTS:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise PermissionError(f"Path not allowed: {path}")


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS
