import React from "react";

/** Display labels for the Scout sweep channels, in sweep order. */
export const LEDGER_LABELS: Record<string, string> = {
  "tavily-search": "Tavily",
  "hn-frontpage": "HN front page",
  "hn-algolia": "HN search",
  reddit: "Reddit",
  gdelt: "GDELT",
  trends: "Google Trends",
  editorial: "Editorial feeds",
  enrich: "Fetch enrichment",
  merged: "Pool merged",
};
const ORDER = Object.keys(LEDGER_LABELS);

/**
 * Pixel's Research Ledger — one persistent row per research source the
 * sweep actually called, fed by Scout progress events (lib/translate.ts
 * "ledger" events). Rows appear as events arrive and stay after Scout
 * finishes: the ledger is accumulated page state, never re-derived.
 */
export default function ResearchLedger({ ledger }: { ledger: Record<string, number> }) {
  const known = ORDER.filter(ch => ledger[ch] != null);
  const unknown = Object.keys(ledger).filter(ch => !(ch in LEDGER_LABELS));
  const rows = [...known, ...unknown];
  // The merged row IS the deduplicated pool total; summing it in would
  // double-count every source row above it.
  const total = ledger["merged"] != null
    ? ledger["merged"]
    : rows.filter(ch => ch !== "merged").reduce((sum, ch) => sum + (ledger[ch] ?? 0), 0);

  return (
    <div className="ledger">
      <h3 style={{ margin: "4px 0 2px", fontSize: 14.5 }}>🔬 Pixel&apos;s Research Ledger — every source called</h3>
      {rows.length === 0 && (
        <p className="ledgerEmpty">No sources called yet — Pixel logs each one here as the sweep runs, and the ledger stays up after Scout finishes.</p>
      )}
      {rows.map(ch => (
        <div key={ch} className={`ledgerRow ${ch === "merged" ? "merged" : ""}`}>
          <span className="ledgerName">{LEDGER_LABELS[ch] ?? ch}</span>
          <span className="ledgerCount">{ledger[ch]} candidates</span>
        </div>
      ))}
      {rows.length > 0 && (
        <div className="ledgerRow total">
          <span className="ledgerName">🧺 Pool total</span>
          <span className="ledgerCount">{total} candidates</span>
        </div>
      )}
    </div>
  );
}
