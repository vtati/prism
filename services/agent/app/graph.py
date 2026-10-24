"""Prism LangGraph: supervisor -> scout -> curator -> archivist -> makers
(parallel) -> reviewer (loop max 2) -> human gate (interrupt) -> ship."""
from __future__ import annotations

import json
import math
import os
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
    scores, picked = scored[0]
    parts = ", ".join(f"{r['label']} {scores.get(r['key'], 0)}/{r['weight']}" for r in pb["rubric"])
    expl = (f"\"{picked['title']}\" scored {scores['total']}/100 ({parts}) across "
            f"{len(scored)} candidates, with {picked.get('points', 0)} points and "
            f"{picked.get('num_comments', 0)} comments of live discussion.")
    if (picked.get("corroboration") or 1) >= 2:
        expl += (f" Corroborated by {picked['corroboration']} independent sources "
                 f"({picked.get('source', '')}) — verification boosted.")
    emit(rid, "curator", "Curator", "done", f"Curator picked the lead story. {expl}",
         {"scores": scores, "picked": picked["title"]})
    return {"picked": picked, "scores": scores, "score_explanation": expl, "status": "archiving"}


def node_archivist(state: PrismState) -> dict:
    rid = state["run_id"]
    past = load_past_runs()
    picked = state["picked"]
    duplicate = any(r.get("url") == picked.get("url") or r.get("title") == picked.get("title") for r in past)
    style = brand_voice()
    emit(rid, "archivist", "Archivist", "done",
         f"Style pack loaded ({len(style)} chars); dedupe check: {'DUPLICATE — flagged' if duplicate else 'fresh story'}",
         {"duplicate": duplicate})
    return {"style_pack": style, "duplicate": duplicate, "status": "making"}


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


def node_reviewer(state: PrismState) -> dict:
    rid = state["run_id"]
    prev = state.get("review") or {}
    rounds = int(prev.get("rounds", 0)) + 1
    evidence_urls = {e["url"] for e in state["evidence"] if e.get("url")}
    notes, per_artifact = [], {}
    for name, art in (state.get("artifacts") or {}).items():
        content = art.get("content") or ""
        cited = [u for u in evidence_urls if u in content] + list(art.get("citations") or [])
        grounded = bool(cited)
        ok = grounded and len(content) >= 80
        per_artifact[name] = {"grounded": grounded, "ok": ok}
        if not grounded:
            notes.append(f"{name}: no evidence URL cited — add sources.")
        if len(content) < 80:
            notes.append(f"{name}: too thin ({len(content)} chars).")
        if any(h in content for h in HYPE_WORDS):
            notes.append(f"{name}: hype language violates tone rule.")
    if state.get("duplicate"):
        notes.append("Picked story was covered in a past run (dedupe rule).")
    verdict = "pass" if not notes else "revise"
    emit(rid, "reviewer", "Reviewer", "done",
         f"Reviewer verdict: {verdict.upper()} (round {rounds})" + (f" — {'; '.join(notes)}" if notes else " — all rules grounded"),
         {"verdict": verdict, "notes": notes, "per_artifact": per_artifact})
    return {"review": {"verdict": verdict, "notes": notes, "rounds": rounds, "per_artifact": per_artifact},
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
    # Crosscast stub: records the exact payload the post-demo adapter will send
    crosscast_payload = {
        "adapter": "crosscast-stub",
        "status": "recorded_not_sent",
        "playbook_id": pb["id"],
        "artifacts": {k: {"type": v.get("type"), "title": v.get("title"),
                          "pdf_path": v.get("pdf_path")} for k, v in artifacts.items()},
        "picked": state["picked"],
    }
    (run_dir / "crosscast_payload.json").write_text(json.dumps(crosscast_payload, indent=2))
    # Run Page export
    art_html = "".join(
        f"<section><h2>{v.get('title', k)}</h2><pre>{_esc(v.get('content', ''))}</pre></section>"
        for k, v in artifacts.items())
    html = (f"<!doctype html><html><head><meta charset='utf-8'><title>Prism Run {rid}</title>"
            "<style>body{font-family:system-ui;background:#F7F9FA;color:#0B1526;max-width:860px;margin:40px auto;padding:0 20px}"
            "pre{white-space:pre-wrap;background:#fff;border-radius:18px;padding:20px}h1{background:linear-gradient(90deg,#38BDF8,#7C6CF0);"
            "-webkit-background-clip:text;color:transparent}</style></head><body>"
            f"<h1>{_esc(state['picked'].get('title', ''))}</h1>"
            f"<p>Playbook: {pb['name']} · Reviewer: {(state.get('review') or {}).get('verdict')} · "
            f"Approved: {approved} · LLM mode: {get_llm().mode}</p>{art_html}</body></html>")
    page_path = run_dir / "index.html"
    page_path.write_text(html)
    bundle = {"run_id": rid, "playbook_id": pb["id"], "picked": state["picked"],
              "scores": state["scores"], "score_explanation": state["score_explanation"],
              "review": state.get("review"), "approval": state.get("approval"),
              "artifacts": {k: {kk: vv for kk, vv in v.items() if kk != "content"} | {"content": v.get("content", "")}
                            for k, v in artifacts.items()},
              "run_page": str(page_path), "crosscast_payload": str(run_dir / "crosscast_payload.json")}
    (run_dir / "bundle.json").write_text(json.dumps(bundle, indent=2))
    if approved:
        record_past_run({"run_id": rid, "playbook_id": pb["id"],
                         "title": state["picked"].get("title"), "url": state["picked"].get("url")})
    ship = {"status": "shipped" if approved else "exported_not_approved",
            "run_page": str(page_path), "bundle": str(run_dir / "bundle.json"),
            "crosscast_payload": str(run_dir / "crosscast_payload.json")}
    emit(rid, "ship", "Ship", "done",
         f"Run Page exported: {page_path} · Crosscast payload recorded (stub, not sent)",
         {"ship": ship})
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
