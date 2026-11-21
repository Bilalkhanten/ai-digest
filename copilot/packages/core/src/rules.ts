import type { Evidence, Hypothesis } from "./types.js";

/**
 * Rule-based reasoning. Each rule looks at evidence kinds and proposes a likely cause with the
 * evidence that backs it. No model calls: the same input always gives the same output.
 * Next steps are read-only suggestions; this tool never changes anything.
 */
interface Rule {
  id: string;
  title: string;
  kinds: string[];
  reasoning: string;
  next: (subjects: string[]) => string[];
  /** Metric evidence on the same subject raises confidence. */
  corroboratedBy?: string[];
}

const RULES: Rule[] = [
  {
    id: "oom",
    title: "Container is being killed for exceeding its memory limit",
    kinds: ["pod.oomkilled", "metric.oomkilled"],
    reasoning: "The last termination reason is OOMKilled, so the kernel stopped the container at its memory limit.",
    corroboratedBy: ["metric.restarts", "pod.crashloop"],
    next: (s) => [
      `kubectl describe pod ${s[0] ?? "<pod>"} -n <namespace>   # check Limits and Last State`,
      "Compare the memory limit with real usage (container_memory_working_set_bytes) before changing it",
    ],
  },
  {
    id: "crashloop",
    title: "Container keeps crashing on start (CrashLoopBackOff)",
    kinds: ["pod.crashloop"],
    reasoning: "The container is repeatedly starting and exiting, and Kubernetes is backing off between restarts.",
    corroboratedBy: ["metric.restarts", "pod.restarts"],
    next: (s) => [
      `kubectl logs ${s[0] ?? "<pod>"} -n <namespace> --previous   # the crashed run's output`,
      "Check the most recent deploy or config change for this workload",
    ],
  },
  {
    id: "image",
    title: "Image cannot be pulled",
    kinds: ["pod.imagepull"],
    reasoning: "The pod is waiting on ErrImagePull or ImagePullBackOff: wrong tag, missing registry credentials or a registry outage.",
    next: (s) => [
      `kubectl describe pod ${s[0] ?? "<pod>"} -n <namespace>   # the Events section names the failing image`,
      "Verify the image tag exists and the imagePullSecret is valid",
    ],
  },
  {
    id: "schedule",
    title: "Pod cannot be scheduled",
    kinds: ["event.failedscheduling"],
    reasoning: "The scheduler found no node that fits (resources, taints or affinity).",
    next: () => [
      "kubectl get nodes   # capacity and taints",
      "Compare the pod's resource requests with free allocatable capacity",
    ],
  },
  {
    id: "probe",
    title: "Health probes are failing",
    kinds: ["event.probefailed"],
    reasoning: "Readiness or liveness probes are failing, so traffic is withheld or the container is restarted.",
    corroboratedBy: ["metric.restarts"],
    next: (s) => [
      `kubectl describe pod ${s[0] ?? "<pod>"} -n <namespace>   # probe settings and recent failures`,
      "Check whether the app is slow to start (initialDelaySeconds) or genuinely unhealthy",
    ],
  },
  {
    id: "throttle",
    title: "CPU throttling is slowing the workload",
    kinds: ["metric.throttling"],
    reasoning: "A large share of CPU periods are throttled, which shows up as latency without crashes.",
    next: () => ["Compare CPU limits with real usage; consider raising or removing the limit after review"],
  },
];

function confidence(direct: number, corroborated: boolean): Hypothesis["confidence"] {
  if (direct >= 2 && corroborated) return "high";
  if (direct >= 2 || corroborated) return "medium";
  return "low";
}

export function rankHypotheses(evidence: readonly Evidence[]): Hypothesis[] {
  const out: Array<Hypothesis & { weight: number }> = [];
  for (const rule of RULES) {
    const direct = evidence.filter((e) => rule.kinds.includes(e.kind));
    if (direct.length === 0) continue;
    const subjects = [...new Set(direct.map((e) => e.subject.replace(/^pod\//, "")))];
    const support = (rule.corroboratedBy ?? [])
      .flatMap((k) => evidence.filter((e) => e.kind === k && subjects.some((s) => e.subject.includes(s))));
    const weight = direct.length + support.length + (direct.some((e) => e.severity === "critical") ? 5 : 0);
    out.push({
      id: rule.id,
      title: rule.title,
      confidence: confidence(direct.length, support.length > 0),
      reasoning: rule.reasoning,
      evidence: [...new Set([...direct, ...support].map((e) => e.id))],
      next: rule.next(subjects),
      weight,
    });
  }
  return out.sort((a, b) => b.weight - a.weight || a.id.localeCompare(b.id)).map(({ weight: _w, ...h }) => h);
}
