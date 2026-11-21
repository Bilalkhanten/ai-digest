import { K8sNameSchema, cleanLine, type Evidence } from "@copilot/core";

/** Runs kubectl with the given arguments and returns stdout. Injected, so tests need no cluster. */
export type Runner = (args: string[]) => Promise<string>;

const ALLOWED_VERBS = new Set(["get"]);
const ALLOWED_RESOURCES = new Set(["pods", "events"]);
const ALLOWED_FLAGS = new Set(["-n", "-o"]);
const ALLOWED_OUTPUT = new Set(["json"]);

/**
 * The only door to the cluster. Anything that is not `get pods|events -n <name> -o json` is refused
 * before kubectl is started, so a bug elsewhere cannot make this tool change anything.
 */
export function assertReadOnly(args: readonly string[]): void {
  const [verb, resource, ...rest] = args;
  if (!verb || !ALLOWED_VERBS.has(verb)) throw new Error(`refused: kubectl verb "${verb ?? ""}" is not allowed`);
  if (!resource || !ALLOWED_RESOURCES.has(resource)) throw new Error(`refused: resource "${resource ?? ""}" is not allowed`);
  for (let i = 0; i < rest.length; i += 2) {
    const flag = rest[i] ?? "";
    const value = rest[i + 1] ?? "";
    if (!ALLOWED_FLAGS.has(flag)) throw new Error(`refused: flag "${flag}" is not allowed`);
    if (flag === "-n" && !K8sNameSchema.safeParse(value).success) throw new Error(`refused: bad namespace "${value}"`);
    if (flag === "-o" && !ALLOWED_OUTPUT.has(value)) throw new Error(`refused: output "${value}" is not allowed`);
  }
}

export function readOnlyRunner(inner: Runner): Runner {
  return async (args) => {
    assertReadOnly(args);
    return inner(args);
  };
}

type Json = Record<string, unknown>;
const obj = (v: unknown): Json => (v && typeof v === "object" && !Array.isArray(v) ? (v as Json) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string => (typeof v === "string" ? v : "");
const num = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? v : 0);

async function getItems(runner: Runner, resource: string, namespace: string): Promise<Json[]> {
  const raw = await runner(["get", resource, "-n", namespace, "-o", "json"]);
  return arr(obj(JSON.parse(raw)).items).map(obj);
}

export interface K8sOptions {
  namespace: string;
  runner: Runner;
  now: Date;
  windowMinutes: number;
}

export async function collectKubernetes(opts: K8sOptions): Promise<Evidence[]> {
  const nsOk = K8sNameSchema.safeParse(opts.namespace);
  if (!nsOk.success) throw new Error(`bad namespace "${opts.namespace}"`);
  const since = opts.now.getTime() - opts.windowMinutes * 60_000;
  const nowIso = opts.now.toISOString();
  const out: Evidence[] = [];

  for (const pod of await getItems(opts.runner, "pods", opts.namespace)) {
    const name = str(obj(pod.metadata).name);
    if (!name) continue;
    for (const cs of arr(obj(pod.status).containerStatuses).map(obj)) {
      const container = str(cs.name) || "container";
      const subject = `pod/${name}`;
      const waiting = obj(obj(cs.state).waiting);
      const terminated = obj(obj(cs.lastState).terminated);
      const reason = str(waiting.reason);
      const restarts = num(cs.restartCount);
      const finished = str(terminated.finishedAt);
      const finishedMs = Date.parse(finished);

      if (str(terminated.reason) === "OOMKilled" && Number.isFinite(finishedMs) && finishedMs >= since) {
        out.push({
          id: `k8s:oom:${name}:${container}`, source: "kubernetes", kind: "pod.oomkilled", at: new Date(finishedMs).toISOString(),
          subject, severity: "critical",
          summary: cleanLine(`container ${container} was OOMKilled (exit ${num(terminated.exitCode)}), restarts: ${restarts}`),
        });
      }
      if (reason === "CrashLoopBackOff") {
        out.push({
          id: `k8s:crashloop:${name}:${container}`, source: "kubernetes", kind: "pod.crashloop", at: nowIso,
          subject, severity: "critical",
          summary: cleanLine(`container ${container} is in CrashLoopBackOff, restarts: ${restarts}`),
        });
      } else if (reason === "ErrImagePull" || reason === "ImagePullBackOff") {
        out.push({
          id: `k8s:imagepull:${name}:${container}`, source: "kubernetes", kind: "pod.imagepull", at: nowIso,
          subject, severity: "critical",
          summary: cleanLine(`container ${container} cannot pull its image (${reason}): ${str(waiting.message)}`),
        });
      } else if (restarts >= 3 && str(terminated.reason) !== "OOMKilled") {
        out.push({
          id: `k8s:restarts:${name}:${container}`, source: "kubernetes", kind: "pod.restarts", at: nowIso,
          subject, severity: "warning",
          summary: cleanLine(`container ${container} restarted ${restarts} times`),
        });
      }
    }
  }

  for (const ev of await getItems(opts.runner, "events", opts.namespace)) {
    if (str(ev.type) !== "Warning") continue;
    const at = str(ev.lastTimestamp) || str(ev.eventTime) || str(obj(ev.metadata).creationTimestamp);
    const atMs = Date.parse(at);
    if (!Number.isFinite(atMs) || atMs < since) continue;
    const reason = str(ev.reason);
    const involved = obj(ev.involvedObject);
    const subject = `${str(involved.kind).toLowerCase() || "object"}/${str(involved.name) || "unknown"}`;
    const kind =
      reason === "FailedScheduling" ? "event.failedscheduling" : reason === "Unhealthy" ? "event.probefailed" : "event.warning";
    out.push({
      id: `k8s:event:${str(obj(ev.metadata).uid) || `${subject}:${reason}:${at}`}`,
      source: "kubernetes", kind, at: new Date(atMs).toISOString(), subject,
      severity: "warning",
      summary: cleanLine(`${reason}: ${str(ev.message)}${num(ev.count) > 1 ? ` (x${num(ev.count)})` : ""}`),
    });
  }
  return out;
}
