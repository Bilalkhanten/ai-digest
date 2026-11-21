import { describe, expect, it, vi } from "vitest";
import { main, type Io } from "./main.js";
import type { Fetch, Runner } from "@copilot/connectors";

const FIXTURE = new URL("../../../examples/crashloop", import.meta.url).pathname;
const NOW = "2026-11-21T10:00:00Z";

function capture() {
  const io = { out: "", err: "" };
  const handle: Io = { out: (t) => { io.out += t; }, err: (t) => { io.err += t; } };
  return { io, handle };
}
const run = async (argv: string[], deps = {}) => {
  const { io, handle } = capture();
  const code = await main(argv, handle, deps);
  return { code, ...io };
};

describe("copilot CLI", () => {
  it("prints help and exits 0 for --help, 2 for no command", async () => {
    const help = await run(["--help"]);
    expect(help.code).toBe(0);
    expect(help.out).toContain("copilot investigate");
    const none = await run([]);
    expect(none.code).toBe(2);
    expect(none.out).toContain("Usage");
  });

  it("prints its version", async () => {
    const r = await run(["--version"]);
    expect(r.code).toBe(0);
    expect(r.out.trim()).toMatch(/^(dev|\d+\.\d+\.\d+)$/);
  });

  it.each([
    [["investigate"], "--namespace is required"],
    [["investigate", "-n", "Bad_NS"], "not a valid Kubernetes namespace"],
    [["investigate", "-n", "shop", "--window", "0"], "--window must be"],
    [["investigate", "-n", "shop", "--window", "abc"], "--window must be"],
    [["investigate", "-n", "shop", "--now", "tomorrow"], "--now must be"],
    [["destroy", "-n", "shop"], "unknown command"],
    [["investigate", "extra", "-n", "shop"], "unknown command"],
    [["investigate", "--bogus"], "Unknown option"],
  ])("rejects %j with exit 2", async (argv, message) => {
    const r = await run(argv);
    expect(r.code).toBe(2);
    expect(r.err).toContain(message);
  });

  it("investigates the bundled scenario and names the likely cause", async () => {
    const r = await run(["investigate", "-n", "shop", "--fixture", FIXTURE, "--now", NOW]);
    expect(r.code).toBe(0);
    expect(r.out).toContain("memory limit");
    expect(r.out).toContain("confidence: high");
    expect(r.out).toContain("nothing was changed");
  });

  it("emits valid JSON with --json", async () => {
    const r = await run(["investigate", "-n", "shop", "--fixture", FIXTURE, "--now", NOW, "--json"]);
    const data = JSON.parse(r.out);
    expect(data.namespace).toBe("shop");
    expect(data.hypotheses[0].id).toBe("oom");
  });

  it("uses only read-only kubectl calls", async () => {
    const calls: string[][] = [];
    const kubectl: Runner = async (args) => { calls.push(args); return JSON.stringify({ items: [] }); };
    const r = await run(["investigate", "-n", "shop"], { kubectl });
    expect(r.code).toBe(0);
    expect(calls).toEqual([["get", "pods", "-n", "shop", "-o", "json"], ["get", "events", "-n", "shop", "-o", "json"]]);
  });

  it("sends the bearer token to Prometheus but never prints it", async () => {
    const seen: unknown[] = [];
    const fetch: Fetch = vi.fn(async (_url, init) => {
      seen.push(init);
      return { ok: true, status: 200, json: async () => ({ status: "success", data: { resultType: "vector", result: [] } }) };
    });
    const kubectl: Runner = async () => JSON.stringify({ items: [] });
    const r = await run(["investigate", "-n", "shop", "--prometheus", "http://prom:9090"], {
      kubectl, fetch, env: { PROMETHEUS_BEARER_TOKEN: "tok-super-secret-123" },
    });
    expect(JSON.stringify(seen)).toContain("Bearer tok-super-secret-123");
    expect(r.out + r.err).not.toContain("tok-super-secret-123");
  });

  it("shows a source that cannot be reached as 'could not check', not a crash", async () => {
    const kubectl: Runner = async () => { throw new Error("kubectl not found"); };
    const r = await run(["investigate", "-n", "shop"], { kubectl });
    expect(r.code).toBe(0);
    expect(r.out).toContain("Could not check");
    expect(r.out).toContain("kubectl not found");
  });
});
