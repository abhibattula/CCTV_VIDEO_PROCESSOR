# User Manual — RasPi CCTV Analyst

> **Who this is for**: Anyone who wants to use the system — no technical knowledge required.
> This guide walks you through everything from first setup to exporting your highlight video.

---

## What Does This App Do?

Security cameras record everything — but 95% of a typical 24-hour recording is nothing interesting. This app automatically finds the moments where something actually moved, shows them to you on a visual timeline, and lets you create a short highlight video of just those moments.

**Example**: You have a 24-hour driveway recording (roughly 21 GB). Instead of watching all 24 hours, the app finds 47 motion events and shows you a 18-minute highlight reel — all in about 2 hours of automatic processing, no watching required.

**Your video never goes to the internet.** Everything runs on the Raspberry Pi plugged into your home network.

---

## What You Need Before Starting

### Hardware
- A **Raspberry Pi 5** (the small single-board computer) set up and powered on
- A **USB drive or SSD** with your CCTV video files and at least 50 GB free space
- An **active cooler** attached to the Pi (looks like a small fan/heatsink — prevents overheating during long jobs)
- The Pi connected to your **home Wi-Fi or router** with an ethernet cable

### For Viewing the Dashboard
- A phone, tablet, or laptop on the **same home network** as the Pi
- **Chrome** (version 110 or newer) or **Firefox** (version 115 or newer)

### Your Video Files
- Must be on the USB drive connected to the Pi (or uploaded from your browser)
- Supported formats: `.mp4`, `.mkv`, `.avi`, `.mov`, `.ts`, `.mts`, `.flv`
- **Best format**: H.264 MP4 (most cameras default to this — check your camera settings)

---

## Preferred Video Format

| Format | What it means | Export Speed |
|---|---|---|
| **H.264 MP4** | Most common; what most cameras use by default | ⚡ Very fast (minutes) |
| H.265/HEVC MP4 | Newer, smaller files, same quality | ⚡ Fast |
| MKV (H.264 inside) | Same as MP4, different wrapper | ⚡ Fast |
| MJPEG | Older format, some budget cameras | 🐢 Slow (hours) |
| VP9/AV1 | Rare for CCTV | 🐢 Slow (hours) |

**Tip**: Check your camera's recording settings. If it offers H.264, choose that. If it only offers MJPEG, the app still works — export just takes longer.

---

## Step 1: Open the Dashboard

On your phone or laptop, open your browser and go to:

```
https://raspberrypi.local:5000
```

> **If "raspberrypi.local" doesn't work**: Ask the person who set up the Pi for its IP address (looks like `192.168.1.xxx`) and go to `https://192.168.1.xxx:5000` instead.

### The Certificate Warning

You will see a security warning the first time. This is normal and safe.

**Chrome**: Click **Advanced** → **Proceed to raspberrypi.local (unsafe)**

**Firefox**: Click **Advanced** → **Accept the Risk and Continue**

**Safari (iPhone)**: Tap **Show Details** → **visit this website**

After accepting once, this warning will not appear again on this device.

---

## Step 2: Install as an App (Recommended)

For the best experience, install the dashboard as an app on your home screen. This makes it open in full screen without the browser toolbar.

**Android (Chrome)**:
1. Tap the three-dot menu (⋮) in the top right
2. Tap **Add to Home Screen**
3. Tap **Install**
4. The app icon appears on your home screen

**iPhone (Safari)**:
1. Tap the Share button (the square with an arrow pointing up)
2. Scroll down and tap **Add to Home Screen**
3. Tap **Add**

**Computer (Chrome)**:
1. Look for a small install icon in the address bar (right side)
2. Click it and select **Install**
3. The app opens in its own window

---

## Step 3: The Dashboard (Home Page)

When you open the app, you see the Dashboard. It shows:

- **System Status**: How hot the Pi is, how much memory and disk space is in use
- **Active Job**: If the Pi is currently processing a video, you see a progress bar here
- **Recent Jobs**: The last 5 videos you processed, with quick links to open them
- **New Analysis Job button**: This is how you start processing a new video

**What the gauges mean:**
- **CPU**: How hard the processor is working (100% is normal during detection)
- **RAM**: Memory usage (should stay under 85% — the system manages this automatically)
- **Disk**: How full your USB drive is (shown as a percentage)
- **Temp**: The Pi's temperature in Celsius (the system automatically slows down if it gets above 80°C)

---

## Step 4: Submit Your First Job

### Option A: Video is already on the USB drive

1. Click **New Analysis Job** (or tap the + New Job link in the sidebar)
2. The **File Path** tab should be selected
3. Click **Browse** to navigate your USB drive and select your video file
4. Click on your USB drive (usually listed under `/media/`)
5. Navigate to your video file and click on it — the path fills in automatically

### Option B: Upload from your phone or computer

1. Click **New Analysis Job**
2. Click the **Upload File** tab
3. Drag your video file onto the upload zone, or click inside it to choose a file
4. Wait for the upload to complete (large files may take several minutes on a home network)

---

### Choosing Detection Settings

After selecting your video, you'll see three main settings:

**Sensitivity** — How easily the app triggers on movement:
- **Low**: Only obvious, large movements. A person walking past will trigger; a leaf blowing may not. Fewer false positives.
- **Medium** (recommended): Balanced. Catches most genuine movement. Good starting point.
- **High**: Very sensitive. Catches subtle movements. May also trigger on lighting changes, shadows, and insects.

> **Recommendation**: Start with **Medium**. You can always resubmit with different settings.

**Padding** (default: 3 seconds) — How many seconds are added before and after each detected movement in the exported video. Prevents clips from starting/ending too abruptly.

**Min Gap** (default: 5 seconds) — If two movements happen within this many seconds of each other, they are treated as one event rather than two separate clips.

**Min Event** (default: 3 seconds) — Any movement shorter than this is ignored. Prevents very brief flickers from creating tiny clips.

**Output Quality:**
- **Original Quality** (recommended): Fastest export. Video quality identical to original.
- **720p Compressed**: Smaller file, slightly lower quality. Takes longer to process.
- **480p Small**: Smallest file. Suitable for sharing. Takes longer to process.

---

### Warnings You Might See

After clicking **Start Analysis**, the app may show amber warning boxes:

> **"MJPEG codec — re-encoding required"**: Your camera uses MJPEG format. Export will take 1–2 hours instead of a few minutes. Detection speed is the same.

> **"4K source on 2GB Pi"**: Your video is 4K resolution. Detection will still work but the Pi may slow down due to memory pressure.

These are warnings, not errors. Click **Start Analysis** to proceed.

---

## Step 5: Watch the Progress

After submitting, you are taken to the **Job Detail** page. This shows:

- **Status badge**: Current state (Queued → Detecting → Completed)
- **Progress bar**: Percentage of the video analysed
- **Log panel** (at the bottom, click to expand): Live text output showing which frames are being processed
- **System gauges**: CPU and temperature update every 10 seconds

**Typical processing times on a Pi 5 (1080p H.264):**
- 1-hour video → ~6 minutes
- 8-hour video → ~50 minutes
- 24-hour video → ~2 hours

**Thermal throttling**: If the Pi gets too hot (above 80°C), detection automatically pauses and the log shows:
> `[THERMAL] 82.4°C — pausing detection`

It will resume automatically when the temperature drops. You do not need to do anything.

**If you need to leave** and come back later — the Pi keeps working. Open the app again when you're ready and everything will be where you left off.

---

## Step 6: Review the Events

When detection finishes, the page shows the **Timeline** view:

### The Timeline Strip

A horizontal bar shows your entire recording. **Green blocks** are motion events; **gray sections** are periods of no movement.

- Click (or tap) anywhere on the timeline to jump to that event
- On mobile: Swipe left/right to pan through long recordings (each swipe moves 4 hours)
- The selected event is highlighted in orange

### Event Cards

Below the timeline, each event appears as a card showing:
- The event number and time range (e.g., "10:34 PM – 10:36 PM")
- Duration (e.g., "2 min 14 sec")
- A thumbnail image from the middle of the event
- Buttons to Preview, Include, Exclude, or Tag the event

### Previewing a Clip

Click **▶ Play Clip** on any event card. The app extracts a short clip (takes 5–10 seconds) and plays it in a video player right in the browser. Use this to check what actually triggered the detection before deciding to include or exclude it.

### Including and Excluding Events

By default, **all events are included** in the export. Use the buttons to manage them:

- **Exclude**: Click this on any event you don't care about (a cat, a shadow, wind-blown leaves). The event turns gray and will not appear in the exported video.
- **Include** (appears after excluding): Bring an event back if you change your mind.
- **Exclude All / Include All**: Bulk action buttons at the top for quick selection.

### Tagging Events

Optionally tag events to help organise them:
- **Person**: A person was detected
- **Vehicle**: A car or other vehicle
- **Animal**: A pet, bird, or wildlife
- **False Positive**: Not a real event (triggered by accident)
- **Review Required**: Not sure — check later

Tags appear in the exported CSV report and can help you find specific events later.

### Summary Bar

A bar at the top of the event list shows:
- How many events are included vs excluded
- Total duration of included events
- Estimated size of the exported video

This updates every time you include or exclude an event.

---

## Step 7: Export

When you are happy with your event selection:

1. Click **Export Selected Clips**
2. A progress bar shows the export status
3. Wait for completion (usually under 2 minutes for H.264 originals)

When done, you'll see a confirmation card showing:
- The output file name (automatically timestamped, e.g., `cam1_activity_20260505_161200.mp4`)
- The file size (typically 95–99% smaller than the original)

**Buttons available:**
- **▶ Preview Output**: Watch the merged video directly in your browser
- **Download**: Save the file to your device
- **Generate Report**: Download a PDF report with event statistics
- **Export CSV**: Download a spreadsheet of all events

The output file is saved on the Pi's USB drive in the configured output folder.

---

## Step 8: Re-Exporting

Changed your mind about which events to include? No problem:

1. Go back to the Job Detail page for the completed job
2. Toggle events as needed
3. Click **Export Selected Clips** again

Each export creates a **new timestamped file** — previous exports are not overwritten. You can see all previous export versions at the bottom of the Job Detail page.

---

## The Job Queue Page

The **Job Queue** (accessible from the sidebar) shows all your submitted jobs. From here you can:

- See which jobs are running, queued, or completed
- Click any row to open the Job Detail page
- Cancel a running job
- Delete old jobs you no longer need
- Retry a job that failed

**Status meanings:**
| Status | What it means |
|---|---|
| **Queued** | Waiting to start (another job is running) |
| **Detecting** | Actively analysing the video for motion |
| **Completed** | Ready to review and export |
| **Exporting** | Creating the merged output video |
| **Failed** | Something went wrong — click Retry to try again |
| **Cancelled** | You cancelled it |

---

## The Reports Page

Select any completed job from the dropdown to see:

- **Summary statistics**: Total events, activity percentage, peak activity hour
- **Hourly activity chart**: Which hours had the most motion
- **Duration breakdown**: How many events were short vs. long

From here you can also download a **PDF report** (suitable for printing or sharing) or a **CSV spreadsheet** of all events.

---

## The System Page

Shows live health information for the Pi:

- **CPU**: Processing load (100% during detection is normal)
- **RAM**: Memory usage (should stay below 1400 MB)
- **Disk**: Storage usage on your USB drive
- **Temperature**: The Pi's CPU temperature (should stay below 80°C)
- **Temperature history**: A small chart showing the last 5 minutes of temperature readings
- **Uptime**: How long the Pi has been running

> **Tip**: Keep this page open during a long detection job to monitor the Pi's health.

---

## The Settings Page

Configure global defaults that apply to new jobs:

| Setting | What it does | Default |
|---|---|---|
| Default Output Directory | Where exported videos are saved on the Pi | `~/cctv_output` |
| Default Sensitivity | Pre-selected sensitivity for new jobs | Medium |
| Default Padding | Default seconds added before/after events | 3s |
| Min Gap | Default minimum gap between events | 5s |
| Min Event | Default minimum event duration | 3s |
| Thermal Limit | Temperature at which detection pauses | 80°C |
| Disk Warning | Disk % at which a warning appears | 85% |
| Dark Mode | Light / Dark / System (follows your device) | System |

Changes take effect for new jobs — they do not change settings of already-submitted jobs.

---

## The Audit Log Page

A complete record of everything that has happened: every job submitted, every export, every settings change. Useful if you want to know exactly when something was processed.

You can filter by:
- **Level**: Info / Warning / Error
- **Actor**: User actions vs. system actions
- **Date range**

The log can be exported as a CSV file.

---

## Troubleshooting

### "Pi not reachable — check that your Raspberry Pi is powered on"

The app is installed but the Pi is off or unreachable. Check:
1. Is the Pi powered on? (Check for red/green LEDs)
2. Is it connected to the same network as your device?
3. Wait 30 seconds after powering on — the service takes a moment to start

### Job stuck on "Queued" forever

- Only one job runs at a time. If another job is running, yours waits.
- Check the Dashboard to see if a job is actively running.

### Detection finished but no events found

Your footage may not have enough motion for the chosen sensitivity. Try:
1. Open the job, click Retry, and choose **High** sensitivity next time
2. Check that your camera was recording correctly (watch a short section of the original)

### Export says "No events selected"

You excluded all events. Include at least one event before clicking Export.

### Export fails with a red error

- Check the disk has enough free space (need roughly 2× the original file size)
- Check the system page to make sure the Pi is not overheating
- Click **Retry** on the job — it will resume from where it left off

### The app is very slow / not responding

During detection, the Pi is doing heavy processing. The web app may respond slowly — this is normal. Wait a few seconds and try again. If it remains unresponsive, check the temperature on the System page.

### "Insufficient disk space" when submitting a job

Free up space on the USB drive. The system needs at least 2× the size of your source video free for temporary processing files.

### I accidentally excluded all events and exported an empty video

Re-open the job from the Job Queue. Click **Include All**, then click **Export Selected Clips** again. A new output file will be created — your previous empty export is still on disk but you can delete it.

---

## Privacy & Security

- **No data leaves your network.** All video processing, storage, and the web dashboard are local to your home network.
- **No account required.** There is no login, no cloud account, no subscription.
- **The certificate warning is safe.** The TLS certificate is self-signed specifically for `raspberrypi.local` — it encrypts your connection on the LAN without involving any external authority.
- **Who can access the dashboard?** Anyone on your home/office network who knows the Pi's address. This is intentional for ease of use on a home network. If you share a network with untrusted users, consult your router's documentation about network isolation.

---

## Quick Reference Card

| I want to... | Go to... |
|---|---|
| Process a new video | New Job (sidebar) → Browse or Upload → Start Analysis |
| Check if my job is done | Dashboard → Active Job, or Job Queue |
| Review and trim events | Job Queue → click the job row |
| Preview a specific clip | Job Detail → Event Card → ▶ Play Clip |
| Export the highlight video | Job Detail → Export Selected Clips |
| Download the output file | Job Detail → Download button (after export) |
| See system temperature | System (sidebar) |
| Change default settings | Settings (sidebar) |
| Get a summary report | Reports (sidebar) → select job → Generate Report |
| See a history of all actions | Audit Log (sidebar) |
