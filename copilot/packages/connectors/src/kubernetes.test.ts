import { describe, expect, it, vi } from "vitest";
import { assertReadOnly, collectKubernetes, readOnlyRunner, type Runner } from "./kubernetes.js";

const NOW = new Date("2026-11-21T10:00:00Z");
const pods = (items: unknown[]) => JSON.stringify({ items });

function runnerFor(data: { pods?: unknown[]; events?: unknown[] }): Runner {
  return async (args) => (args[1] === "pods" ? pods(data.pods ?? []) : JSON.stringify({ items: data.events ?? [] }));
}
const opts = (runner: Runner) => ({ namespace: "shop", runner, now: NOW, windowMinutes: 30 });

describe("assertReadOnly", () => {
  it("allows get pods/events with -n and -o json", () => {
    expect(() => assertReadOnly(["get", "pods", "-n", "shop", "-o", "json"])).not.toThrow();
    expect(() => assertReadOnly(["get", "events", "-n", "kube-system", "-o", "json"])).not.toThrow();
  });

  it.each([
    [["delete", "pods", "-n", "shop", "-o", "json"]],   // only the verb check can stop this one
    [["get", "nodes", "-n", "shop", "-o", "json"]],      // only the resource check can stop this one
    [["delete", "pod", "x"]],
    [["apply", "-f", "x.yaml"]],
    [["exec", "pod", "--", "sh"]],
    [["patch", "pods", "x"]],
    [["scale", "deployment", "x"]],
    [["logs", "pod"]],
    [["get", "secrets", "-n", "shop", "-o", "json"]],
    [["get", "pods", "--all-namespaces", "-o", "json"]],
    [["get", "pods", "-n", "shop", "-o", "yaml"]],
    [["get", "pods", "-n", "shop", "--token", "abc"]],
    [["get", "pods", "-n", "shop;rm -rf", "-o", "json"]],
    [["get", "pods", "-n", "$(id)", "-o", "json"]],
    [["get", "pods", "-n", "shop", "-o", "json", "--as", "admin"]],
    [[]],
  ])("refuses %j", (args) => {
    expect(() => assertReadOnly(args)).toThrow(/refused/);
  });

  it("readOnlyRunner refuses before calling the real runner", async () => {
    const inner = vi.fn(async () => "{}");
    const guarded = readOnlyRunner(inner);
    await expect(guarded(["delete", "pods", "x"])).rejects.toThrow(/refused/);
    expect(inner).not.toHaveBeenCalled();
    await guarded(["get", "pods", "-n", "shop", "-o", "json"]);
    expect(inner).toHaveBeenCalledOnce();
  });
});

describe("collectKubernetes", () => {
  it("finds an OOMKilled crash loop", async () => {
    const out = await collectKubernetes(opts(runnerFor({ pods: [{
      metadata: { name: "web-1" },
      status: { containerStatuses: [{
        name: "app", restartCount: 6,
        state: { waiting: { reason: "CrashLoopBackOff" } },
        lastState: { terminated: { reason: "OOMKilled", exitCode: 137, finishedAt: "2026-11-21T09:50:00Z" } },
      }] },
    }] })));
    expect(out.map((e) => e.kind).sort()).toEqual(["pod.crashloop", "pod.oomkilled"]);
    expect(out.find((e) => e.kind === "pod.oomkilled")?.at).toBe("2026-11-21T09:50:00.000Z");
  });

  it("ignores an OOM kill from before the window", async () => {
    const out = await collectKubernetes(opts(runnerFor({ pods: [{
      metadata: { name: "web-1" },
      status: { containerStatuses: [{ name: "a", restartCount: 1, state: { running: {} },
        lastState: { terminated: { reason: "OOMKilled", finishedAt: "2026-11-20T01:00:00Z" } } }] },
    }] })));
    expect(out).toEqual([]);
  });

  it("flags image pull failures and frequent restarts", async () => {
    const out = await collectKubernetes(opts(runnerFor({ pods: [
      { metadata: { name: "a" }, status: { containerStatuses: [{ name: "c", restartCount: 0,
        state: { waiting: { reason: "ImagePullBackOff", message: "pull access denied" } } }] } },
      { metadata: { name: "b" }, status: { containerStatuses: [{ name: "c", restartCount: 4, state: { running: {} } }] } },
    ] })));
    expect(out.map((e) => e.kind).sort()).toEqual(["pod.imagepull", "pod.restarts"]);
  });

  it("keeps only recent Warning events and maps known reasons", async () => {
    const mk = (uid: string, type: string, reason: string, at: string) => ({
      metadata: { uid }, type, reason, message: "m", lastTimestamp: at, involvedObject: { kind: "Pod", name: "p" },
    });
    const out = await collectKubernetes(opts(runnerFor({ events: [
      mk("1", "Warning", "FailedScheduling", "2026-11-21T09:40:00Z"),
      mk("2", "Warning", "Unhealthy", "2026-11-21T09:45:00Z"),
      mk("3", "Normal", "Pulled", "2026-11-21T09:45:00Z"),
      mk("4", "Warning", "Unhealthy", "2026-11-19T09:45:00Z"),
      mk("5", "Warning", "Weird", "not a date"),
    ] })));
    expect(out.map((e) => e.kind)).toEqual(["event.failedscheduling", "event.probefailed"]);
  });

  it("redacts secrets found in event messages", async () => {
    const out = await collectKubernetes(opts(runnerFor({ events: [{
      metadata: { uid: "9" }, type: "Warning", reason: "Failed", lastTimestamp: "2026-11-21T09:59:00Z",
      message: "pull failed for registry password=supersecretvalue", involvedObject: { kind: "Pod", name: "p" },
    }] })));
    expect(out[0]?.summary).not.toContain("supersecretvalue");
  });

  it("tolerates missing fields and junk shapes", async () => {
    const out = await collectKubernetes(opts(runnerFor({ pods: [null, 5, {}, { metadata: {} }, { metadata: { name: "x" }, status: { containerStatuses: "nope" } }] })));
    expect(out).toEqual([]);
  });

  it("rejects a bad namespace and propagates invalid JSON", async () => {
    await expect(collectKubernetes({ ...opts(runnerFor({})), namespace: "a;b" })).rejects.toThrow(/bad namespace/);
    await expect(collectKubernetes(opts(async () => "not json"))).rejects.toThrow();
  });
});
