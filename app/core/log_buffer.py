import asyncio
from collections import deque
from typing import Optional

from app.config import LOG_RING_SIZE


class LogBuffer:
    def __init__(self):
        self._history: dict[str, deque] = {}
        self._subscribers: dict[str, list] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def _ensure_job(self, job_id: str) -> None:
        if job_id not in self._history:
            self._history[job_id] = deque(maxlen=LOG_RING_SIZE)
        if job_id not in self._subscribers:
            self._subscribers[job_id] = []

    def append(self, job_id: str, line: str) -> None:
        """Append log line. Thread-safe: bridges worker thread → async SSE (ISSUE-08)."""
        self._ensure_job(job_id)
        self._history[job_id].append(line)
        if self._loop is None:
            return
        for q in list(self._subscribers.get(job_id, [])):
            self._loop.call_soon_threadsafe(q.put_nowait, line)

    def subscribe(self, job_id: str) -> asyncio.Queue:
        """Create a queue and replay last 100 lines into it (I3 fix — not all 2000)."""
        self._ensure_job(job_id)
        q: asyncio.Queue = asyncio.Queue()
        # Replay only the last 100 lines to avoid flooding reconnecting clients
        for line in list(self._history[job_id])[-100:]:
            q.put_nowait(line)
        self._subscribers[job_id].append(q)
        return q

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        subs = self._subscribers.get(job_id, [])
        if queue in subs:
            subs.remove(queue)

    def close(self, job_id: str) -> None:
        """Signal all subscribers that the job stream is done."""
        if self._loop is None:
            return
        for q in list(self._subscribers.get(job_id, [])):
            self._loop.call_soon_threadsafe(q.put_nowait, "__DONE__")

    def clear(self, job_id: str) -> None:
        self._history.pop(job_id, None)
        self._subscribers.pop(job_id, None)


log_buffer = LogBuffer()
