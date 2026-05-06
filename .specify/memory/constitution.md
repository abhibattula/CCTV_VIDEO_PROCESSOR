<!--
SYNC IMPACT REPORT
==================
Version change: [template/unfilled] → 1.0.0 (initial ratification)
Modified principles: N/A — initial draft
Added sections:
  - Core Principles (7 principles)
  - Hardware & Performance Standards
  - Superpowers + SpecKit Hybrid Workflow
  - Documentation Requirements
  - Governance
Templates requiring updates:
  ✅ .specify/memory/constitution.md — this file (updated)
  ✅ .specify/templates/plan-template.md — Constitution Check gates align with principles below
  ✅ .specify/templates/spec-template.md — FR/SC sections must reference ISSUES.md and CCTV spec docs
  ✅ .specify/templates/tasks-template.md — task phases align with 10-phase implementation plan
  ⚠️  .specify/templates/commands/*.md — agent-specific references reviewed; no updates needed
Deferred TODOs: None — all placeholders filled.
-->

# RasPi CCTV Analyst — Project Constitution

## Core Principles

### I. Privacy-First, Local-Only (NON-NEGOTIABLE)

All video data, motion analysis, thumbnails, timelines, and exported clips MUST remain entirely
on the local device. No frame, no metadata, and no user configuration may ever be transmitted
to an external server, cloud service, or third-party API.

- Network access is permitted only for serving the dashboard to devices on the same LAN.
- All dependencies (Python packages, FFmpeg, OpenCV) are installed locally at setup time.
- Notifications (future v2.0) MUST be opt-in and user-configured only; disabled by default.

**Rationale**: The system processes private CCTV footage of homes, businesses, and people.
Any cloud dependency — even for analytics or updates — violates user trust and potentially
applicable privacy law. This principle is absolute and supersedes convenience.

### II. Hardware-Adaptive (Pi 5 2GB as Minimum Viable Target)

Every component MUST function correctly on a Raspberry Pi 5 with 2GB RAM. Higher-RAM
configurations (4GB+) may unlock additional features but the baseline MUST be rock-solid.

RAM-adaptive configuration MUST be applied at startup, not hardcoded:
- Detection resolution: 320×240 (2GB) / 640×480 (4GB)
- Frame batch size: 30 (2GB) / 120 (4GB)
- FFmpeg threads: 2 (2GB) / 4 (4GB)
- YOLOv8n: disabled (2GB) / enabled (4GB)

System-wide RAM guard MUST monitor `psutil.virtual_memory().available` (not process RSS)
to account for FFmpeg subprocess memory. Thermal guard MUST use a graceful fallback if
`vcgencmd` is unavailable (non-Pi deployment, Docker, development).

**Rationale**: The Pi 5 2GB is the committed minimum hardware target. Every new component,
dependency, and feature MUST be validated against this constraint before merging.
Exceeding the memory budget risks OOM kills that corrupt in-progress 2-hour detection jobs.

### III. Accuracy Over Speed

Motion detection accuracy MUST take precedence over detection speed. Acceptable false-negative
rate is higher than acceptable false-positive rate — users prefer missing a rare event over
reviewing hours of false-alarm footage.

MUST apply:
- Morphological OPEN + CLOSE kernel filtering on MOG2 foreground mask before scoring.
- Accurate per-frame PTS timestamps from FFmpeg `showinfo` filter (not frame count ÷ FPS).
- MOG2 history parameter matched to sensitivity setting (low=700, medium=500, high=200).
- 500-frame MOG2 warmup pass after any crash resume to prevent false-positive flood.

Frame skip MUST be applied via FFmpeg `fps` filter, not in Python, to reduce pipe bandwidth
and allow FFmpeg to skip non-reference frame decoding.

**Rationale**: This tool's value is reducing hours of footage to minutes of relevant content.
False positives erode trust immediately. A missed event is unfortunate; a system that cries
wolf constantly will be abandoned after one use.

### IV. Resilience & Crash Recovery (NON-NEGOTIABLE)

Every long-running operation MUST be checkpointable and resumable. A power cut, thermal
shutdown, or OOM kill on a 2-hour detection job MUST not require restarting from zero.

Requirements:
- Detection engine MUST write `checkpoint.json` every `BATCH_SIZE` frames (30 in 2GB mode).
- Checkpoint MUST record: `frames_processed`, `pts_time`, `last_confirmed_event_index`.
- On resume: DELETE events after `last_confirmed_event_index` before re-detecting (prevents duplicates).
- On resume: Run 500-frame MOG2 warmup pass before recording events.
- Export engine MUST use `-fflags +genpts+igndts` on all segment extractions to handle NVR
  PTS discontinuities from stream restarts.
- Job queue MUST restore any `running`/`detecting`/`exporting` jobs to `queued` on startup.

**Rationale**: Processing 24-hour CCTV footage takes 1-2 hours on Pi. Crashes happen — power
outages, thermal throttling, OOM events. Losing all progress is unacceptable and guaranteed
to drive users away permanently.

### V. Progressive Web App, No Framework Dependencies

The frontend MUST be a PWA served by the Pi's FastAPI backend. It MUST be installable on
any device on the LAN with no separate app store or client-side installation.

Frontend MUST be implemented in Vanilla HTML5 + CSS + JavaScript (ES Modules):
- Zero npm build step in production. No React, Vue, or Angular.
- No CSS preprocessors. CSS Custom Properties only.
- Client-side router using native `import()` dynamic module loading.
- Zero `innerHTML` assignments with API-sourced data (XSS prevention). Use `el()` builder.
- `IntersectionObserver` for lazy loading thumbnails (never load 200 JPEGs eagerly).

PWA MUST be served over HTTPS (self-signed TLS cert, auto-generated by `install.sh`).
Service workers MUST only cache the app shell — never cache API responses.

Responsive behaviour MUST be handled via `window.matchMedia('(pointer: coarse)')`:
- Touch: canvas height 80px, event segments ≥12px wide, 4-hour pan windows.
- Mouse: canvas height 48px, standard interactions.

**Rationale**: A framework introduces a build step, Node.js dependency, and update surface
that is impractical to maintain on an embedded Pi device. The Vanilla JS approach means the
app runs identically on Pi OS and any other Linux with zero build tooling.

### VI. Transparency & Human-Readable Data

All application state MUST be human-readable and recoverable without the application itself.

MUST:
- `timeline.json` written per-job in documented JSON schema (see spec docs in `AI research/`).
- `checkpoint.json` written per-job and readable by any text editor.
- `config.json` for all user settings — never a binary format.
- SQLite (`cctv_analyst.db`) for job state — inspectable with any SQLite client.
- Audit log MUST record all system actions: job submissions, exports, settings changes, errors.
- All filenames in the audit log and job queue MUST be rendered via DOM `textContent`
  (never `innerHTML`) to prevent XSS from adversarially-named files.

MUST NOT:
- Store any state only in memory that cannot be reconstructed from disk artifacts.
- Use pickle, binary config formats, or proprietary databases.

**Rationale**: This is a single-user self-hosted tool. The user MUST be able to understand,
back up, restore, or migrate their data with standard tools. A `cp -r` should be sufficient
for full backup.

### VII. Superpowers + SpecKit Hybrid Workflow (MANDATORY FOR ALL IMPLEMENTATION)

All implementation in this project MUST follow the Superpowers + SpecKit hybrid pattern.
Neither system alone is sufficient; the combination delivers the discipline and intelligence
required for a professional, Pi-optimised production system.

**SpecKit provides the workflow gates:**
- `/speckit-constitution` — governance ratification (this document)
- `/speckit-specify` — feature specification with testable user stories
- `/speckit-clarify` — requirement disambiguation before planning
- `/speckit-plan` — phased implementation planning with Constitution Checks
- `/speckit-tasks` — atomic, parallelisable task breakdown
- `/speckit-implement` — guided implementation with quality gates
- `/speckit-checklist` — post-implementation compliance verification

**Superpowers provides the intelligence layer:**
- `superpowers:brainstorm` — deep issue discovery BEFORE any implementation (as demonstrated:
  17 issues found before Phase 1 began, documented in `ISSUES.md`)
- `superpowers:code-reviewer` — independent review after each major phase completion
- Plan mode (`/plan`) — architecture alignment before touching code
- Effort mode (`/effort max`) — maximum reasoning depth for hardware-constrained decisions

**Mandatory hybrid sequence for every feature/phase:**
```
1. /speckit-specify        → Define what we're building (user stories + acceptance criteria)
2. superpowers:brainstorm  → Find issues BEFORE implementation
3. /speckit-clarify        → Resolve any ambiguities surfaced in brainstorm
4. /plan                   → Architecture alignment
5. /speckit-plan           → Phased plan with Constitution Checks
6. /speckit-tasks          → Atomic task list
7. /speckit-implement      → Build (with ISSUES.md fixes embedded)
8. superpowers:code-reviewer → Independent phase review
9. /speckit-checklist      → Compliance verification
```

**Rationale**: This project has a hard hardware target (Pi 5 2GB), a complex detection pipeline,
and real-world accuracy requirements. Shortcuts in workflow discipline surface as corrupted
exports, OOM crashes, or false positives at 2 AM. The hybrid pattern was already validated
in pre-implementation review: 17 issues caught before a single line of application code was
written.

## Hardware & Performance Standards

### Validated Hardware Target

| Component | Minimum | Recommended |
|---|---|---|
| Device | Raspberry Pi 5 (2GB RAM) | Raspberry Pi 5 (4GB RAM) |
| Storage | 64GB microSD (dev/test only) | 256GB USB 3.0 SSD |
| OS | Raspberry Pi OS Lite 64-bit | Raspberry Pi OS Lite 64-bit |
| Power | Official 27W USB-C PSU | Official 27W USB-C PSU |
| Cooling | Active cooler recommended | Active cooler required |

### Performance Benchmarks (Pass/Fail Gates)

All implementation MUST meet these benchmarks on Pi 5 2GB USB SSD before a phase is
considered complete:

| Workload | Maximum Allowed Time |
|---|---|
| 1-hour 1080p H.264 detection | ≤ 8 minutes |
| 24-hour 1080p H.264 detection | ≤ 2.5 hours |
| 24-hour export (stream copy) | ≤ 10 minutes |
| Dashboard page load (cold) | ≤ 2 seconds |
| Timeline canvas redraw | ≤ 5ms |
| PDF report generation | ≤ 5 seconds |
| Thumbnail generation (per event) | ≤ 3 seconds |

### Memory Budget (Hard Limits)

| Component | Budget |
|---|---|
| Python process (FastAPI + detection) | ≤ 200MB |
| FFmpeg subprocess (1080p decode) | ≤ 150MB |
| OS + system | ≤ 600MB |
| **Total system budget** | **≤ 1400MB** (systemd MemoryMax) |

RAM guard MUST throttle at 75% system memory used. If `psutil.virtual_memory().available`
falls below 25% of total, detection MUST pause for 2 seconds before next batch.

### Disk Space Requirements

At job creation, MUST check: `free_bytes >= source_size × 2.2`. If insufficient, MUST
reject the job with HTTP 400 and an actionable message before queuing.

## Superpowers + SpecKit Hybrid Development Workflow

### Phase Gate Checklist

Every implementation phase MUST pass these gates before the next phase begins:

**Before Phase N starts:**
- [ ] SpecKit spec or plan updated for this phase
- [ ] `superpowers:brainstorm` run if phase introduces new architecture decisions
- [ ] Constitution Check passed (see plan-template.md gates)
- [ ] ISSUES.md reviewed — all applicable fixes confirmed embedded in this phase

**After Phase N completes:**
- [ ] `superpowers:code-reviewer` agent run for independent review
- [ ] `/speckit-checklist` run for compliance verification
- [ ] Git commit with descriptive message (SpecKit commit format)
- [ ] Benchmark targets met (if applicable to phase)

### Pre-Implementation Brainstorm Requirement

For any phase involving:
- A new backend component (detection engine, export engine, API layer)
- A new frontend page or complex component
- Any change to the SQLite schema
- Any FFmpeg command pipeline

`superpowers:brainstorm` MUST be run against the specific scope BEFORE implementation.
All discovered issues MUST be documented (in `ISSUES.md` or equivalent) and incorporated
into the implementation — not deferred as "known issues".

### Documentation Requirements

All implementation MUST maintain these documents in sync:

| Document | Owner Phase | Update Trigger |
|---|---|---|
| `ISSUES.md` | Pre-implementation | New issue found at any point |
| `CLAUDE.md` | Phase 1 | Any new project-wide constraint added |
| `AI research/*.docx/*.md` | Reference only | Read-only source of truth |
| `.specify/memory/constitution.md` | Governance | Any principle change |
| `requirements.txt` | Phase 1 | Any dependency add/remove |
| `install.sh` | Phase 10 | Any new system dependency |
| `README.md` | Phase 10 | After v1.0 implementation complete |
| Phase plan in `.claude/plans/` | Per feature | After each phase completes |

**Inline documentation MUST follow these rules:**
- Comments: only when the WHY is non-obvious (hidden constraint, subtle invariant, bug workaround)
- No multi-paragraph docstrings or multi-line comment blocks — one short line maximum
- No comments explaining WHAT the code does (identifiers do that)
- No "added for X" or "used by Y" comments (they rot; belong in commit messages)

### Code Review Standards

Every PR/commit MUST be independently reviewed by `superpowers:code-reviewer` before merge.
The reviewer MUST specifically check:
1. All applicable ISSUES.md fixes are present and correct
2. No `innerHTML` with API-sourced data (ISSUE-16)
3. `vcgencmd` calls use graceful fallback (ISSUE-14)
4. FFmpeg commands include `-fflags +genpts+igndts` (ISSUE-10)
5. SSE uses asyncio.Queue, not blocking iterator (ISSUE-08)
6. RAM guard checks system-wide, not process RSS (ISSUE-03)

## Governance

### Amendment Procedure

This constitution supersedes all prior verbal agreements, informal conventions, and spec
document guidance when a conflict exists. To amend:

1. Run `/speckit-constitution` with proposed changes stated explicitly.
2. Version MUST be bumped according to semantic versioning:
   - **MAJOR**: Principle removed, redefined, or fundamentally changed.
   - **MINOR**: New principle, section, or materially expanded guidance added.
   - **PATCH**: Clarification, wording, typo, non-semantic refinement.
3. Sync Impact Report MUST be produced and prepended (as HTML comment) to this file.
4. Amendment committed with message: `docs: amend constitution to vX.Y.Z (description)`.

### Compliance Review

- Constitution Check in every plan (`.specify/templates/plan-template.md`) MUST reference
  these principles. Any plan that cannot pass Constitution Check requires an amendment —
  not a workaround.
- All `superpowers:code-reviewer` sessions MUST verify compliance with Principles I–VII.
- Principle II (Hardware-Adaptive) MUST be validated on actual Pi 5 2GB hardware before
  any phase is declared "done" in production context.

### Non-Negotiable Principles

Principles I (Privacy-First) and IV (Resilience & Crash Recovery) are marked NON-NEGOTIABLE.
They cannot be downgraded by any convenience argument, time pressure, or scope reduction.
If a feature cannot be implemented without violating either, the feature is descoped — the
principle is not weakened.

### Reference Documents

Runtime development guidance and issue register:
- `ISSUES.md` — pre-implementation issue register with all 17 discovered issues and fixes
- `AI research/CCTV_Extractor_Documentation.md` — primary technical specification
- `AI research/RasPi_CCTV_Frontend_Spec.docx` — frontend specification (Document 1 of 2)
- `AI research/RasPi_CCTV_Backend_Spec.docx` — backend specification (Document 2 of 2)
- `.claude/plans/functional-prancing-sunrise.md` — current implementation plan (10 phases)

---

**Version**: 1.0.0 | **Ratified**: 2026-05-05 | **Last Amended**: 2026-05-05
