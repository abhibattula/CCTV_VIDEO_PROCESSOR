from datetime import datetime, timezone
from typing import Optional

from app.database import get_conn


def log(
    action: str,
    detail: Optional[str] = None,
    actor: str = "system",
    level: str = "INFO",
    job_id: Optional[str] = None,
) -> None:
    """Append an audit log entry. Thread-safe via thread-local connection."""
    ts = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    conn = get_conn()
    conn.execute(
        "INSERT INTO audit_log (ts, level, actor, action, detail, job_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ts, level, actor, action, detail, job_id),
    )
    conn.commit()
