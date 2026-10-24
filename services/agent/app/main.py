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
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import BaseModel

from .config import CHECKPOINT_DB
from .events import emit, get_events
from .graph import build_graph
from .llm import get_llm
from .playbooks import list_playbooks, load_playbook

app = FastAPI(title="Prism Agent API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_conn = sqlite3.connect(str(CHECKPOINT_DB), check_same_thread=False)
_checkpointer = SqliteSaver(_conn)
_graph = build_graph(checkpointer=_checkpointer)
_runs: dict[str, dict] = {}
_lock = threading.Lock()


class RunRequest(BaseModel):
    playbook_id: str
    topic: str | None = None


class ApproveRequest(BaseModel):
    decision: str  # approve | changes
    notes: str | None = None


def _config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def _run_graph(run_id: str, initial: dict | None, resume: dict | None = None) -> None:
    try:
        with _lock:
            _runs[run_id]["status"] = "running"
        if resume is not None:
            _graph.invoke(Command(resume=resume), _config(run_id))
        else:
            _graph.invoke(initial, _config(run_id))
        snap = _graph.get_state(_config(run_id))
        vals = snap.values or {}
        status = vals.get("status", "done")
        if snap.next:  # paused at interrupt
            status = "awaiting_approval"
        with _lock:
            _runs[run_id]["status"] = status
            _runs[run_id]["state"] = _clean(vals)
    except Exception as exc:
        with _lock:
            _runs[run_id]["status"] = "failed"
            _runs[run_id]["error"] = str(exc)
        emit(run_id, "api", "API", "error", f"Run failed: {exc}")


def _clean(vals: dict) -> dict:
    out = {}
    for k, v in vals.items():
        try:
            json.dumps(v)
            out[k] = v
        except Exception:
            out[k] = str(v)
    return out


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
        _runs[run_id] = {"run_id": run_id, "playbook_id": req.playbook_id, "status": "queued", "state": {}}
    t = threading.Thread(target=_run_graph, args=(run_id, initial), daemon=True)
    t.start()
    return {"run_id": run_id}


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    with _lock:
        run = _runs.get(run_id)
    if run is None:
        # try checkpoint state (server restart)
        try:
            snap = _graph.get_state(_config(run_id))
            if snap and snap.values:
                return {"run_id": run_id, "status": snap.values.get("status", "unknown"),
                        "state": _clean(snap.values), "events": get_events(run_id)}
        except Exception:
            pass
        raise HTTPException(404, "run not found")
    # refresh state from graph
    try:
        snap = _graph.get_state(_config(run_id))
        if snap and snap.values:
            run = dict(run)
            run["state"] = _clean(snap.values)
            if snap.next and run["status"] == "running":
                run["status"] = "awaiting_approval"
    except Exception:
        pass
    return {**run, "events": get_events(run_id)}


@app.get("/runs/{run_id}/events")
async def run_events(run_id: str):
    async def gen():
        idx = 0
        idle = 0
        while True:
            events = get_events(run_id)
            while idx < len(events):
                yield f"data: {json.dumps(events[idx])}\n\n"
                idx += 1
                idle = 0
            with _lock:
                status = (_runs.get(run_id) or {}).get("status", "unknown")
            if status in ("shipped", "exported_not_approved", "failed", "done"):
                break
            idle += 1
            if idle > 600:  # ~5 min max stream
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/runs/{run_id}/approve")
def approve(run_id: str, req: ApproveRequest):
    with _lock:
        run = _runs.get(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    decision = {"decision": req.decision, "notes": req.notes or ""}
    t = threading.Thread(target=_run_graph, args=(run_id, None, decision), daemon=True)
    t.start()
    return {"run_id": run_id, "resumed": True, "decision": decision}
