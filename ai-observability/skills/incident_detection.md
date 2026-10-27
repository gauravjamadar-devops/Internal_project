---
name: incident-detection
description: >
  Finds genuine active incidents from configured Alertmanager alerts and
  creates a stable, deduplicated investigation record.
---

# Incident Detection

1. Call `get_active_alerts_tool`; Alertmanager is the incident source.
2. Do not manufacture alerts from metrics or assume a previous alert remains
   active.
3. Use the Alertmanager fingerprint as the stable incident identity.
4. Keep only enabled dev workload alerts. If a target is outside scope, explain
   that it cannot be investigated with the current tool permissions.
5. Identify duplicate alerts for the same fingerprint and reuse the incident
   ID returned by the tool.
6. Preserve alert name, state, severity, namespace, workload, pod,
   `startsAt`, summary, description, labels, annotations, and generator URL
   when provided.
7. Call `get_silenced_alerts_tool` when suppression is relevant. Never imply
   that a silenced alert is resolved.
8. Do not claim alert history: the current project does not configure a
   historical incident store beyond its local incident-state records.

Return the incident ID, alert name, namespace/workload, severity, state,
detection source, fingerprint, and whether it is a duplicate.
