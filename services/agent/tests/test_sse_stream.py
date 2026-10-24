"""Regression tests for the SSE event stream.

Incident (2026-10-24 ~17:10 ET): a live UI run sat at 0/6 artifacts for
~372s, then the UI showed "Live stream dropped — replaying recorded demo".
One root cause on the server side: the stream emitted NOTHING during the
whole Scout sweep (measured 133.6s of byte silence; the incident sweep ran
longer), so any idle timeout between server and browser could kill the
connection while the run continued server-side.

Contract these tests lock in:
- every data frame carries an `id:` (its event index), so an EventSource
  reconnect can resume via Last-Event-ID instead of replaying/duplicating;
- when no event has been emitted for HEARTBEAT_S seconds, the stream emits
  an `event: ping` frame — the connection never goes byte-silent while a
  run is active;
- resume via last_event_id yields only later events.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main  # noqa: E402
from app.events import emit  # noqa: E402


def _seed(run_id: str, n: int = 3) -> None:
    for i in range(n):
        emit(run_id, "scout", "Scout", "progress", f"event {i}")


async def _collect(run_id, last_event_id=None, seconds=0.0):
    frames = []
    agen = main._stream_frames(run_id, last_event_id=last_event_id)
    if seconds:
        async def _run():
            async for f in agen:
                frames.append(f)
        try:
            await asyncio.wait_for(_run(), timeout=seconds)
        except asyncio.TimeoutError:
            pass
    else:
        async for f in agen:
            frames.append(f)
    return frames


def _data_frames(frames):
    return [f for f in frames if f.startswith("id:")]


def test_frames_carry_ids_and_stop_at_terminal_status():
    run_id = "test-sse-ids"
    _seed(run_id, 3)
    with main._lock:
        main._runs[run_id] = {"run_id": run_id, "status": "shipped"}
    frames = asyncio.run(_collect(run_id))
    data = _data_frames(frames)
    assert len(data) == 3, frames
    for i, frame in enumerate(data):
        head, _, payload = frame.partition("\n")
        assert head == f"id: {i}", frame
        ev = json.loads(payload.removeprefix("data: ").strip())
        assert ev["message"] == f"event {i}"


def test_resume_via_last_event_id_skips_seen_events():
    run_id = "test-sse-resume"
    _seed(run_id, 3)
    with main._lock:
        main._runs[run_id] = {"run_id": run_id, "status": "shipped"}
    frames = asyncio.run(_collect(run_id, last_event_id=1))
    data = _data_frames(frames)
    assert len(data) == 1, frames
    assert data[0].startswith("id: 2"), data[0]


def test_heartbeat_pings_while_run_active_and_silent(monkeypatch):
    run_id = "test-sse-ping"
    monkeypatch.setattr(main, "HEARTBEAT_S", 0.2)
    with main._lock:
        main._runs[run_id] = {"run_id": run_id, "status": "running"}
    frames = asyncio.run(_collect(run_id, seconds=1.6))
    pings = [f for f in frames if f.startswith("event: ping")]
    assert len(pings) >= 2, frames
