import { readFile } from "node:fs/promises";
import { join } from "node:path";
import type { Runner } from "./kubernetes.js";
import type { Fetch } from "./prometheus.js";

/** A kubectl stand-in that reads `pods.json` / `events.json` from a folder. For demos and tests. */
export function fixtureRunner(dir: string): Runner {
  return async (args) => readFile(join(dir, `${args[1]}.json`), "utf8");
}

/** A Prometheus stand-in: `prometheus.json` maps "restarts" | "oom" | "throttling" to vector results. */
export function fixtureFetch(dir: string): Fetch {
  return async (url) => {
    const query = new URL(url).searchParams.get("query") ?? "";
    const key = query.includes("restarts_total") ? "restarts" : query.includes("OOMKilled") ? "oom" : "throttling";
    const all = JSON.parse(await readFile(join(dir, "prometheus.json"), "utf8")) as Record<string, unknown[]>;
    const result = all[key] ?? [];
    return { ok: true, status: 200, json: async () => ({ status: "success", data: { resultType: "vector", result } }) };
  };
}
