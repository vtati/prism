"""Workstream A tests: carousel artifact serving routes + ship URL.

Routes resolve run state the same way GET /runs/{id} does; for tests the
state loader (main._load_run_state) is monkeypatched with fake states and
the direct renderer (main._render_direct) is monkeypatched when a
regeneration is expected.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import graph as graph_mod  # noqa: E402
from app import main  # noqa: E402
from app.events import get_events  # noqa: E402

PDF_BYTES = b"%PDF-1.4 fake-but-plausible pdf bytes"
REGEN_PDF_BYTES = b"%PDF-1.4 regenerated pdf bytes"
PNG_BYTES = b"\x89PNG\r\n\x1a\n fake png bytes"


def _state_with_carousel(tmp_path: Path, *, pdf_exists=True, slide_count=2,
                           with_spec=False) -> tuple[dict, Path, list[Path]]:
    pdf = tmp_path / "carousel.pdf"
    if pdf_exists:
        pdf.write_bytes(PDF_BYTES)
    pngs = []
    for i in range(slide_count):
        p = tmp_path / f"slide-{i + 1:02d}.png"
        p.write_bytes(PNG_BYTES)
        pngs.append(p)
    art = {"type": "linkedin_carousel", "title": "LinkedIn carousel",
           "content": "Carousel rendered.", "pdf_path": str(pdf),
           "png_paths": [str(p) for p in pngs], "slide_count": slide_count}
    if with_spec:
        art["spec"] = {"title": "Fake spec", "skin": "poster", "edition": 1}
    return {"artifacts": {"linkedin_carousel": art}}, pdf, pngs


@pytest.fixture()
def client_with_state(monkeypatch):
    """TestClient whose run-state loader serves a per-test fake state dict.
    Set `holder['state']` (None = unknown run)."""
    holder = {"state": None}

    def fake_loader(run_id: str):
        return holder["state"]

    monkeypatch.setattr(main, "_load_run_state", fake_loader)
    return TestClient(main.app), holder


def test_helper_serves_existing_pdf_without_rendering(monkeypatch, tmp_path):
    state, pdf, _pngs = _state_with_carousel(tmp_path)
    monkeypatch.setattr(main, "_render_direct",
                        lambda *a, **k: pytest.fail("renderer must not run when the PDF exists"))
    got = main.resolve_carousel_file(state["artifacts"], "run-x")
    assert got is not None and Path(got).read_bytes() == PDF_BYTES


def test_pdf_route_serves_pdf_bytes(client_with_state, tmp_path):
    client, holder = client_with_state
    state, _pdf, _pngs = _state_with_carousel(tmp_path)
    holder["state"] = state
    r = client.get("/runs/run-x/carousel.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content.startswith(b"%PDF")


def test_pdf_route_regenerates_when_file_missing(client_with_state, monkeypatch, tmp_path):
    client, holder = client_with_state
    state, _pdf, _pngs = _state_with_carousel(tmp_path, pdf_exists=False, with_spec=True)
    holder["state"] = state
    calls = []

    def fake_render(spec, out_dir):
        calls.append((spec, out_dir))
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        pdf = out / "carousel.pdf"
        pdf.write_bytes(REGEN_PDF_BYTES)
        png = out / "slide-01.png"
        png.write_bytes(PNG_BYTES)
        return {"pdf_path": str(pdf), "png_paths": [str(png)], "slide_count": 1}

    monkeypatch.setattr(main, "_render_direct", fake_render)
    monkeypatch.setattr(main, "RUNS_DIR", tmp_path / "runs")
    r = client.get("/runs/run-x/carousel.pdf")
    assert r.status_code == 200
    assert r.content == REGEN_PDF_BYTES
    assert calls, "missing PDF must be regenerated via the direct renderer"
    assert calls[0][1].endswith("run-x/carousel")


def test_pdf_route_unknown_run_404(client_with_state):
    client, holder = client_with_state
    holder["state"] = None
    r = client.get("/runs/nope/carousel.pdf")
    assert r.status_code == 404


def test_pdf_route_no_carousel_artifact_404(client_with_state):
    client, holder = client_with_state
    holder["state"] = {"artifacts": {"briefing": {"type": "briefing", "content": "x"}}}
    r = client.get("/runs/run-x/carousel.pdf")
    assert r.status_code == 404


def test_slide_route_serves_png_and_404_beyond_range(client_with_state, tmp_path):
    client, holder = client_with_state
    state, _pdf, _pngs = _state_with_carousel(tmp_path, slide_count=2)
    holder["state"] = state
    r = client.get("/runs/run-x/carousel/slides/1.png")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content == PNG_BYTES
    r2 = client.get("/runs/run-x/carousel/slides/3.png")
    assert r2.status_code == 404
    r0 = client.get("/runs/run-x/carousel/slides/0.png")
    assert r0.status_code == 404


def test_slide_route_unknown_run_404(client_with_state):
    client, holder = client_with_state
    holder["state"] = None
    r = client.get("/runs/nope/carousel/slides/1.png")
    assert r.status_code == 404


def test_ship_includes_run_page_url(monkeypatch):
    monkeypatch.setenv("PUBLIC_WEB_BASE", "https://example.test/")
    run_id = "ship-" + uuid.uuid4().hex[:8]
    state = {"run_id": run_id, "playbook_id": "ai-news-gtm",
             "approval": {"decision": "changes"}, "artifacts": {},
             "picked": {"title": "Some AI story", "url": "https://example.com/x"},
             "scores": {"total": 42.0}, "score_explanation": "expl",
             "review": {"verdict": "pass"}}
    out = graph_mod.node_ship(state)
    assert out["ship"]["run_page_url"] == "https://example.test/runs/ai-news-gtm-latest"
    ship_events = [e for e in get_events(run_id) if e["node"] == "ship"]
    assert ship_events
    data = ship_events[-1]["data"]
    blob = str(data)
    assert "https://example.test/runs/ai-news-gtm-latest" in blob
