import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from app.core.audit_logger import log as audit_log

router = APIRouter()

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config.json"

_DEFAULTS = {
    "default_output_dir": "~/cctv_output",
    "default_sensitivity": "medium",
    "default_padding_s": 3,
    "default_min_gap_s": 5,
    "default_min_event_s": 3,
    "default_output_quality": "original",
    "default_frame_skip": 1,
    "hw_decode": False,
    "thermal_limit_c": 80,
    "disk_warn_percent": 85,
    "dark_mode": "system",
    "mog2_history": None,
    "allowed_browse_roots": ["/media", "/mnt"],
}


class SettingsModel(BaseModel):
    default_output_dir: Optional[str] = None
    default_sensitivity: Optional[str] = None
    default_padding_s: Optional[int] = None
    default_min_gap_s: Optional[int] = None
    default_min_event_s: Optional[int] = None
    default_output_quality: Optional[str] = None
    default_frame_skip: Optional[int] = None
    hw_decode: Optional[bool] = None
    thermal_limit_c: Optional[int] = None
    disk_warn_percent: Optional[int] = None
    dark_mode: Optional[str] = None
    mog2_history: Optional[int] = None
    allowed_browse_roots: Optional[list] = None

    @field_validator("thermal_limit_c")
    @classmethod
    def validate_thermal(cls, v):
        if v is not None and not (60 <= v <= 90):
            raise ValueError("thermal_limit_c must be between 60 and 90")
        return v

    @field_validator("disk_warn_percent")
    @classmethod
    def validate_disk_warn(cls, v):
        if v is not None and not (50 <= v <= 95):
            raise ValueError("disk_warn_percent must be between 50 and 95")
        return v

    @field_validator("default_sensitivity")
    @classmethod
    def validate_sensitivity(cls, v):
        if v is not None and v not in ("low", "medium", "high"):
            raise ValueError("sensitivity must be low, medium, or high")
        return v


def _read_config() -> dict:
    if _CONFIG_PATH.exists():
        try:
            return json.loads(_CONFIG_PATH.read_text())
        except Exception:
            pass
    return dict(_DEFAULTS)


@router.get("/settings")
def get_settings():
    return _read_config()


@router.put("/settings")
def put_settings(body: SettingsModel):
    current = _read_config()
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    current.update(updates)
    _CONFIG_PATH.write_text(json.dumps(current, indent=2))
    audit_log("SETTINGS_CHANGED", actor="user")
    return {"saved": True}
