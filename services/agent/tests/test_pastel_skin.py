"""Pastel skin tests (2026-10-28): Venugopal attached the Prism deck design
(pastel blobs, navy Poppins type, per-slot dash bullets, white cards) and
asked for it as the TRAVEL carousel template in Prism Studio — travel only.
These tests pin: the travel playbook selects the pastel skin (fixed), the
theme + layout are registered with accents for all five travel slots, and a
travel render produces the v3 8 slides with the QA gate passing. The AI
News poster default is untouched (covered in test_carousel_v3.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.editions import skin_for_playbook  # noqa: E402
from app.makers import _carousel_spec  # noqa: E402  (puts carousel dir on sys.path)
import renderer  # noqa: E402
from app.playbooks import load_playbook  # noqa: E402

TRAVEL_SLOTS = ["DESTINATIONS", "DEALS", "ROUTES", "GUIDES", "NEWS"]


def _travel_spec(skin="pastel"):
    stories = [{
        "heading": f"Travel story {i}: " + "a very long heading " * 3,
        "tag": TRAVEL_SLOTS[i],
        "bullets": [
            "Fares on this route dropped again this week, with wide availability.",
            "Why it matters: the shoulder-season window is when the deals land.",
            "Bookable now on the usual channels; prices verified this morning.",
        ],
        "verdict": "Worth it — book before the weekend rush reprices it.",
    } for i in range(5)]
    return {
        "kicker": "TRAVEL BRIEF #3 · OCT 28",
        "title": "Travel Brief",
        "date_line": "WEDNESDAY, OCTOBER 28 · ISSUE No. 3",
        "cover_sub": "5 things in travel today — Oct 28.",
        "lead": {"heading": stories[0]["heading"],
                 "display_headline": "Lisbon in shoulder season: fares down, crowds gone",
                 "deck": stories[0]["bullets"][0] + " " + stories[0]["bullets"][1],
                 "tag": "DESTINATIONS"},
        "contents": [{"n": i + 1, "head": s["heading"], "tease": s["bullets"][0]}
                     for i, s in enumerate(stories[1:], start=1)],
        "slides": stories,
        "recap": {"rows": [[s["heading"], s["verdict"]] for s in stories],
                  "take": "“Lisbon in shoulder season”", "take_sub": "Picked for deal value."},
        "cta": ["Tomorrow's brief,", "new routes, real deals.",
                "Follow so you don't miss it."],
        "persona": {"name": "Venu Tati",
                    "position": "I track routes, fares and seasons so you can just go."},
        "skin": skin, "edition": 3, "total_pages": 8,
    }


def test_travel_playbook_uses_pastel_fixed():
    pb = load_playbook("travel-news")
    assert pb["carousel"]["skin"] == "pastel"
    assert pb["carousel"]["skin_mode"] == "fixed"
    for edition in (1, 2, 5, 9):
        assert skin_for_playbook(pb, edition) == "pastel"


def test_pastel_theme_and_layout_registered():
    theme = renderer.THEMES["pastel"]
    assert theme["layout"] == "pastel"
    assert "pastel" in renderer._LAYOUTS
    accents = theme.get("slot_accents") or {}
    for slot in TRAVEL_SLOTS:
        assert slot in accents, f"missing pastel accent for {slot}"


def test_travel_spec_carries_pastel_skin():
    import uuid
    pb = load_playbook("travel-news")
    cands = [{
        "title": f"Travel story {i}: fares, routes and seasons",
        "url": f"https://example.com/travel-{i}", "source": "Skift",
        "points": 300 - i * 30, "num_comments": 40 - i * 3,
        "snippet": (f"Travel story {i} moved today with a concrete fare change. "
                    "It matters because the season window is short. "
                    "The deal is bookable now with verified prices."),
    } for i in range(6)]
    ctx = {"run_id": "pastel-" + uuid.uuid4().hex[:8], "playbook": pb,
           "picked": cands[0], "candidates": cands, "evidence": cands[:5],
           "scores": {"total": 81.0},
           "score_explanation": "Picked for deal value and seasonality.",
           "topic": "travel destinations", "tone": "warm", "review_notes": ""}
    spec = _carousel_spec(ctx)
    assert spec["skin"] == "pastel"


def test_pastel_render_is_8_slides_and_passes_qa(tmp_path):
    out = renderer.render_carousel(_travel_spec(), str(tmp_path))
    assert out["skin"] == "pastel"
    # Not the frontpage fallback: the pastel layout itself must have run.
    assert renderer.THEMES["pastel"]["layout"] == "pastel"
    assert out["slide_count"] == 8
    # Pixel pin: slide 1 carries the pastel background — the sky blob at the
    # top-left and the gradient bar along the top edge.
    from PIL import Image
    cover = Image.open(out["png_paths"][0]).convert("RGB")
    assert cover.getpixel((30, 120)) == (219, 238, 255)  # sky blob
    r, g, b = cover.getpixel((5, 8))  # gradient bar starts sky-blue
    assert b > 200 and r < 100
    assert len(out["png_paths"]) == 8
    assert Path(out["pdf_path"]).exists()
    qa = out["qa"]
    assert qa["passed"], f"pastel render QA failed: {qa}"
    assert qa["avatar"] == "photo"
    assert qa["fonts_ok"]
    assert qa["overlaps"] == 0
    assert qa["out_of_bounds"] == 0
    assert (qa["cover_headline_size"] or 0) >= renderer.HEADLINE_FLOOR


def test_pastel_glyph_normalization():
    # Poppins has no U+02BB (ʻokina) — it tofu-boxed on the first live
    # staging render ("Faʻa Sāmoa"). It must map to the Poppins apostrophe,
    # recursively, without mutating the caller's spec.
    src = {"lead": {"deck": "Fa\u02bba Sāmoa and Fa\u02bcana"},
           "slides": [{"bullets": ["Fa\u02bba"]}]}
    out = renderer._pastel_normalize(src)
    assert out["lead"]["deck"] == "Fa\u2019a Sāmoa and Fa\u2019ana"
    assert out["slides"][0]["bullets"] == ["Fa\u2019a"]
    assert "\u02bb" in src["lead"]["deck"], "input spec must not be mutated"


def test_pastel_edge_case_specs_pass_qa(tmp_path):
    """The shapes render_carousel itself guarantees must degrade gracefully:
    padded stories (no bullets/verdict/tag), fewer contents, builder-capped
    long deck/verdict, an unknown slot tag, over-long bullets."""
    import copy
    base = _travel_spec()

    padded = copy.deepcopy(base)
    padded["slides"] = [{"heading": f"Story {i}", "tag": "", "bullets": [],
                         "verdict": ""} for i in range(5)]
    padded["contents"] = padded["contents"][:2]
    padded["recap"]["rows"] = [[s["heading"], ""] for s in padded["slides"]]

    capped = copy.deepcopy(base)
    capped["lead"]["deck"] = ("Fares fell again on this route with wide open "
                               "availability across the whole month. ") * 4  # ~300 cap
    capped["slides"][0]["verdict"] = "Worth it — " + "book it before prices move. " * 5
    capped["slides"][1]["tag"] = "UNKNOWN-SLOT"
    capped["slides"][2]["bullets"] = [
        "Why it matters: " + "the season window is short and fares move fast. " * 3,
        "Book early: the early fares vanish first, usually by Friday.",
        "A third point that runs long: " + "with verified prices this morning. " * 3,
        "A fourth bullet a future source might emit beyond the v3 cap.",
    ]

    for name, spec in (("padded", padded), ("capped", capped)):
        out = renderer.render_carousel(spec, str(tmp_path / name))
        assert out["qa"]["passed"], f"{name} spec QA failed: {out['qa']}"
