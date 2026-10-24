"""Scout tools. Key-free first: Hacker News via the Algolia API + generic
fetch. Tavily is used only when TAVILY_API_KEY is present. Tools are also
registered as LangChain tools and, where feasible, loaded via MCP
(langchain-mcp-adapters) — see load_mcp_tools(). Recorded fixture is the
last-resort fallback so the graph still runs offline.
"""
from __future__ import annotations

import html
import os
import re

import httpx

FIXTURE = [
    {
        "title": "Show HN: An open-source multi-agent framework hits 1.0",
        "url": "https://news.ycombinator.com/item?id=40000001",
        "source": "Hacker News (recorded fixture)",
        "points": 412, "num_comments": 188,
        "snippet": "Recorded fixture candidate used only when live search returns nothing.",
        "created_at": "2026-10-24T00:00:00Z",
    },
    {
        "title": "AI agents move from demos to production workflows, teams report",
        "url": "https://news.ycombinator.com/item?id=40000002",
        "source": "Hacker News (recorded fixture)",
        "points": 296, "num_comments": 121,
        "snippet": "Recorded fixture candidate used only when live search returns nothing.",
        "created_at": "2026-10-24T00:00:00Z",
    },
]


def _proxy() -> str | None:
    # NOTE: this environment's NO_PROXY contains bracketed IPv6 entries that
    # crash httpx's env parsing — pass the egress proxy explicitly instead.
    return (os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
            or os.environ.get("http_proxy") or None)


def _get(url, **kw):
    return httpx.get(url, proxy=_proxy(), **kw)


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def fetch_hn(query: str, limit: int = 12) -> list[dict]:
    try:
        r = _get(
            "https://hn.algolia.com/api/v1/search",
            params={"query": query, "tags": "story", "hitsPerPage": limit},
            timeout=20,
        )
        r.raise_for_status()
        out = []
        for h in r.json().get("hits", []):
            url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
            out.append({
                "title": h.get("title") or "(untitled)",
                "url": url,
                "source": "Hacker News",
                "points": h.get("points") or 0,
                "num_comments": h.get("num_comments") or 0,
                "snippet": _strip_html(h.get("story_text") or "")[:400],
                "created_at": h.get("created_at"),
            })
        return out
    except Exception:
        return []


def fetch_tavily(query: str, limit: int = 8) -> list[dict]:
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return []
    try:
        r = httpx.post(
            "https://api.tavily.com/search", proxy=_proxy(),
            json={"api_key": key, "query": query, "max_results": limit,
                  "topic": "news", "search_depth": "basic"},
            timeout=25,
        )
        r.raise_for_status()
        return [{
            "title": x.get("title") or "(untitled)",
            "url": x.get("url"),
            "source": "Tavily News",
            "points": int((x.get("score") or 0) * 500),
            "num_comments": 0,
            "snippet": (x.get("content") or "")[:400],
            "created_at": x.get("published_date"),
        } for x in r.json().get("results", []) if x.get("url")]
    except Exception:
        return []


def fetch_page_text(url: str, limit: int = 1200) -> str:
    try:
        r = _get(url, timeout=15, follow_redirects=True,
                      headers={"User-Agent": "PrismScout/0.1"})
        if r.status_code == 200 and "text/html" in r.headers.get("content-type", ""):
            return _strip_html(r.text)[:limit]
    except Exception:
        pass
    return ""


def scout_search(query: str, sources: list[str]) -> tuple[list[dict], list[str]]:
    """Returns (candidates, tool_calls_made). Retries once via a second
    source when the first returns nothing (spec §3 failure behaviour)."""
    calls: list[str] = []
    candidates: list[dict] = []
    if any("tavily" in s for s in sources):
        candidates = fetch_tavily(query)
        calls.append("mcp:tavily-search" if candidates else "mcp:tavily-search (no key/results)")
    if not candidates:
        candidates = fetch_hn(query)
        calls.append("hn-algolia")
    if not candidates:  # retry via second source with a broader query
        broader = query.split()[0] if query.split() else query
        candidates = fetch_hn(broader)
        calls.append("hn-algolia (retry, broader query)")
    if not candidates:
        candidates = [dict(c) for c in FIXTURE]
        calls.append("recorded-fixture (offline fallback)")
    # enrich top candidates with fetched page text as evidence
    for c in candidates[:5]:
        if not c.get("snippet") and c.get("url"):
            c["snippet"] = fetch_page_text(c["url"], 500)
    return candidates, calls


async def load_mcp_tools() -> list:
    """Load the Prism carousel MCP server's tools via langchain-mcp-adapters.
    Returns [] when MCP loading is unavailable — callers fall back to the
    in-process renderer module (server file remains present and runnable)."""
    try:
        import sys

        from langchain_mcp_adapters.client import MultiServerMCPClient

        from .config import CAROUSEL_DIR

        client = MultiServerMCPClient({
            "prism-carousel": {
                "command": sys.executable,
                "args": [str(CAROUSEL_DIR / "server.py")],
                "transport": "stdio",
            }
        })
        return await client.get_tools()
    except Exception:
        return []
