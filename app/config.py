import psutil
from pathlib import Path

_total_gb = psutil.virtual_memory().total / 1e9
RAM_MODE: str = "2gb" if _total_gb < 3.0 else "4gb"

# Detection constants (2GB-safe values)
DETECT_WIDTH: int = 320
DETECT_HEIGHT: int = 240
BATCH_SIZE: int = 30
FFMPEG_THREADS: int = 2
THUMB_CACHE_SIZE: int = 50
ENABLE_YOLO: bool = False
LOG_RING_SIZE: int = 2000
CHUNK_SIZE: int = 1_048_576  # 1 MB
RAM_GUARD_PERCENT: int = 75
THERMAL_LIMIT_C: int = 80

# Paths
_BASE = Path(__file__).parent.parent
DATA_DIR: Path = _BASE / "data"
JOBS_DIR: Path = DATA_DIR / "jobs"
UPLOAD_DIR: Path = DATA_DIR / "uploads"
PREVIEW_DIR: Path = DATA_DIR / "previews"
OUTPUTS_DIR: Path = _BASE / "outputs"

STREAM_COPY_SAFE = {"h264", "hevc", "mpeg2video", "mpeg4"}
