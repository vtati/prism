"""Maker agents: one artifact per playbook maker name, built ONLY from
Scout evidence. LLM mode polishes the grounded template; fallback mode
ships the template itself. The carousel maker renders via the MCP
carousel server when reachable, else the shared renderer module.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
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


# Public-facing artifacts must NEVER quote the internal rubric score/total —
# scores are curation metadata for the briefing and Run Page only, not
# reader copy (live-run review, 2026-10-24: the LinkedIn post shipped
# "scored 63.9/100" verbatim). Enforced three ways: the maker templates
# use the score-free _public_why(), the LLM prompt carries NO_SCORE_RULE,
# and _scrub_scores() strips any numeric rating from drafts AND results.
PUBLIC_KINDS = {"linkedin_post", "instagram_caption", "email", "reel_script"}
NO_SCORE_RULE = ("NEVER quote the internal rubric score, any numeric rating or score total "
                 "(e.g. '63.9/100', 'scored 87/100', 'Audience Heat 40/40') in the copy — "
                 "scores are internal curation metadata, not reader-facing content. "
                 "Say the story led the sweep, never the number it scored.")


def _system_prompt(kind: str, tone: str) -> str:
    system = (f"You are Prism's {kind} maker. Tone: {tone}. Use ONLY the evidence provided; "
              "keep every source URL in the output. Return just the artifact text.")
    if kind in PUBLIC_KINDS:
        system += " " + NO_SCORE_RULE
    return system


_SCORE_SUBS = [
    # "scored 63.9/100 (Audience Heat 7.9/40, …)" -> clean qualitative claim
    (re.compile(r"scored\s+\d+(?:\.\d+)?\s*/\s*100\s*\([^)]*\)", re.I),
     "topped the playbook rubric"),
    # a bare rubric breakdown parenthetical: "(Consequence 20/20, Novelty 18/20)"
    (re.compile(r"\(\s*(?:[A-Za-z][A-Za-z ]*\d+(?:\.\d+)?\s*/\s*\d+\s*,?\s*)+\)"), ""),
    (re.compile(r"\b\d+(?:\.\d+)?\s*/\s*100\b"), ""),
]


def _scrub_scores(text: str) -> str:
    """Remove internal rubric numbers from public copy (belt-and-braces
    alongside NO_SCORE_RULE, for both templates and LLM output)."""
    out = text or ""
    for rx, repl in _SCORE_SUBS:
        out = rx.sub(repl, out)
    out = re.sub(r"\s+([.,;:])", r"\1", out)
    return re.sub(r"[ \t]{2,}", " ", out)


def _public_why(ctx) -> str:
    """Score-free 'why this story led' sentence for public artifacts."""
    p = ctx["picked"]
    labels = [r["label"] for r in (ctx["playbook"].get("rubric") or [])]
    if labels:
        low = [l.lower() for l in labels]
        joined = ", ".join(low[:-1]) + (f" and {low[-1]}" if len(low) > 1 else low[0])
        basis = f"the playbook rubric's top pick on {joined}"
    else:
        basis = "the playbook rubric's top pick"
    return (f"\"{p['title']}\" led a sweep of {len(ctx['candidates'])} candidates — {basis}.")


def _polish(kind: str, fallback: str, picked: dict, evidence: list[dict], tone: str, notes: str = "") -> str:
    public = kind in PUBLIC_KINDS
    if public:
        fallback = _scrub_scores(fallback)
    llm = get_llm()
    if llm.mode == "fallback":
        return fallback
    user = (f"Story: {picked['title']}\nEvidence:\n{_evidence_block(evidence)}\n"
            f"Draft to improve:\n{fallback}\nReviewer notes: {notes or 'none'}")
    out = llm.generate(_system_prompt(kind, tone), user, fallback)
    return _scrub_scores(out) if public else out


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
            f"**Why it matters:** {_public_why(ctx)} It is the story leading today's conversation.\n\n"
            f"**The take:** Watch this space — the follow-up will land in the next Brief.\n\n"
            f"Sources: {', '.join(e['url'] for e in ev[:3] if e.get('url'))}\n")
    body = _polish("reel_script", body, p, ev, ctx["tone"], ctx.get("review_notes", ""))
    return {"type": "reel_script", "title": "Reel script (90s)", "content": body,
            "citations": [e["url"] for e in ev if e.get("url")]}


# ---------------------------------------------------------------------------
# Carousel — AI Dev Digest format v3 ("Front Page" system), the finalized
# production format: fixed 8 slides = masthead cover (lead headline + deck +
# ALSO IN TODAY'S DIGEST contents) / 5 story slides (why-it-matters bullets
# + one-line verdict) / "Today in one screen" recap / person-led CTA.
# Skin is the playbook's fixed carousel skin (see editions.py): poster for
# the Digest (standing default, Venugopal 2026-10-16–20), sunset for Travel.
# Bullets/verdicts are written from evidence — never raw
# engagement counts. An LLM polish pass rewrites them when a key is live.
# ---------------------------------------------------------------------------
import re
from datetime import datetime, timezone

from .editions import assign_edition, skin_for_playbook

_TAG_HINTS = [
    ("REPO", ["github", "repo", "open-source", "open source", "library", "sdk"]),
    ("RESEARCH", ["paper", "arxiv", "study", "research", "benchmark", "dataset"]),
    ("FRAMEWORKS", ["framework", "runtime", "compiler", "engine", "platform", "api"]),
    ("PRODUCT", ["launch", "launches", "release", "releases", "ships", "model", "app", "tool"]),
]
_TRAVEL_TAG_HINTS = [
    ("DEALS", ["deal", "fare", "sale", "discount", "cheap", "price drop", "offer"]),
    ("ROUTES", ["route", "flight", "airline", "airport", "train", "nonstop"]),
    ("GUIDES", ["guide", "itinerary", "tips", "how to", "best time"]),
    ("DESTINATIONS", ["destination", "city", "island", "beach", "mountain", "park"]),
]

_VERDICTS = {
    "PRODUCT": "Ship-worthy — this changes what builders can use today.",
    "FRAMEWORKS": "Under the hood, but it moves every stack built on it.",
    "REPO": "Star it now; you'll reach for it sooner than you think.",
    "RESEARCH": "Read the paper — the detail is the story.",
    "ECOSYSTEM": "Zoom out: this is the ecosystem redrawing its map.",
    "DESTINATIONS": "Put it on the list — timing is on your side.",
    "DEALS": "Bookable value, not marketing confetti. Check the dates.",
    "ROUTES": "New way in — reprice any trip you were planning.",
    "GUIDES": "Save this one; future-you says thanks at the airport.",
    "NEWS": "Worth knowing before you book anything else.",
    "_default": "Worth your time — a real signal, not noise.",
}


def _cap(text: str, limit: int = 125) -> str:
    """Truncate to `limit` chars at a WORD boundary — never mid-word
    (the old hard cut shipped cover contents lines ending '…P')."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.;:—-") + "…"


_CODEY = ("{", "}", "=>", "window.", "function(", "[data-", "();", "http://", "https://")


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", " ".join((text or "").split()))
    out = []
    for s in parts:
        s = s.strip()
        if len(s) <= 24 or any(tok in s for tok in _CODEY):
            continue  # skip scraped markup/code fragments — not reader copy
        out.append(s)
    return out


def _tag_for(candidate: dict, slots: list[str], idx: int, domain: str) -> str:
    hints = _TRAVEL_TAG_HINTS if domain == "travel-news" else _TAG_HINTS
    hay = f"{candidate.get('title', '')} {candidate.get('snippet', '')}".lower()
    for tag, keys in hints:
        if tag in slots and any(k in hay for k in keys):
            return tag
    return slots[idx % len(slots)] if slots else ""


def _story_bullets(candidate: dict) -> list[str]:
    """Three why-it-matters bullets written from the candidate's evidence.
    Bullet 1 is what happened (never the engagement counts), bullet 2 is the
    implication, bullet 3 is the concrete detail / proof."""
    sents = _sentences(candidate.get("snippet") or "")
    title = candidate.get("title", "")
    b1 = _cap(sents[0]) if sents else _cap(f"{title} — the latest from {candidate.get('source', 'the wire')}.")
    if len(sents) > 1:
        b2 = _cap(sents[1])
        if not b2.lower().startswith("why it matters"):
            b2 = _cap(f"Why it matters: {b2[0].lower() + b2[1:]}" if b2 else b2)
    else:
        b2 = _cap(f"Why it matters: it is setting the agenda in today's discussion — "
                  f"the follow-ups will build on this, not on yesterday's news.")
    if len(sents) > 2:
        b3 = _cap(sents[2])
    else:
        b3 = _cap(f"Source: {candidate.get('source', 'wire')} — full link and discussion in the Run Page.")
    return [b1, b2, b3]


def _polish_stories_llm(stories: list[dict], ctx) -> list[dict]:
    """Optional live-mode rewrite of bullets/verdicts/deck as strict JSON,
    evidence-bound. Any failure returns the grounded templates unchanged."""
    llm = get_llm()
    if llm.mode == "fallback":
        return stories
    try:
        import json as _json

        system = ("You are the carousel editor for a daily digest. Rewrite each story's bullets as "
                  "three why-it-matters bullets (<=120 chars each, no engagement counts, no hype) "
                  "and a one-line verdict (<=85 chars), using ONLY the evidence given. "
                  "Never mention scores, ratings, or '/100' numbers — they are internal metadata. "
                  "Return ONLY a JSON list of {bullets: [..], verdict: str} in the same order.")
        user = "\n\n".join(
            f"[{i}] {s['heading']}\nEvidence: {(s.get('_snippet') or '')[:400]}"
            for i, s in enumerate(stories))
        raw = llm.generate(system, user, "")
        data = _json.loads(raw[raw.find("["): raw.rfind("]") + 1])
        if isinstance(data, list) and len(data) == len(stories):
            for s, d in zip(stories, data):
                if isinstance(d, dict) and len(d.get("bullets") or []) >= 2:
                    s["bullets"] = [_cap(b, 125) for b in d["bullets"][:3]]
                    if d.get("verdict"):
                        s["verdict"] = _cap(d["verdict"], 90)
        return stories
    except Exception:
        return stories


def _resolve_broll(candidate: dict, out_dir: str, idx: int) -> str | None:
    """v3 B-roll sourcing: the story source's own lead (og:image) image,
    downloaded and validated. ANY failure returns None — flat skin design
    is the fallback and a render never blocks on an image."""
    url = candidate.get("url") or ""
    if not url.startswith("http") or "news.ycombinator.com" in url:
        return None
    try:
        import httpx
        from PIL import Image

        from .scout import _proxy  # this env needs the explicit egress proxy

        headers = {"User-Agent": "Mozilla/5.0 (Prism digest b-roll)"}
        page = httpx.get(url, timeout=6, follow_redirects=True, headers=headers, proxy=_proxy())
        m = re.search(r'property=["\']og:image["\']\s+content=["\']([^"\']+)', page.text) or \
            re.search(r'content=["\']([^"\']+)["\']\s+property=["\']og:image["\']', page.text)
        if not m:
            return None
        img_url = m.group(1)
        if img_url.startswith("//"):
            img_url = "https:" + img_url
        raw = httpx.get(img_url, timeout=6, follow_redirects=True, headers=headers, proxy=_proxy())
        if len(raw.content) < 8000:
            return None
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"broll-{idx + 1}.jpg")
        with open(path, "wb") as f:
            f.write(raw.content)
        im = Image.open(path)
        im.verify()
        return path
    except Exception:
        return None


def _carousel_spec(ctx) -> dict:
    pb = ctx["playbook"]
    car = pb.get("carousel") or {}
    domain = pb.get("domain", "")
    picked = ctx["picked"]
    edition = assign_edition(ctx["run_id"], pb.get("id", ""))
    # Skin comes from the playbook's carousel config: ai-news-gtm is fixed
    # to poster (the standing Digest default, Venugopal 2026-10-16–20),
    # travel-news to sunset; the edition rotation applies only when a
    # playbook explicitly sets carousel.skin_mode: rotation.
    skin = skin_for_playbook(pb, edition)

    # Five stories: the curator's pick leads; the rest follow by engagement.
    rest = [c for c in ctx["candidates"] if c.get("url") != picked.get("url")]
    rest.sort(key=lambda c: (c.get("points", 0), c.get("num_comments", 0)), reverse=True)
    stories_src = [picked] + rest[:4]
    while len(stories_src) < 5:  # defensive: the v3 structure needs five
        stories_src.append({"title": f"More from today's {ctx['topic']} sweep",
                              "url": picked.get("url", ""), "source": picked.get("source", ""),
                              "snippet": ctx["score_explanation"], "points": 0, "num_comments": 0})

    slots = car.get("slots") or ["PRODUCT", "FRAMEWORKS", "REPO", "RESEARCH", "ECOSYSTEM"]
    stories = []
    for i, c in enumerate(stories_src):
        tag = _tag_for(c, slots, i, domain)
        stories.append({"heading": _cap(c["title"], 110), "tag": tag,
                        "bullets": _story_bullets(c),
                        "verdict": _VERDICTS.get(tag, _VERDICTS["_default"]),
                        "_src": c, "_snippet": c.get("snippet") or ""})
    stories = _polish_stories_llm(stories, ctx)
    for s in stories:
        s.pop("_snippet", None)
    # The carousel is public copy: the lead verdict must not quote the
    # internal rubric total (score lives in the briefing / Run Page only).
    stories[0]["verdict"] = _cap(
        "Lead story — the playbook rubric's top pick. The one to read first.", 90)

    # B-roll only where the v3 rule allows it, resolved after the skin is known.
    if skin in ("neon-grid", "aurora"):
        broll_dir = str(RUNS_DIR / ctx["run_id"] / "carousel")
        for i, s in enumerate(stories):
            path = _resolve_broll(s["_src"], broll_dir, i)
            if path:
                s["broll"] = path
    for s in stories:
        s.pop("_src", None)

    now = datetime.now(timezone.utc)
    brand_short = car.get("brand_short", (pb.get("name") or "PRISM").upper())
    lead = stories[0]
    lead_sents = _sentences(stories_src[0].get("snippet") or "")
    deck = _cap(" ".join(lead_sents[:2]) if lead_sents else
                f"{picked['title']} — the story leading today's conversation, "
                f"picked from {len(ctx['candidates'])} candidates on the playbook rubric.", 300)
    # contents n = story number (2..5), matching the donor's published specs
    contents = [{"n": i + 1, "head": _cap(s["heading"], 64),
                 "tease": _cap((s["bullets"] or [""])[0], 90)} for i, s in enumerate(stories[1:], start=1)]
    take = _cap(f"“{picked['title']}”", 90)
    return {
        "kicker": f"{brand_short} #{edition} · {now.strftime('%b %d').upper()}",
        "title": car.get("title", pb.get("name", "Prism Digest")),
        "date_line": f"{now.strftime('%A, %B %d').upper()} · ISSUE No. {edition}",
        "cover_sub": f"5 things in {ctx['topic']} today — {now.strftime('%b %d')}.",
        "lead": {"heading": lead["heading"], "deck": deck, "tag": lead["tag"]},
        "contents": contents,
        "slides": stories,
        "recap": {"rows": [[s["heading"], s["verdict"]] for s in stories],
                  "take": take,
                  "take_sub": _cap(_scrub_scores(ctx["score_explanation"]), 110)},
        "cta": car.get("cta") or ["Tomorrow's digest,", "same time, same place.",
                                  "Follow so you don't miss it."],
        "persona": {"name": car.get("persona_name", "Venu Tati"),
                    "brand": car.get("persona_brand", "Venu Tati · AI Dev Digest"),
                    "position": car.get("persona_position",
                                        "AI architect — I read the firehose so you don't have to.")},
        "skin": skin,
        "edition": edition,
        "total_pages": 8,
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
                       f"Format v3 Front Page · edition #{spec['edition']} · skin {spec['skin']}. "
                       f"Cover lead: {spec['lead']['heading']}",
            "pdf_path": result["pdf_path"], "png_paths": result["png_paths"],
            "slide_count": result["slide_count"], "rendered_via": result["via"],
            "skin": spec["skin"], "edition": spec["edition"], "spec": spec,
            "citations": [c["url"] for c in ctx["candidates"][:5] if c.get("url")]}


def make_linkedin_post(ctx) -> dict:
    p, ev = ctx["picked"], ctx["evidence"]
    body = (f"{p['title']} — and it's leading today's conversation.\n\n"
            f"{_public_why(ctx)}\n\n"
            f"What I'm watching: the reaction in the thread ({p.get('num_comments', 0)} comments and counting) "
            f"and what ships next.\n\nFull briefing + carousel in the comments.\n\n"
            f"Source: {p['url']}\n#AI #BuildInPublic")
    body = _polish("linkedin_post", body, p, ev, ctx["tone"], ctx.get("review_notes", ""))
    return {"type": "linkedin_post", "title": "LinkedIn post", "content": body,
            "citations": [p["url"]]}


def make_instagram_caption(ctx) -> dict:
    p = ctx["picked"]
    body = (f"Today's top story 👇\n{p['title']}\n\n{_public_why(ctx)}\n\n"
            f"Full brief at the link in bio. Source: {p['url']}\n#AInews #Tech")
    body = _polish("instagram_caption", body, p, ctx["evidence"], ctx["tone"], ctx.get("review_notes", ""))
    return {"type": "instagram_caption", "title": "Instagram caption", "content": body,
            "citations": [p["url"]]}


def make_email(ctx) -> dict:
    p, ev = ctx["picked"], ctx["evidence"]
    body = (f"Subject: Today's Brief — {p['title'][:70]}\n\n"
            f"Hi there,\n\nToday's top story: {p['title']}.\n\nWhy it led: {_public_why(ctx)}\n\n"
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
