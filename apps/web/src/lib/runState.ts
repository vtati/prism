// Normalizes a live GET /runs/{id} response (and, for demo mode, a
// fixture) into the GateData the Ship Room's Review Panel renders.
//
// Live shape (backend contract): the response wraps the graph state —
//   { run_id, status, state: {
//       artifacts: { <name>: { type, title, content, pdf_path, slide_count } },
//       review:    { verdict, notes, per_artifact: { <name>: { grounded, ok } } },
//       ship:      { run_page_url, status, ... },
//       picked:    { title, url, angle? } } }
// Everything here is defensive: fields that the in-flight backend changes
// have not landed yet (run_page_url, picked.angle) are simply absent and
// the UI falls back gracefully.
import type { RunFixture } from "./fixtures";

export interface PerArtifactCheck { grounded?: boolean; ok?: boolean }

export interface GateReviewView {
  verdict: string;
  notes: string[];
  perArtifact?: Record<string, PerArtifactCheck>;
}

export interface GateArtifactView {
  name: string;
  label: string;
  icon: string;
  content: string;
  slideCount?: number;
  /** Fixture/demo-only reviewer note for this artifact. */
  verdictNote?: string;
}

export interface GateData {
  artifacts: GateArtifactView[];
  review: GateReviewView | null;
  shipRunPageUrl?: string;
  shipStatus?: string;
}

const ICONS: Record<string, string> = {
  briefing: "🗞️",
  reel_script: "🎬",
  linkedin_carousel: "🎠",
  carousel: "🎠",
  linkedin_post: "💼",
  instagram_caption: "📸",
  email: "✉️",
};
export const iconForArtifact = (name: string): string => ICONS[name] ?? "📄";

const prettify = (name: string) =>
  name.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());

type AnyRec = Record<string, unknown>;
const rec = (v: unknown): AnyRec =>
  v && typeof v === "object" && !Array.isArray(v) ? (v as AnyRec) : {};

export interface GateFallbacks {
  /** Artifact names from the gate event, used when state has none yet. */
  artifactNames?: string[];
  /** slide_count per artifact name, from makers/artifact events. */
  slideCounts?: Record<string, number>;
  /** Review already seen over SSE, used when state has none yet. */
  fallbackReview?: GateReviewView | null;
}

export function gateDataFromRunState(raw: unknown, fb: GateFallbacks = {}): GateData | null {
  const root = rec(raw);
  const state = Object.keys(rec(root.state)).length ? rec(root.state) : root;

  // artifacts: normally a name-keyed dict; tolerate a list of {name,...}.
  const artsRaw = state.artifacts;
  const byName: AnyRec = {};
  if (Array.isArray(artsRaw)) {
    for (const entry of artsRaw) {
      const e = rec(entry);
      const n = String(e.name ?? e.id ?? e.type ?? "");
      if (n) byName[n] = e;
    }
  } else {
    Object.assign(byName, rec(artsRaw));
  }
  const names = Object.keys(byName);
  const extraNames = (fb.artifactNames ?? []).filter(n => !names.includes(n));
  if (!names.length && !extraNames.length && !state.review && !state.ship) return null;

  const artifacts: GateArtifactView[] = [...names, ...extraNames].map(name => {
    const a = rec(byName[name]);
    const sc = Number(a.slide_count ?? fb.slideCounts?.[name] ?? 0);
    return {
      name,
      label: typeof a.title === "string" && a.title ? a.title : prettify(name),
      icon: iconForArtifact(name),
      content: typeof a.content === "string" ? a.content : "",
      slideCount: Number.isFinite(sc) && sc > 0 ? sc : undefined,
    };
  });

  const revRaw = rec(state.review);
  let review: GateReviewView | null = null;
  if (Object.keys(revRaw).length) {
    review = {
      verdict: String(revRaw.verdict ?? "").toUpperCase(),
      notes: Array.isArray(revRaw.notes) ? revRaw.notes.map(String) : [],
      perArtifact:
        revRaw.per_artifact && typeof revRaw.per_artifact === "object"
          ? (revRaw.per_artifact as Record<string, PerArtifactCheck>)
          : undefined,
    };
  } else if (fb.fallbackReview) {
    review = fb.fallbackReview;
  }

  const shipRaw = rec(state.ship);
  return {
    artifacts,
    review,
    shipRunPageUrl:
      typeof shipRaw.run_page_url === "string" && shipRaw.run_page_url
        ? shipRaw.run_page_url
        : undefined,
    shipStatus: typeof shipRaw.status === "string" ? shipRaw.status : undefined,
  };
}

/** The editorial angle a run-state fetch may carry on the picked story —
 *  lets the scoreboard pick up the angle even if the curator SSE frame
 *  was missed. */
export function angleFromRunState(raw: unknown): string | undefined {
  const root = rec(raw);
  const state = Object.keys(rec(root.state)).length ? rec(root.state) : root;
  const picked = rec(state.picked);
  const a = picked.angle ?? state.angle;
  return typeof a === "string" && a ? a : undefined;
}

/** Demo mode: the fixture IS the run — same GateData shape, built from
 *  its pieces/slides. PDF/slide routes don't exist for fixture runs, so
 *  callers must hide those links when not live (ShipRoom's `live` prop). */
export function gateDataFromFixture(fx: RunFixture, review: GateReviewView | null): GateData {
  return {
    artifacts: fx.artifacts.map(a => ({
      name: a.id,
      label: a.label,
      icon: a.icon,
      content:
        a.kind === "slides"
          ? (a.slides ?? []).map((s, i) => `**Slide ${i + 1} — ${s.title}**\n${s.body}`).join("\n\n")
          : a.pieces.join("\n\n"),
      slideCount: a.kind === "slides" ? a.slides?.length : undefined,
      verdictNote: a.verdict,
    })),
    review,
  };
}

export const carouselOf = (gate: GateData | null): GateArtifactView | undefined =>
  gate?.artifacts.find(a => a.name.includes("carousel"));
