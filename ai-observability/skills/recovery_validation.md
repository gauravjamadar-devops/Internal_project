---
name: recovery-validation
description: >
  Validates service recovery after human-approved remediation using current
  alert, deployment, endpoint, and Prometheus evidence.
---

# Recovery Validation

1. Run `validate_recovery_tool(namespace, workload, incident_id)` only after the
   human reports that remediation was applied.
2. Require all of the following before reporting RECOVERED:
   - no matching active Alertmanager alert
   - desired replicas are available
   - the approved application health endpoint returns HTTP 200
   - Prometheus has healthy scrape targets and reports healthy application
     state
3. Do not report RECOVERED from pod phase alone.
4. Preserve the tool's status: RECOVERED, PARTIALLY_RECOVERED, STILL_ACTIVE,
   or VALIDATION_INCONCLUSIVE.
5. Report missing telemetry or tool errors and do not infer a pass.
6. Restart history is a current snapshot, not a time series; say so when
   reporting restart stability.
7. Update the incident record with the validation result, without changing any
   Kubernetes resource.
