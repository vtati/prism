# Prism — the Playbook Engine for GTM Content

**One input in, a full spectrum of content out.** Prism is a multi-agent
system (LangGraph + LangChain + MCP tool-calling) that turns a topic, a
product, or the day's news into a ready-to-publish go-to-market suite:
research briefing, 90-second reel script, LinkedIn carousel (PDF),
LinkedIn post, Instagram caption, and email — researched, scored,
claim-checked by a reviewer agent (every extracted factual claim —
numbers, named entities, dates — must be supported by the text of a
source it cites), and approved by a human before anything ships.

The agents never change. Everything domain-specific lives in a
**Playbook** (YAML in `playbooks/`): sources, scoring rubric, brand
voice, artifact set, review rules, theme. Swap the Playbook — AI News
today, Travel News tomorrow — and the same graph produces a different
industry's pipeline. Zero agent-code changes.

Built for The Gen Academy · Mastering Agentic AI · Week 3
(Use case D: GTM Agent — Ideation to Copy). Spec:
`~/workspace/goals/gen-academy-week-3-prism-gtm-agent/files/prism-week3-spec-and-demo-plan.md`
(in the goal workspace).

## Architecture

```
topic → Supervisor → Scout → Curator → Archivist → Makers (parallel)
      → Reviewer (claim-support loop, max 2) → Human Gate (interrupt) → Ship
```

- **Scout** — MCP/key-free research: Hacker News (Algolia) + fetch;
  Tavily when `TAVILY_API_KEY` is set. One retry on a second source;
  gaps are flagged, never invented.
- **Curator** — scores every candidate with the Playbook rubric
  (AI News: Audience Heat 40 / Consequence 20 / Verification 20 /
  Novelty 20) and explains its pick.
- **Archivist** — brand-voice style pack + dedupe against past runs.
- **Makers** — one maker per artifact, run in parallel. The carousel
  maker calls the custom **FastMCP carousel server**
  (`mcp_servers/carousel/`, PIL, 1080×1350, aurora gradients) via
  langchain-mcp-adapters, with an in-process renderer fallback.
- **Reviewer (v2, claim-support gate)** — separate agent; splits every
  artifact into factual claims and requires each claim's numbers, named
  entities and dates to appear in the text of the sources it cites
  (Scout's stored snippets/page text — no new fetching). A claim its
  cited page doesn't support produces a specific note and loops back
  for revision (max 2 rounds). A planted-claim test
  (`tests/test_reviewer_claims.py`) proves a fabricated claim with the
  correct URL cited now revises instead of passing. Honest limit: this
  is a lexical key-fact screen — it verifies that a claim's checkable
  facts are present in its cited sources, not full entailment
  (negation or relation swaps are not caught); the carousel is checked
  on its full spec text, not just its render receipt.
- **Human Gate** — LangGraph interrupt. Reads are autonomous; writes
  need a human. **Ship** — two distinct output kinds: the Run Page is a
  `local_export`; the Crosscast payload is a `publisher_stub` that
  records the exact payload the post-demo publishing adapter will
  send. The stub is recorded, never sent, and never presented as a
  published output.

State is checkpointed in SQLite (LangGraph checkpointer).

## LLM providers

Env-driven, OpenAI-compatible. **OpenAI is primary**
(`OPENAI_API_KEY`, `LLM_MODEL` default `gpt-4o-mini`); `NEBIUS_API_KEY`
/ `FIREWORKS_API_KEY` are drop-in alternatives. **With no key, the
pipeline still runs end-to-end** in a grounded extractive/template
mode that builds artifacts only from fetched evidence — the mode is
logged on every run (`llm_mode` in `/health` and run events).

## Run it

```bash
cd services/agent
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# API (port 8077)
.venv/bin/uvicorn app.main:app --port 8077
curl localhost:8077/health
curl -X POST localhost:8077/runs -H 'Content-Type: application/json' \
  -d '{"playbook_id":"ai-news-gtm","topic":"AI agents"}'
# stream events:  GET /runs/{id}/events   (SSE)
# inspect state:  GET /runs/{id}
# approve:        POST /runs/{id}/approve {"decision":"approve"}

# CLI demo (auto-approves at the gate)
.venv/bin/python run_demo.py ai-news-gtm "AI agents"
.venv/bin/python run_demo.py travel-news "travel destinations"

# tests
.venv/bin/python -m pytest tests/ -q
```

Run outputs land in `data/runs/{run_id}/` (Run Page `index.html`,
`bundle.json`, `crosscast_payload.json`, `carousel/` PDF + PNGs).

## Layout

- `apps/web/` — Run Theater UI (Next.js)
- `services/agent/` — FastAPI + LangGraph backend (this README's code)
- `playbooks/` — Playbook YAMLs + knowledge (brand voice, past runs)
- `mcp_servers/carousel/` — FastMCP carousel renderer server
