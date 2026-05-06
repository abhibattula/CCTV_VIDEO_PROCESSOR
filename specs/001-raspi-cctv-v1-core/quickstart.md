# Quickstart Guide: RasPi CCTV Analyst — v1 Core Pipeline

**Branch**: `001-raspi-cctv-v1-core` | **Date**: 2026-05-05
**Purpose**: End-to-end validation of the v1 implementation on target hardware.

---

## Prerequisites

- Raspberry Pi 5 (2GB RAM) running Raspberry Pi OS Lite 64-bit
- USB 3.0 SSD with ≥50GB free (microSD not recommended for sustained detection)
- Active cooler installed on Pi (required during long detection jobs)
- A test CCTV video file (minimum 5 minutes of footage with some motion)
- A device on the same LAN (phone, tablet, or laptop) with Chrome 110+ or Firefox 115+

---

## Step 1: Install on the Pi

SSH into the Pi, then:

```bash
git clone https://github.com/yourname/raspi-cctv-analyst.git
cd raspi-cctv-analyst
bash install.sh
```

The installer will:
1. Install system packages (`ffmpeg`, `python3-venv`, `libopencv-dev`)
2. Create a Python virtual environment and install all dependencies
3. Generate a self-signed TLS certificate in `ssl/` (valid for 10 years)
4. Initialise the SQLite database
5. Install and enable the systemd service
6. Print the dashboard URL

```
Installation complete.
Dashboard: https://raspberrypi.local:5000
RAM mode detected: 2gb
```

---

## Step 2: Accept the Certificate (Once Per Device)

On each device you want to use:

1. Open Chrome (or Firefox) and navigate to `https://raspberrypi.local:5000`
2. Chrome shows "Your connection is not private" — click **Advanced** → **Proceed to raspberrypi.local**
3. Firefox shows "Warning: Potential Security Risk" — click **Advanced** → **Accept the Risk**
4. You will not see this warning again on this device.

---

## Step 3: Install as a PWA (Optional but Recommended)

**Android (Chrome)**:
- Tap the three-dot menu → **Add to Home Screen** → **Install**
- The app opens without browser chrome. Tap "CCTV Analyst" from your home screen.

**Desktop (Chrome)**:
- Click the install icon in the address bar (right side) → **Install**
- The app opens in its own window.

**iOS (Safari)**:
- Tap the Share icon → **Add to Home Screen** → **Add**

---

## Step 4: Submit Your First Job

1. Open the dashboard. You should see the system status (CPU temp, RAM %, disk %).
2. Click **New Analysis Job**.
3. Choose your video source:
   - **File Path tab**: Click **Browse**, navigate to your USB drive, select the video file.
   - **Upload tab**: Drag your video file into the upload zone.
4. Set detection sensitivity to **Medium** (default).
5. Leave all other settings at defaults.
6. Click **Start Analysis**.

You are redirected to the Job Queue. Your job appears as **Queued**, then transitions to **Running** within 60 seconds.

---

## Step 5: Monitor Detection Progress

Click the job row to open the **Job Detail** page. You will see:

- **Live log panel** (bottom): streaming log lines showing frames processed, events found
- **Progress bar**: percentage of source video analysed
- **System gauges**: CPU %, RAM %, temperature — all updating every 10 seconds
- **Estimated time remaining**

For a 1-hour 1080p test file, detection should complete in ~5-8 minutes on 2GB Pi.

**Thermal check**: If the Pi temperature reaches 80°C, detection pauses automatically and resumes when it cools. The log panel shows "Thermal throttling — detection paused."

---

## Step 6: Review the Timeline

When detection completes, the page transitions to the **Timeline Review** view:

1. A horizontal strip shows **green blocks** (motion events) and **gray** (silence).
2. Click any green block to see a thumbnail and event details below.
3. Click **Play Clip** on any event card — a video player opens within 10 seconds.
4. Click **Exclude** on any event that is a false positive (cat, wind-blown tree, etc.).
5. Check the **Summary Bar** at the top — it shows total activity duration and estimated output size, updating as you include/exclude events.

---

## Step 7: Export

1. Click **Export Selected Clips**.
2. A progress bar tracks the FFmpeg merge.
3. When done, you see the confirmation card:
   - Output file path and size
   - Compression ratio (e.g., "2h → 4 min, 97% smaller")
4. Click **Play** to preview the merged video in the browser.
5. The output file is saved in the configured output directory on the Pi.

**Expected export time** (Original Quality, stream copy): Under 2 minutes for a 1-hour source.

---

## Step 8: Verify Chapter Markers

Open the output file in VLC (or any chapter-aware player):
- Menu → Playback → Chapter → You should see one chapter per exported event
- Each chapter is labelled with the real clock time (e.g., "Event 3 — 10:34 PM")

---

## Step 9: Verify Crash Recovery

To test checkpoint/resume (optional):

1. Start a new job on a long video (30+ minutes).
2. After ~2 minutes of detection, SSH into the Pi and run:
   ```bash
   sudo systemctl restart cctv-analyst
   ```
3. Wait for the service to restart (~5 seconds).
4. Reopen the Job Detail page. You should see:
   - Job status: **Running**
   - Log panel: "Resumed from checkpoint at [timestamp]"
   - Detection continues from approximately where it stopped.

---

## Step 10: PWA Offline Check

1. Disconnect the Pi from power (or stop the service: `sudo systemctl stop cctv-analyst`).
2. Open the installed PWA from your phone's home screen.
3. You should see the app shell (header, nav) with "Pi not reachable — check that your Raspberry Pi is powered on and connected to the network."
4. You should NOT see a browser error page.

---

## Acceptance Criteria Verification

After completing this quickstart, verify these criteria from the spec:

| Criterion | How to verify |
|---|---|
| SC-001: 24h 1080p ≤ 2.5h detection | Submit a 24h file; check job duration in History |
| SC-002: Export ≤ 10min | Check export completion time in the log panel |
| SC-003: Timestamps accurate ±1s | Compare event start time to source at that offset |
| SC-004: Timeline responsive with 200+ events | Use High sensitivity on busy footage; check scroll speed |
| SC-005: Page load ≤ 2s | Cold-load the dashboard; measure in browser DevTools |
| SC-006: Resume within 1-2s of footage | Follow Step 9 crash recovery test |
| SC-007: System under 1400MB throughout | `systemctl status cctv-analyst` → check MemoryCurrent |
| SC-008: PWA opens in 5s | Time home screen tap to app ready |
| SC-009: False positive rate < 5% at Medium | Manual review of exported clips vs source |
| SC-010: History survives reboot | After Pi reboot, verify past jobs in History page |

---

## Troubleshooting

**"Service worker failed to register"**: Ensure you're accessing via `https://` and have accepted the certificate warning. Plain `http://` will never work for PWA.

**Detection runs very slowly**: Check the System page for thermal throttling. If temperature > 75°C continuously, add a heatsink or improve airflow.

**Export fails with codec error**: Check the amber warning shown at job submission. MJPEG/VP9 sources require re-encoding which may take 1-2 hours.

**Disk full during export**: The disk space check at job submission only estimates. High-activity footage can require more than the estimate. Free up space and retry (job resumes from checkpoint).

**`vcgencmd` not found in logs**: This is expected when running in Docker or on non-Pi hardware. Temperature shows "N/A" in the UI. All other features work normally.
