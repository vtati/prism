import React, { useEffect, useState } from "react";
import type { Artifact } from "@/lib/fixtures";

export function mdLite(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) => p.startsWith("**") && p.endsWith("**")
    ? <strong key={i}>{p.slice(2, -2)}</strong>
    : <span key={i}>{p}</span>);
}
function Para({ text }: { text: string }) {
  return <p>{text.split("\n").map((line, i, arr) => (
    <span key={i}>{mdLite(line)}{i < arr.length - 1 && <br />}</span>
  ))}</p>;
}

export default function ArtifactGallery({ artifacts, revealed, review, running }: {
  artifacts: Artifact[];
  revealed: Record<string, number>;
  review: { verdict: string; notes: string[] } | null;
  running: boolean;
}) {
  const [tab, setTab] = useState(artifacts[0]?.id);
  useEffect(() => { setTab(artifacts[0]?.id); }, [artifacts]);
  // auto-follow the artifact currently assembling
  useEffect(() => {
    if (!running) return;
    const active = artifacts.find(a => { const r = revealed[a.id] ?? 0; const total = a.kind === "slides" ? (a.slides?.length ?? 0) : a.pieces.length; return r > 0 && r < total; });
    if (active) setTab(active.id);
  }, [revealed, running, artifacts]);

  const art = artifacts.find(a => a.id === tab) ?? artifacts[0];
  if (!art) return null;
  const total = art.kind === "slides" ? (art.slides?.length ?? 0) : art.pieces.length;
  const shown = Math.min(revealed[art.id] ?? 0, total);
  const complete = shown >= total && total > 0;
  const doneCount = artifacts.filter(a => (revealed[a.id] ?? 0) >= (a.kind === "slides" ? (a.slides?.length ?? 0) : a.pieces.length)).length;

  return (
    <div>
      <div className="tabs" role="tablist">
        {artifacts.map(a => {
          const t = a.kind === "slides" ? (a.slides?.length ?? 0) : a.pieces.length;
          const r = Math.min(revealed[a.id] ?? 0, t);
          return (
            <button key={a.id} className={tab === a.id ? "on" : ""} onClick={() => setTab(a.id)} role="tab">
              {a.icon} {a.label} <span className="cnt">{r}/{t}{r >= t && t > 0 ? " ✓" : ""}</span>
            </button>
          );
        })}
      </div>
      <div style={{ fontSize: 12.5, fontWeight: 800, color: "var(--muted)", marginBottom: 4 }}>
        {doneCount}/{artifacts.length} artifacts complete {running && shown > 0 && !complete ? "· assembling live…" : ""}
      </div>
      {shown === 0 && <div className="empty">🛠️ The makers haven't reached this one yet — watch them work in the Maker Studio.</div>}
      {art.kind === "text" && art.pieces.slice(0, shown).map((p, i) => (
        <div className="piece" key={i}><Para text={p} /></div>
      ))}
      {art.kind === "slides" && (
        <div className="slides">
          {(art.slides ?? []).slice(0, shown).map((s, i) => (
            <div className="slide" key={i} style={{ background: `linear-gradient(150deg, ${s.g1}, ${s.g2})` }}>
              <div className="k">{s.kicker}</div>
              <h4>{s.title}</h4>
              <p>{s.body}</p>
              <div className="num">{i + 1} / {art.slides!.length}</div>
            </div>
          ))}
          {shown < total && shown > 0 && (
            <div className="slide" style={{ background: "repeating-linear-gradient(45deg,#EEF0FA,#EEF0FA 12px,#E4E6FA 12px,#E4E6FA 24px)", color: "var(--muted)", alignItems: "center", justifyContent: "center" }}>
              <div style={{ fontSize: 30 }}>🎨</div><p style={{ color: "var(--muted)", textAlign: "center" }}>Hue is painting<br />the next slide…</p>
            </div>
          )}
        </div>
      )}
      {complete && <span className="verdict">🔍 Vera: {art.verdict}</span>}
      {review && (
        <div className="piece" style={{ borderColor: "#B8EBD4", background: "#F2FCF7" }}>
          <Para text={`**Reviewer verdict: ${review.verdict}** — ${review.notes.join(" · ")}`} />
        </div>
      )}
    </div>
  );
}
