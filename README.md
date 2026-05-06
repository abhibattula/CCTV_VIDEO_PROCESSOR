# RasPi CCTV Analyst

> **Self-hosted, privacy-first CCTV footage analysis on Raspberry Pi 5.**
> Detects motion events in pre-recorded footage, lets you review a visual timeline, and exports only the relevant clips as a merged MP4 — all on your local network with zero cloud dependency.

---

## What It Does

You plug a USB drive with your CCTV recordings into a Raspberry Pi, open a web page on your phone or laptop, and the Pi finds every moment something moved. You review the results on an interactive timeline, exclude false positives (a cat, wind-blown trees), and export a condensed highlight video in minutes instead of scrubbing through hours of footage manually.

---

## Hardware Requirements

| Component | Required | Notes |
|---|---|---|
| **Board** | Raspberry Pi 5 | Pi 4 (4GB+) also works at reduced speed |
| **RAM** | 2GB minimum | 4GB recommended for comfort |
| **Storage** | USB 3.0 SSD ≥ 50GB free | MicroSD not recommended (too slow for sustained I/O) |
| **Cooling** | Active cooler | Required — long detection jobs will throttle without it |
| **Network** | Same LAN as your viewing device | No internet needed |
| **OS** | Raspberry Pi OS Lite 64-bit | Desktop version works too |

---

## Supported Video Formats

| Container | Extensions | Notes |
|---|---|---|
| MPEG-4 | `.mp4`, `.m4v` | **Preferred** — best compatibility |
| Matroska | `.mkv` | Excellent |
| AVI | `.avi` | Good |
| QuickTime | `.mov` | Good |
| MPEG Transport Stream | `.ts`, `.mts` | Common from IP cameras / NVRs |
| Flash Video | `.flv` | Supported |

### Video Codec Performance

| Codec | Export Mode | Speed |
|---|---|---|
| **H.264 (AVC)** | Stream copy | ⚡ Fastest — under 10 min for 24h footage |
| **H.265 (HEVC)** | Stream copy | ⚡ Fast |
| **MPEG-2** | Stream copy | ⚡ Fast |
| **MPEG-4 Part 2** | Stream copy | ⚡ Fast |
| MJPEG | Re-encode required | 🐢 Slow — 1–2 hours for 24h footage |
| VP9 / AV1 | Re-encode required | 🐢 Slow |

**Recommendation**: Use H.264 MP4 recordings from your cameras whenever possible. Most modern IP cameras default to H.264 which gives the fastest export.

---

## Quick Install (Raspberry Pi)

```bash
git clone https://github.com/yourname/raspi-cctv-analyst.git
cd raspi-cctv-analyst
bash install.sh
```

The installer handles everything: system packages, Python virtual environment, TLS certificate, database setup, and systemd service registration.

After completion you'll see:
```
Dashboard: https://raspberrypi.local:5000
RAM mode detected: 2gb
```

Open that URL on any device on your network. Accept the certificate warning once (it is a self-signed cert — completely safe on your home/office LAN).

---

## Development / Non-Pi Setup

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 5000
```

Then open `http://localhost:5000`.

> **Note**: PWA install and service worker require HTTPS. For development on localhost this is fine; for LAN access run `install.sh` to generate the self-signed TLS certificate.

---

## Docker

```bash
docker-compose up
```

The container mounts your `/media` directory read-only so videos on USB drives are accessible. Data and outputs are persisted in `./data` and `./outputs`.

---

## Performance Benchmarks (Pi 5 2GB)

| Source | Duration | Detection Time | Export Time (H.264) |
|---|---|---|---|
| 1080p H.264 | 1 hour | 5–8 min | < 30 sec |
| 1080p H.264 | 8 hours | 40–65 min | 2–3 min |
| 1080p H.264 | 24 hours | 2–2.5 hours | < 10 min |
| 1080p MJPEG | 24 hours | 2–2.5 hours | 1–2 hours (re-encode) |

Detection runs at 320×240 internally (not the full resolution) — this is intentional to stay within the 1400MB RAM ceiling. Timestamps and export quality are full resolution.

---

## PWA Installation (Install as an App)

**Android (Chrome)**: Tap ⋮ → Add to Home Screen → Install  
**Desktop (Chrome)**: Click the install icon in the address bar → Install  
**iOS (Safari)**: Tap Share → Add to Home Screen → Add

Once installed, the app opens in its own window (no browser toolbar) and shows an offline message when the Pi is unreachable instead of a browser error page.

---

## Project Structure

```
raspi-cctv-analyst/
├── app/                    # Python backend
│   ├── main.py             # FastAPI entry point
│   ├── config.py           # Hardware-adaptive constants
│   ├── database.py         # SQLite WAL, thread-local connections
│   ├── models.py           # Job, Event, AuditEntry dataclasses
│   ├── api/                # REST + SSE endpoints (11 modules)
│   ├── core/               # Background engines (detection, export, etc.)
│   └── utils/              # ffprobe, system stats, file validation
├── static/
│   ├── css/                # Design system (base, layout, components)
│   ├── js/                 # Client-side router + ES module pages
│   ├── pages/              # 8 HTML page shells
│   ├── manifest.json       # PWA manifest
│   └── sw.js               # Service worker
├── data/                   # Runtime data (jobs, uploads, previews)
├── outputs/                # Exported merged videos
├── ssl/                    # TLS certificate (generated by install.sh)
├── requirements.txt
├── install.sh              # One-command Pi installer
├── cctv-analyst.service    # systemd unit file
├── Dockerfile
├── docker-compose.yml
├── ARCHITECTURE.md         # Developer reference
└── USER_MANUAL.md          # End-user guide
```

---

## Architecture Overview

```
Browser (PWA)  ←──HTTPS/SSE──→  FastAPI (uvicorn, 1 worker)
                                        │
                                  SQLite WAL DB
                                  (jobs, events, exports, audit_log)
                                        │
                              Background Worker Thread
                              ├── Detection Engine  (OpenCV MOG2 + FFmpeg pipe)
                              ├── Export Engine     (FFmpeg concat + chapters)
                              └── Thumbnail Gen     (FFmpeg frame extract)
```

For the full technical deep-dive, see [ARCHITECTURE.md](ARCHITECTURE.md).  
For step-by-step usage instructions, see [USER_MANUAL.md](USER_MANUAL.md).

---

## Success Criteria

| Criterion | Target | How to verify |
|---|---|---|
| SC-001 | 24h 1080p detected in ≤ 2.5h | Submit 24h file; check job duration in History |
| SC-002 | Export completes in ≤ 10 min | Check time from "Export Started" to "Export Done" in log |
| SC-003 | Timestamps accurate to ±1s | Compare event start clock time to source video at that offset |
| SC-004 | Timeline responsive with 200+ events | Submit high-sensitivity job on busy footage; verify scroll speed |
| SC-005 | Dashboard loads in ≤ 2s | Cold-load dashboard; measure in browser DevTools Network tab |
| SC-006 | Crash recovery resumes within 1–2s | Restart service mid-detection; verify log shows "Resumed from checkpoint" |
| SC-007 | RAM stays ≤ 1400MB throughout | `systemctl status cctv-analyst | grep Memory` during 24h job |
| SC-008 | PWA opens from home screen in ≤ 5s | Time from tap to app ready on phone |
| SC-009 | False positive rate < 5% at Medium | Review Medium-sensitivity job on typical outdoor footage |
| SC-010 | History survives Pi reboot | Reboot Pi; verify past jobs appear in Job Queue page |

---

## FAQ

**"Your connection is not private"** — Click Advanced → Proceed to raspberrypi.local. This warning appears because the TLS certificate is self-signed (not issued by a public CA). It is completely safe on your own LAN. You only see it once per device.

**Detection is very slow** — Check the System page. If temperature exceeds 75°C, detection is being thermal-throttled. Improve airflow around the Pi or add a heatsink. Detection automatically resumes when the Pi cools — you do not need to restart anything.

**Export takes hours** — Your camera records in MJPEG or another codec that requires re-encoding. The amber warning at job submission tells you this upfront. Consider changing your camera's recording codec to H.264 if possible.

**"Insufficient disk space" at job submission** — The Pi needs roughly 2× the source file size free during processing. Free up space on the USB drive and resubmit.

**Temperature shows "N/A"** — Expected when running on a non-Pi host (development laptop, Docker on x86). All other features work normally.

**Job stuck on "Queued"** — Only one job runs at a time. If another job is running, yours waits. Check the active job on the Dashboard.

**I restarted the Pi mid-detection** — The job automatically resumes from its last checkpoint when the service starts back up. Open the job in the dashboard and watch the log panel.

---

## Roadmap

| Version | Features |
|---|---|
| **v1 (current)** | Core pipeline: detect → review → export; 8-page PWA dashboard; crash recovery; chunked upload |
| v1.5 | RTSP live stream snapshot; YOLOv8n object classification (Person/Vehicle/Animal) |
| v2 | Multi-camera scheduling; push notifications (Telegram/email); RTSP motion alerts |
| v3 | Multi-Pi cluster; privacy blur zones; long-term activity heatmaps |

---

## License

MIT — see LICENSE file.
