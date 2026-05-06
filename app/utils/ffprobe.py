import json
import subprocess
from typing import Optional


def probe(source_path: str) -> dict:
    """Run ffprobe and return typed metadata dict. Raises ValueError on bad input."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        source_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        raise RuntimeError("ffprobe not found — install FFmpeg")

    if result.returncode != 0:
        raise ValueError(f"ffprobe failed: {result.stderr.strip()}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise ValueError("ffprobe returned invalid JSON")

    streams = data.get("streams", [])
    fmt = data.get("format", {})

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("No video stream found in file")

    # avg_frame_rate as fraction string e.g. "25/1" — NOT r_frame_rate (ISSUE-02)
    avg_fps_str = video.get("avg_frame_rate", "0/1")
    try:
        num, den = avg_fps_str.split("/")
        avg_frame_rate = float(num) / float(den) if float(den) != 0 else 0.0
    except (ValueError, ZeroDivisionError):
        avg_frame_rate = 0.0

    duration_s: float = float(fmt.get("duration") or video.get("duration") or 0)
    width: int = int(video.get("width", 0))
    height: int = int(video.get("height", 0))
    codec_name: str = video.get("codec_name", "").lower()

    has_audio: bool = any(
        s.get("codec_type") == "audio" for s in streams
    )

    from app.config import STREAM_COPY_SAFE
    needs_reencode: bool = codec_name not in STREAM_COPY_SAFE  # ISSUE-13

    # NVR cameras embed creation_time in format tags (A1 fix, FR-020)
    tags = fmt.get("tags", {})
    recording_start: Optional[str] = (
        tags.get("creation_time") or tags.get("Creation_time")
    )

    return {
        "duration_s": duration_s,
        "avg_frame_rate": avg_frame_rate,
        "width": width,
        "height": height,
        "codec_name": codec_name,
        "has_audio": has_audio,
        "needs_reencode": needs_reencode,
        "recording_start": recording_start,
    }
