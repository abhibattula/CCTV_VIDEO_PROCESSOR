# API Contracts: RasPi CCTV Analyst — v1 Core Pipeline

**Branch**: `001-raspi-cctv-v1-core` | **Date**: 2026-05-05
**Base URL**: `https://raspberrypi.local:5000/api`
**Auth**: None (LAN-only, no authentication in v1 — see spec § Clarifications Q2)

---

## Jobs

### GET /api/jobs
List all jobs. Supports filtering.

**Query params**: `?status=queued|running|detecting|exporting|completed|failed|cancelled`, `?limit=50`, `?offset=0`

**Response 200**:
```json
{
  "jobs": [
    {
      "id": "uuid4",
      "status": "completed",
      "source_name": "cam1_20260115.mp4",
      "duration_s": 86400,
      "file_size": 22548578304,
      "created_at": "2026-05-05T14:00:00",
      "finished_at": "2026-05-05T16:12:00",
      "phase": null,
      "progress": 1.0,
      "output_name": "cam1_activity_20260505_161200.mp4",
      "output_size": 412847104,
      "event_count": 47,
      "included_count": 43
    }
  ],
  "total": 12,
  "limit": 50,
  "offset": 0
}
```

---

### POST /api/jobs
Create and queue a new job.

**Request body**:
```json
{
  "source_path": "/media/usb0/cam1_20260115.mp4",
  "settings": {
    "sensitivity": "medium",
    "padding_s": 3,
    "min_gap_s": 5,
    "min_event_s": 3,
    "output_quality": "original",
    "output_format": "mp4",
    "output_dir": "/media/usb0/output",
    "frame_skip": 1,
    "hw_decode": false,
    "zones": []
  },
  "scheduled_at": null,
  "recording_start": "2026-01-15T22:00:00Z"
}
```

**Response 201**:
```json
{
  "job_id": "uuid4",
  "status": "queued",
  "warnings": [
    {
      "code": "CODEC_REENCODE_REQUIRED",
      "message": "Source uses MJPEG codec. Export will require re-encoding (~2 hours)."
    },
    {
      "code": "SOURCE_4K_ON_2GB",
      "message": "4K source detected. Processing may be RAM-constrained on 2GB Pi."
    }
  ]
}
```

**Response 400** (disk space insufficient):
```json
{
  "detail": "Insufficient disk space. Need ~46.2GB, only 18.4GB available on /media/usb0."
}
```

**Response 422** (invalid file / unsupported format):
```json
{ "detail": "File is not a valid video or uses an unsupported container." }
```

---

### GET /api/jobs/{job_id}
Full job detail including all events.

**Response 200**:
```json
{
  "job": { "...all Job fields..." },
  "events": [
    {
      "id": 1,
      "event_index": 0,
      "start_s": 192.4,
      "end_s": 227.1,
      "duration_s": 34.7,
      "start_clock": "10:03 PM",
      "end_clock": "10:03 PM",
      "peak_motion_score": 0.087,
      "zone_label": null,
      "tag": null,
      "included": true,
      "thumbnail_path": "/api/thumbnails/uuid4/0.jpg"
    }
  ],
  "event_count": 47,
  "included_count": 43,
  "total_activity_s": 1842,
  "activity_percent": 2.1,
  "estimated_output_size": 412000000
}
```

---

### PUT /api/jobs/{job_id}/events/{event_id}
Toggle event include/exclude or update tag.

**Request body** (partial update — only send fields to change):
```json
{ "included": false, "tag": "False Positive" }
```

**Response 200**:
```json
{ "id": 1, "included": false, "tag": "False Positive" }
```

---

### POST /api/jobs/{job_id}/cancel
Cancel a running or queued job.

**Response 200**: `{ "status": "cancelled" }`
**Response 409**: `{ "detail": "Job is not cancellable in state: completed" }`

---

### POST /api/jobs/{job_id}/retry
Re-queue a failed job (resumes from checkpoint if available).

**Response 200**: `{ "status": "queued", "resumed_from_checkpoint": true }`

---

### DELETE /api/jobs/{job_id}
Soft-delete a job. Marks status as `deleted`.

**Query params**: `?delete_output=true` (also removes output video file from disk)
**Response 200**: `{ "deleted": true, "output_deleted": false }`

---

## Export

### POST /api/jobs/{job_id}/export
Trigger export of currently included events.

**Response 400** (no events included — FR-055):
```json
{ "detail": "No events selected — include at least one event to export." }
```

**Response 200** (export queued):
```json
{ "status": "exporting", "output_name": "cam1_activity_20260505_161200.mp4" }
```

---

## Preview (on-demand clip extraction)

### POST /api/jobs/{job_id}/events/{event_id}/preview
Extract a temp clip for in-browser preview. Returns URL valid for 5 minutes.

**Response 200**:
```json
{
  "preview_url": "/api/previews/tok_abc123.mp4",
  "expires_in_seconds": 300
}
```

**Response 503** (preview already being generated):
```json
{ "detail": "Preview generation in progress. Retry in a few seconds." }
```

---

## Zone Editor Frame (C1 fix — FR-009)

### GET /api/jobs/{job_id}/zone-frame
Extract a single representative frame at 10% into the source video for the detection zone
drawing editor. Returns a JPEG image served as `FileResponse`.

**Query params**: `?width=960&height=540` (optional, defaults to 960×540)

**Response 200**: `image/jpeg` — the extracted frame as a JPEG file.
**Response 404**: Job not found or source file no longer accessible.
**Response 503**: Frame extraction in progress (retry in 2 seconds).

*Implementation*: `ffmpeg -ss {duration * 0.10} -i {source_path} -frames:v 1 -vf scale={w}:{h} /tmp/zone_{job_id}.jpg`
Frame is cached to `/tmp/zone_{job_id}.jpg` and re-served on repeat calls without re-extracting.

---

## File Browser

### GET /api/browse
Browse the Pi filesystem under allowed roots (`/media`, `/mnt`, configured INPUT_DIR).

**Query params**: `?path=/media/usb0`

**Response 200**:
```json
{
  "path": "/media/usb0",
  "parent": "/media",
  "entries": [
    { "name": "cam1_20260115.mp4", "is_dir": false, "size": 22548578304, "mtime": 1736985600, "is_video": true },
    { "name": "archive", "is_dir": true, "size": 0, "mtime": 1736985600, "is_video": false }
  ]
}
```

**Response 403**: `{ "detail": "Path not allowed." }` (path outside whitelist roots)

---

## Chunked Upload

### POST /api/upload/init
Initiate a chunked upload session.

**Request body**: `{ "filename": "footage.mp4", "total_size": 22548578304 }`
**Response 200**: `{ "upload_id": "uuid4", "chunk_size": 1048576 }`

---

### POST /api/upload/chunk
Upload one chunk. Uses `multipart/form-data`. Server uses `Request.stream()` with 65KB buffer.

**Form fields**: `upload_id` (text), `chunk_index` (int), `chunk_data` (file)
**Response 200**: `{ "chunk_index": 0, "received": true }`

---

### POST /api/upload/finalize
Assemble chunks into final file. Triggers disk space check before assembly.

**Request body**: `{ "upload_id": "uuid4", "expected_chunks": 21467 }`
**Response 200**: `{ "source_path": "/data/uploads/uuid4/footage.mp4", "size": 22548578304 }`
**Response 400**: Insufficient disk space or missing chunks.

---

### GET /api/upload/status/{upload_id}
Check which chunks were received (for upload resume after disconnection).

**Response 200**: `{ "received_chunks": [0, 1, 2, 5, 6], "total_expected": 21467 }`

---

## Output File Serving (C2 fix — FR-035)

### GET /api/jobs/{job_id}/output
Serve the most recent exported output video for in-browser preview and download.
Uses HTTP range requests so the HTML5 `<video>` element can seek.

**Response 200**: `video/mp4` via `FileResponse` with `Accept-Ranges: bytes`.
**Response 404**: No export completed yet, or output file deleted.
**Response 410**: Output file path recorded in DB but file no longer exists on disk.

### GET /api/jobs/{job_id}/exports
List all export runs for a job (I2 fix — multiple exports per re-export).

**Response 200**:
```json
{
  "exports": [
    {
      "id": 1,
      "output_name": "cam1_activity_20260505_143022.mp4",
      "output_size": 412847104,
      "created_at": "2026-05-05T14:30:22",
      "included_events": 43
    }
  ]
}
```

---

## SSE (Server-Sent Events)

### GET /api/jobs/{job_id}/stream
Live log stream for a running or recently completed job.

**Response**: `text/event-stream`

```
data: {"type":"log","line":"[00:01:23] Processed frame 900/86400 — 3 events found"}
data: {"type":"progress","phase":"detection","value":0.042}
data: {"type":"system","cpu_percent":87,"ram_percent":61,"temp_c":67.4}
data: {"type":"keepalive"}
data: {"type":"done","status":"completed","event_count":47}
```

- Keepalive sent every 30 seconds (`asyncio.wait_for(queue.get(), timeout=30)`).
- On connect: last 100 log lines replayed immediately from history, then live updates begin.
- On job completion: `type:done` sent, then connection closed by server.
- Header: `X-Accel-Buffering: no` (disables Nginx proxy buffering).

---

## System

### GET /api/system/stats

**Response 200**:
```json
{
  "cpu_percent": 87.3,
  "ram_percent": 61.4,
  "ram_used_mb": 768,
  "ram_total_mb": 1966,
  "temp_c": 67.4,
  "temp_c_history": [[1746460800, 65.1], [1746460810, 67.4]],
  "disk_used_gb": 47.2,
  "disk_total_gb": 238.4,
  "disk_warn": false,
  "uptime_s": 86423,
  "app_version": "1.0.0",
  "ram_mode": "2gb"
}
```

`temp_c`: `null` if `vcgencmd` and `/sys/class/thermal` both unavailable (non-Pi host).

---

## Dashboard

### GET /api/dashboard
Summary for the landing page.

**Response 200**:
```json
{
  "system": { "...same as /api/system/stats..." },
  "recent_jobs": [ "...last 5 jobs (abbreviated)..." ],
  "storage_warning": false,
  "active_job": { "id": "uuid4", "status": "detecting", "progress": 0.42, "source_name": "cam1.mp4" }
}
```

`active_job`: `null` if no job is currently running.

---

## Settings

### GET /api/settings
Returns current global defaults from `config.json`.

### PUT /api/settings
Saves global defaults. Validated via Pydantic before writing.

**Request body**: Same structure as `config.json` (partial updates accepted).
**Response 200**: `{ "saved": true }`
**Response 422**: Validation errors (e.g., `thermal_limit_c` out of 60–90 range).

---

## Reports

### GET /api/reports/{job_id}/analytics
Returns computed analytics for a completed job.

**Response 200**:
```json
{
  "hourly_activity": [
    { "hour": 22, "event_count": 12, "total_duration_s": 340 }
  ],
  "duration_histogram": [
    { "bin": "0-5s", "count": 8 },
    { "bin": "5-15s", "count": 21 }
  ],
  "total_events": 47,
  "included_events": 43,
  "activity_percent": 2.1,
  "peak_hour": 22,
  "longest_event_s": 127.3,
  "avg_event_s": 39.2
}
```

### GET /api/reports/{job_id}/pdf
Generate and serve PDF report. Response: `application/pdf` via `FileResponse`.
Generated to temp file, served from disk — never buffered in RAM via BytesIO.

### GET /api/reports/{job_id}/csv
Generate and serve CSV event log. Response: `text/csv`.

---

## Audit Log

### GET /api/audit

**Query params**: `?level=INFO`, `?actor=user`, `?job_id=uuid4`, `?start=2026-05-01`, `?end=2026-05-05`, `?limit=100`, `?offset=0`

**Response 200**:
```json
{
  "entries": [
    { "id": 1, "ts": "2026-05-05T14:00:01.123456", "level": "INFO", "actor": "user",
      "action": "JOB_SUBMITTED", "detail": "cam1.mp4 (22.5 GB, 86400s)", "job_id": "uuid4" }
  ],
  "total": 847
}
```

---

## Thumbnails & Previews (Static File Serving)

### GET /api/thumbnails/{job_id}/{event_index}.jpg
Serve event thumbnail JPEG. `ETag` header based on `{job_id}-{event_index}`.
Returns 404 if thumbnail not yet generated.

### GET /api/previews/{token}.mp4
Serve on-demand preview clip. Valid for 5 minutes from generation.
Returns 404 if token expired or clip not found.

---

## Error Response Format

All errors use this shape (FastAPI default):
```json
{ "detail": "Human-readable error message" }
```

HTTP status codes used:
- `200` OK
- `201` Created (new job)
- `400` Bad Request (disk space, no events to export)
- `403` Forbidden (file browser path restriction)
- `404` Not Found
- `409` Conflict (cancel on non-cancellable job)
- `422` Unprocessable Entity (validation failure)
- `503` Service Unavailable (preview generation in progress)
