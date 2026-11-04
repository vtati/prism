import React, { useState } from "react";
import { Para } from "./ArtifactGallery";
import { carouselOf, type GateData, type PerArtifactCheck } from "@/lib/runState";

export type Phase = "idle" | "running" | "awaiting" | "approved" | "changes";

/** Per-artifact grounded check for a gate artifact: per_artifact keys are
 *  API artifact names; demo fixture ids use "carousel" for the carousel. */
function checkFor(gate: GateData, name: string): PerArtifactCheck | undefined {
  const per = gate.review?.perArtifact;
  if (!per) return undefined;
  return per[name] ?? (name === "carousel" ? per["linkedin_carousel"] : undefined)
    ?? (name === "linkedin_carousel" ? per["carousel"] : undefined);
}

function CheckBadges({ check, verdictNote }: { check?: PerArtifactCheck; verdictNote?: string }) {
  if (check) {
    const claims = typeof check.claims_total === "number"
      ? ` (${check.claims_supported ?? 0}/${check.claims_total} claims)`
      : "";
    return (
      <span className="gateChecks">
        {!check.grounded
          ? <span className="bad">⚠ no source cited</span>
          : check.ok
            ? <span className="ok">✓ claims supported{claims}</span>
            : <span className="bad">⚠ unsupported claims{claims}</span>}
        <span className={check.ok ? "ok" : "bad"}>{check.ok ? "✓ passed" : "⚠ flagged"}</span>
      </span>
    );
  }
  if (verdictNote) return <span className="gateChecks"><span className="ok">🔍 {verdictNote}</span></span>;
  return null;
}

/**
 * The Gate Review Panel: everything the human needs to judge the suite
 * BEFORE approving — the rendered carousel (slide thumbnails + PDF), the
 * full text of every artifact, and Vera's verdict with per-artifact
 * grounding. Purely a read surface: reviewing never publishes anything.
 * After publish it stays visible, alongside the PDF links + Run Page.
 */
function ReviewPanel({ gate, live, runId, apiBase }: {
  gate: GateData;
  live: boolean;
  runId: string | null;
  apiBase: string;
}) {
  const [failedThumbs, setFailedThumbs] = useState<Set<number>>(new Set());
  const carousel = carouselOf(gate);
  const slideCount = carousel?.slideCount ?? 0;
  const pdfUrl = live && runId ? `${apiBase}/runs/${runId}/carousel.pdf` : null;
  const review = gate.review;
  const verdict = (review?.verdict ?? "").toUpperCase();
  const notes = review?.notes ?? [];

  return (
    <div className="reviewPanel">
      <div className="reviewHead">
        <h3>🔍 Review Panel — read the whole suite before you approve</h3>
        {verdict && (
          <span className={`verdictBadge ${verdict === "PASS" ? "pass" : "revise"}`}>
            Vera: {verdict === "PASS" ? "PASS ✓" : verdict}
          </span>
        )}
      </div>

      {/* ---------- Vera's review ---------- */}
      {review && (
        <div className="veraReview">
          {notes.length > 0 ? (
            <ul>{notes.map((n, i) => <li key={i}>{verdict === "PASS" ? "✓" : "⚠"} {n}</li>)}</ul>
          ) : (
            <p className="veraOk">✓ All checks passed — every extracted factual claim (numbers, named entities, dates) is supported by the text of a source it cites.</p>
          )}
          {review.perArtifact && (
            <div className="perArtifact">
              {gate.artifacts.map(a => {
                const c = checkFor(gate, a.name);
                if (!c) return null;
                const claims = typeof c.claims_total === "number" ? ` · ${c.claims_supported ?? 0}/${c.claims_total} claims supported` : "";
                return (
                  <span key={a.name} className="perArt">
                    {a.icon} {a.label}: {c.grounded ? "✓ source-cited" : "⚠ no source cited"}{claims} · {c.ok ? "✓ ok" : "⚠ flagged"}
                  </span>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ---------- Carousel viewer ---------- */}
      {carousel && slideCount > 0 && (
        <div className="carouselViewer">
          <div className="carouselHead">
            <span>🎠 {carousel.label} — {slideCount} slides</span>
            {pdfUrl && (
              <span className="pdfLinks">
                <a className="pdfBtn" href={pdfUrl} target="_blank" rel="noreferrer">📄 Open PDF</a>
                <a className="pdfBtn ghostPdf" href={pdfUrl} download>⬇️ Download PDF</a>
              </span>
            )}
            {!pdfUrl && <span className="pdfNote">PDF links appear for live runs</span>}
          </div>
          <div className="slideThumbs">
            {Array.from({ length: slideCount }, (_, i) => i + 1).map(n =>
              pdfUrl ? (
                <a key={n} className="thumb" href={pdfUrl} target="_blank" rel="noreferrer" title={`Slide ${n} — open the PDF`}>
                  {!failedThumbs.has(n)
                    ? <img src={`${apiBase}/runs/${runId}/carousel/slides/${n}.png`} alt={`Carousel slide ${n}`} loading="lazy"
                        onError={() => setFailedThumbs(prev => new Set(prev).add(n))} />
                    : <span className="thumbFallback">🎠</span>}
                  <span className="thumbNum">{n}</span>
                </a>
              ) : (
                <div key={n} className="thumb demoThumb" title={`Slide ${n}`}>
                  <span className="thumbFallback">🎠</span>
                  <span className="thumbNum">{n}</span>
                </div>
              )
            )}
          </div>
        </div>
      )}

      {/* ---------- All artifacts, full text ---------- */}
      <div className="gateArtifacts">
        {gate.artifacts.map(a => (
          <details key={a.name} className="gateArt">
            <summary>
              <span>{a.icon} {a.label}</span>
              <CheckBadges check={checkFor(gate, a.name)} verdictNote={a.verdictNote} />
            </summary>
            <div className="gateArtBody">
              {a.content
                ? a.content.split(/\n\n+/).map((para, i) => <Para key={i} text={para} />)
                : <p className="noContent">The API didn&apos;t return full text for this artifact in the run state — its tile in the Suite panel above is the live view.</p>}
            </div>
          </details>
        ))}
      </div>
    </div>
  );
}

export default function ShipRoom({ phase, review, runPageTitle, playbookName, topic, onApprove, onChanges, onReset, gate, runId, apiBase, live, runPageUrl }: {
  phase: Phase;
  review: { verdict: string; notes: string[] } | null;
  runPageTitle: string; playbookName: string; topic: string;
  onApprove: () => void; onChanges: () => void; onReset: () => void;
  gate?: GateData | null;
  runId?: string | null;
  apiBase?: string;
  live?: boolean;
  runPageUrl?: string | null;
}) {
  const slug = playbookName.toLowerCase().replace(/[^a-z]+/g, "-").replace(/^-|-$/g, "");
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  // The Run Page URL comes from the run state (ship.run_page_url) when the
  // backend provides it; otherwise it's this deployment's own origin —
  // never a hard-coded production domain.
  const displayRunPageUrl = runPageUrl || (origin ? `${origin}/runs/${slug}-latest` : `/runs/${slug}-latest`);
  const showPanel = (phase === "awaiting" || phase === "approved") && !!gate && gate.artifacts.length > 0;

  return (
    <section className="ship" aria-label="Ship Room">
      <h2>🚀 Ship Room — the human gate</h2>
      {phase === "idle" && <p>Nothing ships without a human. The agents research, write and design autonomously — publishing waits for your thumbs-up. Start a run above and watch this space.</p>}
      {phase === "running" && <p>The team is mid-run… Vera gets the final word before anything reaches you. Reads are autonomous; writes always wait. 🙋</p>}
      {phase === "awaiting" && (
        <>
          {(review?.verdict ?? gate?.review?.verdict ?? "").toUpperCase() === "REVISE" ? (
            <p><b>The suite is complete, but Reviewer issues remain.</b> Vera flagged the notes below after the final revision round — the call is now yours. Read it all before deciding: approve to export anyway (a local export), or send it back with notes.</p>
          ) : (
            <p><b>The suite is complete and Reviewer-approved.</b> {review ? (review.notes.length ? `${review.notes.length} checks passed, including: ${review.notes[0].toLowerCase()}.` : "All claim-support and tone checks passed.") : ""} Read it all below — reviewing publishes nothing. Approve to export the Run Page (a local export), or send it back with notes.</p>
          )}
          {showPanel && <ReviewPanel gate={gate!} live={!!live} runId={runId ?? null} apiBase={apiBase ?? ""} />}
          <div className="row">
            <button className="btn" onClick={onApprove}>✅ Approve &amp; Export</button>
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
          <p><b>Exported locally.</b> The suite is exported as a Run Page — a <b>local export</b>, not a channel publish. The Crosscast publisher is a <b>stub</b>: its payload was recorded, not sent. Post-demo, this same approval fires the real Crosscast adapter and ships to every channel at once.</p>
          {gate?.shipOutputs && gate.shipOutputs.length > 0 && (
            <div className="checks">
              {gate.shipOutputs.map((o, i) => (
                <span key={i}>🏷️ kind: {o.kind} — {o.label}</span>
              ))}
            </div>
          )}
          {review && <div className="checks">{review.notes.map((n, i) => <span key={i}>✓ {n}</span>)}</div>}
          <div className="runpage">
            <a className="u" href={displayRunPageUrl} target="_blank" rel="noreferrer">{displayRunPageUrl}</a>
            <div style={{ fontWeight: 900, fontSize: 16, marginTop: 3 }}>{runPageTitle}</div>
            <div style={{ fontSize: 13, color: "var(--muted)", fontWeight: 700 }}>Topic: “{topic}” · Researched, written, designed &amp; claim-checked against cited sources by Nova&apos;s team · Human-approved 🙋</div>
          </div>
          {showPanel && <ReviewPanel gate={gate!} live={!!live} runId={runId ?? null} apiBase={apiBase ?? ""} />}
          <div className="row"><button className="btn" onClick={onReset}>🎬 Run another one</button></div>
        </>
      )}
    </section>
  );
}
