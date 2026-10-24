import React from "react";

export type Phase = "idle" | "running" | "awaiting" | "approved" | "changes";

export default function ShipRoom({ phase, review, runPageTitle, playbookName, topic, onApprove, onChanges, onReset }: {
  phase: Phase;
  review: { verdict: string; notes: string[] } | null;
  runPageTitle: string; playbookName: string; topic: string;
  onApprove: () => void; onChanges: () => void; onReset: () => void;
}) {
  return (
    <section className="ship" aria-label="Ship Room">
      <h2>🚀 Ship Room — the human gate</h2>
      {phase === "idle" && <p>Nothing ships without a human. The agents research, write and design autonomously — publishing waits for your thumbs-up. Start a run above and watch this space.</p>}
      {phase === "running" && <p>The team is mid-run… Vera gets the final word before anything reaches you. Reads are autonomous; writes always wait. 🙋</p>}
      {phase === "awaiting" && (
        <>
          <p><b>The suite is complete and Reviewer-approved.</b> {review ? `${review.notes.length} checks passed, including: ${review.notes[0].toLowerCase()}.` : ""} Approve it to publish the Run Page — or send it back with notes.</p>
          <div className="row">
            <button className="btn" onClick={onApprove}>✅ Approve &amp; Publish</button>
            <button className="btn ghost2" onClick={onChanges}>✏️ Request changes</button>
          </div>
        </>
      )}
      {phase === "changes" && (
        <>
          <p>Sent back to the makers with your (imaginary but firm) notes. In the live product this re-enters the graph at the Maker nodes — Vera re-reviews before it returns to you.</p>
          <div className="row"><button className="btn" onClick={onReset}>↻ Run it again</button></div>
        </>
      )}
      {phase === "approved" && (
        <>
          <p><b>Published!</b> The suite is live as a public Run Page. Post-demo, this same approval fires the Crosscast adapter and ships to every channel at once.</p>
          {review && <div className="checks">{review.notes.map((n, i) => <span key={i}>✓ {n}</span>)}</div>}
          <div className="runpage">
            <div className="u">prism.genalphalabs.com/runs/{playbookName.toLowerCase().replace(/[^a-z]+/g, "-").replace(/^-|-$/g, "")}-latest</div>
            <div style={{ fontWeight: 900, fontSize: 16, marginTop: 3 }}>{runPageTitle}</div>
            <div style={{ fontSize: 13, color: "var(--muted)", fontWeight: 700 }}>Topic: “{topic}” · Researched, written, designed &amp; fact-checked by Nova's team · Human-approved 🙋</div>
          </div>
          <div className="row"><button className="btn" onClick={onReset}>🎬 Run another one</button></div>
        </>
      )}
    </section>
  );
}
