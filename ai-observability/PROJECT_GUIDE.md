# AI DevOps Observability Assistant: Project Guide

## Executive summary

This project gives a compatible AI client a constrained way to collect
operational evidence from Kubernetes, Prometheus, Alertmanager, and ArgoCD. The
MCP server exposes tools; repository skills teach the AI how to select tools,
correlate evidence, state uncertainty, recommend GitOps changes, and validate
recovery.

The design is **human-approved incident response, not autonomous remediation**.
The MCP service has read-only cluster/GitOps access. It can write its own
SQLite incident-state record, but it cannot restart, scale, delete, sync, roll
back, or modify application resources.

For complete operational instructions and the controlled test scenarios, see
[INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md). For setup and validation entry
points, see [README.md](README.md).

## 1. Architecture

```text
Engineer request
      |
      v
AI client with repository skills
      | MCP over stdio (local) or Streamable HTTP (/mcp in-cluster)
      v
MCP server in dev
   |         |           |            |
Kubernetes Prometheus Alertmanager ArgoCD
   |         |           |            |
   +---------+-----------+------------+
                 evidence
                   |
                   v
       AI investigation report
                   |
           human-reviewed Git change
                   |
           normal GitOps reconcile
                   |
           read-only recovery checks
```

MCP is the tool-discovery and invocation protocol. It does not contain the
language model and does not replace the data sources. The client interprets a
request, calls an MCP tool, receives structured results, and applies the
loaded skill instructions to form a response.

## 2. Component responsibilities

| Component | Responsibility |
|---|---|
| MCP entry point | Registers the public tools, declares read-only investigation instructions, and logs tool start/completion/failure metadata. |
| Alertmanager tools | Fetch and normalize current active alerts and silences; historical Alertmanager API access is not assumed. |
| Incident state | Creates a stable incident ID from Alertmanager fingerprint, deduplicates active observations, stores the latest lifecycle state, and redacts free-text summaries. |
| Workflow logic | Classifies an alert, chooses a targeted tool list, checks scope, and calculates recovery status from independent evidence. |
| Kubernetes tools | Read allowlisted workload, pod, ReplicaSet, event, rollout, and bounded/redacted log evidence; check configured approved application paths. |
| Prometheus tools | Execute constrained expressions and return app, request, latency, resource, restart, and availability metrics. |
| ArgoCD tools | Read allowlisted Application health/sync and live deployment image/revision context. |
| Skills | Give the AI client a repeatable investigation and reporting procedure; they do not grant access or execute server code. |
| PrometheusRule chart | Creates dev-targeted FastAPI incident alerts, subject to the availability of the corresponding metrics. |

## 3. MCP tool catalog

The public MCP names are registered in `mcp-server/main.py`.

### Alert intake and planning

| Tool | Purpose |
|---|---|
| `get_active_alerts_tool` | Get current active alerts in the configured scope and register incident IDs. |
| `get_alert_details_tool` | Fetch the exact active alert by name and optional namespace. |
| `get_silenced_alerts_tool` | Read active silence metadata without comments or creator details. |
| `classify_alert_tool` | Return category, ownership, preserved or derived severity, and target identity. |
| `get_investigation_plan_tool` | Return incident state, classification, selected skill, safety boundary, and targeted tool names. |

### Kubernetes evidence

| Tool | Purpose |
|---|---|
| `get_pods_tool` | Pod phase, container readiness, restart count, and node for the scoped workload. |
| `get_pod_status_tool` | Detailed container state and pod conditions. |
| `get_pod_restarts_tool` | Current restart snapshot, optionally scoped to a workload. |
| `get_deployment_status_tool` | Desired/available replicas, image, probes, resource settings, and deployment conditions. |
| `get_replicaset_status_tool` | ReplicaSet readiness and revision. |
| `get_kubernetes_events_tool` | Bounded recent warning events, optionally associated with a workload. |
| `get_recent_rollout_tool` | Recent ReplicaSet/deployment revision evidence. |
| `describe_workload_tool` | Safe workload/pod/ReplicaSet summary without environment values. |
| `get_pod_logs_tool` | Bounded and redacted current logs. |
| `get_previous_pod_logs_tool` | Bounded and redacted logs from the previous container instance. |
| `search_pod_logs_tool` | Search bounded scoped logs against a small set of literal patterns. |

### Prometheus evidence

| Tool | Purpose |
|---|---|
| `query_prometheus_tool` | Run an exact pre-approved dev PromQL expression; arbitrary expressions are rejected. |
| `get_error_rate_tool` | 5xx rate, total rate, percentage, and simulated error counter. |
| `get_request_rate_tool` | Application request rate over an allowed window. |
| `get_request_latency_tool` | P99 request latency from histogram buckets. |
| `get_resource_usage_tool` | Available CPU/memory, requests, and limits; absent metrics are not fabricated. |
| `get_pod_cpu_tool` | CPU use for the scoped workload or selected pod. |
| `get_pod_memory_tool` | Memory working set for the scoped workload or selected pod. |
| `get_available_replicas_tool` | Available replica metric from kube-state-metrics. |
| `get_container_restart_metrics_tool` | Prometheus restart counter evidence. |
| `get_application_health_tool` | Composite scrape, request, 5xx, and latency health evidence. |

### Endpoint, recovery, GitOps, and incident state

| Tool | Purpose |
|---|---|
| `check_application_endpoint_tool` | Check only a configured service and approved endpoint paths. |
| `validate_recovery_tool` | Evaluate alerts, replicas, `/health`, and Prometheus health after reported remediation. |
| `get_argocd_application_status_tool` | Read Application sync and health. |
| `get_argocd_sync_status_tool` | Read the allowlisted sync/health state. |
| `get_current_image_tool` | Read the deployed image reference without environment values. |
| `get_deployment_revision_tool` | Read observed generation and rollout revision. |
| `get_incidents_tool` | List recent incident state records (maximum 100). |
| `update_incident_state_tool` | Record a state and redacted cause/recommendation/validation summary. |

## 4. Skills and AI workflow

The repository includes seven Markdown skills:

1. `devops_investigator`: orchestrates the alert-first workflow and report.
2. `incident_detection`: verifies active alert identity and duplicate state.
3. `incident_triage`: categorizes impact, ownership, and source severity.
4. `root-cause-analysis`: correlates evidence and labels uncertainty.
5. `kubernetes-troubleshooting`: selects workload/event/log/resource checks.
6. `remediation-recommendation`: proposes a human-approved GitOps change,
   risk, and rollback.
7. `recovery_validation`: checks the post-change state and reports the exact
   result.

The skills are instructions loaded by the AI client. Merely storing a skill
file in this repository does not make every MCP client load it automatically;
configure the client to discover or include the desired skills. The server
still enforces its own namespace/workload allowlists and authorization.

Typical alert-first sequence:

```text
get_active_alerts_tool
  -> get_investigation_plan_tool
  -> only the selected evidence tools
  -> update_incident_state_tool
  -> human-reviewed GitOps recommendation
  -> engineer confirms remediation
  -> validate_recovery_tool
```

The report should identify detection, impact, facts, evidence sources,
probable cause, alternatives, confidence, missing evidence, recommendation,
risk/rollback, and current lifecycle state.

## 5. Incident states and IDs

Supported states are `DETECTED`, `TRIAGING`, `INVESTIGATING`,
`SOLUTION_RECOMMENDED`, `AWAITING_REMEDIATION`, `VALIDATING`, `RECOVERED`,
`STILL_ACTIVE`, and `INCONCLUSIVE`.

Alertmanager fingerprints produce stable IDs. Re-observing an unresolved alert
updates its record rather than duplicating it. Re-observing a fingerprint after
`RECOVERED` reactivates its state as `DETECTED`. This is a latest-state
store—not a complete append-only event log.

The database path is `/data/incidents.sqlite3` in Kubernetes, mounted from
`emptyDir`. Pod recreation loses incident records. A persistent volume or
external data store is required for durable history.

## 6. Alert rules

`monitoring/templates/fastapi-alert-rules.yaml` defines dev-scoped rules for
CrashLoopBackOff, sustained 5xx ratio, missing/down scrape target, unavailable
replicas, high CPU, memory near the configured limit, and OOMKilled.
`monitoring/values.yaml` sets the intended namespace, service, workload, and
thresholds.

Rules are useful only if their label selectors match live series. Validate the
rendered Helm output and query each expression against the configured
Prometheus before applying it. The memory rule is ratio-based and does not
fire without a memory-limit series. The current FastAPI chart does not
guarantee that a limit is configured.

## 7. Operational boundaries and limitations

- Default tool scope is dev-only, with an allowlisted FastAPI workload and
  named ArgoCD application. Production must remain disabled unless separately
  reviewed and explicitly configured.
- The Service is ClusterIP-only. Do not expose it publicly without
  authentication and TLS.
- Tool calls that read the cluster are subject to read-only RBAC. SQLite
  incident updates modify only MCP-owned state.
- Logs are bounded/redacted; arbitrary PromQL, service URLs, endpoint paths,
  namespaces, workloads, and applications are not accepted.
- Recovery requires an alert-free state, all expected replicas, a healthy
  approved endpoint, and healthy Prometheus evidence. A Running pod is not
  enough.
- Restart stability is a current snapshot, not a historical trend.
- App source is not tracked in this checkout, so no undocumented route or
  application startup behavior should be assumed.
- Existing notification credentials require secure-secret migration and
  rotation. Never copy credential values into project documentation.

## 8. Validation and demo

From `ai-observability/mcp-server`, run:

```powershell
python -m unittest discover -s tests -v
```

Render both charts before any deployment:

```powershell
helm lint monitoring
helm template monitoring monitoring --namespace monitoring
helm lint fastapi-chart
helm template fastapi-dev fastapi-chart --namespace dev -f environment/dev/values.yaml
helm template fastapi-dev fastapi-chart --namespace dev -f environment/dev/values.yaml --set incidentTestMode=true
```

`incidentTestMode` is an opt-in, hard-coded startup failure intended only for
the dev Helm release; chart rendering is rejected outside the `dev`
namespace. Restore it to `false` through the reviewed GitOps path immediately
after a demonstration. Do not trigger scenarios during validation unless an
engineer is present and the dev environment is approved for the test.

See [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) for controlled 5xx and
CrashLoop demonstrations, resource-alert limitations, and recovery procedure.

## 9. Presentation questions and answers

**What does MCP add?**

It gives an AI client a standard way to discover and invoke a limited set of
typed tools instead of granting shell or unrestricted cluster access.

**What does a skill add?**

A skill describes when and how the AI should use tools, what evidence matters,
how to state uncertainty, and how to format the report. It does not add
permissions.

**Does the AI fix the cluster?**

No. The server is designed for read-only evidence collection. The AI
recommends a change; a human reviews and applies it through GitOps.

**How is evidence gathered?**

Alertmanager supplies current alerts; Kubernetes supplies workload, event,
rollout, and bounded log data; Prometheus supplies application and resource
metrics; ArgoCD supplies sync, health, image, and revision data.

**How is an incident deduplicated?**

The Alertmanager fingerprint maps repeated observations to a stable incident
ID. The state record reopens after recovery if that fingerprint becomes active
again.

**What does recovery mean?**

No matching active alert, expected replicas available, `/health` successful,
and Prometheus targets/application health healthy. Missing evidence yields an
inconclusive result rather than a false pass.

**Are the skills automatically active?**

Only if the AI client loads them. Configure the client with the repository's
skill files; MCP tool permissions are enforced independently.

**Can it inspect production?**

Not by default. Scope is allowlisted to dev; production requires a separate
authorization and review.

**What happens to incident history if the pod restarts?**

The SQLite file is on `emptyDir`, so it is lost. Durable incident history
requires persistent storage and a defined retention policy.

**Can this project prove every alert condition?**

No. A rule can be rendered and queried, but an alert can only fire when the
relevant metrics exist and meet its threshold. In particular, memory ratio
alerting requires configured limits, and intentionally exhausting resources is
not part of the safe demo.

**Does the existing MCP deployment automatically gain the new tools?**

No. Rebuild and deploy the updated MCP image through the reviewed process,
then verify the running server's MCP tool list and read-only integration
checks. The source change alone does not update a live pod.

## 10. Repository locations

- `mcp-server/main.py`: MCP registration and request audit logging.
- `mcp-server/tools/`: Alertmanager, ArgoCD, Kubernetes, Prometheus,
  security, incident-state, and workflow implementations.
- `mcp-server/tests/`: focused unit tests.
- `k8s/`: MCP deployment, service, and read-only RBAC.
- `config/config.yaml`: in-cluster service URLs and default dev scope.
- `skills/`: AI workflow instructions.
- `monitoring/templates/fastapi-alert-rules.yaml`: Helm-managed alert rules.
- `fastapi-chart/templates/deployment.yaml`: dev-only test mode guard.
