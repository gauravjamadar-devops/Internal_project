# AI DevOps Observability Assistant

The project connects an AI client to read-only observability evidence from
Kubernetes, Prometheus, Alertmanager, and ArgoCD through an MCP server. Skills
guide the AI through alert-first triage, targeted investigation, evidence-based
recommendations, and post-remediation validation.

**The server does not remediate workloads.** It can update its local incident
record, but all cluster changes remain human-approved and GitOps-managed.

## Documentation

- [Project guide](PROJECT_GUIDE.md): architecture, MCP and skills concepts,
  tool catalog, setup, and presentation Q&A.
- [Incident response guide](INCIDENT_RESPONSE.md): incident lifecycle,
  security boundaries, validation, and controlled dev scenarios.
- [DevOps Investigator skill](skills/devops_investigator.md): the end-to-end
  orchestration workflow.

## Architecture

```text
FastAPI /metrics ──scraped──> Prometheus ──query──┐
                                                   │
Kubernetes API <── read-only ServiceAccount ── MCP server
Alertmanager ──────────────────────────────────────┤
ArgoCD API <── read-only Application RBAC ─────────┘
                                                   │ MCP
                                                   v
                                    AI client + incident-response skills
                                                   │
                                                   v
                                    evidence report and recommendation
                                                   │
                               human-reviewed GitOps change, if approved
```

The in-cluster MCP server uses Streamable HTTP at `/mcp`; local development
defaults to stdio. The server is configured for the `dev` namespace and
`fastapi-dev-deployment` workload by default. Production access is not enabled
by the checked-in defaults.

## MCP tool groups

| Group | Tools |
|---|---|
| Alert intake and planning | `get_active_alerts_tool`, `get_alert_details_tool`, `get_silenced_alerts_tool`, `classify_alert_tool`, `get_investigation_plan_tool` |
| Kubernetes evidence | `get_pods_tool`, `get_pod_status_tool`, `get_pod_restarts_tool`, `get_deployment_status_tool`, `get_replicaset_status_tool`, `get_kubernetes_events_tool`, `get_recent_rollout_tool`, `describe_workload_tool`, `get_pod_logs_tool`, `get_previous_pod_logs_tool`, `search_pod_logs_tool` |
| Prometheus evidence | `query_prometheus_tool`, `get_error_rate_tool`, `get_request_rate_tool`, `get_request_latency_tool`, `get_resource_usage_tool`, `get_pod_cpu_tool`, `get_pod_memory_tool`, `get_available_replicas_tool`, `get_container_restart_metrics_tool`, `get_application_health_tool` |
| Approved endpoint and recovery | `check_application_endpoint_tool`, `validate_recovery_tool` |
| ArgoCD evidence | `get_argocd_application_status_tool`, `get_argocd_sync_status_tool`, `get_current_image_tool`, `get_deployment_revision_tool` |
| Incident record | `get_incidents_tool`, `update_incident_state_tool` |

Tools are read-only with respect to the cluster and GitOps. Prometheus queries
are constrained; Kubernetes namespaces/workloads and ArgoCD applications are
allowlisted; logs are bounded and redacted; endpoint checks are restricted to
configured services and approved paths.

## Alert rules

The Helm-managed `PrometheusRule` in `monitoring/templates/fastapi-alert-rules.yaml`
includes dev-scoped rules for CrashLoopBackOff, sustained HTTP 5xx, target down,
no available replicas, high CPU, memory near a configured limit, and
OOMKilled. Thresholds and target labels are in `monitoring/values.yaml`.

The memory rule intentionally produces no alert if the workload has no
configured memory-limit metric. Do not treat absent metrics as a healthy
measurement.

## Local validation

From `ai-observability/mcp-server`:

```powershell
python -m unittest discover -s tests -v
```

The MCP server can be run locally in stdio mode. Configure its Prometheus and
Alertmanager URLs and Kubernetes credentials for the environment being tested;
the in-cluster DNS defaults are not reachable from an ordinary local process.
See the project guide before starting the server.

Validate the Helm charts without deploying:

```powershell
helm lint monitoring
helm template monitoring monitoring --namespace monitoring
helm lint fastapi-chart
helm template fastapi-dev fastapi-chart --namespace dev -f environment/dev/values.yaml
helm template fastapi-dev fastapi-chart --namespace dev -f environment/dev/values.yaml --set incidentTestMode=true
```

`incidentTestMode` is a bounded, hard-coded startup-failure switch and Helm
rejects it outside the `dev` namespace. It defaults to `false`; it is not an
arbitrary command override. Do not enable it outside an approved dev
demonstration window.

## State and operational limitations

- The incident SQLite database is mounted on `emptyDir`; records are lost when
  the MCP pod is recreated. Use a persistent volume or external database if
  durable history is required.
- Incident identity is deduplicated by Alertmanager fingerprint. This is a
  current-state tracker, not a full immutable audit/history system.
- FastAPI application source is not present in this checkout. The guide uses
  the existing dev `/simulate-error` behavior and does not invent app routes.
- The current dev workload has no confirmed memory limit; the memory ratio
  alert therefore may have no data to evaluate.
- The repo's existing Alertmanager notification configuration requires a
  separate secure-secret migration and credential-rotation follow-up. Never
  place webhook credentials in documentation, logs, or source-controlled
  plaintext values.

## Deployment

No cluster changes are applied by the local test commands above. Build and
deploy the MCP server and apply Helm-managed alert changes through the
repository's reviewed deployment process. Confirm rendered manifests and
RBAC before applying them. Do not expose the MCP Service publicly without
authentication and TLS.
