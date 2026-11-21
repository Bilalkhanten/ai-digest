import { describe, expect, it } from "vitest";
import { fixtureFetch, fixtureRunner } from "./fixtures.js";
import { investigate } from "./investigate.js";
import type { Runner } from "./kubernetes.js";
import type { Fetch } from "./prometheus.js";

const NOW = new Date("2026-11-21T10:00:00Z");
const FIXTURE = new URL("../../../examples/crashloop", import.meta.url).pathname;

describe("investigate", () => {
  it("runs the bundled crash-loop scenario end to end", async () => {
    const inv = await investigate({
      namespace: "shop", now: NOW, kubectl: fixtureRunner(FIXTURE), prometheusUrl: "http://fixture.invalid", fetch: fixtureFetch(FIXTURE),
    });
    expect(inv.gaps).toEqual([]);
    expect(inv.hypotheses[0]?.id).toBe("oom");
    expect(inv.hypotheses[0]?.confidence).toBe("high");
    expect(inv.evidence.some((e) => e.source === "prometheus")).toBe(true);
    expect(inv.evidence.every((e) => !e.subject.includes("payments"))).toBe(true); // the healthy pod stays out
    const times = inv.evidence.map((e) => Date.parse(e.at));
    expect(times).toEqual([...times].sort((a, b) => a - b));
  });

  it("reports unconfigured sources as gaps", async () => {
    const inv = await investigate({ namespace: "shop", now: NOW });
    expect(inv.gaps).toEqual(["kubernetes: not configured", "prometheus: not configured"]);
    expect(inv.evidence).toEqual([]);
  });

  it("turns a failing source into a gap and keeps the other source's findings", async () => {
    const broken: Runner = async () => { throw new Error("connection refused"); };
    const inv = await investigate({
      namespace: "shop", now: NOW, kubectl: broken, prometheusUrl: "http://fixture.invalid", fetch: fixtureFetch(FIXTURE),
    });
    expect(inv.gaps).toEqual(["kubernetes: connection refused"]);
    expect(inv.evidence.length).toBeGreaterThan(0);
    expect(inv.evidence.every((e) => e.source === "prometheus")).toBe(true);
  });

  it("drops malformed evidence and says so", async () => {
    const weird: Fetch = async () => ({ ok: true, status: 200, json: async () => ({
      status: "success", data: { resultType: "vector", result: [{ metric: { pod: "x".repeat(300) }, value: [1, "9"] }] },
    }) });
    const inv = await investigate({ namespace: "shop", now: NOW, prometheusUrl: "http://p", fetch: weird });
    expect(inv.evidence).toEqual([]);
    expect(inv.gaps.some((g) => g.includes("malformed"))).toBe(true);
  });

  it("caps the amount of evidence", async () => {
    const many: Runner = async (args) =>
      args[1] === "events"
        ? JSON.stringify({ items: Array.from({ length: 250 }, (_, i) => ({
            metadata: { uid: `u${i}` }, type: "Warning", reason: "Unhealthy", message: "m",
            lastTimestamp: new Date(NOW.getTime() - i * 1000).toISOString(), involvedObject: { kind: "Pod", name: "p" },
          })) })
        : JSON.stringify({ items: [] });
    const inv = await investigate({ namespace: "shop", now: NOW, kubectl: many });
    expect(inv.evidence).toHaveLength(200);
    expect(inv.gaps.some((g) => g.includes("only the newest 200 of 250"))).toBe(true);
  });
});
