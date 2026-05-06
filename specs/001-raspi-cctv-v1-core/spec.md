# Feature Specification: RasPi CCTV Analyst — v1 Core Pipeline

**Feature Branch**: `001-raspi-cctv-v1-core`
**Created**: 2026-05-05
**Status**: Draft
**Reference**: `AI research/CCTV_Extractor_Documentation.md` | `AI research/RasPi_CCTV_Backend_Spec.docx` | `AI research/RasPi_CCTV_Frontend_Spec.docx`
**Issues Register**: `ISSUES.md` — 17 pre-identified issues, all addressed in implementation
**Constitution**: `.specify/memory/constitution.md` v1.0.0 — all requirements comply with Principles I–VII

---

## Overview

An operator uploads pre-recorded CCTV footage to a self-hosted Raspberry Pi 5. The system
automatically finds every segment containing motion, presents them for review on a visual
timeline, and exports only the relevant clips merged into a single output video. Hours of
footage become minutes of meaningful content — all processed privately, on-device.

The system is delivered as an installable web app (PWA) accessible from any phone, tablet,
or computer on the same network. No cloud services, no subscriptions, no data leaves the device.

---

## User Scenarios & Testing

### User Story 1 — Submit a Video Analysis Job (Priority: P1)

An operator wants to process a video file from an overnight CCTV recording. They open the
dashboard, provide the video file (either by browsing the Pi's filesystem for a USB-plugged
drive, or by uploading from their device), set detection preferences, and start the job.

**Why this priority**: This is the entry point to the entire system. Nothing else works
without a job being submitted and processed. It represents the core value proposition.

**Independent Test**: An operator can submit a job for any supported video format, see it
queued, and confirm it transitions to processing — independently of the review, export, or
history features.

**Acceptance Scenarios**:

1. **Given** a USB drive is plugged into the Pi with a `.mp4` recording,
   **When** the operator opens the dashboard, clicks "New Analysis Job", browses to the file
   using the server-side file browser, and clicks "Start Analysis",
   **Then** the job appears in the queue with status "Queued" within 3 seconds.

2. **Given** the operator has a video file on their laptop,
   **When** they drag it into the upload zone on the New Job page,
   **Then** a chunked upload progress bar appears, the file transfers to the Pi, and the
   job is submitted automatically upon completion — without the file being lost on network
   interruption (upload resumes from where it left off).

3. **Given** the disk on the Pi does not have sufficient free space (less than ~2× the source
   file size),
   **When** the operator submits the job,
   **Then** an immediate, clear error message is shown explaining how much space is needed
   and how much is available — the job is rejected before queuing, not after hours of work.

4. **Given** a source video uses a codec that cannot be fast-exported (e.g., MJPEG, VP9),
   **When** the job is submitted,
   **Then** an amber warning is shown: "This video requires re-encoding during export, which
   may take 2+ hours. Detection will proceed normally." The operator can still proceed.

5. **Given** the operator sets detection sensitivity to "Low", padding to 5 seconds, and
   minimum gap to 10 seconds,
   **When** the job is submitted,
   **Then** those specific settings are preserved exactly for this job, independently of
   any future changes to the global defaults.

---

### User Story 2 — Monitor Live Detection Progress (Priority: P2)

While a job is running, the operator wants to see real-time feedback: what timestamp is
being scanned, how many events have been found, system health, and an estimated finish time.
They may be on a phone, tablet, or desktop browser.

**Why this priority**: Long-running jobs (up to 2+ hours) require live feedback. Without it,
the operator cannot tell if the system is working, stuck, or overheating.

**Independent Test**: Start a job, open the Job Detail page, and confirm that log lines,
event count, progress bar, and system gauges update without manually refreshing the page.

**Acceptance Scenarios**:

1. **Given** a job is in the detecting phase,
   **When** the operator opens the Job Detail page,
   **Then** they see a live scrolling log panel, a progress bar showing percentage complete,
   an estimated time remaining, and current system stats (CPU %, RAM %, temperature).

2. **Given** multiple browser tabs are open on the same job,
   **When** new log lines arrive,
   **Then** all tabs receive updates simultaneously without degrading other dashboard
   functionality (settings saves, other page loads remain responsive).

3. **Given** the Pi's CPU temperature exceeds the configured thermal limit (default 80°C),
   **When** this occurs during detection,
   **Then** a visible warning appears on the Job Detail page ("Thermal throttling — detection
   paused") and the log panel shows the pause/resume events.

4. **Given** the operator closes the browser and reopens the Job Detail page later,
   **When** the job is still in progress,
   **Then** they see the last 100 log lines (replayed from history) plus live updates from
   that point forward — no events are missed.

5. **Given** a detection job crashes mid-way (power loss, OOM),
   **When** the system restarts,
   **Then** the job automatically resumes from the last checkpoint (within 30 frames / ~1 second
   of footage) rather than restarting from the beginning. The operator sees a "Resumed from
   checkpoint" log line when they next open the job.

---

### User Story 3 — Review and Edit the Motion Event Timeline (Priority: P1)

After detection completes, the operator sees a visual timeline strip with colored blocks for
each motion event. They can click events to see thumbnail previews and play the clip, mark
false positives for exclusion, add tags, and adjust the in/out points of any event.

**Why this priority**: This is the core differentiator — the visual review experience is why
this tool exists. Without it, the system is a black box that just produces output.

**Independent Test**: Open a completed job's timeline, verify events are shown, click an event
to preview the clip, exclude one event, and confirm it is reflected in the estimated export
size shown in the summary bar.

**Acceptance Scenarios**:

1. **Given** a completed job with detected events,
   **When** the operator opens the Job Detail page,
   **Then** they see a horizontal timeline strip where green blocks represent included motion
   events and gray represents silence, with real clock timestamps on the time axis
   (e.g., "02:34 AM" not just "offset 9212s").

2. **Given** the operator clicks a motion event block on the timeline,
   **Then** a card below highlights showing: a thumbnail image from the middle of the event,
   the clock start/end time, duration, and detection confidence score.

3. **Given** the operator clicks "Play Clip" on an event card,
   **Then** a video player modal opens within 10 seconds playing the clip from the detected
   start time. The clip is properly seekable and playable.

4. **Given** the operator clicks "Exclude" on an event they recognise as a false positive
   (e.g., a cat walking past),
   **Then** the event block turns gray on the timeline immediately, the summary bar updates
   the estimated output size, and the event is flagged for exclusion from export.

5. **Given** the operator uses the dashboard on a mobile phone,
   **When** they tap on the timeline,
   **Then** the touch target is large enough to select individual events reliably, and the
   event cards are displayed in a readable single-column format below the timeline strip.

6. **Given** the source recording has 200+ motion events (e.g., high sensitivity on a busy street),
   **When** the timeline page loads,
   **Then** it remains responsive — scrolling is smooth, thumbnail images load lazily only
   as they scroll into view, not all at once.

---

### User Story 4 — Export Selected Clips as a Merged Video (Priority: P1)

After reviewing the timeline and excluding false positives, the operator clicks "Export".
The system merges all included clips into a single MP4 file with chapter markers at each
event, lets the operator download or save it, and shows compression stats.

**Why this priority**: Export is the final deliverable. The tool's purpose is to produce a
condensed, reviewable video. Without export, there is no output.

**Independent Test**: After review, trigger export on a job with at least 3 included events.
Verify the output file plays in VLC, has the correct total duration, and chapter markers
jump to each event.

**Acceptance Scenarios**:

1. **Given** the operator has reviewed the timeline and excluded some events,
   **When** they click "Export Selected Clips",
   **Then** a progress bar tracks the export, and upon completion a confirmation card shows
   the output file path, final file size, and compression ratio (e.g., "24h → 18 min, 95% smaller").

2. **Given** the source is a standard H.264 MP4,
   **When** exported at "Original Quality",
   **Then** the output video quality is identical to the source (no re-encoding) and export
   completes in under 10 minutes for a 24-hour source.

3. **Given** the output file is produced,
   **When** the operator plays it in any standard video player (VLC, QuickTime, browser),
   **Then** the chapter list shows one chapter per exported event labelled with its real
   clock time (e.g., "Event 3 — 02:34 AM"), allowing instant navigation.

4. **Given** the operator chooses "Compressed 720p" output quality,
   **Then** the system warns that re-encoding will take significantly longer than stream copy,
   and proceeds after confirmation, producing a playable 720p H.264 output.

5. **Given** the source CCTV camera has no audio track,
   **When** the export runs,
   **Then** the output is a clean video-only MP4 with no broken audio track header or
   player error messages about missing audio.

6. **Given** the operator's Pi loses power during a long export,
   **When** it restarts and the operator reopens the job,
   **Then** they can trigger export again. The system detects any partial segment files
   and re-extracts cleanly — no manual cleanup required.

---

### User Story 5 — Browse and Reopen Historical Jobs (Priority: P2)

The operator wants to see all past jobs, their status, how much activity was found, and be
able to re-export a past job with different clip selections — without re-running the slow
detection phase.

**Why this priority**: CCTV review is a recurring workflow. Being able to reopen and
re-export past jobs without re-scanning is a major time saver.

**Independent Test**: Complete a job, navigate to the History page, verify the job appears
with correct stats, click "Reopen Timeline", change one event's inclusion, and re-export.

**Acceptance Scenarios**:

1. **Given** several past jobs exist,
   **When** the operator opens the History/Queue page,
   **Then** they see a table listing all jobs with: source filename, processed date, total
   source duration, total activity duration, activity percentage, output filename, and status badge.

2. **Given** a completed job in history,
   **When** the operator clicks "Reopen Timeline",
   **Then** the full timeline review page reloads from the saved event data — with all
   previous include/exclude decisions preserved. No re-detection occurs.

3. **Given** the operator changes some event inclusions and clicks "Re-export",
   **Then** only the export phase runs (not detection), producing a new output file in under
   10 minutes for original-quality output.

4. **Given** a job failed with an error,
   **When** the operator clicks "Retry",
   **Then** the job is re-queued and resumes from the last checkpoint if one exists, or
   restarts from the beginning if none was saved.

---

### User Story 6 — Install the Dashboard as a Native App (Priority: P2)

The operator wants to install the dashboard on their phone and laptop so it opens like a
native app — no browser address bar, available from the home screen or taskbar, and
accessible with a single tap.

**Why this priority**: The operator interacts with this tool regularly. A proper installable
app experience reduces friction significantly compared to typing a URL each time.

**Independent Test**: On an Android phone on the same LAN, visit the dashboard URL, use
"Add to Home Screen" in Chrome, and confirm the app opens in standalone mode (no browser
UI) with the CCTV Analyst icon.

**Acceptance Scenarios**:

1. **Given** an Android phone and laptop are on the same Wi-Fi network as the Pi,
   **When** the operator visits the dashboard URL in Chrome and taps the install prompt,
   **Then** the app installs on the home screen and opens in standalone mode (no browser
   address bar, no tabs) with the app icon and name "CCTV Analyst".

2. **Given** the app is installed on the phone,
   **When** the Pi is temporarily unreachable (offline),
   **Then** the app opens and shows the last-loaded app shell with a clear "Pi not reachable"
   message — it does not show a blank screen or browser error page.

3. **Given** the dashboard is first visited in a browser,
   **When** the browser processes the first request,
   **Then** a security certificate warning appears once (because the Pi uses a self-signed
   certificate). After accepting, no further warnings appear on that device.

---

### User Story 7 — Monitor System Health (Priority: P3)

The operator wants a dedicated diagnostics view showing the Pi's current CPU temperature,
RAM usage, disk space, uptime, and temperature history so they can spot thermal or storage
issues before they affect processing.

**Why this priority**: The Pi 5 runs hot during sustained detection. Without visibility,
the operator cannot diagnose slowdowns or storage issues.

**Independent Test**: Open the System page while a job runs. Confirm temperature, CPU %,
RAM %, and disk usage are shown and update without page refresh.

**Acceptance Scenarios**:

1. **Given** the operator opens the System Diagnostics page,
   **Then** they see four gauges (CPU temperature, CPU usage, RAM usage, disk usage) and a
   30-point temperature history sparkline, all updating every 10 seconds without page reload.

2. **Given** the Pi's temperature is below 60°C,
   **Then** the temperature gauge is shown in green. Between 60–75°C: amber. Above 75°C: red
   with a pulsing border. Above the configured thermal limit: a banner warning appears.

3. **Given** disk usage exceeds 85%,
   **When** the operator visits any page (not just System),
   **Then** a persistent warning banner appears at the top: "Disk space low — X GB remaining.
   Free up space before starting new jobs."

---

### User Story 8 — Configure Global Defaults (Priority: P3)

The operator wants to set default values for detection sensitivity, clip padding, minimum
gap, output folder, and other settings that apply to all new jobs. They can override these
per-job when needed.

**Why this priority**: Without persistent defaults, the operator must re-enter their preferred
settings for every single job. Defaults save time on recurring workflows.

**Independent Test**: Change default sensitivity to "High" in Settings. Open New Job form.
Confirm the sensitivity slider defaults to "High" without manual adjustment.

**Acceptance Scenarios**:

1. **Given** the operator opens the Settings page and changes "Default Sensitivity" to "High",
   **When** they save and open the New Job page,
   **Then** the sensitivity slider defaults to "High" for the new job.

2. **Given** the operator saves settings,
   **When** the Pi is rebooted,
   **Then** all saved settings are restored exactly as saved — no reset to factory defaults.

3. **Given** the operator changes a setting and then navigates away without saving,
   **Then** an "Unsaved changes" indicator is shown as a reminder, and the old value is
   preserved until the next save.

---

### Edge Cases

- What happens when the source video file is deleted from disk after the job is submitted?
  → Job fails at the detection start with a clear "Source file not found" error. The job
  is marked failed. No crash, no blank error.

- What happens when two browsers submit jobs at exactly the same time?
  → Only one job runs at a time. Both are queued. The second starts automatically when
  the first completes.

- What happens when the source video has no motion at all (static camera, empty scene)?
  → Detection completes normally. The timeline shows no events. The summary bar shows
  "0 events detected — 0% activity." The Export button is disabled and shows the message
  "No events selected — include at least one event to export."

- What happens when the source video is corrupted or unsupported format?
  → At job submission, the system validates the file. If invalid, the job is rejected
  immediately with a descriptive error before queuing.

- What happens when a clip preview is requested but the source file is on a slow USB drive?
  → A loading spinner is shown. The preview clip is ready within 10 seconds in the
  worst case. The player does not show a blank/broken state during extraction.

- What happens when the user draws detection zones and then changes the video source?
  → The zone canvas resets. Zones from a previous file cannot be applied to a different
  file (different resolution/aspect ratio would make coordinates meaningless).

- What happens when the source recording spans midnight (common for 24h NVR files)?
  → Real clock times on the timeline continue correctly past midnight (e.g., 23:58 → 00:02).
  No timestamp reset or discontinuity visible to the operator.

---

## Requirements

### Functional Requirements

**Video Input**

- **FR-001**: The system MUST accept video files via two methods: server-side filesystem path
  (USB drive plugged into Pi) and browser-based chunked upload (file on operator's device).
- **FR-002**: The system MUST support all major container formats: MP4, MKV, AVI, MOV, TS/MTS, FLV.
- **FR-003**: The system MUST validate the video file at job submission time and reject
  unsupported or corrupted files with a descriptive error message before queuing.
- **FR-004**: The system MUST check available disk space at job submission and reject jobs
  where free space is less than approximately 2.2× the source file size.
- **FR-005**: Large file uploads MUST be chunked (1MB chunks minimum) so that network
  interruptions do not require restarting the entire upload.
- **FR-006**: The file browser MUST only expose paths under configured allowed roots
  (`/media`, `/mnt`, configured input directory) — no filesystem traversal outside these roots.

**Detection**

- **FR-007**: The system MUST detect motion events using background subtraction that adapts
  to slow lighting changes (sunrise, dusk, passing clouds) without triggering false positives.
- **FR-008**: Detection sensitivity MUST be configurable at three plain-language levels:
  Low (large movements: vehicles, groups), Medium (persons, pets, doors), High (subtle motion,
  small animals, distant movement).
- **FR-009**: Operators MUST be able to define up to 5 detection zones by drawing polygons
  on a representative frame from the video. The frame shown MUST be extracted from 10% into
  the source duration (past any camera startup artefacts, representative of the scene
  background). Only motion within the drawn zones triggers events.
- **FR-010**: Event timestamps MUST be accurate to within 1 second for any source video
  regardless of the video's nominal vs actual frame rate.
- **FR-011**: The system MUST apply a configurable padding (default 3 seconds) before and
  after each detected event.
- **FR-012**: Events separated by less than a configurable gap (default 5 seconds) MUST be
  merged into a single event to prevent fragmentation.
- **FR-013**: Events shorter than a configurable minimum duration (default 3 seconds) MUST
  be discarded automatically.
- **FR-014**: Detection MUST produce a checkpoint every ~30 frames so that a crash or power
  loss causes at most 1-2 seconds of re-processed footage on resume — not a full restart.
- **FR-015**: The system MUST pause detection automatically if the device temperature exceeds
  the configured thermal limit (default 80°C) and resume when it cools.

**Progress Monitoring**

- **FR-016**: During detection, the dashboard MUST show in real-time: current timestamp being
  scanned, frames per second, events found so far, estimated time remaining, CPU %, RAM %,
  and device temperature.
- **FR-017**: Real-time updates MUST work across multiple browser tabs simultaneously without
  degrading other dashboard functionality.
- **FR-018**: When the operator reopens a running job's page, they MUST see the last 100
  log lines replayed immediately, followed by live updates from that point.

**Timeline Review**

- **FR-019**: After detection, the operator MUST see a visual horizontal timeline strip
  representing the full source duration with motion events as coloured blocks.
- **FR-020**: Event clock times on the timeline axis MUST reflect real recording times
  (e.g., "02:34 AM") derived from the file's metadata timestamp where available, or elapsed
  time from the job's configured start time.
- **FR-021**: Clicking any event MUST show a thumbnail from the middle of that event,
  its clock start/end time, duration, and detection confidence score.
- **FR-022**: Clicking "Play Clip" on any event MUST open a video player with the clip
  ready to play within 10 seconds.
- **FR-023**: Operators MUST be able to toggle any event between Included and Excluded.
  The timeline and estimated output size MUST update immediately on toggle.
- **FR-024**: Operators MUST be able to tag any event with a label: Person, Vehicle, Animal,
  False Positive, Review Required.
- **FR-025**: Operators MUST be able to include/exclude all events with a single action.
- **FR-026**: The timeline MUST remain responsive with 200+ events — thumbnails MUST load
  only when scrolled into view, not all at once.
- **FR-027**: The summary bar MUST always display: total source duration, total included
  activity duration, activity percentage, estimated output file size, and event counts
  (included / excluded).

**Export**

- **FR-028**: Exporting MUST produce a single output file containing only the included clips
  merged in chronological order.
- **FR-029**: The default export mode MUST use stream copy (no re-encoding), preserving
  original quality and completing in under 10 minutes for a 24-hour source on standard
  1080p H.264 footage.
- **FR-030**: The output MUST include chapter markers, one per exported event, labelled with
  the event's real clock time.
- **FR-031**: The operator MUST be able to choose output quality: Original Quality (stream copy),
  Compressed 720p, or Small File 480p.
- **FR-032**: The system MUST correctly handle CCTV sources with no audio track — the output
  MUST be a clean video-only file with no broken audio headers.
- **FR-033**: The system MUST warn the operator when the source codec requires re-encoding
  (e.g., MJPEG, VP9) and estimate the additional time required before the job starts.
- **FR-034**: After export, the operator MUST be shown: output file path, final size, and
  compression ratio compared to the source.
- **FR-035**: The operator MUST be able to preview the output video in the browser immediately
  after export completes.

**History & Re-export**

- **FR-036**: All past jobs MUST be listed in a History view showing: source filename, processed
  date, source duration, activity duration, activity percentage, most recent output file and size,
  and status. Each job's full export history (all re-export runs) MUST be accessible from the
  job detail view, since re-exports produce new timestamped files rather than overwriting.
- **FR-037**: Reopening a past job MUST reload the exact timeline state (include/exclude
  decisions, tags) from saved data — no re-detection required.
- **FR-038**: Re-exporting a past job with different event selections MUST be possible at
  any time without re-running detection. Each re-export MUST produce a new output file
  with a unique timestamped name (e.g., `footage_activity_20260505_143022.mp4`). Previous
  output files MUST NOT be overwritten or deleted automatically.
- **FR-039**: Failed jobs MUST be retryable. The retry MUST resume from the last saved
  checkpoint if one exists.

**Installable PWA**

- **FR-040**: The dashboard MUST be installable as a PWA on any device on the same network
  (Android, iOS, Windows, macOS) via the browser's "Add to Home Screen" or install prompt.
- **FR-041**: The installed app MUST open in standalone mode — no browser address bar,
  tabs, or navigation chrome.
- **FR-042**: When the Pi is unreachable, the installed app MUST show a clear offline
  message rather than a browser error page.
- **FR-043**: On first visit, users MUST be notified once about the self-signed certificate.
  After acceptance, no further certificate warnings MUST appear from that device.

**System Health**

- **FR-044**: A dedicated System Diagnostics page MUST show: CPU temperature (with 30-point
  history sparkline), CPU usage, RAM usage, disk usage, system uptime, and application version.
- **FR-045**: All pages MUST show a persistent disk space warning banner when disk usage
  exceeds 85%.
- **FR-046**: All system health gauges MUST update every 10 seconds without page reload.

**Settings**

- **FR-047**: Operators MUST be able to set and save global defaults for: detection sensitivity,
  clip padding, minimum gap, output folder, thermal limit, dark/light theme.
- **FR-048**: Per-job settings overrides MUST be stored with the job at submission time and
  MUST NOT be affected by later changes to global defaults.
- **FR-049**: Settings MUST persist across Pi reboots.

**Analytics & Reports**

- **FR-050**: A Reports page MUST show, for any completed job: hourly activity bar chart,
  event duration distribution histogram, total events, included events, activity percentage,
  and peak activity period.
- **FR-051**: Operators MUST be able to export a PDF report containing the activity chart,
  event log table, and job statistics.
- **FR-052**: Operators MUST be able to export a CSV of the event log for use in spreadsheets.

**Audit Log**

- **FR-053**: The system MUST maintain an append-only audit log of all actions: job submissions,
  exports, settings changes, and errors — each with a precise timestamp and description.
- **FR-054**: The audit log MUST be filterable by date range, action type, and job ID, and
  exportable as CSV.
- **FR-055**: When no events are included (either none detected or all excluded), the Export
  button MUST be disabled and display the message "No events selected — include at least one
  event to export." No export process MUST be initiated.

### Key Entities

- **Job**: A processing request. Has a source video, detection settings, status lifecycle
  (queued → detecting → exporting → completed / failed / cancelled), timestamps, and output.
- **Motion Event**: A detected segment of activity. Has start/end times, duration, confidence
  score, optional zone label, tag, thumbnail, and include/exclude state.
- **Timeline**: The full collection of motion events for a job, persisted as a human-readable
  JSON file alongside the job's output.
- **Checkpoint**: A crash-recovery record saved every ~30 frames. Contains the last processed
  frame position and the last confirmed event index.
- **Job Settings**: The frozen snapshot of detection and output configuration at job submission
  time. Immutable after submission.
- **Global Settings**: User-configured defaults applied to all new jobs unless overridden.
- **Audit Entry**: An append-only record of a system action with timestamp, actor (user/system),
  action type, details, and associated job ID.

---

## Success Criteria

### Measurable Outcomes

- **SC-001**: An operator can submit a 24-hour 1080p recording and receive a merged activity
  video in under 2.5 hours on a Raspberry Pi 5 (2GB RAM) running from a USB SSD.

- **SC-002**: Export of a 24-hour source (stream copy mode) completes in under 10 minutes
  regardless of how many events were detected.

- **SC-003**: All event timestamps in the output video are accurate to within 1 second of
  the actual recorded clock time — verified against the source at known positions.

- **SC-004**: The timeline review page remains responsive (scroll, click, toggle) with 200
  or more events loaded — no interaction takes longer than 300ms to respond.

- **SC-005**: The dashboard page load time from cold (first visit) is under 2 seconds on
  the same LAN.

- **SC-006**: A detection job interrupted by a crash or power loss resumes from within
  1-2 seconds of footage from where it stopped — verified by comparing checkpoint timestamps.

- **SC-007**: The system operates within the 1400MB systemd memory ceiling throughout a
  complete 24-hour detection + export job cycle, with no OOM kills.

- **SC-008**: The installed PWA opens in standalone mode (no browser chrome) on Android
  and iOS within 5 seconds of tapping the home screen icon.

- **SC-009**: A false positive rate of under 5% at Medium sensitivity on standard indoor
  H.264 1080p footage in a well-lit environment (verified by manual review of exported
  clips against the source).

- **SC-010**: All past jobs remain accessible and re-exportable from the History page,
  with timeline state preserved exactly, even after a Pi reboot.

---

## Clarifications

### Session 2026-05-05

- Q: Which is the binding clip preview time target — US3 Scenario 3 ("3 seconds") or FR-022 ("10 seconds")? → A: 10 seconds (FR-022) is the binding ceiling. US3 Scenario 3 corrected to match.
- Q: What level of dashboard access control is required for v1? → A: None. Any device on the LAN may access the dashboard. The router/network perimeter is the security boundary. Password-protected access is deferred to v3.
- Q: When all events are excluded or none detected, should Export be disabled or produce empty output? → A: Disabled. Export button shows "No events selected — include at least one event to export." FR-055 added.
- Q: When re-exporting a previously exported job, should the system overwrite, prompt, or create a new file? → A: Always create a new timestamped output file. Previous exports are never overwritten. FR-038 updated.
- Q: Which frame is shown in the zone drawing editor? → A: Frame at 10% into the source duration — past camera startup artefacts, representative of the scene background. FR-009 updated.

## Assumptions

- The Pi 5 runs Raspberry Pi OS Lite (64-bit) and is connected to a home or small office LAN.
- Source video files are pre-recorded (not live streams). Live RTSP input is out of scope for v1.
- The system serves a single operator at a time. Multi-user authentication is out of scope for v1.
- The Pi's USB 3.0 SSD is the recommended storage; microSD is supported for testing only.
- The operator accesses the dashboard from a modern browser (Chrome 110+, Firefox 115+,
  Safari 16+). Internet Explorer and legacy browsers are out of scope.
- Video files from CCTV cameras may have no audio track — this is the expected common case.
- NVR-recorded files may contain internal stream restarts (PTS discontinuities) — the system
  handles these automatically without operator intervention.
- Object classification (person/vehicle/animal labels) is out of scope for v1 — the system
  detects motion but does not classify what caused it.
- Push notifications (Telegram, email) are out of scope for v1.
- Batch folder processing and watch-folder automation are out of scope for v1.
- The dashboard has no authentication or access control in v1. Any device on the same LAN may access it. The network router is the security boundary. This is a deliberate v1 scope decision; password-protected access is planned for v3.
- The PWA uses a self-signed TLS certificate. The operator accepts the browser's one-time
  certificate warning on each new device.
- Source files up to 24 hours in length are the intended maximum; files beyond this are not
  tested and may behave unexpectedly.
