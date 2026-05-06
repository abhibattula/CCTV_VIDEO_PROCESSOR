"""Analytics computation over a completed job's events."""
import math
from typing import Optional

from app.database import get_conn


def compute(job_id: str) -> dict:
    conn = get_conn()

    job_row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job_row:
        raise ValueError(f"Job {job_id} not found")

    source_duration_s = float(job_row["duration_s"] or 0)
    events = conn.execute(
        "SELECT * FROM events WHERE job_id=? ORDER BY start_s", (job_id,)
    ).fetchall()

    total_events = len(events)
    included = [e for e in events if e["included"]]
    included_events = len(included)

    if total_events == 0:
        return {
            "hourly_activity": [],
            "duration_histogram": [],
            "total_events": 0,
            "included_events": 0,
            "activity_percent": 0.0,
            "peak_hour": None,
            "longest_event_s": 0.0,
            "avg_event_s": 0.0,
        }

    # Hourly activity (based on start_s)
    hourly: dict[int, dict] = {}
    for ev in included:
        hour = int(float(ev["start_s"]) // 3600)
        if hour not in hourly:
            hourly[hour] = {"hour": hour, "event_count": 0, "total_duration_s": 0.0}
        hourly[hour]["event_count"] += 1
        hourly[hour]["total_duration_s"] += float(ev["duration_s"] or 0)

    hourly_activity = sorted(hourly.values(), key=lambda x: x["hour"])

    # Peak hour
    peak_hour: Optional[int] = None
    if hourly_activity:
        peak_hour = max(hourly_activity, key=lambda x: x["event_count"])["hour"]

    # Duration histogram
    bins = [
        ("0-5s", 0, 5),
        ("5-15s", 5, 15),
        ("15-30s", 15, 30),
        ("30-60s", 30, 60),
        ("60s+", 60, float("inf")),
    ]
    histogram = []
    for label, lo, hi in bins:
        count = sum(
            1 for ev in included
            if lo <= float(ev["duration_s"] or 0) < hi
        )
        histogram.append({"bin": label, "count": count})

    # Activity percent
    total_included_s = sum(float(ev["duration_s"] or 0) for ev in included)
    activity_percent = (total_included_s / source_duration_s * 100) if source_duration_s else 0.0

    durations = [float(ev["duration_s"] or 0) for ev in included]
    longest = max(durations) if durations else 0.0
    avg = (sum(durations) / len(durations)) if durations else 0.0

    return {
        "hourly_activity": hourly_activity,
        "duration_histogram": histogram,
        "total_events": total_events,
        "included_events": included_events,
        "activity_percent": round(activity_percent, 2),
        "peak_hour": peak_hour,
        "longest_event_s": round(longest, 1),
        "avg_event_s": round(avg, 1),
    }
