"use client";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AGENTS, AGENT_MAP, MAKERS, CatAvatar, type AgentId } from "@/lib/agents";
import { FIXTURES, PLAYBOOKS, type DemoEvent, type RunFixture } from "@/lib/fixtures";
import GraphCanvas, { type NodeState } from "@/components/GraphCanvas";
import AgentCard, { type AgentState } from "@/components/AgentCard";
import ArtifactGallery from "@/components/ArtifactGallery";
import ShipRoom, { type Phase } from "@/components/ShipRoom";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const CORE: AgentId[] = ["supervisor", "scout", "curator", "archivist", "reviewer"];

const idleStates = (): Record<AgentId, AgentState> => Object.fromEntries(
  AGENTS.map(a => [a.id, { status: "idle" as const, line: a.idleLine, progress: 0, tools: [] }])
) as unknown as Record<AgentId, AgentState>;

export default function Page() {
  const [pbId, setPbId] = useState("ai-news-gtm");
  const pb = PLAYBOOKS.find(p => p.id === pbId) ?? PLAYBOOKS[0];
  const fixture: RunFixture = FIXTURES[pbId];
  const [topic, setTopic] = useState(pb.defaultTopic);
  const [demoMode, setDemoMode] = useState<boolean | null>(null);
  const [modeNote, setModeNote] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [agents, setAgents] = useState(idleStates);
  const [edges, setEdges] = useState<Set<string>>(new Set());
  const [revealed, setRevealed] = useState<Record<string, number>>({});
  const [scores, setScores] = useState<RunFixture["candidates"] | null>(null);
  const [review, setReview] = useState<{ verdict: string; notes: string[] } | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const esRef = useRef<EventSource | null>(null);
  const startedRef = useRef(false);

  const running = phase === "running";

  const clearTimers = () => { timers.current.forEach(clearTimeout); timers.current = []; };
  useEffect(() => () => { clearTimers(); esRef.current?.close(); }, []);

  // ---- API health check → demo mode auto-enable ----
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const ctl = new AbortController(); const to = setTimeout(() => ctl.abort(), 1600);
        const r = await fetch(`${API}/playbooks`, { signal: ctl.signal }); clearTimeout(to);
        if (!cancelled && r.ok) { setDemoMode(false); setModeNote("Live API connected"); return; }
        throw new Error("not ok");
      } catch {
        if (!cancelled) { setDemoMode(true); setModeNote("API offline — Demo Mode with a recorded run"); }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // ---- elapsed clock ----
  useEffect(() => {
    if (!running) return;
    const iv = setInterval(() => setElapsed(e => e + 1), 1000);
    return () => clearInterval(iv);
  }, [running]);

  const patch = useCallback((id: AgentId, p: Partial<AgentState>) => {
    setAgents(prev => ({ ...prev, [id]: { ...prev[id], ...p, tools: p.tools ?? prev[id].tools } }));
  }, []);

  const applyEvent = useCallback((ev: DemoEvent) => {
    switch (ev.kind) {
      case "status":
        patch(ev.agent, { status: ev.status === "waiting" ? "idle" : ev.status, line: ev.line ?? undefined, progress: ev.status === "done" ? 100 : undefined });
        break;
      case "line": patch(ev.agent, { line: ev.line }); break;
      case "tool": setAgents(prev => ({ ...prev, [ev.agent]: { ...prev[ev.agent], tools: [...prev[ev.agent].tools, ev.tool] } })); break;
      case "progress": patch(ev.agent, { progress: ev.value }); break;
      case "edge": setEdges(prev => new Set(prev).add(ev.edge)); break;
      case "piece": setRevealed(prev => ({ ...prev, [ev.artifact]: Math.max(prev[ev.artifact] ?? 0, ev.index + 1) })); break;
      case "scores": setScores(ev.candidates); break;
      case "review": setReview({ verdict: ev.verdict, notes: ev.notes }); break;
      case "phase": if (ev.phase === "awaiting") setPhase("awaiting"); break;
    }
  }, [patch]);

  const resetState = useCallback(() => {
    clearTimers(); esRef.current?.close();
    setAgents(idleStates()); setEdges(new Set()); setRevealed({}); setScores(null); setReview(null); setElapsed(0);
  }, []);

  const runDemo = useCallback((fx: RunFixture) => {
    setPhase("running");
    fx.events.forEach(ev => { timers.current.push(setTimeout(() => applyEvent(ev), ev.t)); });
    timers.current.push(setTimeout(() => setPhase(prev => (prev === "running" ? "awaiting" : prev)), fx.durationMs));
  }, [applyEvent]);

  const startRun = useCallback(async () => {
    resetState();
    const fx = FIXTURES[pbId];
    if (demoMode) { runDemo(fx); return; }
    // live mode: create run + SSE, fall back to demo on any failure
    try {
      const r = await fetch(`${API}/runs`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ playbook_id: pbId, topic }) });
      if (!r.ok) throw new Error("create failed");
      const data = await r.json(); const id = data.id ?? data.run_id;
      if (!id) throw new Error("no run id");
      setPhase("running");
      const es = new EventSource(`${API}/runs/${id}/events`); esRef.current = es;
      es.onmessage = (m) => { try { const ev = JSON.parse(m.data); if (ev && typeof ev === "object" && "kind" in ev) applyEvent(ev as DemoEvent); } catch { /* ignore */ } };
      es.onerror = () => { es.close(); setModeNote("Live stream dropped — replaying recorded demo"); setDemoMode(true); resetState(); runDemo(fx); };
    } catch {
      setModeNote("API unreachable — Demo Mode with a recorded run"); setDemoMode(true); runDemo(fx);
    }
  }, [demoMode, pbId, topic, resetState, runDemo, applyEvent]);

  // auto-start the recorded demo once we know we're in demo mode — instant wow for judges
  useEffect(() => {
    if (demoMode && !startedRef.current) { startedRef.current = true; const t = setTimeout(() => startRun(), 650); return () => clearTimeout(t); }
  }, [demoMode, startRun]);

  const selectPlaybook = (id: string) => {
    setPbId(id); const p = PLAYBOOKS.find(x => x.id === id)!; setTopic(p.defaultTopic);
    resetState(); setPhase("idle"); startedRef.current = true;
  };

  const approve = async () => {
    setEdges(prev => new Set(prev).add("reviewer-gate").add("gate-ship"));
    patch("supervisor", { status: "done", line: "Human approved! Shipping the Run Page. confetti is a state of mind. ✨" });
    setPhase("approved");
    if (!demoMode) { try { await fetch(`${API}/runs/latest/approve`, { method: "POST" }); } catch { /* demo-safe */ } }
  };
  const requestChanges = () => { setPhase("changes"); patch("reviewer", { line: "Noted. Sending it back — makers, you heard the human." }); };

  const nodeStates: Record<string, NodeState> = useMemo(() => {
    const m: Record<string, NodeState> = { input: phase !== "idle" ? "done" : "idle", gate: phase === "awaiting" ? "active" : phase === "approved" ? "done" : "idle", ship: phase === "approved" ? "done" : "idle" };
    (Object.keys(agents) as AgentId[]).forEach(id => { m[id] = agents[id].status === "working" ? "active" : agents[id].status === "done" ? "done" : "idle"; });
    return m;
  }, [agents, phase]);

  const makerArtifacts = (m: AgentId) => fixture.artifacts.filter(a => a.maker === m);
  const doneArtifacts = fixture.artifacts.filter(a => (revealed[a.id] ?? 0) >= (a.kind === "slides" ? (a.slides?.length ?? 0) : a.pieces.length)).length;

  return (
    <div data-theme={pb.theme} className="wrap">
      {/* ================= header ================= */}
      <header className="topbar">
        <div className="logo">
          <div className="logoMark"><svg width="27" height="27" viewBox="0 0 24 24"><path d="M12 2 L22 20 L2 20 Z" fill="rgba(255,255,255,.92)" /><path d="M12 8 L17.5 20 L6.5 20 Z" fill="rgba(124,108,240,.55)" /></svg></div>
          <div>
            <h1>Prism <span>Studio</span></h1>
            <p>One topic in · a spectrum of content out</p>
          </div>
        </div>
        <div className="pill">
          <span className="chip"><span className="dot" style={{ background: demoMode ? "#F59E0B" : "#0EA47A" }} />{demoMode === null ? "Checking API…" : modeNote}</span>
          <span className="chip">⏱ {elapsed}s {phase !== "idle" && `· ${doneArtifacts}/${fixture.artifacts.length} artifacts`}</span>
          <span className="switch" role="group" aria-label="Mode">
            <button className={demoMode ? "on" : ""} onClick={() => { setDemoMode(true); setModeNote("Demo Mode — recorded run, zero setup"); }}>🎬 Demo</button>
            <button className={!demoMode ? "on" : ""} onClick={() => { setDemoMode(false); setModeNote("Live API mode"); }}>🔴 Live API</button>
          </span>
        </div>
      </header>

      {/* ================= playbooks ================= */}
      <div className="playbooks">
        {PLAYBOOKS.map(p => (
          <button key={p.id} className={`pb ${p.id === pbId ? "sel" : ""}`} style={{ background: p.grad }} onClick={() => selectPlaybook(p.id)}>
            <span className="badge">{p.emojiBadge}</span>
            <h3>{p.name}</h3>
            <p>{p.tagline}</p>
            <span className="tags">{p.sources.map(s => <span key={s}>🔌 {s}</span>)}{p.makers.map(m => <span key={m}>{m}</span>)}</span>
          </button>
        ))}
      </div>
      <div className="runbar">
        <input value={topic} onChange={e => setTopic(e.target.value)} placeholder="Give the team a topic…" aria-label="Topic" />
        <button className="btn" onClick={startRun} disabled={running}>{running ? "🎬 The team is on it…" : "▶ Run the pipeline"}</button>
        {phase !== "idle" && <button className="btn ghost" onClick={() => { resetState(); setPhase("idle"); }}>Reset</button>}
      </div>

      {/* ================= graph ================= */}
      <section className="panel" style={{ marginTop: 18 }}>
        <h2>🗺️ The Floor — live agent graph</h2>
        <p className="sub">Watch work flow: research → score → remember → <b>fan-out to three makers at once</b> → fact-check → your approval.</p>
        <div className="graphWrap"><GraphCanvas nodeStates={nodeStates} activeEdges={edges} /></div>
      </section>

      <div className="grid">
        <div>
          {/* ================= core agents ================= */}
          <section className="panel">
            <h2>🐱 The Cast</h2>
            <p className="sub">Six specialists, one supervisor, zero egos (Vera's is load-bearing).</p>
            <div className="agents">
              {CORE.map(id => <AgentCard key={id} agent={AGENT_MAP[id]} state={agents[id]} />)}
            </div>
            {scores && (
              <div className="scores">
                <h3 style={{ margin: "4px 0 2px", fontSize: 14.5 }}>📊 Otto's Scoreboard — why this story won</h3>
                {scores.map((c, i) => (
                  <div key={c.title} className={`scoreRow ${i === 0 ? "winner" : ""}`}>
                    <span className="t">{i === 0 ? "🏆 " : ""}{c.title}</span>
                    <span className="track"><span className="fill" style={{ display: "block", width: `${c.score}%`, background: i === 0 ? "var(--g-main)" : "#C6CBE4" }} /></span>
                    <span className="n">{c.score}</span>
                    <span className="note">{c.note}</span>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* ================= maker studio ================= */}
          <section className="studio">
            <h2 style={{ margin: 0, fontSize: 17 }}>🎨 Maker Studio</h2>
            <p className="sub" style={{ margin: "2px 0 0" }}>This is the part to watch: <b>all three makers work at the same time</b>, each assembling their artifacts piece by piece.</p>
            <div className="lanes">
              {MAKERS.map(id => {
                const a = AGENT_MAP[id], st = agents[id], arts = makerArtifacts(id);
                return (
                  <div key={id} className={`lane ${st.status}`} style={{ ["--ac" as string]: a.color }}>
                    <div className="mini"><CatAvatar agent={a} size={38} mood={st.status === "done" ? "done" : st.status === "working" ? "working" : "idle"} /> {a.name} <span style={{ color: "var(--muted)", fontSize: 11.5, fontWeight: 800 }}>{a.role.split("·")[1]}</span></div>
                    <div className="bar"><i style={{ width: `${st.progress}%`, background: a.color, display: "block", height: "100%", borderRadius: 99 }} /></div>
                    <p className="feed">“{st.line}”</p>
                    <div className="chips">{arts.map(art => { const tot = art.kind === "slides" ? (art.slides?.length ?? 0) : art.pieces.length; const r = Math.min(revealed[art.id] ?? 0, tot); return <span key={art.id} className={r > 0 ? "got" : ""}>{art.icon} {art.label} {r}/{tot}{r >= tot && tot > 0 ? " ✓" : ""}</span>; })}</div>
                  </div>
                );
              })}
            </div>
          </section>
        </div>

        {/* ================= artifacts ================= */}
        <section className="panel">
          <h2>✨ The Suite, Assembling Live</h2>
          <p className="sub">Every artifact appears piece by piece as its maker finishes it — then Vera stamps her verdict.</p>
          <ArtifactGallery artifacts={fixture.artifacts} revealed={revealed} review={review} running={running} />
        </section>
      </div>

      {/* ================= ship room ================= */}
      <ShipRoom phase={phase} review={review} runPageTitle={fixture.runPageTitle} playbookName={pb.name} topic={topic}
        onApprove={approve} onChanges={requestChanges} onReset={() => { resetState(); setPhase("idle"); }} />

      <footer>Prism Studio · LangGraph + LangChain + MCP multi-agent GTM · Same agents, any Playbook — built for Gen Academy Week 3 🎓</footer>
    </div>
  );
}
