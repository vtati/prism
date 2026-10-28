"""Format v3 (Front Page) carousel tests: fixed 8 slides, contents cover,
story verdicts, CTA last, edition skin rotation — plus a graph-level run
asserting the shipped artifact is an 8-slide v3 carousel."""
from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("PRISM_CAROUSEL_VIA_MCP", "0")  # direct renderer in tests

from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from app.config import CHECKPOINT_DB  # noqa: E402
from app.editions import ROTATION, skin_for_edition, skin_for_playbook  # noqa: E402
from app.graph import build_graph  # noqa: E402
from app.makers import _carousel_spec, render_carousel_for_run  # noqa: E402
from app.playbooks import load_playbook  # noqa: E402


def _ctx(playbook_id: str, run_id: str) -> dict:
    pb = load_playbook(playbook_id)
    cands = [{
        "title": f"Story {i}: a concrete development in the field",
        "url": f"https://example.com/story-{i}",
        "source": "Hacker News",
        "points": 500 - i * 40, "num_comments": 90 - i * 7,
        "snippet": (f"Story {i} shipped today with a concrete change developers can use. "
                    f"It matters because teams were blocked on exactly this problem. "
                    f"The release includes benchmarks, pricing and a migration guide."),
    } for i in range(6)]
    return {"run_id": run_id, "playbook": pb, "picked": cands[0], "candidates": cands,
            "evidence": cands[:5], "scores": {"total": 87.0},
            "score_explanation": "Picked for audience heat and verification strength.",
            "topic": "AI agents", "tone": "clear", "review_notes": ""}


def test_skin_rotation_follows_v3_order():
    assert ROTATION == ["frontpage", "terminal", "neon-grid", "poster", "aurora"]
    assert [skin_for_edition(e) for e in range(1, 7)] == ROTATION + ["frontpage"]
    assert "statdeck" not in ROTATION  # rejected format — never in rotation


def test_ai_news_default_skin_is_poster_fixed():
    # Venugopal, locked 2026-10-16-20: POSTER is the standing default for
    # EVERY daily edition — light bg, colored per-slot vertical bars.
    pb = load_playbook("ai-news-gtm")
    assert pb["carousel"]["skin"] == "poster"
    assert pb["carousel"]["skin_mode"] == "fixed"
    for edition in (1, 2, 3, 4, 5, 9):
        assert skin_for_playbook(pb, edition) == "poster"
    spec = _carousel_spec(_ctx("ai-news-gtm", "poster-" + uuid.uuid4().hex[:8]))
    assert spec["skin"] == "poster"


def test_rotation_only_when_explicitly_enabled():
    pb = load_playbook("ai-news-gtm")
    rotating = {**pb, "carousel": {**pb["carousel"], "skin_mode": "rotation"}}
    assert skin_for_playbook(rotating, 1) == "frontpage"
    assert skin_for_playbook(rotating, 4) == "poster"
    ctx = _ctx("ai-news-gtm", "rot-" + uuid.uuid4().hex[:8])
    ctx["playbook"] = rotating
    spec = _carousel_spec(ctx)
    assert spec["skin"] == skin_for_edition(spec["edition"])


def test_spec_is_v3_structure():
    spec = _carousel_spec(_ctx("ai-news-gtm", "v3-spec-" + uuid.uuid4().hex[:8]))
    assert len(spec["slides"]) == 5, "v3 has exactly five story slides"
    assert len(spec["contents"]) == 4, "cover contents list the other four stories"
    assert all(c["head"] and c["tease"] for c in spec["contents"])
    assert spec["lead"]["heading"] == spec["slides"][0]["heading"]
    assert len(spec["recap"]["rows"]) == 5
    assert all(s["verdict"] for s in spec["slides"]), "every story carries a verdict"
    assert spec["cta"], "CTA lines present (slide 8)"
    assert spec["persona"]["brand"] == "Venu Tati · AI Dev Digest"
    assert spec["skin"] == "poster"  # standing default, not the rotation
    # why-it-matters bullets are written from evidence, not engagement counts
    for s in spec["slides"]:
        assert len(s["bullets"]) == 3
        assert "points ·" not in s["bullets"][0]
        assert "comments on" not in s["bullets"][0]


def test_render_is_exactly_eight_slides_with_cta_last():
    run_id = "v3-render-" + uuid.uuid4().hex[:8]
    spec = _carousel_spec(_ctx("ai-news-gtm", run_id))
    result = render_carousel_for_run(run_id, spec)
    assert result["slide_count"] == 8
    assert len(result["png_paths"]) == 8
    assert Path(result["pdf_path"]).exists()
    # Page order is cover(1) + stories(2-6) + recap(7) + CTA(8): the spec the
    # renderer consumed carries the CTA as its final element.
    assert spec["total_pages"] == 8 and spec["cta"][-1].lower().startswith("follow")


def test_travel_same_structure_pastel_skin():
    # Was sunset until 2026-10-28, when Venugopal replaced the travel skin
    # with his attached pastel deck template (see test_pastel_skin.py).
    run_id = "v3-travel-" + uuid.uuid4().hex[:8]
    ctx = _ctx("travel-news", run_id)
    ctx["topic"] = "travel destinations"
    spec = _carousel_spec(ctx)
    assert spec["skin"] == "pastel"
    assert len(spec["slides"]) == 5 and len(spec["recap"]["rows"]) == 5 and spec["cta"]
    result = render_carousel_for_run(run_id, spec)
    assert result["slide_count"] == 8


def test_graph_run_ships_v3_carousel():
    run_id = "test-v3-" + uuid.uuid4().hex[:8]
    conn = sqlite3.connect(str(CHECKPOINT_DB), check_same_thread=False)
    graph = build_graph(checkpointer=SqliteSaver(conn))
    config = {"configurable": {"thread_id": run_id}}
    graph.invoke({"run_id": run_id, "playbook_id": "ai-news-gtm", "input": "AI agents"}, config)
    assert graph.get_state(config).next, "graph must pause at the human gate"
    graph.invoke(Command(resume={"decision": "approve", "notes": "v3 test"}), config)
    arts = graph.get_state(config).values.get("artifacts") or {}
    car = arts.get("linkedin_carousel") or {}
    assert car.get("slide_count") == 8, f"expected v3 8-slide carousel, got {car.get('slide_count')}"
    assert car.get("skin") == "poster", f"ai-news runs ship poster, got {car.get('skin')}"
    assert isinstance(car.get("edition"), int) and car["edition"] >= 1
