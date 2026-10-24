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

    spec: {title, subtitle, brand, theme:{start,end,accent},
           slides:[{heading, bullets[]}]} — bullets capped at 125 chars.
    Returns a JSON string with pdf_path, png_paths and slide_count.
    """
    spec = json.loads(spec_json)
    result = _render(spec, output_dir)
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run()
