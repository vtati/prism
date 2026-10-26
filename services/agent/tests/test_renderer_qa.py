"""Renderer QA gate tests (2026-10-25 fix round).

The deployed Oct 25 PDF shipped with: persona photo replaced by a monogram
(workspace-only path), all type rendered in PIL's tiny fallback font (the
deploy image has no system DejaVu), the cover headline = the raw over-long
source title, and the verdict strip clipped by the poster bar / colliding
with the persona lockup. These tests pin the fixes: bundled assets, a
display headline, measured non-overlapping layout, and a QA record on
every render that fails loudly in artifact meta instead of silently.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.makers import _carousel_spec  # noqa: E402  (import first: it puts the carousel dir on sys.path)
import renderer  # noqa: E402
from app.playbooks import load_playbook  # noqa: E402

ASSETS = Path(renderer.__file__).resolve().parent / "assets"

LONG_TITLE = ("Launch HN: Cua (YC X25) – Open-Source Docker Container "
              "for Computer-Use Agents and Other Long Headlines")
ANGLE = "Open-source container runtime Cua enables AI agents to operate a full OS"


def _spec(skin="poster"):
    stories = [{
        "heading": LONG_TITLE if i == 0 else f"Story {i}: " + "a very long heading " * 4,
        "tag": ["REPO", "PRODUCT", "FRAMEWORKS", "RESEARCH", "ECOSYSTEM"][i],
        "bullets": [
            "Cua offers a way for AI agents to run full OS in isolated VMs.",
            "Why it matters: open-source nature allows for community-driven development.",
            "Potential to enhance AI deployment in diverse environments everywhere.",
        ],
        "verdict": "Worth watching — the ecosystem is moving this way fast.",
    } for i in range(5)]
    stories[0]["verdict"] = ("Lead story — the playbook rubric's top pick. "
                             "The one to read first.")
    return {
        "kicker": "AI DEV DIGEST #7 · OCT 26",
        "title": "AI Dev Digest",
        "date_line": "SUNDAY, OCTOBER 26 · ISSUE No. 7",
        "cover_sub": "5 things in AI today — Oct 26.",
        "lead": {"heading": stories[0]["heading"], "display_headline": ANGLE,
                 "deck": stories[0]["bullets"][0] + " " + stories[0]["bullets"][1],
                 "tag": "REPO"},
        "contents": [{"n": i + 1, "head": s["heading"], "tease": s["bullets"][0]}
                     for i, s in enumerate(stories[1:], start=1)],
        "slides": stories,
        "recap": {"rows": [[s["heading"], s["verdict"]] for s in stories],
                  "take": "“" + LONG_TITLE + "”", "take_sub": "Picked for heat."},
        "cta": ["Tomorrow's digest,", "same time, same place.",
                "Follow so you don't miss it."],
        "persona": {"name": "Venu Tati",
                    "position": "AI architect — I read the firehose so you don't have to."},
        "skin": skin, "edition": 7, "total_pages": 8,
    }


def _render(spec, tmp_path):
    out = tmp_path / ("r-" + uuid.uuid4().hex[:8])
    return renderer.render_carousel(spec, str(out))


def test_bundled_font_files_exist_and_load_at_size():
    for name in ("DejaVuSans", "DejaVuSans-Bold", "DejaVuSansMono",
                 "DejaVuSansMono-Bold", "DejaVuSerif", "DejaVuSerif-Bold"):
        assert (ASSETS / "fonts" / f"{name}.ttf").exists(), f"bundled font missing: {name}"
    f = renderer.font("DejaVuSans-Bold", 40)
    assert getattr(f, "size", None) == 40, "font() fell back to PIL's default font"


def test_bundled_photo_is_a_candidate_and_resolves():
    assert (ASSETS / "venu-tati-avatar.jpg").exists()
    renderer._PERSONA_PHOTO = ""
    existing = [p for p in renderer._photo_candidates() if p and Path(p).exists()]
    assert existing, "no photo candidate exists"
    assert Path(existing[0]) == ASSETS / "venu-tati-avatar.jpg", (
        f"bundled asset must win over workspace paths, got {existing[0]}")


def test_render_qa_passes_with_long_titles(tmp_path):
    result = _render(_spec(), tmp_path)
    qa = result.get("qa")
    assert qa is not None, "render result must carry QA metadata"
    assert result["slide_count"] == 8 and qa["slide_count"] == 8
    assert qa["avatar"] == "photo", f"expected bundled photo, got {qa['avatar']}"
    assert qa["fonts_ok"] is True
    assert qa["cover_headline_size"] >= 36, qa
    assert qa["overlaps"] == 0, f"text blocks intersect: {qa}"
    assert qa["out_of_bounds"] == 0, f"text runs off the slide: {qa}"
    assert qa["passed"] is True


def test_render_qa_frontpage_skin_no_overlap(tmp_path):
    result = _render(_spec(skin="sunset"), tmp_path)
    qa = result["qa"]
    assert qa["overlaps"] == 0, f"frontpage layout overlaps: {qa}"
    assert qa["avatar"] == "photo"


def test_qa_flags_forced_monogram(tmp_path, monkeypatch):
    monkeypatch.setattr(renderer, "_photo_candidates", lambda: [])
    result = _render(_spec(), tmp_path)
    qa = result["qa"]
    assert qa["avatar"] == "monogram"
    assert qa["passed"] is False, "a monogram render must fail the QA gate visibly"


def test_makers_spec_carries_display_headline_from_angle():
    pb = load_playbook("ai-news-gtm")
    cand = {"title": LONG_TITLE, "url": "https://example.com/cua",
            "source": "Hacker News", "points": 500, "num_comments": 200,
            "snippet": "Cua offers a way for AI agents to run full OS in isolated VMs. "
                       "Open-source nature allows for community-driven development.",
            "angle": ANGLE}
    ctx = {"run_id": "qa-spec-" + uuid.uuid4().hex[:8], "playbook": pb,
           "picked": cand, "candidates": [cand], "evidence": [cand],
           "scores": {"total": 79.2},
           "score_explanation": "Picked for audience heat.",
           "topic": "today's top AI stories", "tone": "clear", "review_notes": ""}
    spec = _carousel_spec(ctx)
    assert spec["lead"].get("display_headline") == ANGLE


def test_makers_display_headline_falls_back_to_truncated_title():
    pb = load_playbook("ai-news-gtm")
    cand = {"title": LONG_TITLE, "url": "https://example.com/cua",
            "source": "Hacker News", "points": 500, "num_comments": 200,
            "snippet": "Cua offers a way for AI agents to run full OS in isolated VMs."}
    ctx = {"run_id": "qa-spec2-" + uuid.uuid4().hex[:8], "playbook": pb,
           "picked": cand, "candidates": [cand], "evidence": [cand],
           "scores": {"total": 79.2},
           "score_explanation": "Picked for audience heat.",
           "topic": "today's top AI stories", "tone": "clear", "review_notes": ""}
    spec = _carousel_spec(ctx)
    dh = spec["lead"].get("display_headline") or ""
    assert dh and len(dh) < len(LONG_TITLE), "fallback must truncate the raw title"
    assert not dh.endswith((" ", "–", "-")), "truncate at a word boundary"
