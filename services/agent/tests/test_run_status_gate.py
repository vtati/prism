"""Regression tests for the run-status / human-gate race.

Bug: GET /runs/{id} inferred "awaiting_approval" from the checkpoint having
ANY next node, so a run that was still executing could report
awaiting_approval; POST /approve then resumed the graph concurrently and
wedged the run. The fix tracks an explicit paused-at-gate flag in the API
layer: status flips to awaiting_approval only when the graph invoke returns
with a pending interrupt, and /approve 409s unless the run is actually
paused at the gate.

These tests drive the real FastAPI app with a controllable fake graph whose
get_state deliberately reports next nodes mid-execution (the exact condition
that produced the false signal).
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from langgraph.types import Command  # noqa: E402

from app import main  # noqa: E402


class FakeSnap:
    def __init__(self, values, next=(), interrupts=()):
        self.values = values
        self.next = next
        self.interrupts = tuple(interrupts)


class FakeInterrupt:
    value = {"type": "approval_request"}


class BlockingGateGraph:
    """Fake compiled graph: the initial invoke blocks until released, then
    returns with a pending interrupt (paused at the human gate). A resume
    invoke completes the run as shipped. get_state always claims there is a
    next node until the run finishes — mid-run included."""

    def __init__(self):
        self.release = threading.Event()
        self.phase = "idle"  # idle -> executing -> paused -> done
        self.values = {"status": "queued"}

    def invoke(self, inp, config):
        if isinstance(inp, Command):
            self.phase = "done"
            self.values = {"status": "shipped", "approval": inp.resume}
            return dict(self.values)
        self.phase = "executing"
        self.values = {"status": "making"}
        assert self.release.wait(timeout=30), "test never released the graph"
        self.phase = "paused"
        self.values = {"status": "awaiting_approval"}
        return {"__interrupt__": [FakeInterrupt()]}

    def get_state(self, config):
        if self.phase == "done":
            return FakeSnap(self.values, next=(), interrupts=())
        if self.phase == "paused":
            return FakeSnap(self.values, next=("ship",), interrupts=(FakeInterrupt(),))
        # executing (or idle): a next node exists but NO interrupt is pending
        return FakeSnap(self.values, next=("makers",), interrupts=())


def _wait_status(client: TestClient, run_id: str, want, timeout=15.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = client.get(f"/runs/{run_id}")
        assert r.status_code == 200
        last = r.json()
        statuses = want if isinstance(want, (list, tuple, set)) else [want]
        if last["status"] in statuses:
            return last
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} never reached {want}; last={last}")


@pytest.fixture()
def gated_client(monkeypatch):
    fake = BlockingGateGraph()
    monkeypatch.setattr(main, "_graph", fake)
    with main._lock:
        main._runs.clear()
    client = TestClient(main.app)
    yield client, fake
    with main._lock:
        main._runs.clear()


def _start_run(client: TestClient) -> str:
    r = client.post("/runs", json={"playbook_id": "ai-news-gtm", "topic": "AI agents"})
    assert r.status_code == 200
    return r.json()["run_id"]


def test_status_while_executing_is_not_awaiting_approval(gated_client):
    client, fake = gated_client
    run_id = _start_run(client)
    body = _wait_status(client, run_id, "running")
    assert body["status"] == "running"
    # checkpoint claims a next node (makers) — the old code flipped this to
    # awaiting_approval; it must stay "running" until the interrupt lands
    for _ in range(5):
        r = client.get(f"/runs/{run_id}")
        assert r.json()["status"] == "running"
        time.sleep(0.05)
    fake.release.set()
    body = _wait_status(client, run_id, "awaiting_approval")
    assert body["status"] == "awaiting_approval"


def test_approve_while_running_returns_409(gated_client):
    client, fake = gated_client
    run_id = _start_run(client)
    _wait_status(client, run_id, "running")
    r = client.post(f"/runs/{run_id}/approve", json={"decision": "approve"})
    assert r.status_code == 409
    assert "not awaiting approval" in r.json()["detail"]
    # the run must still be able to reach the gate afterwards (not wedged)
    fake.release.set()
    _wait_status(client, run_id, "awaiting_approval")


def test_approve_at_gate_resumes_and_second_approve_409(gated_client):
    client, fake = gated_client
    run_id = _start_run(client)
    _wait_status(client, run_id, "running")
    fake.release.set()
    _wait_status(client, run_id, "awaiting_approval")
    r = client.post(f"/runs/{run_id}/approve", json={"decision": "approve"})
    assert r.status_code == 200
    assert r.json()["resumed"] is True
    _wait_status(client, run_id, "shipped")
    # double-approve after resume must be rejected, not resume a finished run
    r2 = client.post(f"/runs/{run_id}/approve", json={"decision": "approve"})
    assert r2.status_code == 409
    assert "not awaiting approval" in r2.json()["detail"]


def test_approve_unknown_run_404(gated_client):
    client, _fake = gated_client
    r = client.post("/runs/does-not-exist/approve", json={"decision": "approve"})
    assert r.status_code == 404
