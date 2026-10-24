import React from "react";

export type AgentId =
  | "supervisor" | "scout" | "curator" | "archivist"
  | "scribe" | "hue" | "herald" | "reviewer";

export interface AgentDef {
  id: AgentId;
  name: string;
  role: string;
  color: string;        // main spectrum color
  soft: string;         // soft tint bg
  ear: string;
  accessory: "star" | "cap" | "glasses" | "book" | "pencil" | "beret" | "megaphone" | "monocle";
  idleLine: string;
}

export const AGENTS: AgentDef[] = [
  { id: "supervisor", name: "Nova", role: "Supervisor · Orchestrator", color: "#7C6CF0", soft: "#EFEBFF", ear: "#B7ACFF", accessory: "star", idleLine: "Conducting the chaos, one baton wave at a time." },
  { id: "scout", name: "Pixel", role: "Scout · Research", color: "#0EA5E9", soft: "#E0F4FF", ear: "#7DD3FC", accessory: "cap", idleLine: "Nose in the news, whiskers in the wind." },
  { id: "curator", name: "Otto", role: "Curator · Scoring", color: "#0EA47A", soft: "#DFF7EE", ear: "#5EEAD4", accessory: "glasses", idleLine: "Only bangers get past my spreadsheet." },
  { id: "archivist", name: "Echo", role: "Archivist · Memory & RAG", color: "#F59E0B", soft: "#FEF3D8", ear: "#FCD34D", accessory: "book", idleLine: "I remember every story we've ever told. Twice." },
  { id: "scribe", name: "Scribe", role: "Maker · Script & Briefing", color: "#EC4899", soft: "#FDE7F3", ear: "#F9A8D4", accessory: "pencil", idleLine: "Give me facts, I'll give you a hook in 3 seconds." },
  { id: "hue", name: "Hue", role: "Maker · Carousel Design", color: "#F97316", soft: "#FFEEDD", ear: "#FDBA74", accessory: "beret", idleLine: "Slides so pretty, people forget it's data." },
  { id: "herald", name: "Herald", role: "Maker · Social & Email", color: "#6366F1", soft: "#E6E7FF", ear: "#A5B4FC", accessory: "megaphone", idleLine: "Same story, five outfits, zero repeats." },
  { id: "reviewer", name: "Vera", role: "Reviewer · Fact & Tone Police", color: "#E11D48", soft: "#FFE3EA", ear: "#FDA4AF", accessory: "monocle", idleLine: "I read footnotes for fun. Try me." },
];

export const AGENT_MAP: Record<AgentId, AgentDef> = Object.fromEntries(AGENTS.map(a => [a.id, a])) as unknown as Record<AgentId, AgentDef>;
export const MAKERS: AgentId[] = ["scribe", "hue", "herald"];

/** Cute cat-leaning mascot, drawn in SVG, themed per agent. */
export function CatAvatar({ agent, size = 56, mood = "idle" }: { agent: AgentDef; size?: number; mood?: "idle" | "working" | "done" }) {
  const c = agent.color, ear = agent.ear;
  const eyes = mood === "done"
    ? <><path d="M36 54 q4 -5 8 0" stroke="#243044" strokeWidth="2.6" fill="none" strokeLinecap="round"/><path d="M56 54 q4 -5 8 0" stroke="#243044" strokeWidth="2.6" fill="none" strokeLinecap="round"/></>
    : <><circle cx="40" cy="52" r="3.4" fill="#243044"/><circle cx="60" cy="52" r="3.4" fill="#243044"/></>;
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" aria-label={agent.name} role="img">
      <circle cx="50" cy="52" r="46" fill={agent.soft} />
      {/* ears */}
      <path d="M22 38 L18 14 L42 26 Z" fill={ear} stroke={c} strokeWidth="3" strokeLinejoin="round"/>
      <path d="M78 38 L82 14 L58 26 Z" fill={ear} stroke={c} strokeWidth="3" strokeLinejoin="round"/>
      {/* head */}
      <circle cx="50" cy="56" r="30" fill="#FFFFFF" stroke={c} strokeWidth="3.5"/>
      {/* forehead tuft */}
      <path d="M44 28 q6 -7 12 0" stroke={c} strokeWidth="3" fill="none" strokeLinecap="round"/>
      {eyes}
      {/* nose + mouth */}
      <path d="M47 62 h6 l-3 3.4 Z" fill={c}/>
      <path d="M50 65.5 q0 3.5 -4.5 3.5 M50 65.5 q0 3.5 4.5 3.5" stroke="#243044" strokeWidth="2" fill="none" strokeLinecap="round"/>
      {/* whiskers */}
      <path d="M12 58 h13 M15 66 l12 -2 M88 58 h-13 M85 66 l-12 -2" stroke={c} strokeWidth="2.2" strokeLinecap="round" opacity="0.7"/>
      {/* blush */}
      <ellipse cx="31" cy="63" rx="4.6" ry="2.8" fill={c} opacity="0.28"/>
      <ellipse cx="69" cy="63" rx="4.6" ry="2.8" fill={c} opacity="0.28"/>
      {/* accessories */}
      {agent.accessory === "star" && <path d="M50 2 l2.2 4.8 5.3.7 -3.8 3.7 1 5.2 -4.7 -2.6 -4.7 2.6 1 -5.2 -3.8 -3.7 5.3 -.7 Z" fill="#FFC53D" stroke="#E8A100" strokeWidth="1.4"/>}
      {agent.accessory === "cap" && <path d="M26 34 q24 -20 48 0 l-4 5 q-20 -13 -40 0 Z" fill={c}/>}
      {agent.accessory === "glasses" && <g stroke="#243044" strokeWidth="2.4" fill="rgba(125,211,252,.18)"><circle cx="40" cy="52" r="9"/><circle cx="60" cy="52" r="9"/><path d="M49 52 h2 M31 50 l-6 -3 M69 50 l6 -3" fill="none"/></g>}
      {agent.accessory === "book" && <g><rect x="66" y="70" width="24" height="18" rx="2.5" fill={c}/><rect x="69" y="73" width="18" height="12" rx="1.5" fill="#FFF"/><path d="M78 73 v12" stroke={c} strokeWidth="1.6"/></g>}
      {agent.accessory === "pencil" && <g transform="rotate(38 82 76)"><rect x="78" y="60" width="7" height="24" fill="#FFC53D" stroke="#E8A100" strokeWidth="1.4"/><path d="M78 84 h7 l-3.5 7 Z" fill="#FFE1B8" stroke="#E8A100" strokeWidth="1.2"/></g>}
      {agent.accessory === "beret" && <g><ellipse cx="38" cy="24" rx="19" ry="7" fill={c}/><circle cx="38" cy="16" r="3" fill={c}/></g>}
      {agent.accessory === "megaphone" && <g><path d="M68 78 l20 -8 v14 l-20 3 Z" fill={c}/><rect x="62" y="76" width="7" height="9" rx="2" fill="#243044"/></g>}
      {agent.accessory === "monocle" && <g><circle cx="62" cy="52" r="10.5" fill="rgba(255,197,61,.15)" stroke="#B8860B" strokeWidth="2.6"/><path d="M68 60 q5 10 2 20" stroke="#B8860B" strokeWidth="2" fill="none"/><path d="M28 44 q6 -4 12 0" stroke="#243044" strokeWidth="2.4" fill="none" strokeLinecap="round"/></g>}
    </svg>
  );
}
