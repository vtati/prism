"""Workstream B tests: curator selection quality — eligibility gate,
rubric floor, fallback, and angle. Keyword path only (LLM forced to
fallback mode), synthetic candidates, no network.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app import graph  # noqa: E402
from app.events import get_events  # noqa: E402


class FakeFallbackLLM:
    mode = "fallback"
    provider = "fallback"
    model = "fake"

    def generate(self, system, user, fallback):
        return fallback


@pytest.fixture(autouse=True)
def _llm_off(monkeypatch):
    monkeypatch.setattr(graph, "get_llm", lambda: FakeFallbackLLM())


def _cand(title, snippet, points, comments, slug, corroboration=1):
    return {"title": title, "snippet": snippet, "url": f"https://example.com/{slug}",
            "source": "Hacker News", "points": points, "num_comments": comments,
            "corroboration": corroboration}


def _curate(candidates, playbook_id="ai-news-gtm"):
    run_id = "sel-" + uuid.uuid4().hex[:8]
    out = graph.node_curator({"run_id": run_id, "playbook_id": playbook_id,
                              "candidates": candidates})
    return run_id, out


# Pure-firmware Samsung story: huge engagement, zero AI signal.
SAMSUNG_PURE = _cand(
    "Root shell on Samsung TV",
    "Attackers exploited the TV firmware update channel to gain a root shell. "
    "The vendor issued a firmware patch and urged owners to reboot the television.",
    10000, 900, "samsung-pure", corroboration=3)

AI_STORY = _cand(
    "OpenAI ships a new LLM agent for developers",
    "OpenAI released a large language model agent for coding teams. "
    "The launch ships today with pricing for teams.",
    50, 10, "openai-agent")


def test_assess_eligibility_samsung_variants():
    pure = {"title": "Root shell on Samsung TV",
            "snippet": "Attackers exploited the TV firmware update channel to gain "
                       "a root shell. The vendor issued a firmware patch."}
    assert graph.assess_eligibility(pure, "ai-news-gtm") is False
    with_ai = {"title": "Root shell on Samsung TV",
               "snippet": "The TV's on-board AI listens continuously and a neural "
                          "network tracks viewing habits, researchers found."}
    assert graph.assess_eligibility(with_ai, "ai-news-gtm") is True


def test_ineligible_top_scorer_passed_over():
    _run_id, out = _curate([SAMSUNG_PURE, AI_STORY])
    assert out["picked"]["title"] == AI_STORY["title"]
    sel = out["selection"]
    assert sel["eligibility"] == "keywords"
    assert sel["passed_over"], "the ineligible top scorer must be recorded"
    first = sel["passed_over"][0]
    assert first["title"] == SAMSUNG_PURE["title"]
    assert "ineligible" in first["reason"]


def test_floor_failure_passed_to_next_eligible():
    low_consequence = _cand(
        "Claude model update quietly improves coding",
        "Anthropic's Claude large language model now writes code with fewer "
        "errors, according to early users testing the chatbot this week.",
        5000, 500, "claude-quiet")
    strong = _cand(
        "OpenAI launches GPT agent platform",
        "OpenAI launches a GPT agent platform today. The release ships with "
        "pricing and a migration guide for teams.",
        60, 15, "gpt-platform")
    _run_id, out = _curate([low_consequence, strong])
    assert out["picked"]["title"] == strong["title"]
    sel = out["selection"]
    assert sel["floor_key"] == "consequence" and sel["floor_min"] == 10
    reasons = [p["reason"] for p in sel["passed_over"]]
    assert any("floor" in r for r in reasons), reasons


def test_angle_present_in_output_and_emit():
    run_id, out = _curate([AI_STORY])
    assert out["angle"], "angle must be present (fallback derivation)"
    assert out["picked"]["angle"] == out["angle"]
    assert "OpenAI released a large language model agent" in out["angle"]
    evs = [e for e in get_events(run_id) if e["node"] == "curator"]
    assert evs
    data = evs[-1]["data"]
    assert data.get("angle") == out["angle"]
    assert "scores" in data and "passed_over" in data


def test_travel_eligibility_uses_travel_terms():
    travel = {"title": "Airlines slash airfare on flights to Lisbon",
              "snippet": "Carriers cut fares on flights and hotels for the "
                         "spring travel season."}
    assert graph.assess_eligibility(travel, "travel-news") is True
    ai_only = {"title": "OpenAI launches GPT model",
               "snippet": "A new large language model tops the benchmarks."}
    assert graph.assess_eligibility(ai_only, "travel-news") is False
    assert graph.assess_eligibility(travel, "ai-news-gtm") is False


def test_no_eligible_falls_back_to_top_overall():
    other = _cand("Local bakery wins national award",
                  "The bakery's sourdough took first prize at the fair this weekend.",
                  100, 20, "bakery")
    _run_id, out = _curate([SAMSUNG_PURE, other])
    assert out["picked"]["title"] == SAMSUNG_PURE["title"]
    assert out["selection"].get("fallback"), "fallback must be recorded in selection info"
