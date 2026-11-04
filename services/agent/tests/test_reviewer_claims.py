"""Reviewer v2 — claim-support gate (Aishwarya's Week 3 review, 2026-11-04).

The old reviewer passed an artifact when a source URL appeared in the
text and the content was >= 80 chars: a URL + length check that says
nothing about whether the claims are TRUE. These tests plant a plausible
fabricated claim carrying the CORRECT citation and plenty of length —
the old reviewer passes it (the bug); Reviewer v2 must REVISE it with a
specific unsupported-claim note, and must PASS the corrected twin whose
claims the cited source's text actually supports.

All synthetic, no network, LLM forced to fallback.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app import graph  # noqa: E402


class FakeFallbackLLM:
    mode = "fallback"
    provider = "fallback"
    model = "fake"

    def generate(self, system, user, fallback):
        return fallback


@pytest.fixture(autouse=True)
def _llm_off(monkeypatch):
    monkeypatch.setattr(graph, "get_llm", lambda: FakeFallbackLLM())


SOURCE = {
    "title": "Cua launches open-source computer-use agent framework",
    "url": "https://example.com/cua-launch",
    "source": "Hacker News",
    "points": 210, "num_comments": 84,
    "snippet": ("Cua released an open-source framework that lets AI agents control "
                "computers through vision and keyboard actions. The framework "
                "supports macOS and Windows and is available on GitHub today."),
}

# Plausible, well-formed, >80 chars, cites the CORRECT source URL — and
# every checkable fact in it (the raise, the user count, the countries,
# the investor, the date) is fabricated: the cited page says none of it.
PLANTED = (
    "Cua announced that its framework raised $40 million in funding and now "
    "has 2 million enterprise users across 30 countries. The company said "
    "the round was led by Sequoia Capital and closed in March 2026.\n\n"
    "Source: https://example.com/cua-launch"
)

# The same artifact with the claims corrected to what the source's text
# actually says.
CORRECTED = (
    "Cua released an open-source framework that lets AI agents control "
    "computers through vision and keyboard actions. The framework supports "
    "macOS and Windows and is available on GitHub today.\n\n"
    "Source: https://example.com/cua-launch"
)


def _review(content: str, name: str = "linkedin_post") -> dict:
    run_id = "rev-" + uuid.uuid4().hex[:8]
    state = {
        "run_id": run_id,
        "playbook_id": "ai-news-gtm",
        "artifacts": {name: {"type": name, "title": name, "content": content,
                             "citations": [SOURCE["url"]]}},
        "evidence": [SOURCE],
        "candidates": [SOURCE],
        "picked": SOURCE,
        "score_explanation": "",
        "topic": "AI agents",
        "duplicate": False,
    }
    return graph.node_reviewer(state)


def test_planted_claim_with_correct_citation_must_revise():
    out = _review(PLANTED)
    review = out["review"]
    assert review["verdict"] == "revise", (
        "a fabricated claim with the correct URL cited must NOT pass — "
        "that is the exact bug Aishwarya flagged")
    notes = " ".join(review["notes"])
    assert "not supported by" in notes
    assert "https://example.com/cua-launch" in notes
    per = review["per_artifact"]["linkedin_post"]
    assert per["ok"] is False
    assert per["claims_total"] >= 1
    assert per["claims_supported"] < per["claims_total"]
    unsupported = per["unsupported_claims"]
    assert unsupported, "the planted claim must be recorded per-claim"
    assert unsupported[0]["support"] == "unsupported"
    assert unsupported[0]["source_url"] == SOURCE["url"]


def test_corrected_claim_twin_passes():
    out = _review(CORRECTED)
    review = out["review"]
    assert review["verdict"] == "pass", f"corrected twin must pass, notes: {review['notes']}"
    per = review["per_artifact"]["linkedin_post"]
    assert per["ok"] is True
    assert per["claims_total"] >= 1
    assert per["claims_supported"] == per["claims_total"]
    assert per["unsupported_claims"] == []


def test_planted_claim_in_any_artifact_blocks_the_suite():
    run_id = "rev-" + uuid.uuid4().hex[:8]
    state = {
        "run_id": run_id, "playbook_id": "ai-news-gtm",
        "artifacts": {
            "briefing": {"type": "briefing", "title": "Briefing", "content": CORRECTED,
                         "citations": [SOURCE["url"]]},
            "email": {"type": "email", "title": "Email", "content": PLANTED,
                      "citations": [SOURCE["url"]]},
        },
        "evidence": [SOURCE], "candidates": [SOURCE], "picked": SOURCE,
        "score_explanation": "", "topic": "AI agents", "duplicate": False,
    }
    review = graph.node_reviewer(state)["review"]
    assert review["verdict"] == "revise"
    assert review["per_artifact"]["briefing"]["ok"] is True
    assert review["per_artifact"]["email"]["ok"] is False
    assert any(n.startswith("email:") and "not supported by" in n for n in review["notes"])


# ---------------------------------------------------------------------------
# Unit-level: claim splitting + key-fact support
# ---------------------------------------------------------------------------

def test_opinion_and_cta_lines_are_not_factual_claims():
    claims = graph.split_claims(
        "Watch this space — the follow-up will land soon.\n\n"
        "Follow for the next one, same time tomorrow.\n\n"
        "Source: https://example.com/cua-launch")
    assert claims == []


def test_numbers_must_appear_in_source_text():
    sources = [{"url": SOURCE["url"], "title": SOURCE["title"],
                "snippet": "The beta reached 1,000 users in its first week."}]
    ok = graph.check_claims("The beta reached 1000 users in its first week.", sources)
    assert ok and ok[0]["support"] == "supported"  # comma form still matches
    bad = graph.check_claims("The beta reached 9000 users in its first week.", sources)
    assert bad and bad[0]["support"] == "unsupported"
    assert "9000" in bad[0]["missing"]


def test_named_entity_must_appear_in_source_text():
    sources = [{"url": SOURCE["url"], "title": SOURCE["title"], "snippet": SOURCE["snippet"]}]
    bad = graph.check_claims(
        "The framework was backed by Sequoia Capital from day one.", sources)
    assert bad and bad[0]["support"] == "unsupported"
    assert any("sequoia" in m for m in bad[0]["missing"])


def test_claim_with_no_cited_source_is_no_source():
    claims = graph.check_claims("Cua raised $40 million in funding.", [])
    assert claims and claims[0]["support"] == "no-source"
    assert claims[0]["source_url"] is None


# ---------------------------------------------------------------------------
# Regression tests from the diff review of v2 (2026-11-04): the stock
# maker templates must PASS in fallback mode, the carousel's real text
# must be checked (not just its render receipt), and entity/magnitude
# extraction must not corrupt names or miss spelled-out facts.
# ---------------------------------------------------------------------------

MORE_AI = [
    {"title": "OpenAI ships GPT-5 for developers",
     "url": "https://example.com/gpt5", "source": "Hacker News",
     "points": 180, "num_comments": 64,
     "snippet": "OpenAI released GPT-5 with a larger context window for developer "
                "workflows. The model is available through the API today."},
    {"title": "Anthropic publishes Claude agent safety study",
     "url": "https://example.com/claude-study", "source": "Hacker News",
     "points": 150, "num_comments": 41,
     "snippet": "Anthropic published a study of agent behaviour in long-running "
                "tasks. The paper reports failure rates across benchmark suites."},
    {"title": "GitHub adds Copilot workspace automations",
     "url": "https://example.com/copilot", "source": "Hacker News",
     "points": 120, "num_comments": 33,
     "snippet": "GitHub announced Copilot workspace automations for pull requests. "
                "The feature runs checks before a human review begins."},
    {"title": "Mistral releases open-weight reasoning model",
     "url": "https://example.com/mistral", "source": "Hacker News",
     "points": 98, "num_comments": 22,
     "snippet": "Mistral released an open-weight reasoning model under the Apache "
                "license. Weights are downloadable from Hugging Face today."},
]

TRAVEL = [
    {"title": "United adds nonstop flights from Washington to Lisbon",
     "url": "https://example.com/lisbon-route", "source": "gdelt",
     "points": 140, "num_comments": 18,
     "snippet": "United announced nonstop flights from Washington Dulles to Lisbon "
                "starting in June. Round trip fares start at $412 in the launch sale."},
    {"title": "Lisbon hotels cut spring rates for early bookings",
     "url": "https://example.com/lisbon-hotels", "source": "gdelt",
     "points": 96, "num_comments": 9,
     "snippet": "Hotels in Lisbon cut spring rates for travellers booking before "
                "February. The Alfama district leads the discounts this season."},
    {"title": "Portugal eases airport queues with new e-gates",
     "url": "https://example.com/e-gates", "source": "gdelt",
     "points": 80, "num_comments": 7,
     "snippet": "Portugal installed new e-gates at Lisbon airport to speed passport "
                "control. Officials expect shorter queues during the summer rush."},
    {"title": "Azores ferry adds weekend sailings for island hoppers",
     "url": "https://example.com/azores-ferry", "source": "gdelt",
     "points": 61, "num_comments": 5,
     "snippet": "The Azores ferry operator added weekend sailings between São Miguel "
                "and Santa Maria. Tickets go on sale through the regional portal."},
    {"title": "Travel editors pick Lisbon for spring city breaks",
     "url": "https://example.com/lisbon-pick", "source": "editorial",
     "points": 55, "num_comments": 4,
     "snippet": "Travel editors picked Lisbon among spring city break destinations. "
                "They cited mild weather, walkable hills and late-night food halls."},
]


def _maker_suite(playbook_id, candidates, picked, monkeypatch):
    import os

    from app import makers as maker_mod
    from app.playbooks import load_playbook

    monkeypatch.setenv("PRISM_CAROUSEL_VIA_MCP", "0")
    monkeypatch.setattr(maker_mod, "get_llm", lambda: FakeFallbackLLM())
    pb = load_playbook(playbook_id)
    evidence = [picked] + [c for c in candidates if c["url"] != picked["url"]][:4]
    expl = (f"\"{picked['title']}\" scored 79.2/100 (Audience Heat 31.2/40, Consequence 13.3/20, "
            f"Verification 20/20, Novelty 14.7/20) across {len(candidates)} candidates, with "
            f"{picked.get('points', 0)} points and {picked.get('num_comments', 0)} comments of "
            f"live discussion.")
    ctx = {"run_id": "gold-" + uuid.uuid4().hex[:8], "playbook": pb, "picked": picked,
           "candidates": candidates, "evidence": evidence,
           "scores": {"total": 79.2}, "score_explanation": expl,
           "topic": "AI agents" if playbook_id == "ai-news-gtm" else "travel destinations",
           "tone": (pb.get("audience") or {}).get("tone", "clear"), "review_notes": ""}
    artifacts = maker_mod.run_makers(ctx)
    # Guard against a vacuous pass: the full suite must actually exist,
    # including a rendered carousel carrying review_text.
    assert set(artifacts) == set(pb.get("makers") or []), artifacts.keys()
    car = next(a for a in artifacts.values() if a["type"] == "linkedin_carousel")
    assert car.get("review_text") and Path(car["pdf_path"]).exists()
    state = {"run_id": ctx["run_id"], "playbook_id": playbook_id, "artifacts": artifacts,
             "evidence": evidence, "candidates": candidates, "picked": picked,
             "score_explanation": expl, "topic": ctx["topic"], "duplicate": False}
    return graph.node_reviewer(state)["review"]


def test_stock_templates_pass_reviewer_v2_ai(monkeypatch):
    picked = dict(SOURCE, corroboration=2)
    review = _maker_suite("ai-news-gtm", [picked] + MORE_AI, picked, monkeypatch)
    assert review["verdict"] == "pass", f"fallback templates must pass v2, notes: {review['notes']}"


def test_stock_templates_pass_reviewer_v2_travel(monkeypatch):
    picked = dict(TRAVEL[0], corroboration=1)
    review = _maker_suite("travel-news", TRAVEL, picked, monkeypatch)
    assert review["verdict"] == "pass", f"fallback templates must pass v2, notes: {review['notes']}"


def test_planted_claim_inside_carousel_text_must_revise():
    run_id = "rev-" + uuid.uuid4().hex[:8]
    state = {
        "run_id": run_id, "playbook_id": "ai-news-gtm",
        "artifacts": {"linkedin_carousel": {
            "type": "linkedin_carousel", "title": "LinkedIn carousel",
            "content": "Carousel rendered (8 slides, via direct-module). "
                       "Format v3 Front Page · edition #3 · skin poster. "
                       f"Cover lead: {SOURCE['title']}",
            "review_text": PLANTED, "citations": [SOURCE["url"]]}},
        "evidence": [SOURCE], "candidates": [SOURCE], "picked": SOURCE,
        "score_explanation": "", "topic": "AI agents", "duplicate": False,
    }
    review = graph.node_reviewer(state)["review"]
    assert review["verdict"] == "revise"
    assert review["per_artifact"]["linkedin_carousel"]["ok"] is False


def test_entity_spans_keep_real_names():
    src = [{"url": "https://example.com/ny", "title": "New York travel guide",
            "snippet": "The New York Times published a guide to New York neighbourhoods."}]
    ok = graph.check_claims("The New York Times published a guide to New York neighbourhoods.", src)
    assert ok and ok[0]["support"] == "supported", ok
    bad = graph.check_claims("First Republic Bank opened a branch in the district.", src)
    assert bad and bad[0]["support"] == "unsupported"
    assert any("first republic bank" in m for m in bad[0]["missing"])


def test_magnitude_word_is_a_checkable_fact():
    src = [{"url": SOURCE["url"], "title": "GPT-5 launches for developers",
            "snippet": "GPT-5 is available through the API today."}]
    bad = graph.check_claims("GPT-5 reached 5 million users in a week.", src)
    assert bad and bad[0]["support"] == "unsupported"
    assert "million" in bad[0]["missing"]


def test_spelled_out_number_with_magnitude_is_a_checkable_fact():
    src = [{"url": SOURCE["url"], "title": SOURCE["title"], "snippet": SOURCE["snippet"]}]
    bad = graph.check_claims("The startup raised forty million dollars last year.", src)
    assert bad and bad[0]["support"] == "unsupported"
    src2 = [{"url": SOURCE["url"], "title": "Funding",
             "snippet": "The startup raised $40 million in seed funding last year."}]
    ok = graph.check_claims("The startup raised forty million dollars last year.", src2)
    assert ok and ok[0]["support"] == "supported", ok


def test_review_state_is_json_serializable():
    import json

    out = _review(PLANTED)
    json.dumps(out["review"])  # checkpoint + SSE + bundle all serialize it


def test_route_after_review_bounds():
    assert graph._route_after_review({"review": {"verdict": "revise", "rounds": 1}}) == "makers"
    assert graph._route_after_review({"review": {"verdict": "revise", "rounds": 2}}) == "human_gate"
    assert graph._route_after_review({"review": {"verdict": "pass", "rounds": 1}}) == "human_gate"


def test_ship_labels_local_export_vs_publisher_stub(tmp_path, monkeypatch):
    """Her second note: the local export and the publisher stub are
    distinct artifact kinds — the stub must never read as published."""
    import json

    from app import graph as g

    monkeypatch.setattr(g, "RUNS_DIR", tmp_path)
    run_id = "ship-" + uuid.uuid4().hex[:8]
    state = {
        "run_id": run_id, "playbook_id": "ai-news-gtm",
        "artifacts": {"briefing": {"type": "briefing", "title": "B", "content": CORRECTED,
                                   "citations": [SOURCE["url"]]}},
        "picked": SOURCE, "scores": {"total": 1}, "score_explanation": "x",
        "review": {"verdict": "pass"}, "approval": {"decision": "approve"},
    }
    out = g.node_ship(state)
    outputs = out["ship"]["outputs"]
    assert [o["kind"] for o in outputs] == ["local_export", "publisher_stub"]
    assert outputs[1]["sent"] is False
    bundle = json.loads((tmp_path / run_id / "bundle.json").read_text())
    assert [o["kind"] for o in bundle["outputs"]] == ["local_export", "publisher_stub"]
    payload = json.loads((tmp_path / run_id / "crosscast_payload.json").read_text())
    assert payload["kind"] == "publisher_stub" and payload["sent"] is False
    html = (tmp_path / run_id / "index.html").read_text()
    assert "kind: local_export" in html and "publisher_stub" in html


def test_artifact_without_any_citation_still_revises():
    run_id = "rev-" + uuid.uuid4().hex[:8]
    state = {
        "run_id": run_id, "playbook_id": "ai-news-gtm",
        "artifacts": {"briefing": {"type": "briefing", "title": "B",
                                   "content": PLANTED.replace(SOURCE["url"], "https://example.com/other"),
                                   "citations": []}},
        "evidence": [SOURCE], "candidates": [SOURCE], "picked": SOURCE,
        "score_explanation": "", "topic": "AI agents", "duplicate": False,
    }
    review = graph.node_reviewer(state)["review"]
    assert review["verdict"] == "revise"
    assert review["per_artifact"]["briefing"]["ok"] is False
