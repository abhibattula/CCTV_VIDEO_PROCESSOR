import time
from typing import Callable

import psutil

from app.config import RAM_GUARD_PERCENT, THERMAL_LIMIT_C
from app.utils.system import get_cpu_temp


def check(job_id: str, logger_fn: Callable[[str], None]) -> None:
    """Check RAM and CPU temp; throttle if over thresholds (ISSUE-03, ISSUE-14)."""
    vm = psutil.virtual_memory()
    used_pct = vm.percent
    if used_pct > RAM_GUARD_PERCENT:
        logger_fn(f"[RAM GUARD] {used_pct:.0f}% RAM used — throttling")
        time.sleep(2)

    temp = get_cpu_temp()
    if temp is not None and temp > THERMAL_LIMIT_C:
        logger_fn(f"[THERMAL] {temp:.1f}°C — pausing detection (limit {THERMAL_LIMIT_C}°C)")
        time.sleep(5)
