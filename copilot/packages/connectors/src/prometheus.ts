import { K8sNameSchema, cleanLine, type Evidence } from "@copilot/core";
import { z } from "zod";

export type Fetch = (url: string, init?: { signal?: AbortSignal }) => Promise<{ ok: boolean; status: number; json(): Promise<unknown> }>;

const VectorSchema = z.object({
  status: z.literal("success"),
  data: z.object({
    resultType: z.literal("vector"),
    result: z.array(z.object({ metric: z.record(z.string(), z.string()), value: z.tuple([z.number(), z.string()]) })),
  }),
});

export interface PromOptions {
  baseUrl: string;
  namespace: string;
  fetch: Fetch;
  now: Date;
  windowMinutes: number;
  timeoutMs?: number;
}

interface Probe {
  key: string;
  kind: string;
  query: (ns: string, window: number) => string;
  severity: (value: number) => Evidence["severity"];
  summary: (pod: string, value: number) => string;
}

const PROBES: Probe[] = [
  {
    key: "restarts",
    kind: "metric.restarts",
    query: (ns, w) => `sum by (pod) (increase(kube_pod_container_status_restarts_total{namespace="${ns}"}[${w}m])) > 0`,
    severity: (v) => (v >= 5 ? "critical" : "warning"),
    summary: (_pod, v) => `restarted ${Math.round(v)} times in the window`,
  },
  {
    key: "oom",
    kind: "metric.oomkilled",
    query: (ns) => `max by (pod) (kube_pod_container_status_last_terminated_reason{namespace="${ns}",reason="OOMKilled"}) == 1`,
    severity: () => "critical",
    summary: () => "last termination reason is OOMKilled",
  },
  {
    key: "throttling",
    kind: "metric.throttling",
    query: (ns) =>
      `sum by (pod) (rate(container_cpu_cfs_throttled_periods_total{namespace="${ns}"}[5m])) / ` +
      `sum by (pod) (rate(container_cpu_cfs_periods_total{namespace="${ns}"}[5m])) > 0.25`,
    severity: () => "warning",
    summary: (_pod, v) => `${(v * 100).toFixed(0)}% of CPU periods throttled`,
  },
];

export function validBaseUrl(raw: string): URL {
  const url = new URL(raw);
  if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error("Prometheus URL must be http or https");
  if (url.username || url.password) throw new Error("put credentials in the environment, not in the URL");
  return url;
}

export async function collectPrometheus(opts: PromOptions): Promise<Evidence[]> {
  // Never interpolate an unchecked name into PromQL.
  if (!K8sNameSchema.safeParse(opts.namespace).success) throw new Error(`bad namespace "${opts.namespace}"`);
  const ns = opts.namespace;
  const base = validBaseUrl(opts.baseUrl);
  const window = Math.max(1, Math.min(1440, Math.round(opts.windowMinutes)));
  const at = opts.now.toISOString();
  const out: Evidence[] = [];
  const errors: string[] = [];

  for (const probe of PROBES) {
    const url = new URL("/api/v1/query", base);
    url.searchParams.set("query", probe.query(ns, window));
    url.searchParams.set("time", String(Math.floor(opts.now.getTime() / 1000)));
    try {
      const res = await opts.fetch(url.toString(), { signal: AbortSignal.timeout(opts.timeoutMs ?? 10_000) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const parsed = VectorSchema.safeParse(await res.json());
      if (!parsed.success) throw new Error("unexpected response shape");
      for (const row of parsed.data.data.result) {
        const pod = row.metric.pod ?? "unknown";
        const value = Number(row.value[1]);
        if (!Number.isFinite(value)) continue;
        out.push({
          id: `prom:${probe.key}:${pod}`, source: "prometheus", kind: probe.kind, at, subject: `pod/${pod}`,
          severity: probe.severity(value), summary: cleanLine(probe.summary(pod, value)),
        });
      }
    } catch (err) {
      errors.push(`${probe.key}: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
  if (errors.length === PROBES.length) throw new Error(`Prometheus unreachable or invalid (${errors[0]})`);
  return out;
}
