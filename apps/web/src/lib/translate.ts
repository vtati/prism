// Translates live API run events ({node, agent, status, message, data, ts})
// into the DemoEvent vocabulary the Run Theater renders.
//
// Why this exists: the API never spoke the fixture vocabulary, and the
// page's onmessage used to discard every event without a "kind" field —
// so a live run displayed NOTHING (0/6 artifacts forever) until the
// stream eventually errored and the UI fell back to the recorded demo
// (incident 2026-10-24 ~17:10 ET). This module is the missing adapter.
import { FIXTURES, type DemoEvent } from "./fixtures";
import type { AgentId } from "./agents";

export interface ApiEvent {
  run_id?: string;
  node: string;
  agent: string;
  status: string;
  message: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data?: Record<string, any>;
  ts?: number;
}

export interface TranslateCtx {
  pbId: string;
  scoutCandidates: { title: string; url: string }[];
  doneArtifacts: Set<string>;
}

export const newTranslateCtx = (pbId: string): TranslateCtx => ({
  pbId,
  scoutCandidates: [],
  doneArtifacts: new Set<string>(),
});

const MAKER_OF: Record<string, AgentId> = {
  briefing: "scribe",
  reel_script: "scribe",
  linkedin_carousel: "hue",
  linkedin_post: "herald",
  instagram_caption: "herald",
  email: "herald",
};
const MAKER_ARTIFACTS: Partial<Record<AgentId, string[]>> = {
  scribe: ["briefing", "reel_script"],
  hue: ["linkedin_carousel"],
  herald: ["linkedin_post", "instagram_caption", "email"],
};
const GALLERY_ID: Record<string, string> = { linkedin_carousel: "carousel" };

const S = (agent: AgentId, status: "working" | "done", line?: string): DemoEvent =>
  ({ t: 0, kind: "status", agent, status, line } as DemoEvent);
const L = (agent: AgentId, line: string): DemoEvent => ({ t: 0, kind: "line", agent, line });
const E = (edge: string): DemoEvent => ({ t: 0, kind: "edge", edge });
const P = (agent: AgentId, value: number): DemoEvent => ({ t: 0, kind: "progress", agent, value });

function piecesFor(ctx: TranslateCtx, apiArtifact: string): DemoEvent[] {
  const gid = GALLERY_ID[apiArtifact] ?? apiArtifact;
  const art = FIXTURES[ctx.pbId]?.artifacts.find(a => a.id === gid);
  if (!art) return [];
  const total = art.kind === "slides" ? (art.slides?.length ?? 0) : art.pieces.length;
  return Array.from({ length: total }, (_, i) => ({ t: 0, kind: "piece", artifact: gid, index: i } as DemoEvent));
}

export function translateApiEvent(ev: ApiEvent, ctx: TranslateCtx): DemoEvent[] {
  const d = ev.data ?? {};
  switch (`${ev.node}/${ev.status}`) {
    case "supervisor/started":
      return [S("supervisor", "working", ev.message), P("supervisor", 40)];
    case "scout/started":
      return [E("supervisor-scout"), S("scout", "working", ev.message)];
    case "scout/progress":
      return [{
        t: 0, kind: "tool", agent: "scout",
        tool: { name: `research · ${d.channel ?? "source"}`, detail: ev.message, result: `${d.count ?? 0} candidates` },
      } as DemoEvent, L("scout", ev.message)];
    case "scout/done": {
      ctx.scoutCandidates = Array.isArray(d.candidates) ? d.candidates : [];
      const tools: DemoEvent[] = (Array.isArray(d.tool_calls) ? d.tool_calls : []).map((c: string) => ({
        t: 0, kind: "tool", agent: "scout",
        tool: { name: "research", detail: String(c), result: "" },
      } as DemoEvent));
      return [...tools, P("scout", 100), S("scout", "done", ev.message), E("scout-curator")];
    }
    case "curator/done": {
      const scores = d.scores ?? {};
      const candidates = [{
        title: String(d.picked ?? "Lead story"),
        score: Number(scores.total ?? 0),
        heat: Number(scores.audience_heat ?? 0),
        note: `Winner across ${ctx.scoutCandidates.length || "the"} candidates · Consequence ${scores.consequence ?? "–"}/20 · Verification ${scores.verification ?? "–"}/20 · Novelty ${scores.novelty ?? "–"}/20`,
      }];
      return [
        S("curator", "working", "Scoring every candidate against the Playbook rubric…"),
        { t: 0, kind: "scores", candidates } as DemoEvent,
        L("curator", ev.message),
        S("curator", "done", ev.message),
        E("curator-archivist"),
      ];
    }
    case "archivist/done":
      return [
        S("archivist", "working", "Diving into the memory vault…"),
        S("archivist", "done", ev.message),
        E("archivist-makers"),
      ];
    case "makers/started":
      return [
        S("scribe", "working", "Briefing first, script second. Writing!"),
        S("hue", "working", "Beret on. Making slides people actually swipe."),
        S("herald", "working", "One story, every outfit. Tailoring!"),
      ];
    case "makers/artifact": {
      const name = String(d.artifact ?? "");
      const agent = MAKER_OF[name];
      if (!agent) return [];
      ctx.doneArtifacts.add(name);
      const mine = MAKER_ARTIFACTS[agent] ?? [];
      const doneCount = mine.filter(a => ctx.doneArtifacts.has(a)).length;
      const out: DemoEvent[] = [...piecesFor(ctx, name), P(agent, Math.round((doneCount / Math.max(mine.length, 1)) * 100))];
      if (doneCount >= mine.length) out.push(S(agent, "done", `${agent === "hue" ? "Carousel" : "Artifacts"} sealed and delivered.`));
      return out;
    }
    case "makers/done":
      return [E("makers-reviewer")];
    case "reviewer/done": {
      const verdict = String(d.verdict ?? "").toUpperCase() === "PASS" ? "PASS" : "REVISE";
      return [
        S("reviewer", "working", "Monocle on. Nobody ships past me unverified."),
        { t: 0, kind: "review", verdict, notes: Array.isArray(d.notes) ? d.notes : [] } as DemoEvent,
        S("reviewer", "done", ev.message),
        E("reviewer-gate"),
      ];
    }
    case "human_gate/waiting":
      return [
        L("supervisor", "The suite is complete and Vera-reviewed. Over to you, human. ✨"),
        { t: 0, kind: "phase", phase: "awaiting" } as DemoEvent,
      ];
    case "human_gate/done":
      return [L("supervisor", ev.message)];
    case "ship/done":
      return [E("gate-ship"), { t: 0, kind: "phase", phase: "approved" } as DemoEvent];
    default:
      return [];
  }
}
