# @bilalkhanten/incident-copilot

Read-only incident triage for Kubernetes and Prometheus. Point it at a namespace and it prints a
timeline of what went wrong and the likely causes, with the evidence behind each one. It only
reads: the single kubectl call it can make is `get pods|events -n <name> -o json`.

```bash
npx @bilalkhanten/incident-copilot investigate -n <namespace> --prometheus http://localhost:9090
```

Needs `kubectl` configured for the cluster. Run `copilot --help` for all options.

Full documentation, the safety model and a no-cluster demo:
https://github.com/Bilalkhanten/ai-digest/tree/main/copilot
