"""Smoke test: run the graph key-free with a fixed topic using live HN
data (recorded fixture if the network fails) and assert the briefing +
carousel PDF exist and the reviewer passed/looped within bounds."""
from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("PRISM_CAROUSEL_VIA_MCP", "0")  # direct renderer in tests for speed

from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from app.config import CHECKPOINT_DB  # noqa: E402
from app.graph import build_graph  # noqa: E402


def test_graph_end_to_end_key_free():
    run_id = "test-" + uuid.uuid4().hex[:8]
    conn = sqlite3.connect(str(CHECKPOINT_DB), check_same_thread=False)
    graph = build_graph(checkpointer=SqliteSaver(conn))
    config = {"configurable": {"thread_id": run_id}}
    graph.invoke({"run_id": run_id, "playbook_id": "ai-news-gtm", "input": "AI agents"}, config)
    snap = graph.get_state(config)
    vals = snap.values
    assert vals.get("picked"), "curator must pick a story"
    assert vals.get("scores", {}).get("total", 0) > 0
    assert vals.get("score_explanation"), "curator must explain its pick"
    assert snap.next, "graph must pause at the human gate"
    graph.invoke(Command(resume={"decision": "approve", "notes": "smoke"}), config)
    vals = graph.get_state(config).values
    arts = vals.get("artifacts") or {}
    assert "briefing" in arts and len(arts["briefing"]["content"]) > 100
    assert "linkedin_carousel" in arts
    pdf = arts["linkedin_carousel"].get("pdf_path")
    assert pdf and Path(pdf).exists() and Path(pdf).stat().st_size > 1000
    for png in arts["linkedin_carousel"].get("png_paths", []):
        assert Path(png).exists()
    assert vals.get("review", {}).get("rounds", 0) >= 1
    assert vals.get("ship", {}).get("run_page") and Path(vals["ship"]["run_page"]).exists()
    # every artifact cites at least one evidence URL
    for name, art in arts.items():
        assert art.get("citations"), f"{name} has no citations"


def test_travel_playbook_same_graph():
    run_id = "test-" + uuid.uuid4().hex[:8]
    conn = sqlite3.connect(str(CHECKPOINT_DB), check_same_thread=False)
    graph = build_graph(checkpointer=SqliteSaver(conn))
    config = {"configurable": {"thread_id": run_id}}
    graph.invoke({"run_id": run_id, "playbook_id": "travel-news", "input": "travel destinations"}, config)
    vals = graph.get_state(config).values
    assert vals.get("picked")
    assert "deal_value" in (vals.get("scores") or {}), "travel rubric must drive scoring"
