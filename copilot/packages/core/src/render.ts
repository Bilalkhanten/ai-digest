import { buildTimeline } from "./timeline.js";
import type { Investigation } from "./types.js";

const MARK = { critical: "CRIT", warning: "WARN", info: "INFO" } as const;

/** Plain-text report for the terminal. */
export function renderText(inv: Investigation): string {
  const lines: string[] = [];
  lines.push(`Incident triage: namespace "${inv.namespace}" (last ${inv.windowMinutes} min, ${inv.generatedAt})`);
  lines.push("");
  const timeline = buildTimeline(inv.evidence);
  lines.push(`Timeline (${timeline.length} events)`);
  if (timeline.length === 0) lines.push("  nothing unusual found");
  for (const e of timeline) {
    lines.push(`  ${e.at}  ${MARK[e.severity]}  [${e.source}] ${e.subject}: ${e.summary}`);
  }
  lines.push("");
  lines.push("Likely causes");
  if (inv.hypotheses.length === 0) lines.push("  no known pattern matched; the timeline above is all the evidence there is");
  inv.hypotheses.forEach((h, i) => {
    lines.push(`  ${i + 1}. ${h.title}  (confidence: ${h.confidence})`);
    lines.push(`     ${h.reasoning}`);
    lines.push(`     evidence: ${h.evidence.join(", ")}`);
    for (const step of h.next) lines.push(`     next: ${step}`);
  });
  if (inv.gaps.length > 0) {
    lines.push("");
    lines.push("Could not check");
    for (const g of inv.gaps) lines.push(`  - ${g}`);
  }
  lines.push("");
  lines.push("This report is read-only: nothing was changed in the cluster.");
  return lines.join("\n") + "\n";
}
