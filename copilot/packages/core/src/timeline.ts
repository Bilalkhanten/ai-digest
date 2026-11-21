import type { Evidence } from "./types.js";

const ORDER = { critical: 0, warning: 1, info: 2 } as const;

/** Oldest first; identical ids collapse to the first one seen. Does not modify its input. */
export function buildTimeline(evidence: readonly Evidence[]): Evidence[] {
  const seen = new Set<string>();
  const unique = evidence.filter((e) => (seen.has(e.id) ? false : (seen.add(e.id), true)));
  return unique.sort(
    (a, b) =>
      Date.parse(a.at) - Date.parse(b.at) ||
      ORDER[a.severity] - ORDER[b.severity] ||
      a.id.localeCompare(b.id),
  );
}

export function worstSeverity(evidence: readonly Evidence[]): Evidence["severity"] {
  if (evidence.some((e) => e.severity === "critical")) return "critical";
  if (evidence.some((e) => e.severity === "warning")) return "warning";
  return "info";
}
