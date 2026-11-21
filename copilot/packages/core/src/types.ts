export type Severity = "info" | "warning" | "critical";
export type Source = "kubernetes" | "prometheus";

/** One observed fact, from one source, at one moment. Everything else is built from these. */
export interface Evidence {
  /** Stable id, used to deduplicate and to cite evidence in a hypothesis. */
  id: string;
  source: Source;
  /** Machine-readable kind, e.g. "pod.crashloop", "pod.oomkilled", "metric.restarts". */
  kind: string;
  /** ISO 8601 timestamp of when it happened (or was observed). */
  at: string;
  /** What it is about, e.g. "pod/checkout-7d9f". */
  subject: string;
  severity: Severity;
  /** One human-readable line. Already redacted. */
  summary: string;
}

export interface Hypothesis {
  id: string;
  title: string;
  confidence: "low" | "medium" | "high";
  /** Why we think so, in plain words. */
  reasoning: string;
  /** Ids of the Evidence items that support it. */
  evidence: string[];
  /** Read-only next steps a human can take. */
  next: string[];
}

export interface Investigation {
  namespace: string;
  generatedAt: string;
  windowMinutes: number;
  evidence: Evidence[];
  hypotheses: Hypothesis[];
  /** Sources that could not be read (the report says so instead of pretending). */
  gaps: string[];
}
