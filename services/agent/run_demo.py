"""CLI end-to-end demo: run the graph key-free (or live if a key is set),
auto-approve at the human gate, and print the artifacts produced.
Usage: python run_demo.py [playbook_id] [topic]
"""
from __future__ import annotations

import sqlite3
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from app.config import CHECKPOINT_DB  # noqa: E402
from app.graph import build_graph  # noqa: E402
from app.llm import get_llm  # noqa: E402


def main() -> int:
    playbook_id = sys.argv[1] if len(sys.argv) > 1 else "ai-news-gtm"
    topic = sys.argv[2] if len(sys.argv) > 2 else "AI agents"
    run_id = uuid.uuid4().hex[:12]
    conn = sqlite3.connect(str(CHECKPOINT_DB), check_same_thread=False)
    graph = build_graph(checkpointer=SqliteSaver(conn))
    config = {"configurable": {"thread_id": run_id}}
    print(f"run_id={run_id} playbook={playbook_id} topic={topic!r} llm_mode={get_llm().mode}")
    graph.invoke({"run_id": run_id, "playbook_id": playbook_id, "input": topic}, config)
    snap = graph.get_state(config)
    vals = snap.values
    print(f"after first pass: status={vals.get('status')} next={snap.next}")
    print(f"picked: {vals.get('picked', {}).get('title')}")
    print(f"scores: {vals.get('scores')}")
    print(f"review: {vals.get('review')}")
    if snap.next:
        print("human gate reached — auto-approving for demo")
        graph.invoke(Command(resume={"decision": "approve", "notes": "demo auto-approve"}), config)
        snap = graph.get_state(config)
        vals = snap.values
    print(f"final status: {vals.get('status')}")
    print(f"ship: {vals.get('ship')}")
    for name, art in (vals.get("artifacts") or {}).items():
        extra = f" pdf={art.get('pdf_path')}" if art.get("pdf_path") else ""
        print(f"artifact: {name} ({art.get('type')}){extra} chars={len(art.get('content', ''))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
