# Incident copilot

Read-only incident triage for Kubernetes and Prometheus, written in TypeScript. Point it at a
namespace and it gathers evidence (pod states, warning events, restart and OOM metrics), builds a
timeline, and lists the likely causes with the evidence behind each one and safe next steps.

It never changes anything. It cannot, by construction: see [Safety](#safety).

```text
$ copilot investigate -n shop --prometheus http://localhost:9090

Timeline (6 events)
  09:52:10  CRIT  [kubernetes] pod/checkout-7d9f6c-abcde: container checkout was OOMKilled (exit 137)
  09:57:02  WARN  [kubernetes] pod/checkout-7d9f6c-abcde: Unhealthy: Readiness probe failed ... (x12)
  ...
Likely causes
  1. Container is being killed for exceeding its memory limit  (confidence: high)
     evidence: k8s:oom:..., prom:oom:..., prom:restarts:..., k8s:crashloop:...
     next: kubectl describe pod checkout-7d9f6c-abcde -n <namespace>   # check Limits and Last State
```

## Try it without a cluster

```bash
cd copilot
npm install
npm run demo
```

The demo replays a recorded out-of-memory crash loop from `examples/crashloop/`.

## Against a real cluster

```bash
npm run build
node packages/cli/dist/main.js investigate -n <namespace> --prometheus http://localhost:9090
```

Needs `kubectl` configured for the cluster. If Prometheus needs a token, set
`PROMETHEUS_BEARER_TOKEN` (it is sent as a header and never printed). Use `--json` for
machine-readable output and `--window <minutes>` to change how far back it looks (default 30).
If a source cannot be reached, the report lists it under "Could not check" instead of failing.

## Layout

| Package | What it does |
|---|---|
| `packages/core` | the evidence model (Zod schemas), secret redaction, timeline, rule-based cause ranking, text report |
| `packages/connectors` | read-only Kubernetes (`kubectl get`) and Prometheus connectors, and the orchestrator |
| `packages/cli` | the `copilot` command |

## Safety

- **Allowlist, not blocklist.** The only kubectl call ever made is `get pods|events -n <name> -o json`.
  Anything else is refused before kubectl starts, and each rule is pinned by its own test.
- **No query injection.** Namespaces are validated as Kubernetes names before they go anywhere near
  a PromQL query. Prometheus URLs with embedded credentials are refused.
- **Secrets are redacted** (tokens, passwords, keys, URLs with credentials) before anything is
  stored or shown.
- **Deterministic.** The cause ranking is plain rules, no model calls: the same input always gives
  the same report, and every claim cites the evidence ids behind it.
- **Suggestions, not actions.** "Next steps" are text for a human to run.

## Development

```bash
npm test          # Vitest, runs against the TypeScript sources
npm run build     # tsc -b with project references
```

CI (`.github/workflows/copilot-ci.yml`) runs the build, the tests and the demo on Node 22 and 24,
only when something under `copilot/` changes.

## Roadmap

Loki log excerpts, deploy correlation from GitHub, an HTTP API with an audit log, a small
dashboard, and a plugin interface for new connectors.
