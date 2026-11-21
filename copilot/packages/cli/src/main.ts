#!/usr/bin/env node
import { execFile } from "node:child_process";
import { parseArgs } from "node:util";
import { promisify } from "node:util";
import { K8sNameSchema, renderText } from "@copilot/core";
import {
  fixtureFetch, fixtureRunner, investigate, readOnlyRunner, type Fetch, type Runner,
} from "@copilot/connectors";

const run = promisify(execFile);

const HELP = `copilot: read-only incident triage for Kubernetes and Prometheus

Usage:
  copilot investigate --namespace <name> [options]

Options:
  -n, --namespace <name>   namespace to look at (required)
      --prometheus <url>   Prometheus base URL, e.g. http://localhost:9090
      --window <minutes>   how far back to look (default 30)
      --json               machine-readable output
      --fixture <dir>      read pods.json, events.json, prometheus.json from a folder instead of a cluster
      --now <iso>          pretend it is this time (for reproducible demos)
  -h, --help               show this help

Environment:
  PROMETHEUS_BEARER_TOKEN  sent as an Authorization header to Prometheus, never printed

The tool only reads. It runs "kubectl get pods|events -o json" and Prometheus instant queries.
`;

export interface Io {
  out: (text: string) => void;
  err: (text: string) => void;
}

export interface Deps {
  kubectl?: Runner;
  fetch?: Fetch;
  env?: Record<string, string | undefined>;
}

const realKubectl: Runner = async (args) => (await run("kubectl", args, { maxBuffer: 32 * 1024 * 1024, timeout: 30_000 })).stdout;

function withBearer(inner: Fetch, token: string | undefined): Fetch {
  if (!token) return inner;
  return (url, init) => inner(url, { ...init, headers: { Authorization: `Bearer ${token}` } } as never);
}

/** Returns the process exit code. All I/O goes through `io` so tests can capture it. */
export async function main(argv: string[], io: Io, deps: Deps = {}): Promise<number> {
  let parsed;
  try {
    parsed = parseArgs({
      args: argv,
      allowPositionals: true,
      options: {
        namespace: { type: "string", short: "n" },
        prometheus: { type: "string" },
        window: { type: "string", default: "30" },
        json: { type: "boolean", default: false },
        fixture: { type: "string" },
        now: { type: "string" },
        help: { type: "boolean", short: "h", default: false },
      },
    });
  } catch (err) {
    io.err(`${err instanceof Error ? err.message : String(err)}\n\n${HELP}`);
    return 2;
  }
  const { values, positionals } = parsed;
  if (values.help || positionals.length === 0) {
    io.out(HELP);
    return values.help ? 0 : 2;
  }
  if (positionals[0] !== "investigate" || positionals.length > 1) {
    io.err(`unknown command "${positionals.join(" ")}"\n\n${HELP}`);
    return 2;
  }
  if (!values.namespace) {
    io.err("--namespace is required\n");
    return 2;
  }
  if (!K8sNameSchema.safeParse(values.namespace).success) {
    io.err(`"${values.namespace}" is not a valid Kubernetes namespace name\n`);
    return 2;
  }
  const windowMinutes = Number(values.window);
  if (!Number.isInteger(windowMinutes) || windowMinutes < 1 || windowMinutes > 1440) {
    io.err("--window must be a whole number of minutes between 1 and 1440\n");
    return 2;
  }
  const now = values.now ? new Date(values.now) : new Date();
  if (Number.isNaN(now.getTime())) {
    io.err("--now must be an ISO 8601 timestamp\n");
    return 2;
  }

  const env = deps.env ?? process.env;
  const kubectl = values.fixture ? fixtureRunner(values.fixture) : (deps.kubectl ?? realKubectl);
  const baseFetch: Fetch | undefined = values.fixture
    ? fixtureFetch(values.fixture)
    : (deps.fetch ?? (globalThis.fetch as unknown as Fetch));
  const prometheusUrl = values.prometheus ?? (values.fixture ? "http://fixture.invalid" : undefined);

  try {
    const result = await investigate({
      namespace: values.namespace,
      windowMinutes,
      now,
      kubectl: readOnlyRunner(kubectl),
      ...(prometheusUrl && baseFetch ? { prometheusUrl, fetch: withBearer(baseFetch, env.PROMETHEUS_BEARER_TOKEN) } : {}),
    });
    io.out(values.json ? `${JSON.stringify(result, null, 2)}\n` : renderText(result));
    return 0;
  } catch (err) {
    io.err(`investigation failed: ${err instanceof Error ? err.message : String(err)}\n`);
    return 1;
  }
}

const invokedDirectly = process.argv[1] !== undefined && import.meta.url.endsWith(process.argv[1].split("/").pop() ?? "\0");
if (invokedDirectly) {
  main(process.argv.slice(2), {
    out: (t) => process.stdout.write(t),
    err: (t) => process.stderr.write(t),
  }).then((code) => process.exit(code));
}
