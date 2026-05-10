import threading
import time
from typing import Optional

from app.database import get_conn
from app.models import JobStatus


class JobQueue:
    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._cancel_event = threading.Event()
        self._current_job_id: Optional[str] = None

    def start(self) -> None:
        self._restore_interrupted_jobs()
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True, name="job-queue")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._cancel_event.set()

    def _restore_interrupted_jobs(self) -> None:
        """On startup: restore interrupted jobs to a recoverable state.

        Detection-phase jobs (running/detecting) → queued: worker re-runs detection,
        which resumes from checkpoint (ISSUE-09 crash-recovery design).

        Export-phase jobs (exporting) → completed: detection already finished and
        all events are in the DB. Re-queuing would wastefully re-run detection (1–2h
        on a 24h video). Setting to completed lets the user re-trigger export manually
        from the Job Detail page. (CRIT-4 fix)
        """
        conn = get_conn()
        # Jobs interrupted mid-detection → re-queue for detection (with checkpoint resume)
        conn.execute(
            "UPDATE jobs SET status=? WHERE status IN (?,?,?)",
            (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.DETECTING, JobStatus.RUNNING),
        )
        # Jobs interrupted mid-export → revert to completed so user can re-trigger export
        # without re-running detection. Detection output (events table) is intact.
        conn.execute(
            "UPDATE jobs SET status=?, phase=NULL WHERE status=?",
            (JobStatus.COMPLETED, JobStatus.EXPORTING),
        )
        conn.commit()

    def _worker(self) -> None:
        while self._running:
            self._cancel_event.clear()
            job_row = self._pick_next_job()
            if job_row is None:
                time.sleep(2)
                continue

            job_id = job_row["id"]
            self._current_job_id = job_id
            self._run_job(job_id, dict(job_row))
            self._current_job_id = None

    def _pick_next_job(self):
        conn = get_conn()
        row = conn.execute(
            """SELECT * FROM jobs
               WHERE status=?
               AND (scheduled_at IS NULL OR scheduled_at <= datetime('now'))
               ORDER BY created_at LIMIT 1""",
            (JobStatus.QUEUED,),
        ).fetchone()
        return row

    def _run_job(self, job_id: str, job: dict) -> None:
        import json
        from app.core import detection_engine, export_engine, thumbnail_gen
        from app.core.audit_logger import log as audit_log
        from app.core.log_buffer import log_buffer

        conn = get_conn()

        def logger(line: str) -> None:
            log_buffer.append(job_id, line)

        try:
            # Mark running
            conn.execute(
                "UPDATE jobs SET status=?, started_at=datetime('now'), phase='detection', progress=0 WHERE id=?",
                (JobStatus.RUNNING, job_id),
            )
            conn.commit()
            audit_log("DETECTION_STARTED", job["source_name"], job_id=job_id)

            settings = json.loads(job["settings"]) if isinstance(job["settings"], str) else job["settings"]

            # --- Detection phase ---
            conn.execute("UPDATE jobs SET status=? WHERE id=?", (JobStatus.DETECTING, job_id))
            conn.commit()

            detection_engine.run(job_id, job, settings, self._cancel_event, logger)

            if self._cancel_event.is_set():
                conn.execute(
                    "UPDATE jobs SET status=?, finished_at=datetime('now') WHERE id=?",
                    (JobStatus.CANCELLED, job_id),
                )
                conn.commit()
                audit_log("JOB_CANCELLED", "Cancelled by user", job_id=job_id)
                log_buffer.close(job_id)
                return

            audit_log("DETECTION_DONE", job["source_name"], job_id=job_id)

            # --- Thumbnail generation (post-detection) ---
            thumbnail_gen.run(job_id, job["source_path"], logger)

            # --- Export phase (only if output_quality triggers immediate export) ---
            # The export is user-triggered via POST /api/jobs/{id}/export
            # Mark completed after detection + thumbnails
            conn.execute(
                "UPDATE jobs SET status=?, finished_at=datetime('now'), phase=NULL WHERE id=?",
                (JobStatus.COMPLETED, job_id),
            )
            conn.commit()
            audit_log("JOB_COMPLETED", job["source_name"], job_id=job_id)

        except Exception as e:
            conn.execute(
                "UPDATE jobs SET status=?, error_msg=?, finished_at=datetime('now') WHERE id=?",
                (JobStatus.FAILED, str(e), job_id),
            )
            conn.commit()
            from app.core.audit_logger import log as audit_log2
            audit_log2("JOB_FAILED", str(e), level="ERROR", job_id=job_id)
        finally:
            log_buffer.close(job_id)

    def cancel(self, job_id: str) -> None:
        if self._current_job_id == job_id:
            self._cancel_event.set()
        conn = get_conn()
        conn.execute(
            "UPDATE jobs SET status=? WHERE id=? AND status IN (?,?,?,?)",
            (JobStatus.CANCELLED, job_id,
             JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.DETECTING, JobStatus.EXPORTING),
        )
        conn.commit()

    def retry(self, job_id: str) -> bool:
        """Reset a failed job to queued. Returns True if checkpoint exists."""
        from app.config import JOBS_DIR
        checkpoint = JOBS_DIR / job_id / "checkpoint.json"
        has_checkpoint = checkpoint.exists()
        conn = get_conn()
        conn.execute(
            "UPDATE jobs SET status=?, error_msg=NULL, progress=0 WHERE id=? AND status=?",
            (JobStatus.QUEUED, job_id, JobStatus.FAILED),
        )
        conn.commit()
        return has_checkpoint

    def run_export(self, job_id: str) -> None:
        """Trigger export phase for a completed job (called from export API endpoint)."""
        import json
        from app.core import export_engine
        from app.core.audit_logger import log as audit_log
        from app.core.log_buffer import log_buffer

        conn = get_conn()
        job_row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job_row:
            raise ValueError(f"Job {job_id} not found")

        job = dict(job_row)
        settings = json.loads(job["settings"]) if isinstance(job["settings"], str) else job["settings"]

        def logger(line: str) -> None:
            log_buffer.append(job_id, line)

        try:
            conn.execute(
                "UPDATE jobs SET status=?, phase='export', progress=0 WHERE id=?",
                (JobStatus.EXPORTING, job_id),
            )
            conn.commit()
            audit_log("EXPORT_STARTED", job["source_name"], job_id=job_id)

            output_path, output_name, output_size = export_engine.run(
                job_id, job, settings, logger
            )

            # Update jobs table (denormalised convenience fields)
            conn.execute(
                "UPDATE jobs SET status=?, output_path=?, output_name=?, output_size=?, "
                "finished_at=datetime('now'), phase=NULL WHERE id=?",
                (JobStatus.COMPLETED, str(output_path), output_name, output_size, job_id),
            )

            # Insert into exports table (I2 fix — tracks all re-export runs)
            included_events = conn.execute(
                "SELECT id FROM events WHERE job_id=? AND included=1", (job_id,)
            ).fetchall()
            snapshot = json.dumps({"included_event_ids": [r["id"] for r in included_events]})
            conn.execute(
                "INSERT INTO exports (job_id, output_path, output_name, output_size, created_at, settings_snapshot) "
                "VALUES (?, ?, ?, ?, datetime('now'), ?)",
                (job_id, str(output_path), output_name, output_size, snapshot),
            )
            conn.commit()
            audit_log("EXPORT_DONE", f"{output_name} ({output_size} bytes)", job_id=job_id)

        except Exception as e:
            conn.execute(
                "UPDATE jobs SET status=?, error_msg=? WHERE id=?",
                (JobStatus.FAILED, str(e), job_id),
            )
            conn.commit()
            audit_log("EXPORT_FAILED", str(e), level="ERROR", job_id=job_id)
            raise
        finally:
            log_buffer.close(job_id)


job_queue = JobQueue()
