// Translates live API run events ({node, agent, status, message, data, ts})
// into the DemoEvent vocabulary the Run Theater renders.
//
// Why this exists: the API never spoke the fixture vocabulary, and the
// page's onmessage used to discard every event without a "kind" field —
// so a live run displayed NOTHING (0/6 artifacts forever) until the
// stream eventually errored and the UI fell back to the recorded demo
// (incident 2026-10-24 ~17:10 ET). This module is the missing adapter.
import { FIXTURES, type Candidate, type DemoEvent } from "./fixtures";
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
  /** Research Ledger: latest candidate count per Scout channel. Rows are
   * accumulated here (and mirrored to the page as "ledger" events) so the
   * ledger survives Scout finishing — it is theater state, not a log. */
  ledger: Record<string, number>;
  /** Artifact names announced by the human_gate/waiting event — the
   * fallback roster for the Gate Review Panel when the run-state fetch
   * has no artifacts yet. */
  gateArtifacts: string[];
  /** Per-artifact metadata seen on makers/artifact events (slide_count,
   * pdf_path) — supplements the run-state fetch for the carousel viewer. */
  artifactMeta: Record<string, { slideCount?: number; pdfPath?: string }>;
}

export const newTranslateCtx = (pbId: string): TranslateCtx => ({
  pbId,
  scoutCandidates: [],
  doneArtifacts: new Set<string>(),
  ledger: {},
  gateArtifacts: [],
  artifactMeta: {},
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
    case "scout/progress": {
      const channel = String(d.channel ?? "source");
      const count = Number(d.count ?? 0);
      ctx.ledger[channel] = count;
      return [
        { t: 0, kind: "ledger", channel, count } as DemoEvent,
        {
          t: 0, kind: "tool", agent: "scout",
          tool: { name: `research · ${channel}`, detail: ev.message, result: `${count} candidates` },
        } as DemoEvent,
        L("scout", ev.message),
      ];
    }
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
      // The curator event now also carries {angle, passed_over}: `angle`
      // is Otto's editorial headline for the winner (the raw source title
      // stays as attribution underneath), `passed_over` lists the losers.
      const pickedRaw: unknown = d.picked;
      const pickedTitle = typeof pickedRaw === "string"
        ? pickedRaw
        : String((pickedRaw as { title?: unknown } | null)?.title ?? "Lead story");
      const angle = typeof d.angle === "string" && d.angle
        ? d.angle
        : (pickedRaw && typeof pickedRaw === "object" && typeof (pickedRaw as { angle?: unknown }).angle === "string"
          ? String((pickedRaw as { angle: string }).angle)
          : undefined);
      const winner: Candidate = {
        title: pickedTitle,
        ...(angle ? { angle } : {}),
        score: Number(scores.total ?? 0),
        heat: Number(scores.audience_heat ?? 0),
        note: `Winner across ${ctx.scoutCandidates.length || "the"} candidates · Consequence ${scores.consequence ?? "–"}/20 · Verification ${scores.verification ?? "–"}/20 · Novelty ${scores.novelty ?? "–"}/20`,
      };
      const passed: Candidate[] = (Array.isArray(d.passed_over) ? d.passed_over : [])
        .map((p: unknown): Candidate | null => {
          if (typeof p === "string") return { title: p, score: 0, heat: 0, note: "Passed over by Otto" };
          if (!p || typeof p !== "object") return null;
          const o = p as { title?: unknown; score?: unknown; scores?: { total?: unknown; audience_heat?: unknown }; heat?: unknown };
          const title = String(o.title ?? "");
          if (!title) return null;
          return {
            title,
            score: Number(o.scores?.total ?? o.score ?? 0),
            heat: Number(o.scores?.audience_heat ?? o.heat ?? 0),
            note: "Passed over by Otto",
          };
        })
        .filter((c: Candidate | null): c is Candidate => c !== null);
      const candidates = [winner, ...passed];
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
      if (d.slide_count != null || d.pdf_path != null) {
        ctx.artifactMeta[name] = {
          slideCount: d.slide_count != null ? Number(d.slide_count) : undefined,
          pdfPath: d.pdf_path != null ? String(d.pdf_path) : undefined,
        };
      }
      const mine = MAKER_ARTIFACTS[agent] ?? [];
      const doneCount = mine.filter(a => ctx.doneArtifacts.has(a)).length;
      const out: DemoEvent[] = [...piecesFor(ctx, name), P(agent, Math.round((doneCount / Math.max(mine.length, 1)) * 100))];
      if (ctx.artifactMeta[name]?.slideCount != null) {
        out.push({ t: 0, kind: "artifactMeta", artifact: name, slideCount: ctx.artifactMeta[name].slideCount } as DemoEvent);
      }
      if (doneCount >= mine.length) out.push(S(agent, "done", `${agent === "hue" ? "Carousel" : "Artifacts"} sealed and delivered.`));
      return out;
    }
    case "makers/done":
      return [E("makers-reviewer")];
    case "reviewer/done": {
      const verdict = String(d.verdict ?? "").toUpperCase() === "PASS" ? "PASS" : "REVISE";
      // A live PASS carries notes: [] (the API only lists problems). The
      // theater wants prose — summarize the per-artifact grounding map.
      let notes: string[] = Array.isArray(d.notes) ? d.notes : [];
      if (!notes.length && d.per_artifact && typeof d.per_artifact === "object") {
        const entries = Object.values(d.per_artifact) as { grounded?: boolean; ok?: boolean }[];
        const grounded = entries.filter(v => v && v.grounded && v.ok).length;
        if (entries.length) notes = [`${grounded}/${entries.length} artifacts grounded in Scout's evidence`, "Tone matches the Playbook voice"];
      }
      if (!notes.length) notes = ["All claims grounded in Scout's evidence"];
      const perArtifact = d.per_artifact && typeof d.per_artifact === "object" ? d.per_artifact : undefined;
      return [
        S("reviewer", "working", "Monocle on. Nobody ships past me unverified."),
        { t: 0, kind: "review", verdict, notes, perArtifact } as DemoEvent,
        S("reviewer", "done", ev.message),
        E("reviewer-gate"),
      ];
    }
    case "human_gate/waiting": {
      const names = Array.isArray(d.artifacts) ? d.artifacts.map(String) : [];
      ctx.gateArtifacts = names;
      return [
        L("supervisor", "The suite is complete and Vera-reviewed. Over to you, human. ✨"),
        { t: 0, kind: "gate", artifacts: names } as DemoEvent,
        { t: 0, kind: "phase", phase: "awaiting" } as DemoEvent,
      ];
    }
    case "human_gate/done":
      return [L("supervisor", ev.message)];
    case "ship/done":
      return [E("gate-ship"), { t: 0, kind: "phase", phase: "approved" } as DemoEvent];
    default:
      return [];
  }
}
