import sqlite3
from dataclasses import dataclass
from typing import Optional


class JobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    DETECTING = "detecting"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DELETED = "deleted"

    VALID = {QUEUED, RUNNING, DETECTING, EXPORTING, COMPLETED, FAILED, CANCELLED, DELETED}
    CANCELLABLE = {QUEUED, RUNNING, DETECTING, EXPORTING}


@dataclass
class Job:
    id: str
    status: str
    source_path: str
    source_name: str
    duration_s: Optional[float]
    source_fps: Optional[float]
    source_width: Optional[int]
    source_height: Optional[int]
    source_codec: Optional[str]
    source_has_audio: bool
    needs_reencode: bool
    file_size: Optional[int]
    settings: dict
    created_at: str
    scheduled_at: Optional[str]
    started_at: Optional[str]
    finished_at: Optional[str]
    error_msg: Optional[str]
    phase: Optional[str]
    progress: float
    output_path: Optional[str]
    output_name: Optional[str]
    output_size: Optional[int]
    recording_start: Optional[str]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Job":
        import json
        d = dict(row)
        d["settings"] = json.loads(d["settings"]) if d["settings"] else {}
        d["source_has_audio"] = bool(d.get("source_has_audio", 0))
        d["needs_reencode"] = bool(d.get("needs_reencode", 0))
        d["progress"] = float(d.get("progress") or 0.0)
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})


@dataclass
class Event:
    id: int
    job_id: str
    event_index: int
    start_s: float
    end_s: float
    duration_s: float
    start_clock: Optional[str]
    end_clock: Optional[str]
    peak_motion_score: Optional[float]
    zone_label: Optional[str]
    tag: Optional[str]
    included: bool
    thumbnail_path: Optional[str]
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Event":
        d = dict(row)
        d["included"] = bool(d.get("included", 1))
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "event_index": self.event_index,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "duration_s": self.duration_s,
            "start_clock": self.start_clock,
            "end_clock": self.end_clock,
            "peak_motion_score": self.peak_motion_score,
            "zone_label": self.zone_label,
            "tag": self.tag,
            "included": self.included,
            "thumbnail_path": (
                f"/api/thumbnails/{self.job_id}/{self.event_index}.jpg"
                if self.thumbnail_path else None
            ),
            "created_at": self.created_at,
        }


@dataclass
class AuditEntry:
    id: int
    ts: str
    level: str
    actor: str
    action: str
    detail: Optional[str]
    job_id: Optional[str]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "AuditEntry":
        d = dict(row)
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})


@dataclass
class GlobalSettings:
    default_output_dir: str = "~/cctv_output"
    default_sensitivity: str = "medium"
    default_padding_s: int = 3
    default_min_gap_s: int = 5
    default_min_event_s: int = 3
    default_output_quality: str = "original"
    default_frame_skip: int = 1
    hw_decode: bool = False
    thermal_limit_c: int = 80
    disk_warn_percent: int = 85
    dark_mode: str = "system"
    mog2_history: Optional[int] = None
    allowed_browse_roots: list = None

    def __post_init__(self):
        if self.allowed_browse_roots is None:
            self.allowed_browse_roots = ["/media", "/mnt"]
