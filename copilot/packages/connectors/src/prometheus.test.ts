import { describe, expect, it, vi } from "vitest";
import { collectPrometheus, validBaseUrl, type Fetch } from "./prometheus.js";

const NOW = new Date("2026-11-21T10:00:00Z");
const vector = (rows: Array<{ pod: string; v: string }>) => ({
  status: "success",
  data: { resultType: "vector", result: rows.map((r) => ({ metric: { pod: r.pod }, value: [1795254000, r.v] })) },
});
const okFetch = (byKey: Record<string, ReturnType<typeof vector>>): Fetch =>
  vi.fn(async (url: string) => {
    const q = new URL(url).searchParams.get("query") ?? "";
    const key = q.includes("restarts_total") ? "restarts" : q.includes("OOMKilled") ? "oom" : "throttling";
    return { ok: true, status: 200, json: async () => byKey[key] ?? vector([]) };
  });
const opts = (fetch: Fetch, over: Record<string, unknown> = {}) => ({
  baseUrl: "http://prom:9090", namespace: "shop", fetch, now: NOW, windowMinutes: 30, ...over,
});

describe("collectPrometheus", () => {
  it("turns query results into evidence with severities", async () => {
    const out = await collectPrometheus(opts(okFetch({
      restarts: vector([{ pod: "a", v: "7" }, { pod: "b", v: "2" }]),
      oom: vector([{ pod: "a", v: "1" }]),
      throttling: vector([{ pod: "c", v: "0.6" }]),
    })));
    const byId = Object.fromEntries(out.map((e) => [e.id, e]));
    expect(byId["prom:restarts:a"]?.severity).toBe("critical");
    expect(byId["prom:restarts:b"]?.severity).toBe("warning");
    expect(byId["prom:oom:a"]?.kind).toBe("metric.oomkilled");
    expect(byId["prom:throttling:c"]?.summary).toContain("60%");
  });

  it("sends the namespace and window only inside the query, to /api/v1/query", async () => {
    const f = okFetch({});
    await collectPrometheus(opts(f, { baseUrl: "https://prom.example.com/", windowMinutes: 15 }));
    const urls = (f as ReturnType<typeof vi.fn>).mock.calls.map((c) => new URL(c[0] as string));
    expect(urls).toHaveLength(3);
    for (const u of urls) {
      expect(u.origin).toBe("https://prom.example.com");
      expect(u.pathname).toBe("/api/v1/query");
    }
    expect(urls[0]?.searchParams.get("query")).toContain('namespace="shop"');
    expect(urls[0]?.searchParams.get("query")).toContain("[15m]");
  });

  it.each(['shop"} or vector(1) #', "a;b", "Shop", '{namespace=~".*"}', ""])("refuses namespace %j without calling Prometheus", async (ns) => {
    const f = okFetch({});
    await expect(collectPrometheus(opts(f, { namespace: ns }))).rejects.toThrow(/bad namespace/);
    expect(f).not.toHaveBeenCalled();
  });

  it("clamps the window and rejects URLs with credentials or odd schemes", async () => {
    const f = okFetch({});
    await collectPrometheus(opts(f, { windowMinutes: 999999 }));
    expect(new URL((f as ReturnType<typeof vi.fn>).mock.calls[0]?.[0] as string).searchParams.get("query")).toContain("[1440m]");
    expect(() => validBaseUrl("ftp://x")).toThrow();
    expect(() => validBaseUrl("http://user:pw@x")).toThrow(/credentials/);
    expect(() => validBaseUrl("not a url")).toThrow();
  });

  it("survives one failing query but throws when every query fails", async () => {
    let n = 0;
    const flaky: Fetch = async () => (++n === 1 ? { ok: false, status: 503, json: async () => ({}) } : { ok: true, status: 200, json: async () => vector([{ pod: "a", v: "9" }]) });
    expect((await collectPrometheus(opts(flaky))).length).toBeGreaterThan(0);
    const down: Fetch = async () => ({ ok: false, status: 500, json: async () => ({}) });
    await expect(collectPrometheus(opts(down))).rejects.toThrow(/unreachable or invalid/);
    const garbage: Fetch = async () => ({ ok: true, status: 200, json: async () => ({ hello: "world" }) });
    await expect(collectPrometheus(opts(garbage))).rejects.toThrow(/unexpected response shape/);
  });

  it("skips non-numeric values instead of emitting junk", async () => {
    const out = await collectPrometheus(opts(okFetch({ restarts: vector([{ pod: "a", v: "NaN-ish" }]) })));
    expect(out).toEqual([]);
  });
});
