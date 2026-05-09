# Testing Practices — RasPi CCTV Analyst

> This guide documents how to properly test the system end-to-end, what videos to use, how to read the logs, and what to verify at each stage. Written from real deployment experience on Raspberry Pi 5.

---

## Table of Contents

1. [Quick Start Test (5 minutes)](#1-quick-start-test-5-minutes)
2. [Recommended Test Videos](#2-recommended-test-videos)
3. [Videos That Will NOT Work](#3-videos-that-will-not-work)
4. [Reading the Log Panel](#4-reading-the-log-panel)
5. [Phase-by-Phase Verification](#5-phase-by-phase-verification)
6. [Sensitivity Settings Guide](#6-sensitivity-settings-guide)
7. [Detection Diagnostic Reference](#7-detection-diagnostic-reference)
8. [Export Verification](#8-export-verification)
9. [Common Failures and Fixes](#9-common-failures-and-fixes)
10. [Full End-to-End Test Checklist](#10-full-end-to-end-test-checklist)
11. [Known Limitations](#11-known-limitations)

---

## 1. Quick Start Test (5 minutes)

The fastest way to confirm the system is working end-to-end:

**Step 1** — Record a 30–60 second test clip on your phone:
- Walk in front of the camera for 5–10 seconds
- Stand still for 5 seconds
- Walk again for 5–10 seconds

**Step 2** — Upload it via the browser:
- Open `https://RASPBERRYPIABHI.local:5000/jobs/new`
- Click **Upload File** tab → drag the video in
- Set sensitivity to **High**
- Leave all other settings at default
- Click **Start Analysis →**

**Step 3** — Expand the Live Log panel on the Job Detail page and verify:
```
[DETECTION] FFmpeg starting — target=XX.Xfps ...
[DETECTION] First frame received — Frame brightness: 87/255 (OK)
[DIAG frame 10] MOG2 raw=XXXX px → after_morph=XXXX px (need >=38px ...)
[00:00:00] Frame 30/XXX — max_motion=0.XXXX (threshold=0.0005) — 0 events so far
...
[DONE] Detection complete — N motion events found
```

**Step 4** — After detection:
- A green card says "N motion events found"
- Click **Export Selected Clips**
- A progress bar runs, then "Export Complete!" appears
- Click **▶ Preview Output** to verify the video plays

If all 4 steps succeed, the system is working correctly.

---

## 2. Recommended Test Videos

### Best: Short Phone Video (Your Own Recording)

| Property | Ideal Value |
|---|---|
| Duration | 30 seconds – 5 minutes |
| Format | H.264 MP4 (.mp4) |
| Resolution | 1080p or 720p |
| Motion content | Someone walking clearly in frame |
| Lighting | Good daylight or well-lit indoor |

**Why this works well**: H.264 MP4 uses stream copy (no re-encode), exports in seconds, and the system is tuned to detect person-sized motion.

### Good: Standard CCTV/Dashcam Footage

| Property | Acceptable Value |
|---|---|
| Format | H.264 or HEVC in MP4, MKV, TS |
| Resolution | 720p – 4K |
| Duration | Up to 24 hours |
| Frame rate | 15fps – 60fps |

### Minimum Motion for Detection to Trigger

At 320×240 detection resolution and **Medium** sensitivity:
- At least **154 pixels** must be classified as foreground
- A person 3 metres away fills approximately 800–2000 pixels at 320×240
- A car at 10 metres fills approximately 400–800 pixels

At **High** sensitivity:
- Only **38 pixels** required — detects hand movements, distant pedestrians

---

## 3. Videos That Will NOT Work

### Avoid These Video Types

| Type | Why It Fails | Workaround |
|---|---|---|
| `.mp4` with embedded edit list and corrupt keyframe index | FFmpeg produces only 5–10 frames before EOF | Fixed in code with `-ignore_editlist 1`; if still failing, re-encode with HandBrake |
| MJPEG `.avi` | Re-encode required; takes 1–2 hours per hour of footage | Convert to H.264 first |
| VP9 / AV1 | Re-encode required | Convert to H.264 |
| Completely static footage (no movement) | No motion → no events | Use video with actual movement |
| Footage where camera itself is moving | MOG2 sees entire frame as foreground | Fixed cameras only |
| Footage with strobing/flashing lights | Every other frame triggers motion | Use High sensitivity with Low padding |
| Videos shorter than 5 seconds | MOG2 needs ~3 seconds to build background model | Use 10+ second clips |

### Warning Signs in the Log

| Log Message | Meaning | Action |
|---|---|---|
| `FFmpeg produced 0 frames` → Job FAILED | Video format incompatible or file corrupt | Re-encode or try different file |
| `Frame brightness: 3/255 (WARNING: very dark)` | Frames are black — codec issue | Re-encode video |
| `[ffmpeg] edit list ... Cannot find an index entry` | Phone video edit list warning | Safe to ignore — fixed by `-ignore_editlist 1` |
| `[ffmpeg] Invalid data found when processing input` | Corrupt video file | Use a different file |
| `[RAM GUARD] XX% RAM used — throttling` | Pi RAM under pressure | Reduce to one job at a time, reduce frame_skip |

---

## 4. Reading the Log Panel

Open the **Live Log** panel at the bottom of the Job Detail page. Here is what each line means:

```
[START] Detection started — source: video.mp4
```
Detection thread has started. No frames read yet.

```
[DETECTION] FFmpeg starting — target=25.0fps, source=59.6fps, frame_skip=0, output=320×240px, sensitivity=high
```
FFmpeg is about to launch. Verify `target fps` makes sense. With `frame_skip=0`, target = source fps. With `frame_skip=1`, target = source/2.

```
[DETECTION] cmd: ffmpeg -hide_banner -loglevel warning -ignore_editlist 1 -fflags +igndts…
```
Confirms the FFmpeg flags are correct. **Must include `-ignore_editlist 1`** for phone videos to work.

```
[DETECTION] First frame received — Frame brightness: 87/255 (OK)
```
FFmpeg is producing frames. Brightness 87 = normal content. If < 5 = black frames (broken pipeline).

```
[DIAG frame 10] MOG2 raw=1842px → after_morph=1204px (need >=38px for a detection at high sensitivity)
```
Diagnostic at the 10th frame. **Most important line for diagnosing 0-event issues:**
- `MOG2 raw=0` → MOG2 producing no foreground; check if video is static
- `MOG2 raw=1842px → after_morph=0px` → Morphological filter is too aggressive
- `MOG2 raw=1842px → after_morph=1204px, need>=38px` → Detection is working, events will form

```
[00:00:30] Frame 750/3000 — max_motion=0.0124 (threshold=0.0005) — 2 events so far
```
Progress checkpoint every 30 frames. Columns:
- `00:00:30` = 30 seconds into the video
- `Frame 750/3000` = processed 750 of estimated 3000 frames (25% done)
- `max_motion=0.0124` = highest motion ratio in this 30-frame window (1.24% of pixels were moving)
- `threshold=0.0005` = the detection threshold for current sensitivity
- `2 events so far` = events confirmed in the DB so far

**If `max_motion` is always < threshold**: No motion is being detected. Lower sensitivity or check video content.

```
[DONE] Detection complete — 8 motion events found
```
Detection finished. 8 events created in the database.

```
[HINT] No motion detected. If the video has movement, try resubmitting with High sensitivity.
```
Appears only when 0 events found. Check the `max_motion` values in earlier checkpoint lines.

---

## 5. Phase-by-Phase Verification

### Phase 1: Job Submission

**Verify:**
- [ ] Job appears in the Job Queue with status **Queued** within 3 seconds of clicking Submit
- [ ] Any codec or disk space warnings appear as amber boxes before submitting
- [ ] After submission, browser navigates automatically to the Job Detail page

**If job never appears queued:**
- Check `sudo systemctl status cctv-analyst` — service must be `active (running)`
- Check `sudo journalctl -u cctv-analyst -n 20` for startup errors

---

### Phase 2: Detection Running

**Verify (within 60 seconds of submission):**
- [ ] Job status changes from **Queued** → **Running** → **Detecting**
- [ ] Progress bar starts moving
- [ ] Log panel shows `[DETECTION] First frame received`
- [ ] Log panel shows `[DIAG frame 10]` line
- [ ] Checkpoint logs appear every 30 frames with non-zero `max_motion`

**Typical detection times on Pi 5:**

| Video | Duration | Detection Time |
|---|---|---|
| 1-minute 1080p H.264 at 25fps | 1 min | ~45–90 seconds |
| 5-minute 1080p H.264 | 5 min | ~4–8 minutes |
| 24-hour 1080p H.264 | 24 hours | ~2–2.5 hours |

---

### Phase 3: Timeline Review

When detection completes, the Job Detail page shows:

**Verify:**
- [ ] Green card appears: "Detection complete — N motion events found"
- [ ] Timeline canvas shows green blocks (events) on a gray background
- [ ] Clicking a timeline block highlights the corresponding event card
- [ ] Thumbnails load lazily as you scroll
- [ ] Summary bar shows total activity duration and estimated output size
- [ ] "Export Selected Clips" button is enabled (if events > 0)

**If 0 events:**
- [ ] Amber warning card appears with troubleshooting tips
- Check `max_motion` values in the log — if all 0.0000, the video has no detectable motion
- Try resubmitting with **High** sensitivity

---

### Phase 4: Preview a Clip

Click **▶ Play Clip** on any event card.

**Verify:**
- [ ] Loading spinner appears (1–10 seconds depending on Pi load)
- [ ] Video player opens in a modal
- [ ] Clip plays correctly with the right content (not black, not corrupt)
- [ ] Video is seekable (you can click on the progress bar)

---

### Phase 5: Export

Click **Export Selected Clips**.

**Verify:**
- [ ] Progress bar appears and moves
- [ ] Log panel shows `[EXPORT]` lines: segment extraction then merge
- [ ] "Export Complete!" card appears with file name and size
- [ ] Compression ratio makes sense (e.g., 24h → 18 min, 97% smaller)

**Test: Preview the output video**
- [ ] Click **▶ Preview Output** — video plays in browser
- [ ] Video is seekable (HTML5 range requests working)
- [ ] Duration matches total activity time (sum of included events)

**Test: Download the output video**
- [ ] Click **Download** — file downloads
- [ ] Open in VLC: Playback → Chapter shows chapter list (one per event)
- [ ] Each chapter title shows real clock time, e.g. "Event 3 — 10:34 PM"

**Test: Re-export with different selection**
- [ ] Exclude 2 events, click Export again
- [ ] A NEW timestamped file is created (old file NOT overwritten)
- [ ] Export history at bottom of page shows both exports

---

### Phase 6: Crash Recovery

Tests the checkpoint/resume mechanism.

1. Start a detection job on a **10+ minute video**
2. Wait ~2 minutes until you see checkpoint progress in the log
3. SSH into the Pi and run: `sudo systemctl restart cctv-analyst`
4. Wait 10 seconds, then reload the Job Detail page

**Verify:**
- [ ] Job status returns to **Detecting** (not Failed)
- [ ] Log shows: `[RESUME] Resuming from checkpoint at XX.Xs (frame XXXX)`
- [ ] Log shows warmup frames being processed
- [ ] Detection continues from approximately where it stopped

---

## 6. Sensitivity Settings Guide

| Setting | Threshold | Use Case | False Positive Risk |
|---|---|---|---|
| **Low** | 1.0% of pixels | Large vehicles, obvious crowd motion | Very low |
| **Medium** | 0.2% of pixels | Standard CCTV — people walking, cars passing | Low |
| **High** | 0.05% of pixels | Distant pedestrians, subtle motion, nighttime | Medium |

### How to Choose

**Start with Medium.** If you get 0 events on a video with obvious motion, switch to High.

**Sensitivity affects:**
- MOG2 history window (Low: 700 frames, Medium: 500, High: 200)
- MOG2 variance threshold (Low: 32, Medium: 16, High: 8)
- Motion ratio threshold (Low: 0.01, Medium: 0.002, High: 0.0005)

**Rule of thumb:**
- Daytime outdoor CCTV → Medium
- Nighttime or indoor → High
- Busy intersection or parking lot → Medium or Low (reduce false positives)
- Static camera, distant subjects → High

---

## 7. Detection Diagnostic Reference

### The DIAG Line Explained

```
[DIAG frame 10] MOG2 raw=1842px → after_morph=1204px (need >=38px for a detection at high sensitivity)
```

| Value | Healthy Range | Problem if... |
|---|---|---|
| `MOG2 raw` | > 500px for any movement | = 0: frames are black or static |
| `after_morph` | > 80% of raw | Much lower than raw: morphological filter too aggressive |
| `need >=Xpx` | 38 (high), 154 (medium), 768 (low) | If `after_morph` < needed: no events will form |

### max_motion Values Explained

```
[00:00:30] Frame 750/3000 — max_motion=0.0124 (threshold=0.0005) — 2 events so far
```

| max_motion | Interpretation |
|---|---|
| `0.0000` | No motion at all in this 30-frame window |
| `0.0001–0.0005` | Subtle noise or very distant motion |
| `0.001–0.01` | Clear motion (person at medium distance) |
| `0.01–0.10` | Strong motion (person close to camera) |
| `> 0.10` | Very strong motion (multiple people, vehicle close) |

---

## 8. Export Verification

### Checking Chapter Markers (VLC)

1. Open the exported MP4 in VLC
2. Menu → Playback → Chapter
3. You should see: `Event 1 — 10:34 PM`, `Event 2 — 10:41 PM`, etc.

If chapters are missing: the `ffmetadata.txt` was not injected. Check export log for errors.

### Checking Output Quality

| Quality Setting | Expected File Size vs Original | Use Case |
|---|---|---|
| Original Quality | ~(activity_pct%) of original | Archiving, evidence |
| 720p Compressed | ~50–80% smaller than Original | Sharing, email |
| 480p Small | ~70–90% smaller than Original | Messaging apps |

### Verifying Timestamps

Compare the exported video's chapter timestamps against the source:
1. Note an event start time, e.g. "Event 3 — 10:34 PM"
2. Open the original video in VLC
3. Seek to approximately the same clock time
4. The content should match the exported event within ±2 seconds

---

## 9. Common Failures and Fixes

### Detection Finds 0 Events

**Check the log in this order:**

1. Is `[DETECTION] First frame received` present?
   - **No** → Job shows FAILED status. FFmpeg could not read the file. Re-encode the video.
   - **Yes** → Continue to step 2.

2. Is `[DIAG frame 10]` present?
   - **No** → FFmpeg produced fewer than 10 frames. Likely an edit list issue (phone video). The latest code includes `-ignore_editlist 1` — ensure you `git pull` and restart.
   - **Yes** → Read the values and continue.

3. Is `MOG2 raw` in the DIAG line > 0?
   - **raw=0** → MOG2 sees no foreground. Video may be completely static or have unusual color format. Try a different video to confirm the system works.
   - **raw > 0** → Continue to step 4.

4. Is `after_morph >= needed`?
   - **after_morph < needed** → Switch to **High** sensitivity and resubmit.
   - **after_morph >= needed** → Motion IS being detected. Check `max_motion` in checkpoint lines.

5. Are `max_motion` values always > threshold?
   - **Yes, but still 0 events** → Check the `min_gap_s` and `min_event_s` settings. If motion is continuous (max_motion never drops to 0), the event never closes during the video but IS closed at the very end. Check the final log line for the event count.

---

### Job Shows FAILED

Read `error_msg` in the job details. Common causes:

| Error Message | Cause | Fix |
|---|---|---|
| `FFmpeg produced 0 frames` | Unsupported codec or corrupt file | Re-encode with HandBrake to H.264 MP4 |
| `Insufficient disk space` | USB drive full | Free up space, retry |
| `[Errno 2] No such file or directory` | Uploaded file was deleted | Re-upload |

---

### Export Button Disabled

- You have 0 included events. Either detection found nothing, or you excluded all events.
- Solution: Click **Include All** or resubmit with higher sensitivity.

---

### Preview Clip Fails (503 error)

- Another preview is already generating (Pi can only do one at a time).
- Wait 5–10 seconds and try again.

---

### Service Not Starting

```bash
sudo journalctl -u cctv-analyst -n 30 --no-pager
```

Common causes:
- Path with spaces in the systemd unit file → Run `bash install.sh` again after latest `git pull`
- Python dependency missing → Run `source venv/bin/activate && pip install -r requirements.txt`
- Port 5000 already in use → `sudo lsof -i :5000` to find the conflicting process

---

## 10. Full End-to-End Test Checklist

Use this checklist for a complete validation of the system.

### Prerequisites
- [ ] Pi is running and dashboard is accessible at `https://RASPBERRYPIABHI.local:5000`
- [ ] `sudo systemctl status cctv-analyst` shows `active (running)`
- [ ] At least 10GB free on the USB drive

### Test Videos Prepared
- [ ] Short video (30–60 seconds, H.264 MP4, clear motion)
- [ ] Phone video (recorded with Android or iPhone, tests edit list handling)
- [ ] Nighttime video (if available, tests dark-frame detection)

---

### Test 1: Upload and Detection ✅

- [ ] Upload short video via Upload File tab
- [ ] Job appears in queue within 3 seconds
- [ ] Log shows `[DETECTION] cmd: ffmpeg ... -ignore_editlist 1 -fflags +igndts ...`
- [ ] Log shows `First frame received — Frame brightness: XX/255 (OK)`
- [ ] Log shows `[DIAG frame 10]` with `after_morph >= needed`
- [ ] Checkpoint lines appear with non-zero `max_motion`
- [ ] Detection completes with `N > 0 motion events found`
- [ ] Green guidance card appears on Job Detail page

### Test 2: Timeline Review ✅

- [ ] Timeline canvas renders green blocks
- [ ] Clicking a timeline block scrolls to the correct event card
- [ ] Summary bar shows correct event count, activity duration, estimated size
- [ ] Excluding 1 event: summary bar updates immediately
- [ ] Including it back: summary bar updates immediately

### Test 3: Preview ✅

- [ ] Click Play Clip on an event — video loads within 10 seconds
- [ ] Preview clip shows the correct scene
- [ ] Modal closes cleanly on ✕ click or Escape key

### Test 4: Export ✅

- [ ] Click Export Selected Clips
- [ ] Export progress log lines appear
- [ ] Export Complete card appears with file size
- [ ] Preview Output: video plays in browser, is seekable
- [ ] Download: file saves locally
- [ ] VLC: chapter markers present (Playback → Chapter)
- [ ] Re-export after excluding 1 event: different timestamp in filename
- [ ] Export history at bottom shows 2 separate export records

### Test 5: Crash Recovery ✅

- [ ] Start a 5+ minute video detection job
- [ ] After 1 minute of detection: `sudo systemctl restart cctv-analyst`
- [ ] After ~10 seconds: job resumes from checkpoint (log confirms)
- [ ] Detection completes correctly after resume
- [ ] Event count is consistent (no duplicates)

### Test 6: PWA and Offline ✅

- [ ] Open `https://RASPBERRYPIABHI.local:5000` on Android Chrome
- [ ] Install prompt appears (⋮ → Add to Home Screen)
- [ ] App opens from home screen in standalone mode (no address bar)
- [ ] Stop service: `sudo systemctl stop cctv-analyst`
- [ ] Open app from home screen: shows "Pi not reachable" message (not browser error)
- [ ] Start service again: `sudo systemctl start cctv-analyst`
- [ ] App recovers automatically

### Test 7: System Health ✅

- [ ] Open System page during detection
- [ ] CPU gauge shows ~80–100% (normal during detection)
- [ ] Temperature gauge shows a reading (not N/A — Pi should report vcgencmd)
- [ ] Disk gauge shows correct usage percentage
- [ ] All 4 gauges update every 10 seconds

---

## 11. Known Limitations

| Limitation | Detail | Planned |
|---|---|---|
| One job at a time | Only one video is analysed simultaneously | Multi-queue in v2 |
| No object classification | System detects motion — cannot distinguish person vs cat vs vehicle | YOLOv8n in v1.5 |
| MOG2 and continuously crowded scenes | If objects are always in frame, MOG2 may learn them as background | Use High sensitivity; restart service between tests |
| 4K video on 2GB Pi | Detection works but is slower; may thermal-throttle | Use 4GB Pi or pre-scale video |
| Phone videos with extreme encoding | Some ultra-HDR or variable-frame-rate recordings may still fail | Re-encode with HandBrake to H.264 MP4 |
| MJPEG export time | 24h MJPEG source requires re-encode: ~1–2 hours export | Camera-side setting to change to H.264 |
| No authentication | Anyone on the LAN can access the dashboard | By design for home use; auth in v3 |

---

*Last updated: 2026-05-09 — reflects code through commit `7db2c0d`*
