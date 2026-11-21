import { parseEvidence, rankHypotheses, buildTimeline, type Evidence, type Investigation } from "@copilot/core";
import { collectKubernetes, type Runner } from "./kubernetes.js";
import { collectPrometheus, type Fetch } from "./prometheus.js";

const MAX_EVIDENCE = 200;

export interface InvestigateOptions {
  namespace: string;
  windowMinutes?: number;
  now?: Date;
  kubectl?: Runner;
  prometheusUrl?: string;
  fetch?: Fetch;
}

/** Gathers evidence from every configured source. A source that fails becomes a "gap", never a crash. */
export async function investigate(opts: InvestigateOptions): Promise<Investigation> {
  const now = opts.now ?? new Date();
  const windowMinutes = opts.windowMinutes ?? 30;
  const gaps: string[] = [];
  const raw: Evidence[] = [];

  if (opts.kubectl) {
    try {
      raw.push(...(await collectKubernetes({ namespace: opts.namespace, runner: opts.kubectl, now, windowMinutes })));
    } catch (err) {
      gaps.push(`kubernetes: ${err instanceof Error ? err.message : String(err)}`);
    }
  } else {
    gaps.push("kubernetes: not configured");
  }
  if (opts.prometheusUrl && opts.fetch) {
    try {
      raw.push(
        ...(await collectPrometheus({ baseUrl: opts.prometheusUrl, namespace: opts.namespace, fetch: opts.fetch, now, windowMinutes })),
      );
    } catch (err) {
      gaps.push(`prometheus: ${err instanceof Error ? err.message : String(err)}`);
    }
  } else {
    gaps.push("prometheus: not configured");
  }

  const valid: Evidence[] = [];
  let dropped = 0;
  for (const e of raw) {
    const ok = parseEvidence(e);
    if (ok.success) valid.push(ok.data);
    else dropped++;
  }
  if (dropped > 0) gaps.push(`${dropped} malformed evidence item(s) were dropped`);
  const evidence = buildTimeline(valid).slice(-MAX_EVIDENCE);
  if (valid.length > MAX_EVIDENCE) gaps.push(`only the newest ${MAX_EVIDENCE} of ${valid.length} items are shown`);

  return {
    namespace: opts.namespace,
    generatedAt: now.toISOString(),
    windowMinutes,
    evidence,
    hypotheses: rankHypotheses(evidence),
    gaps,
  };
}
