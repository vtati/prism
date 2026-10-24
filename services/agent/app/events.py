"""In-process event bus: graph nodes emit, the SSE endpoint streams."""
from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_events: dict[str, list[dict]] = {}


def emit(run_id: str, node: str, agent: str, status: str, message: str, data: dict | None = None) -> dict:
    ev = {
        "run_id": run_id,
        "node": node,
        "agent": agent,
        "status": status,
        "message": message,
        "data": data or {},
        "ts": time.time(),
    }
    with _lock:
        _events.setdefault(run_id, []).append(ev)
    print(f"[prism:{run_id}] {agent}/{node} {status}: {message}", flush=True)
    return ev


def get_events(run_id: str) -> list[dict]:
    with _lock:
        return list(_events.get(run_id, []))
