import React from "react";
import { AGENT_MAP, type AgentId } from "@/lib/agents";

export type NodeState = "idle" | "active" | "done";
interface N { id: string; label: string; emoji: string; agent?: AgentId; x: number; y: number; w?: number; }
const NW = 150, NH = 54;
const NODES: N[] = [
  { id: "input", label: "Topic In", emoji: "💡", x: 15, y: 30 },
  { id: "supervisor", label: "Nova", emoji: "⭐", agent: "supervisor", x: 215, y: 30 },
  { id: "scout", label: "Pixel", emoji: "🔭", agent: "scout", x: 415, y: 30 },
  { id: "curator", label: "Otto", emoji: "📊", agent: "curator", x: 615, y: 30 },
  { id: "archivist", label: "Echo", emoji: "🗄️", agent: "archivist", x: 815, y: 30 },
  { id: "scribe", label: "Scribe", emoji: "✍️", agent: "scribe", x: 90, y: 150, w: 200 },
  { id: "hue", label: "Hue", emoji: "🎨", agent: "hue", x: 400, y: 150, w: 200 },
  { id: "herald", label: "Herald", emoji: "📣", agent: "herald", x: 710, y: 150, w: 200 },
  { id: "reviewer", label: "Vera", emoji: "🔍", agent: "reviewer", x: 90, y: 262, w: 200 },
  { id: "gate", label: "Human Gate", emoji: "🙋", x: 400, y: 262, w: 200 },
  { id: "ship", label: "Ship It!", emoji: "🚀", x: 710, y: 262, w: 200 },
];
const byId = Object.fromEntries(NODES.map(n => [n.id, n]));
const cx = (n: N) => n.x + (n.w ?? NW) / 2, cy = (n: N) => n.y + NH / 2;

const EDGES: { id: string; d: string }[] = [
  { id: "input-supervisor", d: `M ${byId.input.x + NW} ${cy(byId.input)} L ${byId.supervisor.x} ${cy(byId.supervisor)}` },
  { id: "supervisor-scout", d: `M ${byId.supervisor.x + NW} ${cy(byId.supervisor)} L ${byId.scout.x} ${cy(byId.scout)}` },
  { id: "scout-curator", d: `M ${byId.scout.x + NW} ${cy(byId.scout)} L ${byId.curator.x} ${cy(byId.curator)}` },
  { id: "curator-archivist", d: `M ${byId.curator.x + NW} ${cy(byId.curator)} L ${byId.archivist.x} ${cy(byId.archivist)}` },
  { id: "archivist-scribe", d: `M ${cx(byId.archivist)} ${byId.archivist.y + NH} C ${cx(byId.archivist)} 140, ${cx(byId.scribe)} 110, ${cx(byId.scribe)} ${byId.scribe.y}` },
  { id: "archivist-hue", d: `M ${cx(byId.archivist) - 10} ${byId.archivist.y + NH} C ${cx(byId.archivist) - 40} 130, ${cx(byId.hue)} 115, ${cx(byId.hue)} ${byId.hue.y}` },
  { id: "archivist-herald", d: `M ${cx(byId.archivist)} ${byId.archivist.y + NH} C ${cx(byId.archivist)} 130, ${cx(byId.herald)} 112, ${cx(byId.herald)} ${byId.herald.y}` },
  { id: "scribe-reviewer", d: `M ${cx(byId.scribe)} ${byId.scribe.y + NH} L ${cx(byId.scribe)} ${byId.reviewer.y}` },
  { id: "hue-reviewer", d: `M ${cx(byId.hue)} ${byId.hue.y + NH} C ${cx(byId.hue)} 245, ${cx(byId.reviewer)} 235, ${cx(byId.reviewer)} ${byId.reviewer.y}` },
  { id: "herald-reviewer", d: `M ${cx(byId.herald)} ${byId.herald.y + NH} C ${cx(byId.herald)} 250, ${cx(byId.reviewer) + 30} 240, ${cx(byId.reviewer) + 10} ${byId.reviewer.y}` },
  { id: "reviewer-gate", d: `M ${byId.reviewer.x + 200} ${cy(byId.reviewer)} L ${byId.gate.x} ${cy(byId.gate)}` },
  { id: "gate-ship", d: `M ${byId.gate.x + 200} ${cy(byId.gate)} L ${byId.ship.x} ${cy(byId.ship)}` },
];

export function edgeLit(active: Set<string>, id: string): boolean {
  if (active.has(id)) return true;
  if (id.startsWith("archivist-") && active.has("archivist-makers")) return true;
  if (id.endsWith("-reviewer") && active.has("makers-reviewer")) return true;
  return false;
}

export default function GraphCanvas({ nodeStates, activeEdges }: { nodeStates: Record<string, NodeState>; activeEdges: Set<string> }) {
  return (
    <svg viewBox="0 0 1000 336" style={{ width: "100%", height: "auto", display: "block" }} role="img" aria-label="Agent pipeline graph">
      <defs>
        <linearGradient id="gg" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#38BDF8" /><stop offset="55%" stopColor="#7C6CF0" /><stop offset="100%" stopColor="#EC4899" />
        </linearGradient>
      </defs>
      {EDGES.map(e => {
        const lit = edgeLit(activeEdges, e.id);
        return (
          <g key={e.id}>
            <path id={`p-${e.id}`} d={e.d} fill="none" stroke={lit ? "url(#gg)" : "#D8DBEF"} strokeWidth={lit ? 3.4 : 2.2} className={lit ? "edgeFlow" : ""} strokeLinecap="round" />
            {lit && [0, 1].map(i => (
              <circle key={i} r="5" fill="#7C6CF0" className="packet">
                <animateMotion dur="1.15s" begin={`${i * 0.57}s`} repeatCount="indefinite">
                  <mpath href={`#p-${e.id}`} />
                </animateMotion>
              </circle>
            ))}
          </g>
        );
      })}
      {NODES.map(n => {
        const st = nodeStates[n.id] ?? "idle";
        const color = n.agent ? AGENT_MAP[n.agent].color : "#7C6CF0";
        return (
          <g key={n.id} className="nodeBox" style={{ filter: st === "active" ? `drop-shadow(0 6px 16px ${color}66)` : "none" }}>
            <rect x={n.x} y={n.y} width={n.w ?? NW} height={NH} rx="16"
              fill={st === "idle" ? "#FFFFFF" : color} fillOpacity={st === "active" ? 1 : st === "done" ? 0.16 : 1}
              stroke={color} strokeWidth={st === "idle" ? 1.6 : 2.6} />
            <text x={n.x + 16} y={cy(n) + 7} fontSize="19">{st === "done" ? "✅" : n.emoji}</text>
            <text x={n.x + 42} y={cy(n) + 2} fontSize="14.5" fontWeight="800" fill={st === "active" ? "#fff" : "#232946"} fontFamily="var(--font-display)">{n.label}</text>
            <text x={n.x + 42} y={cy(n) + 18} fontSize="10" fontWeight="700" fill={st === "active" ? "rgba(255,255,255,.85)" : "#7A81A0"}>
              {n.agent ? AGENT_MAP[n.agent].role.split("·")[1]?.trim() ?? "" : n.id === "input" ? "your idea" : n.id === "gate" ? "you approve" : "publish"}
            </text>
            {st === "active" && <circle cx={n.x + (n.w ?? NW) - 14} cy={n.y + 14} r="5" fill="#fff"><animate attributeName="opacity" values="1;.3;1" dur="1s" repeatCount="indefinite" /></circle>}
          </g>
        );
      })}
    </svg>
  );
}
