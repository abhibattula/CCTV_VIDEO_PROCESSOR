import shutil
import threading
import time
from collections import deque
from datetime import datetime, timezone

import psutil
from fastapi import APIRouter

from app.config import DATA_DIR, RAM_MODE
from app.utils.system import get_cpu_temp

router = APIRouter()

# Rolling temperature history: last 30 readings (10s interval)
_temp_history: deque = deque(maxlen=30)
_temp_poller_started = False
_temp_lock = threading.Lock()


def _poll_temp() -> None:
    global _temp_poller_started
    temp = get_cpu_temp()
    with _temp_lock:
        _temp_history.append((int(time.time()), temp))
    # Reschedule itself every 10 seconds
    t = threading.Timer(10.0, _poll_temp)
    t.daemon = True
    t.start()


def _ensure_poller() -> None:
    global _temp_poller_started
    if not _temp_poller_started:
        _temp_poller_started = True
        _poll_temp()


@router.get("/system/stats")
def system_stats():
    _ensure_poller()

    cpu_pct = psutil.cpu_percent(interval=None)
    vm = psutil.virtual_memory()
    temp = get_cpu_temp()

    try:
        disk = shutil.disk_usage(str(DATA_DIR))
        disk_used_gb = disk.used / 1e9
        disk_total_gb = disk.total / 1e9
        disk_percent = disk.used / disk.total * 100 if disk.total else 0
    except OSError:
        disk_used_gb = disk_total_gb = disk_percent = 0.0

    from app.config import THERMAL_LIMIT_C
    try:
        config_path = DATA_DIR.parent / "config.json"
        if config_path.exists():
            import json
            cfg = json.loads(config_path.read_text())
            disk_warn_pct = cfg.get("disk_warn_percent", 85)
        else:
            disk_warn_pct = 85
    except Exception:
        disk_warn_pct = 85

    with _temp_lock:
        temp_history = list(_temp_history)

    return {
        "cpu_percent": round(cpu_pct, 1),
        "ram_percent": round(vm.percent, 1),
        "ram_used_mb": round(vm.used / 1e6, 0),
        "ram_total_mb": round(vm.total / 1e6, 0),
        "temp_c": round(temp, 1) if temp is not None else None,
        "temp_c_history": temp_history,
        "disk_used_gb": round(disk_used_gb, 1),
        "disk_total_gb": round(disk_total_gb, 1),
        "disk_warn": disk_percent > disk_warn_pct,
        "uptime_s": int(time.time() - psutil.boot_time()),
        "app_version": "1.0.0",
        "ram_mode": RAM_MODE,
    }
