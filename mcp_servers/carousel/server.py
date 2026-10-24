"""Prism carousel MCP server (FastMCP, stdio).

Exposes render_carousel(spec_json, output_dir) -> {pdf_path, png_paths, slide_count}.
Run: python server.py   (speaks MCP over stdio)
The same renderer is importable as a module for in-process fallback.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from renderer import render_carousel as _render  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("prism-carousel")


@mcp.tool()
def render_carousel(spec_json: str, output_dir: str) -> str:
    """Render a 1080x1350 carousel (PDF + PNG slides) from a JSON spec.

    spec: AI Dev Digest format v3 — {kicker, title, date_line, cover_sub,
           lead{heading, deck, tag}, contents[{n, head, tease}],
           slides[5]{heading, tag, bullets[<=125 chars], verdict, broll?},
           recap{rows[[head, verdict] x5], take, take_sub}, cta[lines],
           persona{name, brand, position}, skin, edition}
    Always renders exactly 8 pages: cover + 5 stories + recap + CTA.
    Returns a JSON string with pdf_path, png_paths and slide_count.
    """
    spec = json.loads(spec_json)
    result = _render(spec, output_dir)
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run()
