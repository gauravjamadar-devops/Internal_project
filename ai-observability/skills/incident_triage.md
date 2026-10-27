---
name: incident-triage
description: >
  Assigns incident category, scope, initial ownership, and an evidence-based
  severity while preserving the original alert severity.
---

# Incident Triage

1. Use `classify_alert_tool` or the classification in
   `get_investigation_plan_tool`.
2. Preserve Alertmanager severity. If it is absent, label any derived severity
   as a fallback rather than silently replacing source metadata.
3. Classify initial ownership as application, Kubernetes workload,
   configuration, resource, deployment/GitOps, or unknown.
4. Determine namespace, workload, and pod from alert labels/annotations and
   safe live evidence. Do not guess missing values.
5. Severity guidance when source severity is absent:
   - **Critical:** application unavailable or all replicas unavailable.
   - **High:** major measured error increase, repeated crashes, or serious
     service degradation.
   - **Medium:** partial degradation, elevated resource use, or limited
     replica impact.
   - **Low:** early warning without observed service impact.
6. State the reason and cite the source tool for each triage conclusion.
7. Use the category's targeted tool list; do not run unrelated diagnostics.
