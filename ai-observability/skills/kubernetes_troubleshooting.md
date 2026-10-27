---
name: kubernetes-troubleshooting
description: >
  Selects targeted, read-only Kubernetes evidence for workload, scheduling,
  probe, restart, image, and resource incidents.
---

# Kubernetes Troubleshooting

Use only the tools returned in the investigation plan.

- **CrashLoopBackOff:** pod status, current/previous logs, events, deployment
  image/config/probes/resources, rollout revisions, and ArgoCD status. Route
  `OOMKilled` to resource analysis. Do not recommend increasing restart limits.
- **ImagePullBackOff:** pod status/events, image and pull policy, Secret
  reference names, and deployment revision. Never read Secret contents.
- **Pending:** pod conditions and scheduling events. Report resource/PVC/
  selector/taint causes only when an event or API result supports them.
- **Readiness/liveness:** probe path/port/timing, pod conditions, events, logs,
  approved application health endpoint, and resource metrics. Do not
  automatically increase probe delays.
- **OOM/high memory:** compare observed working set with configured requests
  and limits where available, previous logs, restarts, traffic, and rollout.
- **High CPU:** compare CPU use, traffic, latency, error rate, replicas, and
  configured resources. Report missing throttling metrics as unavailable.
- **Unavailable/degraded deployment:** compare desired, ready, and available
  replicas, ReplicaSets, warning events, image/revision, and ArgoCD sync/health.

Do not invoke unrestricted commands or perform mutation. Return facts,
evidence-based cause candidates, missing evidence, and a handoff to the
remediation recommendation skill.
