import shutil
import subprocess
from pathlib import Path
from typing import Optional


def get_cpu_temp() -> Optional[float]:
    """Return CPU temp in Celsius. Returns None if unavailable — never crashes (ISSUE-14)."""
    # Try vcgencmd first (Pi-native)
    try:
        out = subprocess.check_output(
            ["vcgencmd", "measure_temp"], text=True, timeout=2
        )
        # output: "temp=54.2'C\n"
        return float(out.strip().replace("temp=", "").replace("'C", ""))
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass

    # Fallback: Linux thermal zone sysfs
    thermal = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        return int(thermal.read_text().strip()) / 1000.0
    except (FileNotFoundError, ValueError, OSError):
        return None


def get_disk_usage(path: str) -> dict:
    usage = shutil.disk_usage(path)
    return {
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "percent": usage.used / usage.total * 100 if usage.total else 0.0,
    }
