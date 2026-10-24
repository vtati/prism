"""Maker agents: one artifact per playbook maker name, built ONLY from
Scout evidence. LLM mode polishes the grounded template; fallback mode
ships the template itself. The carousel maker renders via the MCP
carousel server when reachable, else the shared renderer module.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from .config import CAROUSEL_DIR, RUNS_DIR
from .llm import get_llm

sys.path.insert(0, str(CAROUSEL_DIR))
from renderer import render_carousel as _render_direct  # noqa: E402


def _citations(evidence: list[dict]) -> str:
    lines = [f"- [{e['title']}]({e['url']}) — {e.get('source', '')}" for e in evidence if e.get("url")]
    return "\n".join(lines)


def _evidence_block(evidence: list[dict]) -> str:
    parts = []
    for e in evidence[:5]:
        parts.append(f"• {e['title']} ({e.get('source', '')}, {e.get('points', 0)} pts) — {e['url']}"
                     + (f"\n  {e['snippet'][:220]}" if e.get("snippet") else ""))
    return "\n".join(parts)


def _polish(kind: str, fallback: str, picked: dict, evidence: list[dict], tone: str, notes: str = "") -> str:
    llm = get_llm()
    if llm.mode == "fallback":
        return fallback
    system = (f"You are Prism's {kind} maker. Tone: {tone}. Use ONLY the evidence provided; "
              "keep every source URL in the output. Return just the artifact text.")
    user = (f"Story: {picked['title']}\nEvidence:\n{_evidence_block(evidence)}\n"
            f"Draft to improve:\n{fallback}\nReviewer notes: {notes or 'none'}")
    return llm.generate(system, user, fallback)


def make_briefing(ctx) -> dict:
    p, ev, scores = ctx["picked"], ctx["evidence"], ctx["scores"]
    expl = ctx["score_explanation"]
    body = (f"# Research Briefing — {p['title']}\n\n"
            f"**The story:** {p['title']} is the top pick from {len(ctx['candidates'])} candidates "
            f"Scout gathered for \"{ctx['topic']}\".\n\n"
            f"**Why this one (Curator):** {expl}\n\n"
            f"**Scores:** {json.dumps(scores)}\n\n"
            f"**Evidence:**\n{_evidence_block(ev)}\n\n"
            f"**Sources:**\n{_citations(ev)}\n")
    body = _polish("briefing", body, p, ev, ctx["tone"], ctx.get("review_notes", ""))
    return {"type": "briefing", "title": f"Briefing: {p['title']}", "content": body,
            "citations": [e["url"] for e in ev if e.get("url")]}


def make_reel_script(ctx) -> dict:
    p, ev = ctx["picked"], ctx["evidence"]
    body = (f"# 90-Second Reel Script\n\n"
            f"**Hook (0–5s):** You need to see this — {p['title']}.\n\n"
            f"**What happened:** {p['title']}. The discussion is live right now "
            f"({p.get('points', 0)} points, {p.get('num_comments', 0)} comments on {p.get('source', '')}).\n\n"
            f"**Why it matters:** This is the story leading today's conversation — scored on the "
            f"playbook rubric: {ctx['score_explanation']}\n\n"
            f"**The take:** Watch this space — the follow-up will land in the next Brief.\n\n"
            f"Sources: {', '.join(e['url'] for e in ev[:3] if e.get('url'))}\n")
    body = _polish("reel_script", body, p, ev, ctx["tone"], ctx.get("review_notes", ""))
    return {"type": "reel_script", "title": "Reel script (90s)", "content": body,
            "citations": [e["url"] for e in ev if e.get("url")]}


def _carousel_spec(ctx) -> dict:
    p = ctx["picked"]
    theme = ctx["playbook"].get("theme") or {}
    slides = []
    for c in ctx["candidates"][:5]:
        bullets = [
            f"{c.get('points', 0)} points · {c.get('num_comments', 0)} comments on {c.get('source', '')}",
            (c.get("snippet") or "Fresh signal from today's sweep.")[:120],
            f"Source: {c['url']}"[:120],
        ]
        slides.append({"heading": c["title"][:90], "bullets": bullets})
    slides.append({"heading": "Today in one screen",
                   "bullets": [f"Top pick: {p['title']}"[:120],
                               f"Why: {ctx['score_explanation']}"[:120],
                               "Full suite + sources in the Run Page."]})
    return {
        "title": p["title"],
        "subtitle": f"Today's lead story · {ctx['scores'].get('total', '')}/100 on the rubric · "
                    f"{p.get('points', 0)} points, {p.get('num_comments', 0)} comments live",
        "brand": theme.get("brand", "Prism"),
        "theme": {"start": theme.get("start", "#38BDF8"),
                  "end": theme.get("end", "#7C6CF0"),
                  "accent": theme.get("accent", "#7C6CF0")},
        "slides": slides,
    }


def render_carousel_for_run(run_id: str, spec: dict) -> dict:
    """Try the MCP server (langchain-mcp-adapters, stdio); fall back to the
    shared renderer module. Returns renderer result + which route ran."""
    out_dir = str(RUNS_DIR / run_id / "carousel")

    async def _via_mcp():
        from .scout import load_mcp_tools

        tools = await load_mcp_tools()
        tool = next((t for t in tools if t.name == "render_carousel"), None)
        if tool is None:
            raise RuntimeError("render_carousel tool not found via MCP")
        raw = await tool.ainvoke({"spec_json": json.dumps(spec), "output_dir": out_dir})
        if isinstance(raw, list) and raw and isinstance(raw[0], dict) and "text" in raw[0]:
            text = raw[0]["text"]
        elif isinstance(raw, dict) and "text" in raw:
            text = raw["text"]
        elif isinstance(raw, str):
            text = raw
        else:
            text = json.dumps(raw)
            text = text[text.find("{"): text.rfind("}") + 1]
        return json.loads(text)

    if os.environ.get("PRISM_CAROUSEL_VIA_MCP", "1") == "1":
        try:
            result = asyncio.run(_via_mcp())
            result["via"] = "mcp"
            return result
        except Exception:
            pass
    result = _render_direct(spec, out_dir)
    result["via"] = "direct-module (MCP unavailable)"
    return result


def make_carousel(ctx) -> dict:
    spec = _carousel_spec(ctx)
    result = render_carousel_for_run(ctx["run_id"], spec)
    return {"type": "linkedin_carousel", "title": "LinkedIn carousel",
            "content": f"Carousel rendered ({result['slide_count']} slides, via {result['via']}). "
                       f"Cover: {spec['title']}",
            "pdf_path": result["pdf_path"], "png_paths": result["png_paths"],
            "slide_count": result["slide_count"], "rendered_via": result["via"],
            "citations": [c["url"] for c in ctx["candidates"][:5] if c.get("url")]}


def make_linkedin_post(ctx) -> dict:
    p, ev = ctx["picked"], ctx["evidence"]
    body = (f"{p['title']} — and it's leading today's conversation.\n\n"
            f"{ctx['score_explanation']}\n\n"
            f"What I'm watching: the reaction in the thread ({p.get('num_comments', 0)} comments and counting) "
            f"and what ships next.\n\nFull briefing + carousel in the comments.\n\n"
            f"Source: {p['url']}\n#AI #BuildInPublic")
    body = _polish("linkedin_post", body, p, ev, ctx["tone"], ctx.get("review_notes", ""))
    return {"type": "linkedin_post", "title": "LinkedIn post", "content": body,
            "citations": [p["url"]]}


def make_instagram_caption(ctx) -> dict:
    p = ctx["picked"]
    body = (f"Today's top story 👇\n{p['title']}\n\n{ctx['score_explanation']}\n\n"
            f"Full brief at the link in bio. Source: {p['url']}\n#AInews #Tech")
    body = _polish("instagram_caption", body, p, ctx["evidence"], ctx["tone"], ctx.get("review_notes", ""))
    return {"type": "instagram_caption", "title": "Instagram caption", "content": body,
            "citations": [p["url"]]}


def make_email(ctx) -> dict:
    p, ev = ctx["picked"], ctx["evidence"]
    body = (f"Subject: Today's Brief — {p['title'][:70]}\n\n"
            f"Hi there,\n\nToday's top story: {p['title']}.\n\nWhy it led: {ctx['score_explanation']}\n\n"
            f"Read the sources:\n{_citations(ev)}\n\n— Prism, for the {ctx['playbook'].get('name', '')} playbook")
    body = _polish("email", body, p, ev, ctx["tone"], ctx.get("review_notes", ""))
    return {"type": "email", "title": "Email draft", "content": body,
            "citations": [e["url"] for e in ev if e.get("url")]}


MAKER_FUNCS = {
    "briefing": make_briefing,
    "deal_briefing": make_briefing,
    "reel_script": make_reel_script,
    "linkedin_carousel": make_carousel,
    "destination_carousel": make_carousel,
    "linkedin_post": make_linkedin_post,
    "instagram_caption": make_instagram_caption,
    "email": make_email,
}


def run_makers(ctx) -> dict:
    """Run all playbook makers in parallel; unknown makers are skipped loudly."""
    names = ctx["playbook"].get("makers") or ["briefing"]
    artifacts: dict[str, dict] = {}

    def _one(name):
        fn = MAKER_FUNCS.get(name)
        if fn is None:
            return name, {"type": name, "title": name, "content": f"(no maker registered for {name})",
                          "citations": []}
        return name, fn(ctx)

    with ThreadPoolExecutor(max_workers=max(2, len(names))) as ex:
        for name, art in ex.map(_one, names):
            artifacts[name] = art
    return artifacts
