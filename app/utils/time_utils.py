import re
from datetime import datetime, timezone, timedelta
from typing import Optional


def seconds_to_clock(s: float, recording_start: Optional[str] = None) -> str:
    """Convert seconds offset to human-readable clock time.

    If recording_start (ISO 8601 UTC) is provided, return absolute clock time (e.g. "10:03 PM").
    Otherwise return HH:MM:SS offset format.
    """
    if recording_start:
        try:
            base = datetime.fromisoformat(
                recording_start.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            wall = base + timedelta(seconds=s)
            return wall.strftime("%I:%M %p").lstrip("0")  # "10:03 PM"
        except (ValueError, AttributeError):
            pass
    # Fallback: elapsed HH:MM:SS
    total = int(s)
    h, rem = divmod(total, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


_PTS_RE = re.compile(r"pts_time:(\d+(?:\.\d+)?)")


def parse_pts_time(ffmpeg_stderr_line: str) -> Optional[float]:
    """Extract pts_time from FFmpeg showinfo filter stderr line (ISSUE-02)."""
    m = _PTS_RE.search(ffmpeg_stderr_line)
    return float(m.group(1)) if m else None
