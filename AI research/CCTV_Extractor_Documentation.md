# CCTV Activity Extractor — Project Documentation

## Overview

CCTV Activity Extractor is a self-hosted, privacy-first video analysis tool designed to run on a Raspberry Pi 5. It ingests long-duration CCTV recordings (up to 24 hours), automatically detects all segments containing activity, and compiles only those segments into a single condensed output video — reducing hours of footage down to minutes of relevant content for fast human review.

The system runs entirely on-device. No video data is sent to the cloud. The user interacts through a local web dashboard accessible from any browser on the same network at `http://raspberrypi.local:5000`.

---

## Target Hardware

| Component | Minimum | Recommended |
|---|---|---|
| **Device** | Raspberry Pi 5 (2 GB RAM) | Raspberry Pi 5 (4 GB RAM) |
| **Storage** | 64 GB microSD | 256 GB USB 3.0 SSD |
| **OS** | Raspberry Pi OS Lite (64-bit) | Raspberry Pi OS Lite (64-bit) |
| **Power** | Official 27W USB-C PSU | Official 27W USB-C PSU |
| **Cooling** | Active cooler recommended | Active cooler required |

The system automatically detects available RAM at startup and adjusts processing parameters accordingly — no manual configuration needed when switching between the 2 GB and 4 GB Pi variants.

---

## Installation

### Prerequisites

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ffmpeg python3-pip python3-venv git
```

### Clone & Setup

```bash
git clone https://github.com/yourname/cctv-extractor.git
cd cctv-extractor
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Start the Server

```bash
python app.py
```

The dashboard is now accessible at `http://raspberrypi.local:5000` from any device on the same network.

### Auto-Start on Boot (Optional)

```bash
sudo cp cctv-extractor.service /etc/systemd/system/
sudo systemctl enable cctv-extractor
sudo systemctl start cctv-extractor
```

---

## Supported Video Formats

The system accepts all major video container and codec formats via FFmpeg:

| Container | Codecs Supported |
|---|---|
| MP4 | H.264, H.265/HEVC, MPEG-4 |
| MKV | H.264, H.265, VP8, VP9 |
| AVI | MPEG-4, DivX, Xvid, MJPEG |
| MOV | H.264, ProRes, MJPEG |
| TS / MTS | H.264, H.265 (common NVR format) |
| FLV | H.264, Sorenson Spark |

Mixed-format batch jobs (e.g., `.ts` and `.mp4` from different cameras) are handled automatically with a re-encode normalization pass before concatenation.

---

## User Workflow

### Step 1 — Job Setup

The user opens the dashboard and is presented with the **New Job** screen. From here:

1. **Upload or path-select** the source video file (drag-and-drop supported)
2. **Choose a Detection Sensitivity** using a plain-language slider:
   - *Low* — only large, clear movements (vehicles, multiple people)
   - *Medium* — default; persons, pets, door activity
   - *High* — subtle changes; small animals, distant movement, flickering
3. **Set Clip Padding** — how many seconds to include before and after detected motion (default: 3 seconds)
4. **Set Minimum Gap** — if two events are within this many seconds, merge them into one clip (default: 5 seconds)
5. **Select Output Format** — MP4 (default), MKV
6. **Choose Output Quality**:
   - *Original Quality* — stream copy, no re-encode, fastest
   - *Compressed 720p* — re-encode to H.264 720p
   - *Small File 480p* — re-encode to H.264 480p
7. **Draw Detection Zones** (optional) — click "Set Zone" to open a frame from the video and draw polygon regions. Only motion inside drawn zones will trigger detection.
8. Click **Start Analysis**

### Step 2 — Processing

The system runs two sequential phases, shown live on the **Processing Screen**:

#### Phase 1: Activity Analysis
- The source video is decoded frame-by-frame at reduced resolution (480p) to conserve RAM
- OpenCV's MOG2 background subtractor scans each frame for foreground activity
- On 4 GB RAM, a lightweight YOLOv8n model additionally classifies detected objects (Person, Vehicle, Animal, Unknown)
- All activity windows are written to a `timeline.json` sidecar file in real time

The dashboard displays live:
- Current timestamp being analyzed
- Frames processed per second
- Number of activity events detected so far
- System health: CPU %, RAM usage, Pi temperature
- Estimated time remaining

#### Phase 2: Clip Extraction & Merge
- FFmpeg seeks to each activity timestamp in the source file using hardware-accelerated decode where available (`h264_v4l2m2m` on Pi 5)
- Clips are extracted at **full original resolution**, regardless of the lower-resolution detection pass
- All clips are concatenated into a single output file using the FFmpeg concat demuxer
- A `concat.txt` manifest file is written before the merge for transparency and reuse

Both phases can be cancelled at any time. Partial results and the `timeline.json` are preserved so re-runs can skip Phase 1.

### Step 3 — Timeline Review

After analysis completes, the user is taken to the **Timeline Review Screen** — the core feature of the application.

#### Visual Timeline Strip
A horizontal bar represents the full duration of the source video (e.g., 0:00 → 24:00). Activity segments are shown as colored blocks:
- **Green** — activity detected; included in export
- **Gray** — silence; excluded
- **Orange** — flagged event (person detected in a high-alert time window, e.g., midnight–6 AM)

Clicking any segment highlights it and shows:
- A **thumbnail strip** of keyframes from that event
- Object labels detected (if YOLOv8n was active)
- Zone name (if zone detection was configured)
- Timestamp, duration, and detection confidence score

#### Manual Editing Controls
- **Drag segment handles** to expand or shrink a clip's in/out points
- **Delete** a segment to exclude it from export (false positive rejection)
- **Add Segment** — click and drag on the timeline to manually define a new clip window
- **Merge adjacent segments** with one click
- **Tag a segment** — label it: Person, Vehicle, Animal, False Positive, Review Required

#### Summary Bar
Displayed above the timeline at all times:
- Total source duration
- Total activity duration
- Activity percentage
- Estimated output file size
- Number of events, number excluded

### Step 4 — Export

Once the review is complete, the user clicks **Export Selected Clips**.

Export options:
- **Output filename** — editable, defaults to `[source_name]_activity_[date].mp4`
- **Destination path** — local folder, mounted USB drive, or NAS share
- **Burn-in Annotations** toggle — overlays timestamps and object labels onto output frames
- **Export Timeline JSON** — saves `timeline.json` alongside the video for archival
- **Export Contact Sheet** — generates a single JPEG mosaic of one keyframe per event

A final progress bar tracks the FFmpeg merge. When done, the user receives:
- A confirmation card showing output file path, size, and compression ratio
- A "Play" button to preview the output in the browser (via HTML5 video player)
- Optional: send a Telegram/email notification with the summary

### Step 5 — History

All past jobs are listed in the **History** screen:

| Column | Description |
|---|---|
| Date | When the job was run |
| Source File | Original filename |
| Duration | Source video length |
| Activity | Total activity duration and % |
| Output | Output filename and size |
| Actions | Reopen timeline, re-export, delete |

Reopening a past job loads the saved `timeline.json` and allows re-export with different segments or settings — without re-running the analysis phase.

---

## Settings

All settings are persisted to `config.json` and applied across all future jobs unless overridden per-job.

| Setting | Default | Description |
|---|---|---|
| Default Output Folder | `~/cctv_output/` | Where exported videos are saved |
| Default Sensitivity | Medium | Detection threshold |
| Default Clip Padding | 3 seconds | Pre/post buffer on each clip |
| Default Min Gap | 5 seconds | Gap threshold for merging clips |
| Thumbnail Resolution | 320×180 | Size of timeline thumbnail previews |
| Hardware Decode | Auto | Use VideoCore VII acceleration when available |
| Object Classification | On (4 GB), Off (2 GB) | YOLOv8n object labeling |
| Thermal Limit | 80°C | Pause processing above this temperature |
| Dark Mode | System Default | UI theme preference |
| Notifications | Off | Telegram bot token and chat ID |
| Watch Folder | Disabled | Path to auto-process incoming files |

---

## RAM-Adaptive Behavior

The system calls `psutil.virtual_memory().total` at startup and configures itself automatically:

| Parameter | 2 GB Mode | 4 GB Mode |
|---|---|---|
| Detection resolution | 320×240 | 640×480 |
| Frame batch size | 30 frames | 120 frames |
| Object classification | Disabled | YOLOv8n enabled |
| FFmpeg threads | 2 | 4 |
| Concurrent operations | Sequential | Decode + detect in parallel |
| Thumbnail cache size | 50 thumbnails | 200 thumbnails |

---

## CLI Mode

For headless or scripted use, all functionality is available via command line:

```bash
python extractor.py \
  --input /path/to/footage.mp4 \
  --output /path/to/digest.mp4 \
  --sensitivity medium \
  --padding 3 \
  --min-gap 5 \
  --timeline timeline.json \
  --annotate \
  --notify telegram
```

| Flag | Type | Description |
|---|---|---|
| `--input` | path | Source video file |
| `--output` | path | Output merged video file |
| `--sensitivity` | low/medium/high | Detection threshold |
| `--padding` | integer | Seconds to pad each clip |
| `--min-gap` | integer | Seconds gap before splitting clips |
| `--timeline` | path | Path to save/load JSON timeline |
| `--zones` | path | JSON file defining detection polygon zones |
| `--annotate` | flag | Burn timestamps and labels onto output |
| `--no-classify` | flag | Disable object classification |
| `--notify` | telegram/email/none | Post-completion notification channel |
| `--dry-run` | flag | Run detection only, no video export |

Batch processing a folder:

```bash
python extractor.py --batch /path/to/folder/ --output /path/to/output/ --sensitivity medium
```

---

## Output Files

For each processed job, the following files are produced:

```
cctv_output/
├── footage_activity_2026-05-04.mp4       ← merged activity video
├── footage_activity_2026-05-04.json      ← timeline sidecar (all event timestamps)
├── footage_activity_2026-05-04_sheet.jpg ← keyframe contact sheet (optional)
└── footage_activity_2026-05-04_report.html ← analytics report (optional)
```

### Timeline JSON Schema

```json
{
  "source": "footage.mp4",
  "processed_at": "2026-05-04T22:30:00",
  "source_duration_seconds": 86400,
  "total_activity_seconds": 1842,
  "activity_percent": 2.1,
  "ram_mode": "2gb",
  "events": [
    {
      "id": 1,
      "start": "00:03:12",
      "end": "00:03:47",
      "duration_seconds": 35,
      "zone": "Front Door",
      "objects_detected": ["Person"],
      "confidence": 0.87,
      "flagged": false,
      "tag": "Person",
      "included_in_export": true
    }
  ]
}
```

---

## Feature Roadmap

### v1.0 — Core Pipeline
- [x] Video ingestion (all major formats via FFmpeg)
- [x] MOG2 motion detection with configurable sensitivity
- [x] Timeline JSON export
- [x] FFmpeg clip extraction and concatenation
- [x] Web dashboard (Job Setup, Processing, Timeline Review, Export, History)
- [x] RAM-adaptive processing (2 GB / 4 GB modes)
- [x] CLI mode
- [x] Dark/light theme

### v1.5 — Intelligence Layer
- [ ] YOLOv8n object classification (Person, Vehicle, Animal)
- [ ] Detection zone drawing tool
- [ ] Exclusion zones
- [ ] Thumbnail contact sheet export
- [ ] Annotated video output (burn-in timestamps and labels)
- [ ] False positive tagging and exclusion

### v2.0 — Analytics & Automation
- [ ] Activity heatmap overlay
- [ ] Hourly activity bar chart
- [ ] PDF/HTML report export
- [ ] Telegram and email notifications
- [ ] Batch folder processing
- [ ] Watch folder auto-processing mode
- [ ] Scheduled nightly jobs via cron integration

### v2.5 — Advanced Detection
- [ ] Virtual tripwire (directional line crossing)
- [ ] Loitering detection (object in zone > N seconds)
- [ ] People counter with hourly graph
- [ ] Audio peak detection (flag clips with sound events)
- [ ] Night vision enhancement (CLAHE preprocessing)

### v3.0 — Multi-Camera & Privacy
- [ ] Multi-camera job grouping
- [ ] Cross-camera event correlation
- [ ] Camera profile presets
- [ ] Face blurring mode
- [ ] License plate redaction
- [ ] Password-protected dashboard
- [ ] Audit log

---

## Technology Stack

| Component | Technology |
|---|---|
| Backend | Python 3.11, FastAPI |
| Motion Detection | OpenCV (MOG2 background subtractor) |
| Object Classification | YOLOv8n (Ultralytics, 4 GB mode only) |
| Video Processing | FFmpeg via `ffmpeg-python` |
| RAM Detection | `psutil` |
| Frontend | HTML5 + Vanilla JS + CSS (no framework dependency) |
| Video Preview | HTML5 `<video>` element |
| Progress Streaming | Server-Sent Events (SSE) |
| Data Persistence | JSON flat files (no database required) |
| System Monitoring | `psutil`, `subprocess` (vcgencmd for Pi temp) |
| Notifications | `python-telegram-bot`, `smtplib` |

The flat-file JSON approach (no SQLite, no PostgreSQL) keeps the stack simple and portable — the entire application state is human-readable and can be backed up with a single `cp` command.

---

## Performance Reference

These are approximate benchmarks on a Raspberry Pi 5 running from a USB 3.0 SSD:

| Source Video | RAM Mode | Detection Time | Export Time | Total |
|---|---|---|---|---|
| 1 hour, 1080p H.264 @ 2 Mbps | 2 GB | ~5 min | ~1 min | ~6 min |
| 1 hour, 1080p H.264 @ 2 Mbps | 4 GB | ~3 min | ~1 min | ~4 min |
| 24 hours, 1080p H.264 @ 2 Mbps | 2 GB | ~2 hrs | ~5 min | ~2.1 hrs |
| 24 hours, 1080p H.264 @ 2 Mbps | 4 GB | ~1.2 hrs | ~5 min | ~1.3 hrs |
| 24 hours, 720p H.264 @ 1 Mbps | 2 GB | ~1 hr | ~3 min | ~1.1 hrs |

Export time uses `-c copy` (no re-encode). Re-encode passes (Compressed/Small output modes) add 30–120 minutes depending on source length. Hardware-accelerated decode reduces detection time by approximately 20–30% when enabled.

---

## Limitations

- **Not real-time**: This tool is a batch processor for pre-recorded footage, not a live monitoring system. For live feeds, consider Frigate NVR as a companion tool.
- **No onboard display required**: Designed to run headless. All interaction is via the browser dashboard.
- **Single user**: No multi-user authentication in v1.0. The dashboard is intended for personal/small-team use on a trusted local network.
- **Object classification accuracy**: YOLOv8n is a lightweight model optimized for speed on constrained hardware. Accuracy on low-resolution or night-vision CCTV footage may be lower than on high-quality video.
- **Storage dependency**: A 24-hour 1080p recording at 2 Mbps requires approximately 21 GB of free disk space. An SSD is strongly recommended over a microSD card for both speed and longevity.

---

## License

MIT License. Free for personal and commercial use.

