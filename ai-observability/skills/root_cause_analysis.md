---
name: root-cause-analysis
description: >
  Correlates live Kubernetes, Prometheus, log, and GitOps evidence without
  presenting unsupported hypotheses as facts.
---

# Root Cause Analysis

Use the `get_investigation_plan_tool` category-specific path and produce:

1. **Observed facts** — values returned by tools, with tool names and timestamps
   where available.
2. **Evidence sources** — Kubernetes API, Prometheus, Alertmanager, logs, or
   ArgoCD.
3. **Correlation** — explain how timing and independent sources relate.
4. **Probable root cause** — state the strongest supported explanation and why.
5. **Alternative possibilities** — list only plausible alternatives supported
   by evidence.
6. **Confidence** — High, Medium, or Low, with a reason.
7. **Missing evidence** — identify unavailable tools/metrics or uncertainty.

Rules:

- Distinguish observation from inference.
- A restart count is not proof of OOM; require the termination reason/event.
- A high 5xx rate does not prove a specific code defect; use safe log evidence.
- Do not claim CPU throttling unless a throttling metric was returned.
- Do not claim a memory limit was exceeded without a limit and observed usage.
- Do not expose credentials, Secret values, tokens, or unredacted connection
  strings.
