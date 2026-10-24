import React from "react";
import { CatAvatar, type AgentDef } from "@/lib/agents";
import type { ToolCall } from "@/lib/fixtures";

export interface AgentState { status: "idle" | "working" | "done"; line: string; progress: number; tools: ToolCall[]; }

export default function AgentCard({ agent, state }: { agent: AgentDef; state: AgentState }) {
  const mood = state.status === "done" ? "done" : state.status === "working" ? "working" : "idle";
  return (
    <div className={`acard ${state.status}`} style={{ ["--ac" as string]: agent.color }}>
      <span className="stateTag">{state.status === "working" ? "WORKING" : state.status === "done" ? "DONE ✓" : "ON DECK"}</span>
      <div className="head">
        <span className="avatar"><CatAvatar agent={agent} size={52} mood={mood} /></span>
        <span>
          <div className="name">{agent.name}</div>
          <div className="role">{agent.role}</div>
        </span>
      </div>
      <p className="statusline">“{state.line}”</p>
      <div className="bar"><i style={{ width: `${state.progress}%` }} /></div>
      {state.tools.length > 0 && (
        <div className="tools">
          <details>
            <summary>🔧 {state.tools.length} tool call{state.tools.length > 1 ? "s" : ""} — peek inside</summary>
            {state.tools.map((t, i) => (
              <div className="tool" key={i}><b>{t.name}</b> · {t.detail}<br /><span className="res">→ {t.result}</span></div>
            ))}
          </details>
        </div>
      )}
    </div>
  );
}
