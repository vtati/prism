"""Prism LangGraph: supervisor -> scout -> curator -> archivist -> makers
(parallel) -> reviewer (loop max 2) -> human gate (interrupt) -> ship."""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from . import makers as maker_mod
from .config import RUNS_DIR
from .events import emit
from .llm import get_llm
from .playbooks import brand_voice, load_past_runs, load_playbook, record_past_run
from .scout import scout_search


class PrismState(TypedDict, total=False):
    run_id: str
    playbook_id: str
    input: str
    topic: str
    candidates: list
    evidence: list
    picked: dict
    scores: dict
    score_explanation: str
    selection: dict
    angle: str
    style_pack: str
    duplicate: bool
    artifacts: dict
    review: dict
    review_notes: str
    approval: dict
    ship: dict
    status: str
    run_meta: dict


# ---------- scoring (Curator) ----------
CONSEQUENCE_WORDS = ["launch", "release", "raises", "acquire", "regulation", "law", "price",
                     "security", "outage", "breakthrough", "ships", "announces", "open-source", "open source"]
DEAL_WORDS = ["deal", "sale", "off", "%", "cheap", "flight", "hotel", "discount"]
URGENCY_WORDS = ["today", "limited", "deadline", "last chance", "ends", "now", "hurry"]
SEASON_WORDS = ["summer", "winter", "fall", "autumn", "spring", "holiday", "christmas", "festival"]


def _kw(text: str, words: list[str]) -> float:
    t = (text or "").lower()
    return min(1.0, sum(1 for w in words if w in t) / 3.0)


def score_candidate(c: dict, rubric: list[dict], past_urls: set, past_titles: set) -> dict:
    pts, comments = c.get("points", 0), c.get("num_comments", 0)
    heat = min(1.0, (math.log10(pts + 1) / 3.0) * 0.7 + (math.log10(comments + 1) / 2.5) * 0.3)
    text = f"{c.get('title', '')} {c.get('snippet', '')}"
    # Verification: a resolvable source URL is the base signal (0.9).
    # Independent corroboration — Scout's merge saw the same story on 2+
    # channels (HN + Reddit + GDELT + Trends + editorial) — adds +0.1 per
    # extra channel, capped at 1.0: a single-source story tops out at
    # 0.9 (18/20 on the Digest rubric), a corroborated one can max it.
    corr = int(c.get("corroboration") or 1)
    verification = min(1.0, (0.9 if c.get("url") else 0.2) + 0.1 * max(0, corr - 1))
    raw = {
        "audience_heat": heat,
        "consequence": max(0.25, _kw(text, CONSEQUENCE_WORDS)),
        "verification": verification,
        "novelty": 0.1 if (c.get("url") in past_urls or c.get("title") in past_titles) else 0.9,
        "deal_value": max(heat * 0.6, _kw(text, DEAL_WORDS)),
        "urgency": max(0.3, _kw(text, URGENCY_WORDS)),
        "seasonality": max(0.35, _kw(text, SEASON_WORDS)),
    }
    scores, total = {}, 0.0
    for r in rubric:
        v = round(raw.get(r["key"], 0.5) * r["weight"], 1)
        scores[r["key"]] = v
        total += v
    scores["total"] = round(total, 1)
    return scores


# ---------- selection quality (Curator) ----------
# Eligibility is a hard gate BEFORE the winner is picked: a story must be
# materially about the playbook's domain, judged over title + snippet.
# Keyword lists live here, keyed by playbook id; when the OpenAI LLM is
# live, one batched classification over the top-scored candidates wins
# and the keyword test is only the fallback.
_DOMAIN_LABELS = {"ai-news-gtm": "AI", "travel-news": "travel"}
_DOMAIN_TERMS = {
    "ai-news-gtm": [
        "ai", "artificial intelligence", "llm", "llms", "large language model",
        "large language models", "gpt", "chatgpt", "claude", "openai",
        "anthropic", "gemini", "deepmind", "machine learning", "deep learning",
        "neural", "neural network", "neural networks", "ai model", "ai models",
        "ai agent", "ai agents", "agentic", "agent", "agents", "chatbot",
        "chatbots", "on-device ai", "generative ai", "genai", "copilot",
        "mistral", "llama", "perplexity", "hugging face", "ai-powered",
        "ai powered", "ai chip", "ai chips",
    ],
    "travel-news": [
        "flight", "flights", "airline", "airlines", "airport", "airports",
        "airfare", "airfares", "travel", "traveler", "travelers", "vacation",
        "vacations", "cruise", "cruises", "destination", "destinations",
        "hotel", "hotels", "tourism", "tourist", "tourists", "itinerary",
        "itineraries", "resort", "resorts", "fare", "fares", "trip", "trips",
        "getaway", "visa", "passport",
    ],
}


def _norm_text(s: str) -> str:
    return re.sub(r"[-_]+", " ", (s or "").lower())


def assess_eligibility(candidate: dict, playbook_id: str) -> bool:
    """Keyword-path domain eligibility over title + snippet. Playbooks
    without a term list are ungated (everything is eligible)."""
    terms = _DOMAIN_TERMS.get(playbook_id)
    if not terms:
        return True
    text = _norm_text(f"{candidate.get('title', '')} {candidate.get('snippet', '')}")
    return any(re.search(rf"\b{re.escape(_norm_text(t))}\b", text) for t in terms)


def _llm_eligibility(scored: list, playbook_id: str) -> dict | None:
    """One batched LLM classification over the top 8 scored candidates.
    Returns {scored_index: bool} or None when unavailable/unparseable —
    the caller then falls back to the keyword test. LLM result wins."""
    label = _DOMAIN_LABELS.get(playbook_id)
    if not label:
        return None
    llm = get_llm()
    if getattr(llm, "mode", None) != "openai":
        return None
    top = scored[:8]
    listing = "\n\n".join(
        f"[{i}] {c.get('title', '')}\n{(c.get('snippet') or '')[:300]}"
        for i, (_s, c) in enumerate(top))
    system = (f"You classify news stories for a {label} digest. For each story, decide whether it is "
              f"STRICTLY and materially about {label} (the domain itself is a real angle of the "
              f"story, not a passing mention in an unrelated story). "
              f"Return ONLY a JSON list of booleans in the same order, e.g. [true, false].")
    try:
        raw = llm.generate(system, listing, "")
    except Exception:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw[raw.find("["): raw.rfind("]") + 1])
    except Exception:
        return None
    out: dict[int, bool] = {}
    if isinstance(data, list):
        for i, v in enumerate(data[: len(top)]):
            if isinstance(v, bool):
                out[i] = v
            elif isinstance(v, dict) and isinstance(v.get("eligible"), bool):
                out[i] = v["eligible"]
    return out or None


def _fallback_angle(picked: dict) -> str:
    """Angle without an LLM: the snippet's first sentence, trimmed;
    the title when there is no usable snippet."""
    snippet = " ".join((picked.get("snippet") or "").split())
    if snippet:
        first = re.split(r"(?<=[.!?])\s+", snippet)[0].strip()
        if first:
            if len(first) > 200:
                first = first[:199].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"
            return first
    return (picked.get("title") or "").strip()


def derive_angle(picked: dict, playbook_id: str) -> str:
    """One-line headline angle for the winner. LLM when live (<=16 words,
    no hype, no score); grounded fallback otherwise."""
    fallback = _fallback_angle(picked)
    llm = get_llm()
    if getattr(llm, "mode", "fallback") == "fallback":
        return fallback
    label = _DOMAIN_LABELS.get(playbook_id, "the playbook's domain")
    system = (f"Frame the story as a one-line {label} headline: at most 16 words, "
              f"no hype, no exclamation, never mention any score or rating. "
              f"Return only the headline.")
    user = f"Title: {picked.get('title', '')}\nSnippet: {(picked.get('snippet') or '')[:400]}"
    try:
        out = llm.generate(system, user, fallback)
    except Exception:
        return fallback
    out = (out or "").strip().strip('"').splitlines()[0].strip() if out else ""
    if not out:
        return fallback
    words = out.split()
    return " ".join(words[:16]) if len(words) > 16 else out


# ---------- nodes ----------
def node_supervisor(state: PrismState) -> dict:
    rid = state["run_id"]
    pb = load_playbook(state["playbook_id"])
    topic = (state.get("input") or "").strip() or pb.get("default_query", "today")
    llm = get_llm()
    emit(rid, "supervisor", "Supervisor", "started",
         f"Run started · playbook={pb['id']} · LLM mode={llm.mode} · topic=\"{topic}\"",
         {"playbook_id": pb["id"], "llm_mode": llm.mode, "llm_model": llm.model})
    return {"topic": topic, "status": "scouting",
            "run_meta": {"llm_mode": llm.mode, "llm_model": llm.model, "playbook_name": pb["name"]}}


def node_scout(state: PrismState) -> dict:
    rid = state["run_id"]
    pb = load_playbook(state["playbook_id"])
    emit(rid, "scout", "Scout", "started", f"Scout is rummaging for \"{state['topic']}\"…")

    def _progress(channel: str, count: int) -> None:
        # The sweep can run for minutes; one event per finished source
        # family keeps the SSE stream (and the UI) visibly alive.
        labels = {"tavily-search": "Tavily search", "hn-frontpage": "HN front page",
                  "hn-algolia": "HN search", "reddit": "Reddit", "gdelt": "GDELT news wire",
                  "trends": "Google Trends", "editorial": "Editorial feeds",
                  "recorded-fixture": "Recorded fixture"}
        if channel == "enrich":
            msg = "Reading the top stories in full to build the evidence pack…"
        elif channel == "merged":
            msg = f"Pool merged — {count} unique candidates"
        else:
            msg = f"{labels.get(channel, channel)} — {count} candidates so far"
        emit(rid, "scout", "Scout", "progress", msg,
             {"channel": channel, "count": count})

    candidates, calls, stats = scout_search(state["topic"], pb.get("research") or {},
                                            pb.get("sources") or [], progress=_progress)
    emit(rid, "scout", "Scout", "done",
         f"Scout gathered {len(candidates)} candidates via {', '.join(calls)}",
         {"tool_calls": calls, "count": len(candidates), "by_source": stats,
          "candidates": [{"title": c["title"], "url": c["url"]} for c in candidates]})
    meta = dict(state.get("run_meta") or {})
    meta["tool_calls"] = calls
    meta["source_counts"] = stats
    return {"candidates": candidates, "evidence": candidates[:5], "run_meta": meta, "status": "curating"}


def node_curator(state: PrismState) -> dict:
    rid = state["run_id"]
    pb = load_playbook(state["playbook_id"])
    past = load_past_runs()
    past_urls = {r.get("url") for r in past}
    past_titles = {r.get("title") for r in past}
    scored = [(score_candidate(c, pb["rubric"], past_urls, past_titles), c) for c in state["candidates"]]
    scored.sort(key=lambda x: x[0]["total"], reverse=True)

    # Selection gate: in score order, skip ineligible stories and stories
    # below the playbook's rubric floor; the first candidate passing both
    # wins. If none pass, fall back to the top eligible story, else the
    # top story overall — selection never crashes a run.
    sel_cfg = pb.get("selection") or {}
    floor_key = sel_cfg.get("floor_key")
    floor_min = sel_cfg.get("floor_min")
    label = _DOMAIN_LABELS.get(pb["id"], "the domain")
    llm_map = _llm_eligibility(scored, pb["id"])
    if llm_map is not None:
        eligibility_source = "llm"
    elif pb["id"] in _DOMAIN_TERMS:
        eligibility_source = "keywords"
    else:
        eligibility_source = "none"

    def _eligible(idx: int, cand: dict) -> bool:
        if llm_map is not None and idx in llm_map:
            return bool(llm_map[idx])
        return assess_eligibility(cand, pb["id"])

    passed_over: list[dict] = []
    winner = None
    for idx, (s, c) in enumerate(scored):
        if not _eligible(idx, c):
            passed_over.append({"title": c.get("title"),
                                "reason": f"ineligible — not materially about {label}"})
            continue
        if floor_key and floor_min is not None and s.get(floor_key, 0) < floor_min:
            passed_over.append({"title": c.get("title"),
                                "reason": f"below {floor_key} floor {floor_min}"})
            continue
        winner = (s, c)
        break
    fallback = None
    if winner is None:
        eligible = [(s, c) for idx, (s, c) in enumerate(scored) if _eligible(idx, c)]
        if eligible:
            winner, fallback = eligible[0], "top_eligible"
        else:
            winner, fallback = scored[0], "top_overall"
    selection = {"passed_over": passed_over, "floor_key": floor_key,
                 "floor_min": floor_min, "eligibility": eligibility_source,
                 "fallback": fallback}

    scores, picked_src = winner
    angle = derive_angle(picked_src, pb["id"])
    picked = dict(picked_src)
    picked["angle"] = angle
    parts = ", ".join(f"{r['label']} {scores.get(r['key'], 0)}/{r['weight']}" for r in pb["rubric"])
    expl = (f"\"{picked['title']}\" scored {scores['total']}/100 ({parts}) across "
            f"{len(scored)} candidates, with {picked.get('points', 0)} points and "
            f"{picked.get('num_comments', 0)} comments of live discussion.")
    if (picked.get("corroboration") or 1) >= 2:
        expl += (f" Corroborated by {picked['corroboration']} independent sources "
                 f"({picked.get('source', '')}) — verification boosted.")
    if passed_over:
        detail = "; ".join(f"\"{p['title']}\" ({p['reason']})" for p in passed_over)
        expl += f" Passed over {len(passed_over)} higher-scored stories: {detail}."
    if fallback:
        expl += f" No candidate cleared the selection gate; fell back to the {fallback.replace('_', ' ')}."
    emit(rid, "curator", "Curator", "done", f"Curator picked the lead story. {expl}",
         {"scores": scores, "picked": picked["title"], "angle": angle,
          "passed_over": passed_over, "selection": selection})
    return {"picked": picked, "scores": scores, "score_explanation": expl,
            "selection": selection, "angle": angle, "status": "archiving"}


def node_archivist(state: PrismState) -> dict:
    rid = state["run_id"]
    past = load_past_runs()
    picked = state["picked"]
    duplicate = any(r.get("url") == picked.get("url") or r.get("title") == picked.get("title") for r in past)
    style = brand_voice()
    emit(rid, "archivist", "Archivist", "done",
         f"Style pack loaded ({len(style)} chars); dedupe check: {'DUPLICATE — flagged' if duplicate else 'fresh story'}",
         {"duplicate": duplicate})
    # The evidence pack the Makers build from leads with the picked
    # story: Scout's top-5-by-engagement can miss the Curator's winner,
    # and every artifact is about the pick — its record must be in the
    # pack they cite (Reviewer v2 checks claims against cited records).
    ev = state.get("evidence") or []
    evidence = [picked] + [e for e in ev if e.get("url") != picked.get("url")]
    return {"style_pack": style, "duplicate": duplicate,
            "evidence": evidence[:5], "status": "making"}


def _maker_ctx(state: PrismState, review_notes: str = "") -> dict:
    pb = load_playbook(state["playbook_id"])
    return {"run_id": state["run_id"], "playbook": pb, "picked": state["picked"],
            "candidates": state["candidates"], "evidence": state["evidence"],
            "scores": state["scores"], "score_explanation": state["score_explanation"],
            "topic": state["topic"], "tone": (pb.get("audience") or {}).get("tone", "clear"),
            "review_notes": review_notes or state.get("review_notes", "")}


def node_makers(state: PrismState) -> dict:
    rid = state["run_id"]
    names = load_playbook(state["playbook_id"]).get("makers") or []
    emit(rid, "makers", "Makers", "started", f"{len(names)} makers building in parallel: {', '.join(names)}")
    artifacts = maker_mod.run_makers(_maker_ctx(state))
    for name, art in artifacts.items():
        emit(rid, "makers", "Makers", "artifact", f"Artifact ready: {name}",
             {"artifact": name, "type": art.get("type"),
              "pdf_path": art.get("pdf_path"), "slide_count": art.get("slide_count")})
    emit(rid, "makers", "Makers", "done", f"Suite assembled: {len(artifacts)} artifacts")
    return {"artifacts": artifacts, "status": "reviewing"}


HYPE_WORDS = ["mind-blowing", "revolutionary!!!", "guaranteed", "!!!"]


# ---------- Reviewer v2: claim-support check ----------
# Aishwarya's Week 3 review (2026-11-04): a cited URL + length check does
# NOT establish that a claim is true. Reviewer v2 splits each artifact
# into factual claims (sentences carrying a checkable key fact — a
# number, a named entity, a month/weekday date) and requires every key
# fact to appear in the text of the sources the artifact actually cites
# (Scout already stores title + snippet/page text per record in state;
# no new fetching layer). The lexical key-fact check is the HARD gate:
# an unsupported claim produces a specific note and feeds the existing
# revise loop. Pure opinion / CTA sentences carry no key fact and are
# exempt, as are headings, source listings, the internal Scores line,
# production receipts (carousel render lines) and sign-offs — none of
# those assert a fact about the story.
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday"]
# Prism's own product vocabulary, pronouns and sentence furniture:
# capitalised in copy all the time, never an external factual entity.
# Name components are deliberately NOT here — "New" (New York), "First"
# (First Republic Bank), "LinkedIn"/"Instagram" (claims can be ABOUT
# them) must survive extraction; edge trimming uses _LEADING_STOP only.
_ENTITY_STOP = {
    "prism", "briefing", "brief", "sources", "source", "subject", "hook",
    "take", "why", "what", "when", "the", "a", "an", "it", "this", "that",
    "today", "full", "read", "watch", "follow", "carousel", "digest",
    "slide", "slides", "edition", "playbook", "curator", "scout",
    "reviewer", "maker", "makers", "research", "scores", "score",
    "evidence", "story", "stories", "top", "next", "hi", "hello",
    "reel", "script", "post", "caption", "email", "page",
    "you", "we", "they", "he", "she", "i", "i'm", "you're", "we're",
    "let's", "us", "our", "your", "their",
}
# Furniture words trimmed from the EDGES of a capitalised run only.
_LEADING_STOP = {"the", "a", "an", "this", "that", "today", "what",
                 "why", "when", "hi", "hello"}
_ENTITY_CONNECTORS = {"of", "the", "and", "&", "for", "de"}
_MAGNITUDES = {"thousand", "million", "billion", "trillion"}
_MONTH_CANON = {"jan": "january", "feb": "february", "mar": "march",
                "apr": "april", "jun": "june", "jul": "july",
                "aug": "august", "sep": "september", "sept": "september",
                "oct": "october", "nov": "november", "dec": "december",
                **{m: m for m in ["january", "february", "march", "april",
                                   "june", "july", "august", "september",
                                   "october", "november", "december"]}}
_NUMBER_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
                 "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                 "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
                 "fourteen": 14, "fifteen": 15, "sixteen": 16,
                 "seventeen": 17, "eighteen": 18, "nineteen": 19,
                 "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
                 "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_NUMBER_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000,
                  "billion": 1_000_000_000, "trillion": 1_000_000_000_000}


def _num_norm(raw: str) -> str:
    """Normalise a numeric token so '1,000', '1000' and '1000.0' compare
    equal; percentages and $ amounts reduce to the bare number."""
    s = (raw or "").replace(",", "").replace("$", "").replace("%", "").strip()
    try:
        v = float(s)
    except ValueError:
        return s
    return str(int(v)) if v == int(v) else str(v)


def _extract_numbers(text: str) -> set:
    return {_num_norm(m) for m in re.findall(r"\$?\d[\d,]*(?:\.\d+)?\s?%?", text or "")}


def _match_norm(text: str) -> str:
    """Lowercase word-normal form for entity matching: punctuation and
    hyphens become spaces, so 'computer-use' matches 'computer use'."""
    t = re.sub(r"[-_/]+", " ", (text or "").lower())
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _cap_kind(tok: str) -> str | None:
    core = (tok or "").strip("'.-")
    if len(core) < 2:
        return None
    if core.isupper():
        return "acronym"
    if any(c.isupper() for c in core[1:]):
        return "internal"  # OpenAI, GitHub, macOS, iPhone
    if core[:1].isupper() and core[1:].islower():
        return "capitalized"
    if core[:1].isupper():
        return "capitalized"
    return None


def _stop_form(tok: str) -> str:
    """Comparison form for stop-word checks: lowercase, punctuation
    stripped, possessive 's dropped ('Today's' -> 'today')."""
    s = (tok or "").lower().strip("'.-")
    return s[:-2] if s.endswith("'s") else s


def _extract_entities(sentence: str) -> list:
    """Named entities: runs of capitalised tokens. A lone capitalised
    token counts only mid-sentence (sentence-start capitals are grammar,
    not names) or when it is an acronym / internally capitalised. The
    returned phrase is built from the RETAINED span (after furniture
    trimming), so 'New York Times' and 'First Republic Bank' survive
    whole."""
    toks = re.findall(r"[A-Za-z][A-Za-z0-9&'.-]*", sentence or "")
    kinds = [_cap_kind(t) for t in toks]
    entities, run = [], []

    def _flush(run):
        words = [(t, k, i) for (t, k, i) in run if k is not None]
        # A clause-start gerund/past-tense verb is grammar, not a name:
        # 'Sharing API data…' must not mint the entity 'Sharing API'.
        if len(words) > 1 and words[0][2] == 0 \
                and _stop_form(words[0][0]).endswith(("ing", "ed")):
            words.pop(0)
        while words and _stop_form(words[0][0]) in _LEADING_STOP:
            words.pop(0)
        while words and _stop_form(words[-1][0]) in _LEADING_STOP:
            words.pop()
        if not words:
            return
        if all(_stop_form(w[0]) in _ENTITY_STOP for w in words):
            return
        if len(words) == 1:
            tok, kind, idx = words[0]
            if _stop_form(tok) in _ENTITY_STOP:
                return
            if idx == 0 and kind == "capitalized":
                return  # ordinary sentence-start capital
            entities.append(tok.strip("'.-"))
        else:
            entities.append(" ".join(toks[words[0][2]: words[-1][2] + 1]).strip("'.-"))

    for i, (tok, kind) in enumerate(zip(toks, kinds)):
        if kind is not None or tok.lower() in _ENTITY_CONNECTORS:
            run.append((tok, kind, i))
        else:
            _flush(run)
            run = []
    _flush(run)
    return entities


def _extract_dates(text: str) -> set:
    """Month (canonicalised: sep/sept -> september) and weekday names.
    'May' counts only in a date context (May 2026 / 4 May) — as a bare
    word it is usually the verb."""
    t = f" {_match_norm(text)} "
    out = {_MONTH_CANON[d] for d in _MONTH_CANON if f" {d} " in t}
    if re.search(r"\bmay\s+\d{1,2}\b|\bmay\s+\d{4}\b|\b\d{1,2}\s+may\b", (text or "").lower()):
        out.add("may")
    out |= {d for d in _WEEKDAYS if f" {d} " in t}
    return out


def _extract_magnitudes(text: str) -> set:
    toks = set(_match_norm(text).split())
    return {m for m in _MAGNITUDES if m in toks}


def _extract_number_words(text: str) -> set:
    """Spelled-out quantities — counted only when a scale word makes
    them unambiguous facts ('forty million', 'two hundred'), so idioms
    like 'the one to read' stay exempt. Yields both the full value and,
    for magnitude scales, the base ('40' for 'forty million', matching
    how sources write '$40 million')."""
    toks = _match_norm(text).split()
    out, i = set(), 0
    while i < len(toks):
        if toks[i] in _NUMBER_WORDS or toks[i] in _NUMBER_SCALES:
            j, current, total, scale_seen, biggest = i, 0, 0, False, 1
            while j < len(toks) and (toks[j] in _NUMBER_WORDS or toks[j] in _NUMBER_SCALES
                                     or toks[j] == "and"):
                w = toks[j]
                if w in _NUMBER_WORDS:
                    current += _NUMBER_WORDS[w]
                elif w == "hundred":
                    scale_seen = True
                    current = (current or 1) * 100
                elif w in _NUMBER_SCALES:
                    scale_seen = True
                    biggest = max(biggest, _NUMBER_SCALES[w])
                    total += (current or 1) * _NUMBER_SCALES[w]
                    current = 0
                j += 1
            value = total + current
            if scale_seen and value > 0:
                out.add(_num_norm(str(value)))
                if biggest >= 1000:
                    out.add(_num_norm(str(value // biggest)))
            i = j
        else:
            i += 1
    return out


def key_facts(text: str) -> dict:
    """The checkable facts in a claim: numbers (digits + spelled-out
    quantities), named entities, dates, and magnitude words — 'million'
    in '5 million users' is itself a fact the source must contain."""
    return {"numbers": _extract_numbers(text) | _extract_number_words(text),
            "entities": _extract_entities(text),
            "dates": _extract_dates(text),
            "magnitudes": _extract_magnitudes(text)}


def _is_exempt_line(line: str) -> bool:
    s = line.strip().lstrip("#> ").strip()
    bare = s.replace("**", "").strip()
    if not bare:
        return True
    if line.lstrip().startswith("#"):
        return True  # heading
    if bare.startswith("- [") or bare.startswith("• ["):
        return True  # citation listing
    if re.match(r"(?i)^(sources?|scores?)\s*:", bare):
        return True  # source list header / internal rubric JSON
    if bare.lower().startswith("why this one"):
        return True  # the briefing's curator paragraph restates internal
        # scoring metadata (totals, rubric splits) — curation, not a
        # claim about the story; the Scores line rule covers the JSON.
    if bare.startswith("— Prism") or bare.startswith("- Prism,"):
        return True  # sign-off
    if re.fullmatch(r"https?://\S+", bare):
        return True  # bare URL line
    return False


def _clean_line(line: str) -> str:
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)      # md link -> text
    s = re.sub(r"https?://\S+", " ", s)                    # bare URLs
    s = re.sub(r"\(\d+\s*[–—-]\s*\d+\s*s\)", " ", s)       # reel timing (0–5s)
    s = re.sub(r"#\w+", " ", s)                            # hashtags are tags, not claims
    s = s.replace("**", " ").replace("__", " ").replace("`", " ")
    s = re.sub(r"^\s*[•\-*]\s+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _is_receipt(sentence: str) -> bool:
    """Production receipts describe the render, not the story."""
    return ("carousel rendered" in sentence.lower()
            or (sentence.startswith("Format v") and "skin" in sentence))


def _lead_token(text: str) -> str:
    toks = re.findall(r"[A-Za-z][A-Za-z0-9&'.-]*", text or "")
    return toks[0] if toks else ""


def split_claims(content: str, known_tokens: set | None = None) -> list:
    """Factual claims in an artifact: clauses carrying at least one
    checkable key fact, after exempt lines/receipts are removed.
    Sentences are split into clauses on ':' / ';' / ' — ' so maker
    labels ('Hook:', 'What happened:', 'Subject:') never merge into
    the claim that follows them. A clause whose first word is a
    capitalised entity the cited sources themselves name also counts
    (sentence-start names are otherwise skipped as grammar)."""
    claims = []
    for raw in re.split(r"\n+", content or ""):
        line = raw.strip()
        if not line or _is_exempt_line(line):
            continue
        cleaned = _clean_line(line)
        if not cleaned:
            continue
        for sent in re.split(r"(?<=[.!?])\s+", cleaned):
            for clause in re.split(r":\s+|;\s+|\s+—\s+", sent):
                s = clause.strip()
                if len(s) < 12 or _is_receipt(s):
                    continue
                # A standalone all-capitalised short line is a heading
                # or label ('Key Insights:', 'Separation Strategy'),
                # not a claim — LLM-polished artifacts use them as
                # section furniture.
                clause_toks = re.findall(r"[A-Za-z][A-Za-z0-9&'.-]*", s)
                if 0 < len(clause_toks) <= 6 and all(
                        _cap_kind(t) is not None or t.lower() in _ENTITY_CONNECTORS
                        for t in clause_toks):
                    continue
                facts = key_facts(s)
                lead = _lead_token(s)
                lead_known = (known_tokens and lead
                              and _cap_kind(lead) is not None
                              and _stop_form(lead) not in _ENTITY_STOP
                              and _match_norm(lead) in known_tokens)
                if facts["numbers"] or facts["entities"] or facts["dates"] \
                        or facts["magnitudes"] or lead_known:
                    claims.append(s)
    return claims


def _record_text(rec: dict) -> str:
    """The support text a source record carries in state: title +
    snippet/page text + channel, plus its engagement metadata (makers
    legitimately quote the picked story's points/comments) and its
    corroboration count."""
    text = (f"{rec.get('title', '')}. {rec.get('snippet', '')} "
            f"Source: {rec.get('source', '')}. "
            f"{rec.get('points', 0)} points, {rec.get('num_comments', 0)} comments.")
    corr = int(rec.get("corroboration") or 1)
    if corr >= 2:
        text += f" Corroborated by {corr} independent sources."
    return text


def check_claims(content: str, sources: list, internal_text: str = "") -> list:
    """Link each factual claim to supporting source content.

    Returns one dict per claim: {claim, source_url, supporting_sources,
    support, missing}. support is 'supported' when every key fact
    (number / named entity / date / magnitude) in the claim appears in
    the text of the sources the artifact CITES, 'unsupported' with the
    missing facts listed, or 'no-source' when the artifact cites no
    source record at all.

    Named entities are checked ONLY against cited source text — never
    against internal run state. `internal_text` carries verified
    run-state facts (candidate count, run date) and may support NUMBER
    and DATE facts only: makers legitimately restate 'from 318
    candidates', and a fabricated story entity must never pass because
    an internal string happened to contain it.

    This is a lexical key-fact screen: it verifies that a claim's
    checkable facts are present in its cited sources. It does not
    prove entailment (negation or relation swaps remain a known
    limitation, documented in the README).
    """
    src_corpus = "\n".join(_record_text(r) for r in (sources or []))
    src_norm = _match_norm(src_corpus)
    src_tokens = set(src_norm.split())
    full_norm = _match_norm(src_corpus + "\n" + (internal_text or ""))
    full_numbers = _extract_numbers(src_corpus) | _extract_numbers(internal_text or "") \
        | _extract_number_words(src_corpus + " " + (internal_text or ""))
    full_dates = _extract_dates(src_corpus) | _extract_dates(internal_text or "")
    full_magnitudes = _extract_magnitudes(src_corpus) | _extract_magnitudes(internal_text or "")
    # Sources write '$40 million' (base + magnitude word); claims may
    # write '40,000,000' or 'forty million' (full value). Expand corpus
    # numbers with base x magnitude so both forms can match.
    for n in list(full_numbers):
        try:
            v = float(n)
        except ValueError:
            continue
        for m in full_magnitudes:
            full_numbers.add(_num_norm(str(v * _NUMBER_SCALES[m])))
    known_tokens = set()
    for r in (sources or []):
        raw = f"{r.get('title', '')} {r.get('snippet', '')}"
        for tok in re.findall(r"[A-Za-z][A-Za-z0-9&'.-]*", raw):
            if _cap_kind(tok) is not None and _stop_form(tok) not in _ENTITY_STOP:
                known_tokens.add(_match_norm(tok))
    per_source = []
    for r in (sources or []):
        rt = _record_text(r)
        per_source.append((r.get("url"), _match_norm(rt),
                           _extract_numbers(rt) | _extract_number_words(rt),
                           _extract_dates(rt), _extract_magnitudes(rt)))

    def _missing_from(facts, norm, tokens, numbers, dates, magnitudes, entities=True):
        miss = []
        for n in sorted(facts["numbers"]):
            if n not in numbers:
                miss.append(n)
        if entities:
            for e in facts["entities"]:
                en = _match_norm(e)
                if en and f" {en} " not in f" {norm} " and not all(t in tokens for t in en.split()):
                    miss.append(en)
        for d in sorted(facts["dates"]):
            if d not in dates:
                miss.append(d)
        for m in sorted(facts["magnitudes"]):
            if m in magnitudes:
                continue
            # '40,000,000 users' in the source supports the claim's
            # 'million' even though the word itself never appears.
            scale = _NUMBER_SCALES[m]
            implied = False
            for n in facts["numbers"]:
                if n not in numbers:
                    continue
                try:
                    v = float(n)
                except ValueError:
                    continue
                if v >= scale and v % scale == 0:
                    implied = True
                    break
            if not implied:
                miss.append(m)
        return miss

    def _fact_total(facts):
        return (len(facts["numbers"]) + len(facts["entities"])
                + len(facts["dates"]) + len(facts["magnitudes"]))

    out = []
    for claim in split_claims(content, known_tokens):
        facts = key_facts(claim)
        lead = _lead_token(claim)
        if (lead and _cap_kind(lead) is not None
                and _stop_form(lead) not in _ENTITY_STOP
                and _match_norm(lead) in known_tokens
                and lead not in facts["entities"]):
            facts["entities"] = facts["entities"] + [lead]
        if not sources:
            miss = (sorted(facts["numbers"]) + [_match_norm(e) for e in facts["entities"]]
                    + sorted(facts["dates"]) + sorted(facts["magnitudes"]))
            out.append({"claim": claim, "source_url": None, "supporting_sources": [],
                        "support": "no-source", "missing": miss})
            continue
        miss = _missing_from(facts, src_norm, src_tokens, full_numbers, full_dates,
                             full_magnitudes)
        # Entities alone decide against source text; numbers/dates/
        # magnitudes may also come from internal run facts (above).
        total = _fact_total(facts)
        best_url, best_score, supporting = None, -1, []
        for url, snorm, snums, sdates, smags in per_source:
            stoks = set(snorm.split())
            smiss = _missing_from(facts, snorm, stoks, snums, sdates, smags)
            score = total - len(smiss)
            if score > best_score:
                best_url, best_score = url, score
            if not smiss:
                supporting.append(url)
        if best_score <= 0:
            best_url = sources[0].get("url")  # the citation the claim rides on
        out.append({"claim": claim, "source_url": best_url,
                    "supporting_sources": supporting,
                    "support": "supported" if not miss else "unsupported",
                    "missing": miss})
    return out


def node_reviewer(state: PrismState) -> dict:
    rid = state["run_id"]
    prev = state.get("review") or {}
    rounds = int(prev.get("rounds", 0)) + 1
    # Source records the run actually holds, keyed by Scout's normalized
    # URL: evidence pack, candidates, and the picked story. A citation
    # only counts when it resolves to one of these records — its TEXT
    # is what claims are checked against, never the URL string alone.
    from .scout import _norm_url

    pool: dict[str, dict] = {}
    for rec in list(state.get("evidence") or []) + list(state.get("candidates") or []):
        if rec.get("url"):
            pool[_norm_url(rec["url"])] = rec
    picked = state.get("picked") or {}
    if picked.get("url"):
        pool[_norm_url(picked["url"])] = picked
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    # Verified run-state facts makers may restate as NUMBERS/DATES only
    # (see check_claims): how many candidates the sweep pooled, and the
    # run's own date. Never free text, never the user-supplied topic,
    # never the curator's explanation — those must not support claims.
    internal_text = (f"{len(state.get('candidates') or [])} candidates. "
                     f"Run date: {now.strftime('%B %Y %A %d')}.")
    notes, per_artifact = [], {}
    total_claims, supported_claims = 0, 0
    for name, art in (state.get("artifacts") or {}).items():
        content = art.get("content") or ""
        # The carousel's factual text lives in review_text (its content
        # is a render receipt); other artifacts are checked on content.
        check_text = content
        if art.get("review_text"):
            check_text = content + "\n\n" + art["review_text"]
        raw_cited = [u.rstrip(".,;:") for u in re.findall(r"https?://[^\s)\]]+", check_text)]
        cited_urls = list(dict.fromkeys(raw_cited + list(art.get("citations") or [])))
        sources = [pool[_norm_url(u)] for u in cited_urls if _norm_url(u) in pool]
        grounded = bool(sources)
        claims = check_claims(check_text, sources, internal_text=internal_text)
        unsupported = [c for c in claims if c["support"] != "supported"]
        total_claims += len(claims)
        supported_claims += len(claims) - len(unsupported)
        ok = grounded and len(content) >= 80 and not unsupported
        per_artifact[name] = {"grounded": grounded, "ok": ok,
                              "claims_total": len(claims),
                              "claims_supported": len(claims) - len(unsupported),
                              "unsupported_claims": unsupported}
        if not grounded:
            notes.append(f"{name}: no evidence URL cited — add sources.")
        if len(content) < 80:
            notes.append(f"{name}: too thin ({len(content)} chars).")
        for c in unsupported[:3]:
            where = c["source_url"] or "any cited source"
            miss = f" (missing: {', '.join(c['missing'][:4])})" if c["missing"] else ""
            notes.append(f"{name}: claim '{c['claim'][:110]}' not supported by {where}{miss}")
        if len(unsupported) > 3:
            notes.append(f"{name}: +{len(unsupported) - 3} more unsupported claims.")
        if any(h in content for h in HYPE_WORDS):
            notes.append(f"{name}: hype language violates tone rule.")
    if state.get("duplicate"):
        notes.append("Picked story was covered in a past run (dedupe rule).")
    verdict = "pass" if not notes else "revise"
    emit(rid, "reviewer", "Reviewer", "done",
         f"Reviewer verdict: {verdict.upper()} (round {rounds})"
         + (f" — {'; '.join(notes)}" if notes
            else f" — every extracted factual claim supported by its cited source ({supported_claims}/{total_claims} claims)"),
         {"verdict": verdict, "notes": notes, "per_artifact": per_artifact})
    return {"review": {"verdict": verdict, "notes": notes, "rounds": rounds,
                       "per_artifact": per_artifact,
                       "claims": {"total": total_claims, "supported": supported_claims}},
            "review_notes": "; ".join(notes), "status": "awaiting_approval" if verdict == "pass" or rounds >= 2 else "making"}


def _route_after_review(state: PrismState) -> str:
    rev = state.get("review") or {}
    if rev.get("verdict") == "pass" or int(rev.get("rounds", 0)) >= 2:
        return "human_gate"
    return "makers"


def node_human_gate(state: PrismState) -> dict:
    rid = state["run_id"]
    emit(rid, "human_gate", "Human Gate", "waiting",
         "Waiting for human approval before anything is published.",
         {"artifacts": list((state.get("artifacts") or {}).keys())})
    decision = interrupt({"type": "approval_request", "run_id": rid,
                          "artifacts": list((state.get("artifacts") or {}).keys()),
                          "review": state.get("review")})
    if isinstance(decision, str):
        decision = {"decision": decision}
    emit(rid, "human_gate", "Human Gate", "done", f"Human decision: {decision.get('decision')}",
         {"approval": decision})
    return {"approval": decision, "status": "shipping"}


def node_ship(state: PrismState) -> dict:
    rid = state["run_id"]
    pb = load_playbook(state["playbook_id"])
    run_dir = RUNS_DIR / rid
    run_dir.mkdir(parents=True, exist_ok=True)
    approved = (state.get("approval") or {}).get("decision") == "approve"
    artifacts = state.get("artifacts") or {}
    # Publisher stub: records the exact payload the post-demo adapter will
    # send. kind=publisher_stub — it is NOT a published output and must
    # never be presented as one (Aishwarya's Week 3 note, 2026-11-04).
    crosscast_payload = {
        "kind": "publisher_stub",
        "label": "Publisher stub — Crosscast payload recorded, NOT sent",
        "sent": False,
        "adapter": "crosscast-stub",
        "status": "recorded_not_sent",
        "playbook_id": pb["id"],
        "artifacts": {k: {"type": v.get("type"), "title": v.get("title"),
                          "pdf_path": v.get("pdf_path")} for k, v in artifacts.items()},
        "picked": state["picked"],
    }
    (run_dir / "crosscast_payload.json").write_text(json.dumps(crosscast_payload, indent=2))
    # Local export (kind=local_export): the Run Page is a file on disk /
    # a page on this deployment — the ONLY output that exists after a run.
    # It is distinct from the publisher stub above, which sends nothing.
    art_html = "".join(
        f"<section><h2>{v.get('title', k)}</h2><pre>{_esc(v.get('content', ''))}</pre></section>"
        for k, v in artifacts.items())
    html = (f"<!doctype html><html><head><meta charset='utf-8'><title>Prism Run {rid}</title>"
            "<style>body{font-family:system-ui;background:#F7F9FA;color:#0B1526;max-width:860px;margin:40px auto;padding:0 20px}"
            "pre{white-space:pre-wrap;background:#fff;border-radius:18px;padding:20px}h1{background:linear-gradient(90deg,#38BDF8,#7C6CF0);"
            "-webkit-background-clip:text;color:transparent}.kind{display:inline-block;border:1px solid #7C6CF0;border-radius:999px;"
            "padding:2px 10px;font-size:12px;font-weight:700;color:#7C6CF0}</style></head><body>"
            f"<h1>{_esc(state['picked'].get('title', ''))}</h1>"
            f"<p><span class='kind'>kind: local_export</span></p>"
            f"<p>Playbook: {pb['name']} · Reviewer: {(state.get('review') or {}).get('verdict')} · "
            f"Approved: {approved} · LLM mode: {get_llm().mode}</p>"
            f"<p>Local export — this Run Page is an exported file, not a channel publish. "
            f"The Crosscast publisher is a stub (kind: publisher_stub): its payload was "
            f"recorded, not sent.</p>{art_html}</body></html>")
    page_path = run_dir / "index.html"
    page_path.write_text(html)
    public_base = os.environ.get("PUBLIC_WEB_BASE", "https://prism.genalphalabs.com").rstrip("/")
    run_page_url = f"{public_base}/runs/{pb['id']}-latest"
    outputs = [
        {"kind": "local_export",
         "label": "Local export — Run Page (exported file, not a channel publish)",
         "path": str(page_path), "bundle": str(run_dir / "bundle.json"),
         "url": run_page_url},
        {"kind": "publisher_stub",
         "label": "Publisher stub — Crosscast payload recorded, NOT sent",
         "path": str(run_dir / "crosscast_payload.json"), "sent": False},
    ]
    bundle = {"run_id": rid, "playbook_id": pb["id"], "picked": state["picked"],
              "scores": state["scores"], "score_explanation": state["score_explanation"],
              "review": state.get("review"), "approval": state.get("approval"),
              "artifacts": {k: {kk: vv for kk, vv in v.items() if kk != "content"} | {"content": v.get("content", "")}
                            for k, v in artifacts.items()},
              "run_page": str(page_path), "crosscast_payload": str(run_dir / "crosscast_payload.json"),
              "outputs": outputs}
    (run_dir / "bundle.json").write_text(json.dumps(bundle, indent=2))
    if approved:
        record_past_run({"run_id": rid, "playbook_id": pb["id"],
                         "title": state["picked"].get("title"), "url": state["picked"].get("url")})
    ship = {"status": "shipped" if approved else "exported_not_approved",
            "run_page": str(page_path), "bundle": str(run_dir / "bundle.json"),
            "crosscast_payload": str(run_dir / "crosscast_payload.json"),
            "run_page_url": run_page_url,
            "outputs": outputs}
    emit(rid, "ship", "Ship", "done",
         f"Local export ready: {page_path} (kind: local_export) · "
         f"Crosscast payload recorded (kind: publisher_stub, not sent)",
         {"ship": ship, "run_page_url": run_page_url})
    return {"ship": ship, "status": ship["status"]}


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_graph(checkpointer=None):
    g = StateGraph(PrismState)
    g.add_node("supervisor", node_supervisor)
    g.add_node("scout", node_scout)
    g.add_node("curator", node_curator)
    g.add_node("archivist", node_archivist)
    g.add_node("makers", node_makers)
    g.add_node("reviewer", node_reviewer)
    g.add_node("human_gate", node_human_gate)
    g.add_node("ship", node_ship)
    g.add_edge(START, "supervisor")
    g.add_edge("supervisor", "scout")
    g.add_edge("scout", "curator")
    g.add_edge("curator", "archivist")
    g.add_edge("archivist", "makers")
    g.add_edge("makers", "reviewer")
    g.add_conditional_edges("reviewer", _route_after_review, {"human_gate": "human_gate", "makers": "makers"})
    g.add_edge("human_gate", "ship")
    g.add_edge("ship", END)
    return g.compile(checkpointer=checkpointer)
