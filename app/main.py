import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import (
    RAM_MODE, DATA_DIR, JOBS_DIR, UPLOAD_DIR, PREVIEW_DIR, OUTPUTS_DIR,
)
from app.database import init_db

_BASE = Path(__file__).parent.parent


async def _preview_cleanup_loop() -> None:
    """Delete preview clips older than 300 seconds, every 60 seconds (A5 fix)."""
    while True:
        await asyncio.sleep(60)
        try:
            now = time.time()
            for f in PREVIEW_DIR.glob("*.mp4"):
                if now - f.stat().st_mtime > 300:
                    f.unlink(missing_ok=True)
        except Exception:
            pass


def _serve_page(filename: str):
    """Return a route handler that serves the given static HTML page."""
    def handler():
        page_path = _BASE / "static" / "pages" / filename
        if page_path.exists():
            return FileResponse(str(page_path), media_type="text/html")
        return HTMLResponse("<h1>Page not found</h1>", status_code=404)
    return handler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    for d in [DATA_DIR, JOBS_DIR, UPLOAD_DIR, PREVIEW_DIR, OUTPUTS_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    init_db()

    from app.core.log_buffer import log_buffer
    log_buffer.set_loop(asyncio.get_running_loop())  # get_event_loop() deprecated in Python 3.10+

    from app.core.job_queue import job_queue
    job_queue.start()

    asyncio.create_task(_preview_cleanup_loop())

    yield

    # Shutdown
    job_queue.stop()


def create_app() -> FastAPI:
    application = FastAPI(title="RasPi CCTV Analyst", version="1.0.0", lifespan=lifespan)

    # --- API routers (registered BEFORE static files) ---
    from app.api.jobs import router as jobs_router
    from app.api.export import router as export_router
    from app.api.filebrowser import router as browser_router
    from app.api.upload import router as upload_router
    from app.api.thumbnails import router as thumbnails_router
    from app.api.sse import router as sse_router
    from app.api.system import router as system_router
    from app.api.dashboard import router as dashboard_router
    from app.api.settings import router as settings_router
    from app.api.audit import router as audit_router
    from app.api.reports import router as reports_router

    application.include_router(jobs_router, prefix="/api")
    application.include_router(export_router, prefix="/api")
    application.include_router(browser_router, prefix="/api")
    application.include_router(upload_router, prefix="/api")
    application.include_router(thumbnails_router, prefix="/api")
    application.include_router(sse_router, prefix="/api")
    application.include_router(system_router, prefix="/api")
    application.include_router(dashboard_router, prefix="/api")
    application.include_router(settings_router, prefix="/api")
    application.include_router(audit_router, prefix="/api")
    application.include_router(reports_router, prefix="/api")

    # --- Health check ---
    @application.get("/api/health")
    def health():
        return {"status": "ok", "ram_mode": RAM_MODE}

    # --- 8 page routes (all explicit — A4 fix) ---
    application.get("/")(lambda: FileResponse(str(_BASE / "static" / "pages" / "index.html")))
    application.get("/jobs/new")(lambda: FileResponse(str(_BASE / "static" / "pages" / "new-job.html")))
    application.get("/jobs")(lambda: FileResponse(str(_BASE / "static" / "pages" / "jobs.html")))
    application.get("/jobs/{job_id}")(lambda job_id: FileResponse(str(_BASE / "static" / "pages" / "job-detail.html")))
    application.get("/reports")(lambda: FileResponse(str(_BASE / "static" / "pages" / "reports.html")))
    application.get("/settings")(lambda: FileResponse(str(_BASE / "static" / "pages" / "settings.html")))
    application.get("/system")(lambda: FileResponse(str(_BASE / "static" / "pages" / "system.html")))
    application.get("/audit")(lambda: FileResponse(str(_BASE / "static" / "pages" / "audit.html")))

    # --- Static files (mounted LAST — lower priority than API routes) ---
    static_dir = _BASE / "static"
    if static_dir.exists():
        application.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return application


app = create_app()
