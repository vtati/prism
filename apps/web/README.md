# Prism Studio — Run Theater (web)

The face of Prism: a Next.js app where you watch a multi-agent GTM pipeline work **live and in parallel**.

## Run it
```bash
cd apps/web
npm install
npm run dev        # http://localhost:3000
# or production:
npm run build && npm run start
```

## Modes
- **Demo Mode (default when the API is offline):** on load, the app checks `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`, `GET /playbooks`). If unreachable, it auto-plays a fully recorded run — Scout → Curator (+ scoreboard) → Archivist → **three Makers fanning out simultaneously** → Reviewer → human gate. Toggle Demo/Live in the header.
- **Live API mode:** `POST /runs {playbook_id, topic}` → SSE `GET /runs/{id}/events` (events use the same shape as the demo fixtures in `src/lib/fixtures.ts`) → `POST /runs/{id}/approve`. Any failure falls back to the demo replay automatically.

## What's on the page
- **Playbooks gallery** — AI News (aurora sky→violet) and Travel (sunset). Selecting Travel re-skins the whole theater.
- **Live graph canvas** — SVG pipeline; nodes light up, handoff edges flow with animated packets, the fan-out/fan-in is explicit.
- **The Cast** — cat-mascot agent cards (Nova, Pixel, Otto, Echo, Vera) with witty status lines, progress, and expandable MCP tool calls. Otto's Scoreboard shows why the winning story won.
- **Maker Studio** — three parallel swimlanes (Scribe, Hue, Herald) working concurrently, artifact chips filling in real time.
- **Artifact gallery** — Briefing, Reel Script, Carousel slides (gradient slide components), LinkedIn, Instagram, Email assemble piece-by-piece, each stamped with Vera's Reviewer verdict.
- **Ship Room** — the human gate: Approve & Publish (renders the public Run Page preview) or Request changes.
