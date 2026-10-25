"""Prism agent API. Contract (frontend depends on this — do not drift):
POST /runs {playbook_id, topic?} -> {run_id}
GET  /runs/{id}/events   SSE stream of {node, agent, status, message, data}
GET  /runs/{id}          state incl. artifacts + review verdicts
POST /runs/{id}/approve {decision: approve|changes, notes?} -> resumes graph
GET  /playbooks          list
GET  /health
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import BaseModel

from .config import CHECKPOINT_DB, RUNS_DIR
from .events import emit, get_events
from .graph import build_graph
from .llm import get_llm
from .makers import _render_direct
from .playbooks import list_playbooks, load_playbook

app = FastAPI(title="Prism Agent API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_conn = sqlite3.connect(str(CHECKPOINT_DB), check_same_thread=False)
_checkpointer = SqliteSaver(_conn)
_graph = build_graph(checkpointer=_checkpointer)
_runs: dict[str, dict] = {}
_lock = threading.Lock()
_exec_locks: dict[str, threading.Lock] = {}


def _exec_lock(run_id: str) -> threading.Lock:
    with _lock:
        return _exec_locks.setdefault(run_id, threading.Lock())


class RunRequest(BaseModel):
    playbook_id: str
    topic: str | None = None


class ApproveRequest(BaseModel):
    decision: str  # approve | changes
    notes: str | None = None


def _config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def _interrupt_pending(result, snap) -> bool:
    """True only when the graph is genuinely paused at an interrupt (the
    human gate). A checkpoint having next nodes is NOT evidence of a pause:
    mid-execution snapshots carry next nodes too."""
    if isinstance(result, dict) and result.get("__interrupt__"):
        return True
    return bool(getattr(snap, "interrupts", None))


def _run_graph(run_id: str, initial: dict | None, resume: dict | None = None) -> None:
    exec_lock = _exec_lock(run_id)
    if not exec_lock.acquire(blocking=False):
        # A graph invoke for this run is already in flight. Starting a
        # second one concurrently on the same thread wedges the run —
        # refuse instead (the /approve endpoint also guards this).
        emit(run_id, "api", "API", "error",
             "Graph invoke already in progress for this run; ignoring duplicate start/resume")
        return
    try:
        with _lock:
            run = _runs.setdefault(run_id, {"run_id": run_id, "state": {}})
            run["status"] = "running"
            run["executing"] = True
            run["paused_at_gate"] = False
        try:
            if resume is not None:
                result = _graph.invoke(Command(resume=resume), _config(run_id))
            else:
                result = _graph.invoke(initial, _config(run_id))
            snap = _graph.get_state(_config(run_id))
            vals = snap.values or {}
            paused = _interrupt_pending(result, snap)
            # awaiting_approval ONLY on a real pending interrupt; while the
            # graph is executing the registry simply stays "running".
            status = "awaiting_approval" if paused else vals.get("status", "done")
            with _lock:
                _runs[run_id]["status"] = status
                _runs[run_id]["paused_at_gate"] = paused
                _runs[run_id]["state"] = _clean(vals)
        except Exception as exc:
            with _lock:
                _runs[run_id]["status"] = "failed"
                _runs[run_id]["paused_at_gate"] = False
                _runs[run_id]["error"] = str(exc)
            emit(run_id, "api", "API", "error", f"Run failed: {exc}")
    finally:
        with _lock:
            if run_id in _runs:
                _runs[run_id]["executing"] = False
        exec_lock.release()


def _clean(vals: dict) -> dict:
    out = {}
    for k, v in vals.items():
        try:
            json.dumps(v)
            out[k] = v
        except Exception:
            out[k] = str(v)
    return out


# ---------- carousel artifact serving ----------

def _load_run_state(run_id: str) -> dict | None:
    """The run's state dict, resolved the same way GET /runs/{run_id}
    resolves it: the in-process registry first (refreshed from the
    checkpoint), else the checkpoint snapshot alone (server restart).
    None when the run is unknown."""
    with _lock:
        run = _runs.get(run_id)
    if run is not None:
        state = run.get("state") or {}
        try:
            snap = _graph.get_state(_config(run_id))
            if snap and snap.values:
                state = _clean(snap.values)
        except Exception:
            pass
        return state
    try:
        snap = _graph.get_state(_config(run_id))
        if snap and snap.values:
            return _clean(snap.values)
    except Exception:
        pass
    return None


def find_carousel_artifact(artifacts: dict) -> dict | None:
    """The carousel artifact in a run's artifacts dict: by its maker key
    ('linkedin_carousel') first, else any artifact of that type."""
    arts = artifacts or {}
    art = arts.get("linkedin_carousel")
    if isinstance(art, dict):
        return art
    for v in arts.values():
        if isinstance(v, dict) and v.get("type") == "linkedin_carousel":
            return v
    return None


def _regenerate_carousel(artifact: dict, run_id: str) -> dict | None:
    """Re-render from the artifact's retained spec via the direct
    renderer into RUNS_DIR/<run_id>/carousel. None when impossible."""
    spec = artifact.get("spec")
    if not spec:
        return None
    out_dir = RUNS_DIR / run_id / "carousel"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        return _render_direct(spec, str(out_dir))
    except Exception:
        return None


def resolve_carousel_file(artifacts: dict, run_id: str, slide: int | None = None) -> Path | None:
    """Filesystem path of the carousel PDF (slide=None) or of the 1-based
    slide PNG. When the recorded file is missing, the carousel is
    regenerated from the artifact's retained spec and the fresh path is
    returned. None when there is no carousel artifact, the slide is out
    of range, or no file can be produced."""
    art = find_carousel_artifact(artifacts)
    if art is None:
        return None
    if slide is not None:
        if slide < 1:
            return None
        paths = art.get("png_paths") or []
        if slide <= len(paths) and Path(paths[slide - 1]).is_file():
            return Path(paths[slide - 1])
        result = _regenerate_carousel(art, run_id)
        if result:
            paths = result.get("png_paths") or []
            if slide <= len(paths) and Path(paths[slide - 1]).is_file():
                return Path(paths[slide - 1])
        return None
    pdf = art.get("pdf_path")
    if pdf and Path(pdf).is_file():
        return Path(pdf)
    result = _regenerate_carousel(art, run_id)
    if result:
        pdf = result.get("pdf_path")
        if pdf and Path(pdf).is_file():
            return Path(pdf)
    return None


@app.get("/health")
def health():
    llm = get_llm()
    return {"status": "ok", "llm_mode": llm.mode, "llm_provider": llm.provider, "llm_model": llm.model}


@app.get("/playbooks")
def playbooks():
    return {"playbooks": list_playbooks()}


@app.post("/runs")
def create_run(req: RunRequest):
    try:
        load_playbook(req.playbook_id)
    except FileNotFoundError:
        raise HTTPException(404, f"playbook not found: {req.playbook_id}")
    run_id = uuid.uuid4().hex[:12]
    initial = {"run_id": run_id, "playbook_id": req.playbook_id, "input": req.topic or ""}
    with _lock:
        _runs[run_id] = {"run_id": run_id, "playbook_id": req.playbook_id, "status": "queued",
                         "state": {}, "paused_at_gate": False, "executing": False}
    t = threading.Thread(target=_run_graph, args=(run_id, initial), daemon=True)
    t.start()
    return {"run_id": run_id}


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    with _lock:
        run = _runs.get(run_id)
    if run is None:
        # try checkpoint state (server restart). No invoke is in flight in
        # this process, so a pending interrupt here really is the gate.
        try:
            snap = _graph.get_state(_config(run_id))
            if snap and snap.values:
                status = snap.values.get("status", "unknown")
                if getattr(snap, "interrupts", None):
                    status = "awaiting_approval"
                return {"run_id": run_id, "status": status,
                        "state": _clean(snap.values), "events": get_events(run_id)}
        except Exception:
            pass
        raise HTTPException(404, "run not found")
    # Refresh artifact state from the checkpoint, but NEVER derive status
    # from the snapshot: snap.next is non-empty throughout execution, so the
    # registry's explicit lifecycle (running / awaiting_approval / terminal)
    # is the only source of truth for status.
    try:
        snap = _graph.get_state(_config(run_id))
        if snap and snap.values:
            run = dict(run)
            run["state"] = _clean(snap.values)
    except Exception:
        pass
    return {**run, "events": get_events(run_id)}


@app.get("/runs/{run_id}/carousel.pdf")
def get_carousel_pdf(run_id: str):
    state = _load_run_state(run_id)
    if state is None:
        raise HTTPException(404, "run not found")
    path = resolve_carousel_file(state.get("artifacts") or {}, run_id)
    if path is None:
        raise HTTPException(404, "no carousel artifact for run")
    return FileResponse(path, media_type="application/pdf", filename="carousel.pdf")


@app.get("/runs/{run_id}/carousel/slides/{n}.png")
def get_carousel_slide(run_id: str, n: int):
    state = _load_run_state(run_id)
    if state is None:
        raise HTTPException(404, "run not found")
    path = resolve_carousel_file(state.get("artifacts") or {}, run_id, slide=n)
    if path is None:
        raise HTTPException(404, "slide not found")
    return FileResponse(path, media_type="image/png", filename=f"slide-{n}.png")


HEARTBEAT_S = 15.0  # SSE ping cadence: the stream never goes byte-silent
TERMINAL_STATUSES = ("shipped", "exported_not_approved", "failed", "done")


async def _stream_frames(run_id: str, last_event_id: int | None = None):
    """SSE frames for a run. Each data frame carries `id: <event index>` so
    an EventSource reconnect can resume via Last-Event-ID; while the run
    is active but quiet (e.g. the Scout sweep), an `event: ping` frame is
    emitted every HEARTBEAT_S seconds so no hop's idle timeout can kill
    the connection — the 2026-10-24 incident was 130-370s of byte silence
    during Scout, after which the UI declared the stream dropped while
    the run shipped server-side."""
    idx = (last_event_id + 1) if last_event_id is not None else 0
    idle = 0
    last_yield = time.monotonic()
    while True:
        events = get_events(run_id)
        while idx < len(events):
            yield f"id: {idx}\ndata: {json.dumps(events[idx])}\n\n"
            idx += 1
            idle = 0
            last_yield = time.monotonic()
        with _lock:
            status = (_runs.get(run_id) or {}).get("status", "unknown")
        if status in TERMINAL_STATUSES:
            return
        if time.monotonic() - last_yield >= HEARTBEAT_S:
            yield "event: ping\ndata: {}\n\n"
            last_yield = time.monotonic()
        idle += 1
        if idle > 3600:  # ~30 min absolute cap
            return
        await asyncio.sleep(0.5)


@app.get("/runs/{run_id}/events")
async def run_events(run_id: str, request: Request):
    last = request.headers.get("last-event-id")
    try:
        last_id = int(last) if last is not None else None
    except ValueError:
        last_id = None
    return StreamingResponse(_stream_frames(run_id, last_id),
                             media_type="text/event-stream")


@app.post("/runs/{run_id}/approve")
def approve(run_id: str, req: ApproveRequest):
    with _lock:
        run = _runs.get(run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        if run.get("executing") or not run.get("paused_at_gate") \
                or run.get("status") != "awaiting_approval":
            raise HTTPException(
                409,
                f"run is not awaiting approval (status={run.get('status')}); "
                "approve is only accepted while the run is paused at the human gate")
        # Claim the gate atomically so a concurrent or duplicate approve
        # (double-click, retry, second client) 409s instead of resuming an
        # already-resuming or finished run.
        run["paused_at_gate"] = False
        run["executing"] = True
        run["status"] = "running"
    decision = {"decision": req.decision, "notes": req.notes or ""}
    t = threading.Thread(target=_run_graph, args=(run_id, None, decision), daemon=True)
    t.start()
    return {"run_id": run_id, "resumed": True, "decision": decision}
