import { describe, expect, it } from "vitest";
import {
  EvidenceSchema, K8sNameSchema, buildTimeline, cleanLine, rankHypotheses, redact, renderText, worstSeverity,
  type Evidence, type Investigation,
} from "./index.js";

const ev = (over: Partial<Evidence> = {}): Evidence => ({
  id: "e1", source: "kubernetes", kind: "pod.crashloop", at: "2026-11-21T10:00:00Z",
  subject: "pod/web-1", severity: "warning", summary: "something", ...over,
});

describe("redact", () => {
  it.each([
    ["Authorization: Bearer abcdef1234567890", "abcdef1234567890"],
    ["password=hunter2hunter2", "hunter2hunter2"],
    ['{"api_key": "sk-live-abcdefghijklmnop"}', "sk-live-abcdefghijklmnop"],
    ["key AKIAABCDEFGHIJKLMNOP leaked", "AKIAABCDEFGHIJKLMNOP"],
    ["token ghp_abcdefghijklmnopqrstuvwxyz0123", "ghp_abcdefghijklmnopqrstuvwxyz0123"],
    ["jwt eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4", "eyJhbGciOiJIUzI1"],
    ["postgres://admin:s3cretpass@db:5432/x", "s3cretpass"],
  ])("hides the secret in %s", (input, secret) => {
    const out = redact(input);
    expect(out).not.toContain(secret);
    expect(out).toContain("REDACTED");
  });

  it("leaves ordinary text alone", () => {
    const text = "container checkout was OOMKilled (exit 137), restarts: 7";
    expect(redact(text)).toBe(text);
  });

  it("cleanLine flattens whitespace and caps the length", () => {
    expect(cleanLine("a\n\n  b\tc")).toBe("a b c");
    const long = cleanLine("word ".repeat(200), 50);
    expect(long.length).toBeLessThanOrEqual(50);
    expect(long.endsWith("...")).toBe(true);
  });
});

describe("schemas", () => {
  it("accepts a good evidence item and rejects bad ones", () => {
    expect(EvidenceSchema.safeParse(ev()).success).toBe(true);
    expect(EvidenceSchema.safeParse(ev({ at: "yesterday" })).success).toBe(false);
    expect(EvidenceSchema.safeParse(ev({ severity: "fatal" as never })).success).toBe(false);
    expect(EvidenceSchema.safeParse(ev({ summary: "x".repeat(501) })).success).toBe(false);
  });

  it("K8sNameSchema only allows real names", () => {
    for (const ok of ["shop", "kube-system", "a1", "x-y-z"]) expect(K8sNameSchema.safeParse(ok).success).toBe(true);
    for (const bad of ["", "Shop", "-x", "x-", 'a"}', "a;b", "a b", "a/b", "x".repeat(64), "{namespace=~\".*\"}"]) {
      expect(K8sNameSchema.safeParse(bad).success, bad).toBe(false);
    }
  });
});

describe("timeline", () => {
  it("sorts oldest first, then worst first, and drops duplicate ids", () => {
    const a = ev({ id: "a", at: "2026-11-21T10:05:00Z" });
    const b = ev({ id: "b", at: "2026-11-21T10:00:00Z", severity: "info" });
    const c = ev({ id: "c", at: "2026-11-21T10:00:00Z", severity: "critical" });
    const input = [a, b, c, { ...a, summary: "dup" }];
    const out = buildTimeline(input);
    expect(out.map((e) => e.id)).toEqual(["c", "b", "a"]);
    expect(out.find((e) => e.id === "a")?.summary).toBe("something");
    expect(input).toHaveLength(4); // input untouched
  });

  it("reports the worst severity", () => {
    expect(worstSeverity([])).toBe("info");
    expect(worstSeverity([ev({ severity: "warning" })])).toBe("warning");
    expect(worstSeverity([ev({ severity: "warning" }), ev({ severity: "critical" })])).toBe("critical");
  });
});

describe("rankHypotheses", () => {
  it("is empty when nothing matches", () => {
    expect(rankHypotheses([])).toEqual([]);
    expect(rankHypotheses([ev({ kind: "event.warning" })])).toEqual([]);
  });

  it("explains an OOM crash loop and cites its evidence", () => {
    const evidence = [
      ev({ id: "oom", kind: "pod.oomkilled", severity: "critical", subject: "pod/shop-1" }),
      ev({ id: "loop", kind: "pod.crashloop", severity: "critical", subject: "pod/shop-1" }),
      ev({ id: "r", source: "prometheus", kind: "metric.restarts", subject: "pod/shop-1" }),
    ];
    const [top, second] = rankHypotheses(evidence);
    expect(top?.id).toBe("oom");
    expect(top?.evidence).toEqual(expect.arrayContaining(["oom", "loop", "r"]));
    expect(top?.confidence).toBe("medium"); // one direct item plus corroboration
    expect(second?.id).toBe("crashloop");
    expect(top?.next.every((s) => !/delete|apply|patch|scale|restart/i.test(s.replace("restarts", "")))).toBe(true);
  });

  it("raises confidence with more direct evidence plus corroboration", () => {
    const evidence = [
      ev({ id: "o1", kind: "pod.oomkilled", subject: "pod/a" }),
      ev({ id: "o2", kind: "metric.oomkilled", subject: "pod/a" }),
      ev({ id: "r", kind: "metric.restarts", subject: "pod/a" }),
    ];
    expect(rankHypotheses(evidence)[0]?.confidence).toBe("high");
  });

  it("only counts corroboration from the same pod", () => {
    const evidence = [
      ev({ id: "o", kind: "pod.oomkilled", subject: "pod/a" }),
      ev({ id: "r", kind: "metric.restarts", subject: "pod/other" }),
    ];
    const top = rankHypotheses(evidence)[0];
    expect(top?.evidence).toEqual(["o"]);
    expect(top?.confidence).toBe("low");
  });

  it("is deterministic", () => {
    const evidence = [ev({ kind: "pod.imagepull" }), ev({ id: "s", kind: "event.failedscheduling" })];
    expect(rankHypotheses(evidence)).toEqual(rankHypotheses([...evidence].reverse()));
  });
});

describe("renderText", () => {
  const base: Investigation = {
    namespace: "shop", generatedAt: "2026-11-21T10:00:00Z", windowMinutes: 30, evidence: [], hypotheses: [], gaps: [],
  };

  it("says so when nothing was found", () => {
    const text = renderText(base);
    expect(text).toContain("nothing unusual found");
    expect(text).toContain("no known pattern matched");
    expect(text).toContain("nothing was changed");
  });

  it("lists gaps instead of hiding failed sources", () => {
    expect(renderText({ ...base, gaps: ["prometheus: HTTP 503"] })).toContain("prometheus: HTTP 503");
  });
});
